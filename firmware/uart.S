/*
 * UART routines shared by all demos. TX on uo_out[0], RX on ui_in[0], 8N1.
 * SPDX-License-Identifier: Apache-2.0
 *
 * BIT_CYCLES = clock frequency / baud rate. Every edge is anchored on an
 * absolute deadline (WAIT_UNTIL), so the bit period does not depend on how
 * many instructions run between edges.
 *
 * Calling convention: arguments/results in a0; clobbers a0, a5, t0, t1, t2.
 */
#include "pinv.h"

#ifndef BIT_CYCLES
#define BIT_CYCLES 347      /* 40 MHz / 115200 baud */
#endif

    .text
    .globl uart_init, uart_tx, uart_rx

/* Drive the TX line idle (high). */
uart_init:
    li   t0, 1
    PIN_OUT(zero, t0, t0)
    ret

/* Send the byte in a0. */
uart_tx:
    PINV_BUDGET(BIT_CYCLES)
    li   t1, BIT_CYCLES
    li   t2, 1              /* TX mask = bit 0 */
    ori  a0, a0, 0x100      /* stop bit (1) above the 8 data bits */
    slli a0, a0, 1          /* start bit (0) in bit 0 */
    li   a5, 10             /* start + 8 data + stop */
    TIME(t0)
    add  t0, t0, t1         /* first edge one bit period from now */
1:  WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a0, t2)   /* drive bit 0 of a0 on TX */
    srli a0, a0, 1
    add  t0, t0, t1
    addi a5, a5, -1
    bnez a5, 1b
    WAIT_UNTIL(zero, t0)    /* hold the stop bit for a full period */
    ret

/* Receive a byte into a0. */
uart_rx:
    PINV_BUDGET(BIT_CYCLES)
    li   t1, BIT_CYCLES
    li   t2, 1              /* RX = ui_in[0] */
    WAIT_PIN(zero, t2, t2)  /* line idle (high) first */
    WAIT_PIN(t0, t2, zero)  /* start bit: t0 = time of the falling edge */
    srli a5, t1, 1
    add  t0, t0, a5         /* middle of the start bit */
    li   a0, 0
    li   a5, 8
2:  add  t0, t0, t1         /* middle of the next data bit */
    WAIT_UNTIL(zero, t0)
    PIN_IN(t2)
    andi t2, t2, 1
    slli t2, t2, 8
    or   a0, a0, t2
    srli a0, a0, 1          /* LSB first */
    addi a5, a5, -1
    bnez a5, 2b
    ret
