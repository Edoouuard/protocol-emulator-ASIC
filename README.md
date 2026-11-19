![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# PinV — a RISC-V protocol emulator ASIC

Entry for the [Jane Street × Tiny Tapeout Protocol Emulator ASIC Competition](https://blog.janestreet.com/protocol-emulator-asic-competition/) (deadline 18 January 2027).

PinV is the open-source [PicoRV32](https://github.com/YosysHQ/picorv32) RISC-V core (RV32EC) plus six pin and deadline instructions. Protocols are written as ordinary programs and built with the standard RISC-V GNU toolchain; every edge is anchored on an absolute cycle-counter deadline, so bit timing is exact.

**Timing is proven, not just tested.** The hardware timing contract (zero-jitter `WAIT_UNTIL`, exact `PIN_OUT`, safe loading) is proven formally with SymbiYosys (`formal/`). On top of it, `tools/pinv_check.py` analyses every path of a program and proves, before it is loaded, that no deadline can be missed. The build refuses a program it cannot prove. Its cost model is calibrated on the RTL and matches the simulation to the cycle.

- Target: IHP 130 nm CMOS5L via Tiny Tapeout, 8x4 tiles.
- Architecture, instruction set and timing model: [`docs/architecture.md`](docs/architecture.md)
- Datasheet: [`docs/info.md`](docs/info.md)

## Status

| Milestone | Status |
|---|---|
| Template configured (8x4, top module) | ✅ |
| PicoRV32 integrated, pin/timing unit, SPI program loader | ✅ |
| UART TX + RX echo demo, cycle-exact in simulation | ✅ |
| SPI master demo (JEDEC ID read), modes 0-3 | ✅ |
| I2C master demo (register read, repeated START, clock stretching, NACK) | ✅ |
| Static timing proof of every program (`pinv_check`), validated on the RTL | ✅ |
| Formal proof of the pin/timing unit, loader and top level (SymbiYosys) | ✅ |
| GDS + precheck passing | ⏳ first run pending |
| Base ISA tests, gate-level simulation | ⏳ |
| Write-up | ⏳ |

## Repository layout

```
src/            RTL: top level, pin/timing unit, loader, PicoRV32 (vendored)
firmware/       pinv.h (instruction macros), demo programs, linker script
tools/          pinv_check.py (timing proof); timing/ (cost-model calibration on the RTL)
formal/         SymbiYosys proofs of the hardware (make -C formal)
docs/journal.md step-by-step build log, in French
test/           cocotb tests; test/programs holds prebuilt binaries
docs/           architecture, datasheet
third_party/    licenses of reused code
```

## Running the tests

```bash
cd test
pip install -r requirements.txt
make
```

Requires Icarus Verilog. The repository includes a dev container (GitHub Codespaces) with the Tiny Tapeout tools.

## Building programs

```bash
make -C firmware BIT_CYCLES=347   # e.g. 40 MHz / 115200 baud
```

Each program is linked, then checked by `tools/pinv_check.py`; the binary is only produced if every deadline is proven. Programs declare their timing budget with `PINV_BUDGET(cycles)` (see `firmware/pinv.h`).

Requires `riscv64-unknown-elf-gcc` (any RISC-V GNU toolchain with RV32E support).

## Third-party code

`src/picorv32.v` is [PicoRV32](https://github.com/YosysHQ/picorv32) by Claire Xenia Wolf, ISC license, commit `ef203c2`, unmodified. License: [`third_party/picorv32_COPYING`](third_party/picorv32_COPYING).

## Tools

AI tools are used during development; how they are used will be documented in the write-up, as the competition rules require.

## Resources

- [Tiny Tapeout FAQ](https://tinytapeout.com/faq/) — the GDS action needs [GitHub Pages enabled](https://tinytapeout.com/faq/#my-github-action-is-failing-on-the-pages-part).
- [Local hardening guide](https://www.tinytapeout.com/guides/local-hardening/)

## License

Apache-2.0 for PinV's own code. PicoRV32 keeps its ISC license.
