# Build PinV programs with the standard RISC-V GNU toolchain.
#   make                                  -> all demos with default settings
#   make BIT_CYCLES=64 SPI_MODE=3         -> override build-time settings
#   make CHECK=0                          -> skip the timing proof (not recommended)
#
# Every program is checked by tools/pinv_check.py after linking: if any
# deadline could be missed, the build fails and no binary is produced.
#
# Settings (clock cycles, so they depend on the chip clock):
#   BIT_CYCLES  UART bit period = clock / baud        (default 347 = 40 MHz / 115200)
#   SPI_MODE    0-3                                   (default 0)
#   SPI_HALF    half SCK period                       (default 80; the checker proves >= 77)
#   I2C_Q       quarter SCL period                    (default 94: about 100 kHz at 40 MHz)

PREFIX  ?= riscv64-unknown-elf-
CC      := $(PREFIX)gcc
OBJCOPY := $(PREFIX)objcopy
OBJDUMP := $(PREFIX)objdump

BIT_CYCLES ?= 347
SPI_MODE   ?= 0
SPI_HALF   ?= 80
I2C_Q      ?= 94

DEFS   := -DBIT_CYCLES=$(BIT_CYCLES) -DSPI_MODE=$(SPI_MODE) -DSPI_HALF=$(SPI_HALF) -DI2C_Q=$(I2C_Q)
CFLAGS := -march=rv32ec -mabi=ilp32e -nostdlib -nostartfiles -Os -I. -T link.ld $(DEFS)

PROGRAMS := uart_echo spi_jedec i2c_read

all: $(PROGRAMS:%=build/%.bin)

build/%.elf: %.S uart.S pinv.h link.ld
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $< uart.S

CHECK ?= 1

build/%.bin: build/%.elf
ifeq ($(CHECK),1)
	@python3 ../tools/pinv_check.py $< || (echo "timing not proven: $@ not built"; exit 1)
endif
	$(OBJCOPY) -O binary $< $@
	@$(OBJDUMP) -d $< > build/$*.lst
	@echo "$@: $$(stat -c %s $@) bytes"

clean:
	rm -rf build

.PHONY: all clean
.PRECIOUS: build/%.elf
