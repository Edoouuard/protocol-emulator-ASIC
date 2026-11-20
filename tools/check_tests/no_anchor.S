/* EXPECT rejected: without any anchor
 * The timer starts from a constant, not from the counter: the first deadline
 * may already be in the past. */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(50)
    li   t0, 1000
    li   t1, 50
    SET_TIMER(t0, t1)
1:  WAIT_TICK(zero)
    j    1b
