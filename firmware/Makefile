# Build PinV programs with the standard RISC-V GNU toolchain.
#   make                      -> build/uart_echo.bin
#   make BIT_CYCLES=40        -> override the UART bit period (clock / baud)

PREFIX  ?= riscv64-unknown-elf-
CC      := $(PREFIX)gcc
OBJCOPY := $(PREFIX)objcopy
OBJDUMP := $(PREFIX)objdump

BIT_CYCLES ?= 521
CFLAGS := -march=rv32ec -mabi=ilp32e -nostdlib -nostartfiles -Os -I. -T link.ld -DBIT_CYCLES=$(BIT_CYCLES)

PROGRAMS := uart_echo

all: $(PROGRAMS:%=build/%.bin)

build/%.elf: %.S pinv.h link.ld
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $<

build/%.bin: build/%.elf
	$(OBJCOPY) -O binary $< $@
	@$(OBJDUMP) -d $< > build/$*.lst
	@echo "$@: $$(stat -c %s $@) bytes"

clean:
	rm -rf build

.PHONY: all clean
