/*
 * PinV custom instructions for the standard RISC-V GNU assembler.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Usable from assembly (.S) and from C inline assembly. No custom assembler
 * is needed: each instruction is emitted with the .insn directive
 * (R-type, opcode custom-0 = 0x0B, funct7 = 0).
 */
#ifndef PINV_H
#define PINV_H

#ifdef __ASSEMBLER__

/* out = (out & ~mask) | (val & mask);  rd = new out */
#define PIN_OUT(rd, val, mask)    .insn r 0x0B, 0, 0, rd, val, mask
/* rd = {uio_in, ui_in} */
#define PIN_IN(rd)                .insn r 0x0B, 1, 0, rd, zero, zero
/* uio_oe = (oe & ~mask[15:8]) | (val & mask)[15:8] */
#define PIN_DIR(rd, val, mask)    .insn r 0x0B, 2, 0, rd, val, mask
/* rd = cycle counter */
#define TIME(rd)                  .insn r 0x0B, 3, 0, rd, zero, zero
/* stall until counter reaches deadline; rd = counter */
#define WAIT_UNTIL(rd, deadline)  .insn r 0x0B, 4, 0, rd, deadline, zero
/* stall until (pins & mask) == (level & mask); rd = counter */
#define WAIT_PIN(rd, mask, level) .insn r 0x0B, 5, 0, rd, mask, level

#else

#include <stdint.h>

static inline uint32_t pin_out(uint32_t val, uint32_t mask) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 0, 0, %0, %1, %2" : "=r"(r) : "r"(val), "r"(mask)); return r;
}
static inline uint32_t pin_in(void) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 1, 0, %0, zero, zero" : "=r"(r)); return r;
}
static inline uint32_t pin_dir(uint32_t val, uint32_t mask) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 2, 0, %0, %1, %2" : "=r"(r) : "r"(val), "r"(mask)); return r;
}
static inline uint32_t pinv_time(void) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 3, 0, %0, zero, zero" : "=r"(r)); return r;
}
static inline uint32_t wait_until(uint32_t deadline) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 4, 0, %0, %1, zero" : "=r"(r) : "r"(deadline)); return r;
}
static inline uint32_t wait_pin(uint32_t mask, uint32_t level) {
    uint32_t r; __asm__ volatile (".insn r 0x0B, 5, 0, %0, %1, %2" : "=r"(r) : "r"(mask), "r"(level)); return r;
}

#endif
#endif
