## How it works

PinV is a reprogrammable protocol emulator. A PicoRV32 RISC-V core (RV32EC) runs a program from 512 bytes of on-chip memory and drives the pins through custom instructions: set outputs, read inputs, set directions, read the cycle counter, wait for a deadline or a pin level, shift a bit in or out at a deadline, and generate exact pulses (a waveform serializer for WS2812 LEDs). Security features: bounded waits, a program lock and an idle state for the pins during a reload. Protocols such as UART are written as ordinary programs, with every edge anchored on an absolute cycle-counter deadline so the bit timing is exact.

See [architecture.md](architecture.md) for the instruction set and timing model.

## How to test

1. Hold `ui[7]` (LOAD) high.
2. Shift the program in on `ui[5]` (MOSI) with `ui[6]` (SCK), SPI mode 0, MSB first, SCK at most clk/4.
3. Release LOAD: the core runs from address 0.

With the UART demo (`firmware/uart_echo.S`), connect a 3.3 V UART adapter: TX on `uo[0]`, RX on `ui[0]`. The chip prints `Hello` and echoes each received character. The baud rate is `clock / BIT_CYCLES`, set when the program is built.

Other demos in `firmware/`: SPI flash JEDEC ID (`spi_jedec.S`), I2C register read (`i2c_read.S`), a WS2812 LED chain on `uo[1]` (`ws2812.S`), and an SPI bus firewall between a host and a flash (`spi_firewall.S`).

## External hardware

A 3.3 V USB-UART adapter for the UART demo. Optional: an SPI flash, an I2C device, WS2812 LEDs (with a 3.3 V to 5 V level shifter). The RP2350 on the demo board loads the program.
