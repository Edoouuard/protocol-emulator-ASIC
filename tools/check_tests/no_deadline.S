/* EXPECT no_deadlines
 * No deadline at all: the checker must not claim a timing proof. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    li   t0, 1
1:  PIN_OUT(zero, t0, t0)
    j    1b
