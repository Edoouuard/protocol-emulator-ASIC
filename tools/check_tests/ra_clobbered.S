/* EXPECT rejected: overwrites
 * f calls g without saving ra, so its own return comes back into f forever. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    TIME(t0)
    addi t0, t0, 40
    call f
    WAIT_UNTIL(zero, t0)
    j    _start
f:
    call g
    ret
g:
    ret
