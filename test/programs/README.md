# Test programs

Prebuilt binaries loaded by `test/test.py`, so the tests (including gate-level runs in CI) do not need a RISC-V toolchain. They are built with short periods to keep simulations fast.

| File | Source | Build command (from `firmware/`) |
|---|---|---|
| `uart_echo.bin` | `uart_echo.S` | `make BIT_CYCLES=64` |
| `spi_jedec_mode<N>.bin` | `spi_jedec.S` | `make BIT_CYCLES=64 SPI_HALF=80 SPI_MODE=<N>` |
| `i2c_read.bin` | `i2c_read.S` | `make BIT_CYCLES=64 I2C_Q=60 EXTRA=-DI2C_LIMIT=1000` |
| `uart_echo_locked.bin` | `uart_echo.S` | `make BIT_CYCLES=64 EXTRA=-DPINV_LOCKED` |
| `ws2812.bin` | `ws2812.S` | `make` (defaults: 40 MHz timings) |
| `spi_firewall.bin` | `spi_firewall.S` | `make BIT_CYCLES=64` |

After changing a program, rebuild it and copy `firmware/build/<name>.bin` here. `UART_BIT_CYCLES` and `I2C_Q` in `test.py` must match the build settings.

Every binary here passes the timing proof (`tools/pinv_check.py`), and the tests check the same thing on the RTL: `DeadlineMonitor` fails a test if any WAIT_UNTIL is reached after its deadline.
