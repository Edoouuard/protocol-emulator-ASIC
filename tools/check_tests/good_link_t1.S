/* EXPECT proven
 * A routine called with jal t1 and returning with jr t1 (as in i2c_read),
 * and a first deadline 1.5 periods away then 1 period (as in uart_rx). */
#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    PINV_BUDGET(40)
    li   t1, 40
    TIME(t0)
    addi t0, t0, 60
    SET_TIMER(t0, t1)
    li   a5, 4
1:  jal  t2, tick
    addi a5, a5, -1
    bnez a5, 1b
    j    _start
tick:
    WAIT_TICK(zero)
    jr   t2
