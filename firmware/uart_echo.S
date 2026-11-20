/*
 * UART demo: prints "Hello\n", then echoes every received byte.
 * TX on uo_out[0], RX on ui_in[0] (routines in uart.S).
 * SPDX-License-Identifier: Apache-2.0
 */
#include "pinv.h"

    .section .text.start
    .globl _start
_start:
#ifdef PINV_LOCKED
    LOCK                    /* from here on, LOAD is ignored until reset */
#endif
    call uart_init
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

    .section .rodata
hello:
    .asciz "Hello\n"
