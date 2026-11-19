![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# PinV — a RISC-V protocol emulator ASIC

Entry for the [Jane Street × Tiny Tapeout Protocol Emulator ASIC Competition](https://blog.janestreet.com/protocol-emulator-asic-competition/) (deadline 18 January 2027).

PinV is the open-source [PicoRV32](https://github.com/YosysHQ/picorv32) RISC-V core (RV32EC) plus six pin and deadline instructions. Protocols are written as ordinary programs and built with the standard RISC-V GNU toolchain; every edge is anchored on an absolute cycle-counter deadline, so bit timing is exact.

- Target: IHP 130 nm CMOS5L via Tiny Tapeout, 8x4 tiles.
- Architecture, instruction set and timing model: [`docs/architecture.md`](docs/architecture.md)
- Datasheet: [`docs/info.md`](docs/info.md)

## Status

| Milestone | Status |
|---|---|
| Template configured (8x4, top module) | ✅ |
| PicoRV32 integrated, pin/timing unit, SPI program loader | ✅ |
| UART TX + RX echo demo, cycle-exact in simulation | ✅ |
| GDS + precheck passing | ⏳ first run pending |
| SPI and I2C demo programs | ⏳ |
| Base ISA tests, gate-level simulation | ⏳ |
| Write-up | ⏳ |

## Repository layout

```
src/            RTL: top level, pin/timing unit, loader, PicoRV32 (vendored)
firmware/       pinv.h (instruction macros), demo programs, linker script
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
make -C firmware BIT_CYCLES=434   # e.g. 50 MHz / 115200 baud
```

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
