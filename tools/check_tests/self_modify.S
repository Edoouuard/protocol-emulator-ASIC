/* EXPECT rejected: aliases
 * Address 0x204 is address 0x4 in a 512-byte memory: the store overwrites the
 * proven code, so the proof no longer describes what runs. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    li   a0, 0x200
    sw   zero, 4(a0)
    TIME(t0)
    addi t0, t0, 40
    WAIT_UNTIL(zero, t0)
    j    _start
