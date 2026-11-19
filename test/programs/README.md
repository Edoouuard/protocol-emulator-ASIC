# Test programs

Prebuilt binaries loaded by `test/test.py`, so the tests (including gate-level runs in CI) do not need a RISC-V toolchain. They are built with short periods to keep simulations fast.

| File | Source | Build command (from `firmware/`) |
|---|---|---|
| `uart_echo.bin` | `uart_echo.S` | `make BIT_CYCLES=64` |
| `spi_jedec_mode<N>.bin` | `spi_jedec.S` | `make BIT_CYCLES=64 SPI_HALF=48 SPI_MODE=<N>` |
| `i2c_read.bin` | `i2c_read.S` | `make BIT_CYCLES=64 I2C_Q=32` |

After changing a program, rebuild it and copy `firmware/build/<name>.bin` here. `UART_BIT_CYCLES` and `I2C_Q` in `test.py` must match the build settings.
