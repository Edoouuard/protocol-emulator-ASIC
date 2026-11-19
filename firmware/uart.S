/*
 * UART routines shared by all demos. TX on uo_out[0], RX on ui_in[0], 8N1.
 * SPDX-License-Identifier: Apache-2.0
 *
 * BIT_CYCLES = clock frequency / baud rate. Every edge is anchored on an
 * absolute deadline (WAIT_UNTIL), so the bit period does not depend on how
 * many instructions run between edges.
 *
 * Calling convention: arguments/results in a0; uart_tx clobbers a0, a5,
 * t0, t1, t2; uart_rx also clobbers a4.
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

/* Send the byte in a0. One fused SHIFT_OUT per bit: it waits for the
 * deadline, drives the bit, shifts the data and advances the deadline. */
uart_tx:
    PINV_BUDGET(BIT_CYCLES)
    li   t1, BIT_CYCLES
    ori  a0, a0, 0x100      /* stop bit (1) above the 8 data bits */
    slli a0, a0, 1          /* start bit (0) in bit 0 */
    li   a5, 10             /* start + 8 data + stop */
    li   t2, 0              /* TX = output bit 0 */
    TIME(t0)
    add  t0, t0, t1         /* first edge one bit period from now */
    SET_TIMER(t0, t1)
1:  SHIFT_OUT(a0, a0, t2)
    addi a5, a5, -1
    bnez a5, 1b
    WAIT_TICK(zero)         /* hold the stop bit for a full period */
    ret

/* Receive a byte into a0. One fused SHIFT_IN per bit, sampled mid-bit.
 * Everything that can be computed before the start bit is, so the only
 * work between the start edge and the first sample is one add and SET_TIMER.
 * Clobbers a0, a4, a5, t0, t1, t2. */
uart_rx:
    PINV_BUDGET(BIT_CYCLES)
    li   t1, BIT_CYCLES
    li   t2, 1              /* RX = ui_in[0] */
    li   a0, 0
    li   a5, 8
    srli a4, t1, 1
    add  a4, a4, t1         /* 1.5 bit periods: start edge -> middle of bit 0 */
    WAIT_PIN(zero, t2, t2)  /* line idle (high) first */
    WAIT_PIN(t0, t2, zero)  /* start bit: t0 = time of the falling edge */
    add  t0, t0, a4
    SET_TIMER(t0, t1)
2:  SHIFT_IN(a0, a0, zero)  /* input bit 0, LSB first: bits enter at the top */
    addi a5, a5, -1
    bnez a5, 2b
    srli a0, a0, 24
    ret
