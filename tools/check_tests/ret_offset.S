/* EXPECT rejected: offset 4: not a return
 * The function returns 4 bytes past its return address, into slow code. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    TIME(t0)
    addi t0, t0, 40
    call f
    jal  x0, fast           /* 4 bytes: the return lands after it */
    .rept 20
    addi a1, a1, 1
    .endr
fast:
    WAIT_UNTIL(zero, t0)
    j    _start
f:
    jalr x0, 4(ra)
