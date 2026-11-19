/*
 * UART demo: prints "Hello\n", then echoes every received byte.
 * TX on uo_out[0], RX on ui_in[0]. 8N1, LSB first.
 * SPDX-License-Identifier: Apache-2.0
 *
 * BIT_CYCLES = clock frequency / baud rate, set at build time
 * (e.g. 60 MHz / 115200 = 521). Every edge is anchored on an absolute
 * deadline with WAIT_UNTIL, so the bit period does not depend on how many
 * instructions run between edges.
 */
#include "pinv.h"

#ifndef BIT_CYCLES
#define BIT_CYCLES 521
#endif

    .section .text.start
    .globl _start
_start:
    li   s0, BIT_CYCLES
    li   s1, 1              /* mask for TX = bit 0 */
    PIN_OUT(zero, s1, s1)   /* line idle high */

    la   a2, hello
1:  lbu  a0, 0(a2)
    beqz a0, echo
    call uart_tx
    addi a2, a2, 1
    j    1b

echo:
    call uart_rx
    call uart_tx
    j    echo

/* Send byte a0. Uses a1, a3, a4, a5. */
uart_tx:
    ori  a0, a0, 0x100      /* stop bit (1) above the 8 data bits */
    slli a0, a0, 1          /* start bit (0) in bit 0 */
    li   a3, 10             /* start + 8 data + stop */
    TIME(a4)
    addi a4, a4, 32         /* first edge 32 cycles from now */
2:  WAIT_UNTIL(zero, a4)
    PIN_OUT(zero, a0, s1)   /* drive bit 0 of a0 on TX */
    srli a0, a0, 1
    add  a4, a4, s0
    addi a3, a3, -1
    bnez a3, 2b
    WAIT_UNTIL(zero, a4)    /* hold the stop bit for a full period */
    ret

/* Receive a byte into a0. Uses a1, a3, a4, a5. */
uart_rx:
    li   a5, 1              /* RX = ui_in[0] */
    WAIT_PIN(zero, a5, a5)  /* line must be idle (high) first */
    WAIT_PIN(a4, a5, zero)  /* start bit: a4 = time of falling edge */
    srli a1, s0, 1
    add  a4, a4, a1         /* middle of the start bit */
    li   a0, 0
    li   a3, 8
3:  add  a4, a4, s0         /* middle of next data bit */
    WAIT_UNTIL(zero, a4)
    PIN_IN(a1)
    andi a1, a1, 1
    slli a1, a1, 8
    or   a0, a0, a1
    srli a0, a0, 1          /* shift in LSB first */
    addi a3, a3, -1
    bnez a3, 3b
    ret

    .section .rodata
hello:
    .asciz "Hello\n"
