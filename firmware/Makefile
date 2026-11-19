# Build PinV programs with the standard RISC-V GNU toolchain.
#   make                                  -> all demos with default settings
#   make BIT_CYCLES=64 SPI_MODE=3         -> override build-time settings
#
# Settings (clock cycles, so they depend on the chip clock):
#   BIT_CYCLES  UART bit period = clock / baud        (default 347 = 40 MHz / 115200)
#   SPI_MODE    0-3                                   (default 0)
#   SPI_HALF    half SCK period                       (default 48)
#   I2C_Q       quarter SCL period                    (default 94: about 100 kHz at 40 MHz)

PREFIX  ?= riscv64-unknown-elf-
CC      := $(PREFIX)gcc
OBJCOPY := $(PREFIX)objcopy
OBJDUMP := $(PREFIX)objdump

BIT_CYCLES ?= 347
SPI_MODE   ?= 0
SPI_HALF   ?= 48
I2C_Q      ?= 94

DEFS   := -DBIT_CYCLES=$(BIT_CYCLES) -DSPI_MODE=$(SPI_MODE) -DSPI_HALF=$(SPI_HALF) -DI2C_Q=$(I2C_Q)
CFLAGS := -march=rv32ec -mabi=ilp32e -nostdlib -nostartfiles -Os -I. -T link.ld $(DEFS)

PROGRAMS := uart_echo spi_jedec i2c_read

all: $(PROGRAMS:%=build/%.bin)

build/%.elf: %.S uart.S pinv.h link.ld
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $< uart.S

build/%.bin: build/%.elf
	$(OBJCOPY) -O binary $< $@
	@$(OBJDUMP) -d $< > build/$*.lst
	@echo "$@: $$(stat -c %s $@) bytes"

clean:
	rm -rf build

.PHONY: all clean
.PRECIOUS: build/%.elf
