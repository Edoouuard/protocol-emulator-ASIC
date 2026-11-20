/* EXPECT rejected: runs off the end of the program
 * After the last instruction the core runs whatever the memory holds. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    TIME(t0)
    addi t0, t0, 40
    WAIT_UNTIL(zero, t0)
