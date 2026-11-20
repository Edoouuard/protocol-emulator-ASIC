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

Timer and fused shift instructions (funct3 = 6 and 7, variant in funct7). The unit keeps an internal deadline and step, so a periodic signal costs one instruction per bit:

| funct3/funct7 | Instruction | Effect |
|---|---|---|
| 6/0 | `SET_TIMER start, step` | deadline ← start; step ← step[15:0] |
| 6/1 | `WAIT_TICK rd` | stall until the deadline; deadline += step; rd ← counter |
| 7/0 | `SHIFT_OUT rd, data, idx` | at the deadline, output pin idx ← data[0]; rd ← data >> 1; deadline += step |
| 7/2 | `SHIFT_OUTM rd, data, idx` | same, MSB first: pin ← data[31]; rd ← data << 1 |
| 7/1 | `SHIFT_IN rd, data, idx` | at the deadline, rd ← {pin idx, data[31:1]}; deadline += step |
| 7/3 | `SHIFT_INM rd, data, idx` | same, MSB first: rd ← {data[30:0], pin idx} |
| 6/2 | `SET_LIMIT cycles` | a `WAIT_PIN` gives up after `cycles` cycles (24 bits; 0 = wait forever, the reset value) |
| 6/3 | `LOCK` | lock the program: the LOAD pin is ignored until the chip is reset |

`PIN_IN` returns `{15'b0, timed_out, pins}`: `timed_out` (bit 16, `PIN_TIMED_OUT` in `pinv.h`) is set when a `WAIT_PIN` gave up and cleared when `PIN_IN` reads it.

Bit map: outputs [7:0] = `uo_out`, [15:8] = `uio_out`; inputs [7:0] = `ui_in`, [15:8] = `uio_in`.

## Timing model: deadline-anchored I/O

PicoRV32 is a multi-cycle core: instructions take several cycles, and shifts take a number of cycles that depends on the shift amount. PinV does not try to make every instruction take a fixed time. Instead, every timing-critical edge is anchored on an **absolute deadline** of the cycle counter:

```
WAIT_UNTIL(zero, t)     # release exactly one cycle after counter == t
PIN_OUT(zero, bit, m)   # pin changes a fixed number of cycles later
t += BIT_CYCLES         # next deadline, computed from the previous one
```

The edge lands at a fixed offset from the deadline whatever the code in between did, as long as it finished before the deadline. Errors never accumulate, because each deadline is derived from the previous deadline, not from "now". `WAIT_PIN` returns the time of the input edge, so receivers can sample in the middle of each bit by adding offsets to that timestamp.

Measured in simulation (UART demo): every TX edge falls exactly on a multiple of the bit period. With the fused `SHIFT_OUT`/`SHIFT_IN` instructions, the timing checker proves the demo for any bit period of at least 18 cycles (about 2.2 Mbaud at 40 MHz), against 44 cycles with separate wait, output and shift instructions.

## Proven timing: pinv_check

A deadline-anchored program is only correct if the code between an anchor and the next `WAIT_UNTIL` always finishes before the deadline. Tests can show that it did on the paths they ran. `tools/pinv_check.py` proves that it does on every path, before the program is loaded:

1. It rebuilds the control-flow graph of the linked program, including calls and returns through any link register.
2. For every anchor (`TIME`, `WAIT_UNTIL`, `WAIT_PIN`) it explores every path to each `WAIT_UNTIL` reachable without another anchor, and computes the worst-case cycle count with a cost model of PinV's PicoRV32 calibrated on the RTL (`tools/timing/`).
3. It compares that worst case with the budget the source declares with `PINV_BUDGET(cycles)` (stored in a section that is not loaded on the chip). A loop without a bound between an anchor and a deadline is an error.

The firmware build runs it on every program: if a deadline can be missed, no binary is produced. CI does the same.

What it found on the demos: the SPI demo asked for 48-cycle half periods, but one path through the bit loop takes 77 cycles. SPI is clocked by the master, so the tests still passed, at a slower SCK than requested. The default is now 80.

Validation on the RTL: at the smallest budget the checker proves for each demo, the simulation shows no missed deadline; one cycle less, it shows a miss. Details in `tools/timing/README.md`.

Scope and assumptions: the cost model holds for PinV's configuration (single-cycle memory, no interrupts); `WAIT_PIN` waits for an input and has no deadline, so only `WAIT_UNTIL` deadlines are checked; indirect calls are rejected.

## Formal proof of the hardware

`pinv_check` assumes the hardware keeps its contract (for instance, that `WAIT_UNTIL` releases the core exactly at the deadline). That contract is proven with SymbiYosys and Z3 (`formal/`, `make -C formal`), by k-induction, for every reachable state and every input sequence:

| Module | Proven |
|---|---|
| `pinv_io` | internal deadline advances by exactly one step at each `WAIT_TICK`/`SHIFT_*`, is set only by `SET_TIMER`, never drifts; `SHIFT_OUT` drives exactly the selected pin with the outgoing bit; shift results move exactly one bit and sample the selected pin; counter advances by exactly 1 per cycle; exactly one answer per instruction; every instruction completes in the cycle right after its condition holds; **zero jitter**: a `WAIT_UNTIL`, `WAIT_TICK` or `SHIFT_*` whose deadline is in the future releases when the counter equals the deadline; `WAIT_*`/`TIME` return the release cycle; `PIN_OUT` changes exactly the masked bits one cycle later, and nothing else changes the outputs; only `PIN_DIR` changes directions; reset state |
| `pinv_io` (bounded group) | a `WAIT_PIN` with a limit never waits longer than it; without a limit it only ends on a match; the limit changes only by `SET_LIMIT`; `timed_out` is set exactly when a wait gives up, reported and cleared by `PIN_IN`; `LOCK` raises the lock request for exactly one cycle |
| `pinv_io` × 2 (non-interference) | same instructions and timing operands, arbitrary different data: identical timing state and answer cycles forever |
| `pinv_loader` | writes only in load mode after the 8th SCK edge; each load starts at address 0; addresses advance by exactly one per byte; the written byte is the one shifted in |
| top level | the loader never writes memory while the core runs; the core is held in reset while LOAD is high and released when it falls; once locked, stays locked until reset, LOAD has no effect (no loader write, core never stopped) |

The PicoRV32 side of the PCPI handshake is modelled by assumptions (operands stable while waiting, request kept while told to wait, dropped after the answer). For the top level, PicoRV32 and the pin/timing unit are replaced by stand-ins with completely free outputs (`formal/picorv32_free.v`, `formal/pinv_io_free.v`), which over-approximate any behaviour of both; the unit is proven on its own.

Covers show that the key situations are reachable (no vacuous proof). Mutation check: ten injected bugs — the six below plus a limit that is ignored, a wait that gives up one cycle too late, a deadline that depends on the data bit, and a bypassed lock — each make the proof fail with a concrete counterexample. The first six: (release one cycle early, ignore the `PIN_OUT` mask, answer twice, a `SHIFT` that does not advance the deadline, `SHIFT_OUT` on the wrong pin, a tick released one cycle early) each make the proof fail on the expected property, with a concrete counterexample from bounded model checking.

Together: the formal proof establishes the hardware timing contract; `pinv_check` proves each program respects it.

## Security properties

| Threat | Mechanism | Guarantee |
|---|---|---|
| A device holds a line forever (denial of service) | `SET_LIMIT` bounds `WAIT_PIN`; sticky `timed_out` flag | **proven**: a limited `WAIT_PIN` never waits longer than its limit, whatever the pins do; without a limit it only ends on a match. Tested: the I2C demo reports `#` when SCL is held low forever |
| Replacing or halting the program from outside | `LOCK`; LOAD ignored until reset | **proven** at top level (any core behaviour, any pin sequence): once locked, the loader never writes and the core is never held in reset; unlocked only by reset. Tested |
| Code injection while running | loader writes only while the core is held in reset | **proven** |
| Timing side channel on the pins | deadline-anchored I/O | **proven** by self-composition (`formal/pinv_io_ni.sv`): two copies of the unit fed the same instructions and timing operands but arbitrary different data keep identical timing state (counter, deadline, step, limits) and answer at the same cycles, so when a bit leaves does not depend on its value. For a whole program, `pinv_check` proves no deadline is missed, so every edge sits on its deadline whatever the data |

Out of scope, stated plainly: physical attacks (voltage or clock glitching, laser fault injection, power and electromagnetic side channels, probing); PicoRV32 itself, used unmodified and not re-proven here; properties nobody wrote down; protocol-level loss (the UART echo cannot receive while it transmits).

Solver note: the proofs run with Yices (`pip install yices-solver`). Z3 4.8.12, from Ubuntu 24.04, did not finish on the unit once the timeout logic was added.

## Demo programs

All three are in `firmware/` and are tested end to end in `test/test.py` against simulated devices.

| Program | Pins | What it does | Measured in simulation |
|---|---|---|---|
| `uart_echo.S` | TX `uo[0]`, RX `ui[0]` | prints `Hello`, then echoes | timing proven for ≥ 18 cycles per bit (~2.2 Mbaud at 40 MHz), with `SHIFT_OUT`/`SHIFT_IN`; 44 cycles with the separate `WAIT_UNTIL` + `PIN_OUT` version |
| `spi_jedec.S` | SCK `uo[1]`, MOSI `uo[2]`, CS_n `uo[3]`, MISO `ui[1]` | reads a flash JEDEC ID (0x9F), prints it | modes 0-3; timing proven for `SPI_HALF` ≥ 77 (~260 kHz at 40 MHz) |
| `i2c_read.S` | SDA `uio[0]`, SCL `uio[1]` (open drain) | reads one register with repeated START, prints it; prints `!` on NACK | clock stretching handled; timing proven for `I2C_Q` ≥ 54 (~160 kHz at 40 MHz); default ~100 kHz |

I2C uses `PIN_DIR` for open drain: the output value stays 0 and the pin is either driven low (output enabled) or released (input), with external pull-ups. After releasing SCL the program waits with `WAIT_PIN` until the line is actually high, which handles clock stretching, and re-anchors its deadlines on that moment.

## Loading a program

1. Drive `ui_in[7]` (LOAD) high: the core is held in reset, the byte address returns to 0.
2. Shift the program in on `ui_in[5]` (MOSI) with `ui_in[6]` (SCK), SPI mode 0, MSB first, SCK ≤ clk/4.
3. Drive LOAD low: the core starts at address 0.

When LOAD is low, `ui_in[5]` and `ui_in[6]` are ordinary inputs again. The chip loses its state when deselected, so the program must be reloaded after reselection, as the competition rules point out.

## Known limitations (v0.1)

- 512 bytes of memory: enough for UART/SPI/I2C routines, tight for C code with a stack.
- Single-threaded: one protocol loop at a time; the UART echo cannot receive while transmitting.
- Outputs reset to 0, so an active-low chip select is asserted until the program sets it. A configurable reset value is a candidate fix.
- I2C fast mode (400 kHz) is not reached at 40 MHz (about 160 kHz with proven timing); the bit loop needs optimising.
- First GDS run (50 MHz target): full layout completed at about 43% utilisation, but setup timing failed post-route in the slow corner (1.08 V, 125 °C), after about 5,200 hold buffers were inserted, mostly around the flip-flop memory. Target lowered to 40 MHz (`CLOCK_PERIOD` = 25 ns in `src/config.json`, which sets the timing constraint; `clock_hz` in `info.yaml` is documentation only). A latch-based memory would cut area, run time and hold fixing.

## Roadmap

1. Confirm area and timing with the GDS flow; tune `clock_hz` and memory size.
2. Reach I2C 400 kHz; a shift-and-output instruction if loops stay too slow.
3. Timeout on `WAIT_PIN`; configurable output reset value.
4. Base ISA tests (`riscv-tests`) and gate-level simulation.
5. A protocol written after the design is frozen (e.g. WS2812 or PS/2) to demonstrate flexibility.
