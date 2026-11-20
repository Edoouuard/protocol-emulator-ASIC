/* EXPECT rejected: not a proven return
 * A computed jump into slow code. The old checker gave `jr` no successor,
 * never saw the slow path, and printed PROVEN. The deadline is missed. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    TIME(t0)
    addi t0, t0, 40
    la   a0, slow
    jr   a0
slow:
    .rept 20
    addi a1, a1, 1
    .endr
    WAIT_UNTIL(zero, t0)
    j    _start
