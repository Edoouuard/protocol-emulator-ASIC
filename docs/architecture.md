# PinV — architecture proposal (draft v0)

> Status: proposal, not implemented. Everything below is open to change.

## Idea in one sentence

A small RISC-V core (RV32E) whose every instruction takes a **fixed, known number of cycles**, extended with a handful of **pin and timing instructions**, so any serial protocol can be written as an ordinary program — and assembled with the standard GNU toolchain.

## Why RISC-V rather than a custom ISA

The competition rewards flexibility (protocols the chip was not designed for), a usable toolchain and a clear write-up.

- **Toolchain for free.** Standard RV32E code is compiled by stock GCC/LLVM. Custom instructions are emitted with the assembler's `.insn` directive and wrapped in macros, so no custom assembler has to be written or trusted.
- **General purpose by construction.** Branches, arithmetic and memory are there, so protocol logic (CRC, addressing, ACK/NACK handling, framing) runs on the chip, not only bit shifting.
- **Deterministic timing is the differentiator.** No caches, no branch prediction, no variable-latency stalls: a program's timing can be computed exactly from its instruction count, which is what bit-banging needs.

Trade-off accepted: a PIO-style state machine (RP2040) moves bits in fewer cycles. PinV trades raw speed for programmability and toolchain reuse. At a 60 MHz clock and 2 cycles per instruction, 30 M instructions/s is ample for UART, SPI and I2C at 100/400 kHz; 10 Mbit Ethernet is out of scope.

## Blocks

| Block | Role | Area estimate (to verify) |
|---|---|---|
| RV32E core | 16 × 32-bit registers, fixed-latency execution | to measure after synthesis |
| Program/data SRAM | program loaded at reset (chip loses state when deselected) | SRAM macro, size TBD |
| Loader | SPI slave on input pins; RP2350 on the demo board writes the program, then releases the core | small |
| Pin unit | drives `uo_out`, samples `ui_in`, controls `uio` direction | small |
| Cycle counter | free-running counter for timed waits | small |

## Pin and timing extension (custom-0 opcode space, draft)

| Instruction | Effect |
|---|---|
| `pin.out rs1, rs2` | outputs ← (outputs & ~mask rs2) \| (rs1 & rs2) |
| `pin.in rd` | rd ← sampled inputs (`ui_in`, `uio_in`) |
| `pin.dir rs1` | sets `uio_oe` |
| `wait.cyc rs1` | stalls exactly rs1 cycles |
| `wait.pin rs1, rs2` | stalls until pin rs1 equals level rs2, with timeout in a CSR |
| `shift.out rd, rs1, rs2` | output LSB of rs1 on pin rs2, rd ← rs1 >> 1 (one-bit shift for SPI/UART) |
| `shift.in rd, rs1, rs2` | sample pin rs2 into rd's MSB, shift right |

## Verification plan

- Per-instruction cocotb tests against a Python reference model.
- Subset of the official `riscv-tests` for the base ISA.
- Protocol tests: PinV programs talking to cocotb bus models (UART, SPI modes 0-3, I2C 100/400 kHz).
- Gate-level simulation of the hardened netlist.
- Timing check: measured bit periods in simulation vs. the cycle count computed from the program.

## Demonstrations targeted

UART TX/RX, SPI master modes 0-3, I2C master. Stretch: a protocol nobody asked for (e.g. WS2812 LEDs or PS/2), written after the chip design is frozen, to prove flexibility.
