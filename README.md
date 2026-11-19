![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# PinV — a RISC-V protocol emulator ASIC

Entry for the [Jane Street × Tiny Tapeout Protocol Emulator ASIC Competition](https://blog.janestreet.com/protocol-emulator-asic-competition/) (deadline 18 January 2027).

PinV is a small RISC-V core (RV32E) with deterministic, fixed-latency execution and a few pin and timing instructions. Protocols such as UART, SPI and I2C are written as ordinary programs and built with the standard RISC-V GNU toolchain.

- Target: IHP 130 nm CMOS5L via Tiny Tapeout, 8x4 tiles.
- Architecture proposal: [`docs/architecture.md`](docs/architecture.md)
- Datasheet: [`docs/info.md`](docs/info.md)

## Status

| Milestone | Status |
|---|---|
| Template configured (8x4, top module, cocotb test) | ✅ |
| Architecture and ISA extension frozen | ⏳ |
| RV32E core passing base ISA tests | ⏳ |
| Pin/timing extension + loader | ⏳ |
| UART, SPI, I2C demo programs | ⏳ |
| GDS + precheck passing | ⏳ |
| Gate-level simulation | ⏳ |
| Write-up | ⏳ |

## Running the tests

```bash
cd test
pip install -r requirements.txt
make
```

Requires Icarus Verilog. The repository includes a dev container (GitHub Codespaces) with the Tiny Tapeout tools.

## Tools

AI tools are used during development; how they are used is documented in the write-up, as the competition rules require.

## Resources

- [Tiny Tapeout FAQ](https://tinytapeout.com/faq/) — the GDS action needs [GitHub Pages enabled](https://tinytapeout.com/faq/#my-github-action-is-failing-on-the-pages-part).
- [Local hardening guide](https://www.tinytapeout.com/guides/local-hardening/)

## License

Apache-2.0.
