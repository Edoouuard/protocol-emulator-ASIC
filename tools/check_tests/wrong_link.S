/* EXPECT rejected: is called with link register
 * f is called with jal t1 but returns through ra. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    TIME(t0)
    addi t0, t0, 40
    jal  t1, f
    WAIT_UNTIL(zero, t0)
    j    _start
f:
    ret
