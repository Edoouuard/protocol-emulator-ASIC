/* PinV memory map: 512 bytes of program + data at address 0. */
MEMORY { RAM (rwx) : ORIGIN = 0, LENGTH = 512 }
SECTIONS {
    .text : { *(.text.start) *(.text*) *(.rodata*) } > RAM
    .data : { *(.data*) *(.sdata*) } > RAM
    .bss  : { *(.bss*) *(.sbss*) } > RAM
}
