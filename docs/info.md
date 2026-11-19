## How it works

PinV is a reprogrammable protocol emulator. A PicoRV32 RISC-V core (RV32EC) runs a program from 512 bytes of on-chip memory and drives the pins through six custom instructions: set outputs, read inputs, set bidirectional directions, read the cycle counter, wait until a deadline, and wait for a pin level. Protocols such as UART are written as ordinary programs, with every edge anchored on an absolute cycle-counter deadline so the bit timing is exact.

See [architecture.md](architecture.md) for the instruction set and timing model.

## How to test

1. Hold `ui[7]` (LOAD) high.
2. Shift the program in on `ui[5]` (MOSI) with `ui[6]` (SCK), SPI mode 0, MSB first, SCK at most clk/4.
3. Release LOAD: the core runs from address 0.

With the UART demo (`firmware/uart_echo.S`), connect a 3.3 V UART adapter: TX on `uo[0]`, RX on `ui[0]`. The chip prints `Hello` and echoes each received character. The baud rate is `clock / BIT_CYCLES`, set when the program is built.

## External hardware

A 3.3 V USB-UART adapter for the UART demo. The RP2350 on the demo board loads the program.
