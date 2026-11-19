# Test programs

Prebuilt binaries loaded by `test/test.py`, so the tests (including gate-level runs in CI) do not need a RISC-V toolchain.

| File | Source | Build command |
|---|---|---|
| `uart_echo.bin` | `firmware/uart_echo.S` | `make -C firmware BIT_CYCLES=64` |

After changing a program, rebuild it with the command above and copy `firmware/build/<name>.bin` here. `UART_BIT_CYCLES` in `test.py` must match `BIT_CYCLES`.
