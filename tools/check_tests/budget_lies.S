/* EXPECT rejected: can be missed
 * Declares 100 cycles but waits only 10 after its anchor. The old checker
 * trusted the declaration and printed PROVEN. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(100)
    TIME(t0)
    addi t0, t0, 10
    .rept 10
    addi a1, a1, 1
    .endr
    WAIT_UNTIL(zero, t0)
    j    _start
