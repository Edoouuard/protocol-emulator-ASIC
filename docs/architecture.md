# PinV architecture (v0.1)

> Status: first working version in simulation. Area and timing still to be confirmed by the Tiny Tapeout GDS flow.

## Idea in one sentence

A small open-source RISC-V core with a few **pin and deadline instructions**, so any serial protocol can be written as an ordinary program — and built with the standard RISC-V GNU toolchain, without a custom assembler.

## Building blocks

| Block | Source | Role |
|---|---|---|
| Core | [PicoRV32](https://github.com/YosysHQ/picorv32) (ISC license), unmodified, commit `ef203c2` | RV32EC: 16 registers, compressed instructions |
| Pin/timing unit | `src/pinv_io.v` | Custom instructions through PicoRV32's co-processor interface (PCPI) |
| Memory | `src/project.v` | 512 bytes of program + data, single-cycle, byte-writable |
| Loader | `src/pinv_loader.v` | Write-only SPI slave; the demo board's RP2350 loads the program |

PicoRV32 configuration: RV32E (`ENABLE_REGS_16_31=0`), compressed ISA on, counters off, single-port register file, PCPI on, illegal-instruction and misalignment traps off (area).

Reusing a mature, widely used core means verification effort goes into the part that is new — the pin unit, the loader and the protocol programs.

## Pin and timing instructions

R-type, opcode custom-0 (`0x0B`), selected by funct3. Emitted with `.insn` through the macros in `firmware/pinv.h`.

| funct3 | Instruction | Effect |
|---|---|---|
| 0 | `PIN_OUT rd, val, mask` | out ← (out & ~mask) \| (val & mask); rd ← new out |
| 1 | `PIN_IN rd` | rd ← {uio_in, ui_in} (synchronised) |
| 2 | `PIN_DIR rd, val, mask` | uio_oe ← (oe & ~mask) \| (val & mask), bits 15:8 |
| 3 | `TIME rd` | rd ← free-running cycle counter |
| 4 | `WAIT_UNTIL rd, deadline` | stall until counter reaches deadline; rd ← counter |
| 5 | `WAIT_PIN rd, mask, level` | stall until (pins & mask) == (level & mask); rd ← counter (timestamp) |

Bit map: outputs [7:0] = `uo_out`, [15:8] = `uio_out`; inputs [7:0] = `ui_in`, [15:8] = `uio_in`.

## Timing model: deadline-anchored I/O

PicoRV32 is a multi-cycle core: instructions take several cycles, and shifts take a number of cycles that depends on the shift amount. PinV does not try to make every instruction take a fixed time. Instead, every timing-critical edge is anchored on an **absolute deadline** of the cycle counter:

```
WAIT_UNTIL(zero, t)     # release exactly one cycle after counter == t
PIN_OUT(zero, bit, m)   # pin changes a fixed number of cycles later
t += BIT_CYCLES         # next deadline, computed from the previous one
```

The edge lands at a fixed offset from the deadline whatever the code in between did, as long as it finished before the deadline. Errors never accumulate, because each deadline is derived from the previous deadline, not from "now". `WAIT_PIN` returns the time of the input edge, so receivers can sample in the middle of each bit by adding offsets to that timestamp.

Measured in simulation (UART demo): every TX edge falls exactly on a multiple of the bit period. The shortest bit period the demo loop sustains is between 41 and 48 cycles (48 passes, 40 fails), i.e. about 1 Mbaud at a 50 MHz clock.

## Demo programs

All three are in `firmware/` and are tested end to end in `test/test.py` against simulated devices.

| Program | Pins | What it does | Measured in simulation |
|---|---|---|---|
| `uart_echo.S` | TX `uo[0]`, RX `ui[0]` | prints `Hello`, then echoes | every edge on the bit grid; works down to 48 cycles/bit (~1 Mbaud at 50 MHz) |
| `spi_jedec.S` | SCK `uo[1]`, MOSI `uo[2]`, CS_n `uo[3]`, MISO `ui[1]` | reads a flash JEDEC ID (0x9F), prints it | modes 0-3; works down to `SPI_HALF=16` |
| `i2c_read.S` | SDA `uio[0]`, SCL `uio[1]` (open drain) | reads one register with repeated START, prints it; prints `!` on NACK | clock stretching handled; SCL low ≥ ~77 cycles (code time): ~100 kHz by default, ~380 kHz at most at 50 MHz |

I2C uses `PIN_DIR` for open drain: the output value stays 0 and the pin is either driven low (output enabled) or released (input), with external pull-ups. After releasing SCL the program waits with `WAIT_PIN` until the line is actually high, which handles clock stretching, and re-anchors its deadlines on that moment.

## Loading a program

1. Drive `ui_in[7]` (LOAD) high: the core is held in reset, the byte address returns to 0.
2. Shift the program in on `ui_in[5]` (MOSI) with `ui_in[6]` (SCK), SPI mode 0, MSB first, SCK ≤ clk/4.
3. Drive LOAD low: the core starts at address 0.

When LOAD is low, `ui_in[5]` and `ui_in[6]` are ordinary inputs again. The chip loses its state when deselected, so the program must be reloaded after reselection, as the competition rules point out.

## Known limitations (v0.1)

- 512 bytes of memory: enough for UART/SPI/I2C routines, tight for C code with a stack.
- Single-threaded: one protocol loop at a time; the UART echo cannot receive while transmitting.
- `WAIT_PIN` has no timeout yet.
- Outputs reset to 0, so an active-low chip select is asserted until the program sets it. A configurable reset value is a candidate fix.
- I2C fast mode (400 kHz) is not reached at 50 MHz; the bit loop needs optimising or a faster clock.
- Area and maximum clock are estimates until the GDS flow runs (generic synthesis: ~15k cells, ~5.2k flip-flops, most of them memory).

## Roadmap

1. Confirm area and timing with the GDS flow; tune `clock_hz` and memory size.
2. Reach I2C 400 kHz; a shift-and-output instruction if loops stay too slow.
3. Timeout on `WAIT_PIN`; configurable output reset value.
4. Base ISA tests (`riscv-tests`) and gate-level simulation.
5. A protocol written after the design is frozen (e.g. WS2812 or PS/2) to demonstrate flexibility.
