/* EXPECT rejected: does not fix how far it is from its anchor
 * The deadline offset comes from memory: nothing bounds it. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    la   a0, delay
    lw   t1, 0(a0)
    TIME(t0)
    add  t0, t0, t1
    WAIT_UNTIL(zero, t0)
    j    _start
    .section .data
delay: .word 40
