/*
 * WS2812 demo: drives a chain of NLEDS addressable RGB LEDs on uo_out[1]
 * with the PULSE waveform serializer, and rotates the colours every frame.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A WS2812 bit is one period of 1.25 us that starts high: high for 0.4 us
 * for a 0, for 0.8 us for a 1. PULSEM places both edges in hardware: the
 * rising edge at the deadline, the falling edge t0 or t1 cycles later. The
 * software only has to issue one instruction per bit before the next
 * deadline, which pinv_check proves at build time (budget: one period).
 *
 * Settings, in clock cycles (defaults for 40 MHz):
 *   WS_PERIOD  bit period            50  (1.25 us)
 *   WS_T0      high time of a 0      16  (0.40 us)
 *   WS_T1      high time of a 1      32  (0.80 us)
 *   WS_RESET   latch time (low)   12000  (300 us, enough for WS2812B)
 */
#include "pinv.h"

#ifndef WS_PERIOD
#define WS_PERIOD 50
#endif
#ifndef WS_T0
#define WS_T0 16
#endif
#ifndef WS_T1
#define WS_T1 32
#endif
#ifndef WS_RESET
#define WS_RESET 12000
#endif
#define WS_PIN 1            /* uo_out[1] */
#define NLEDS  4

    .section .text.start
    .globl _start
_start:
    /* Idle state while the core is in reset (reload): UART TX high, LED line low. */
    li   t0, 1
    SET_IDLE(t0, zero)
    li   t0, (WS_T1 << 16) | WS_T0
    SET_WAVE(t0)
    li   a2, WS_PIN

frame:
    PINV_BUDGET(WS_PERIOD)
    la   a3, colors
    li   a4, NLEDS
    li   t1, WS_PERIOD
    TIME(t0)
    add  t0, t0, t1
    SET_TIMER(t0, t1)
led:
    lw   a0, 0(a3)          /* 0x00GGRRBB */
    slli a0, a0, 8          /* MSB first: G7 in bit 31 */
    li   a5, 24
bit:
    PULSEM(a0, a0, a2)      /* one bit, both edges placed by the hardware */
    addi a5, a5, -1
    bnez a5, bit
    addi a3, a3, 4
    addi a4, a4, -1
    bnez a4, led

    /* Latch: keep the line low for WS_RESET cycles after the last bit. */
    PINV_BUDGET(WS_RESET)
    TIME(t0)
    li   t1, WS_RESET
    add  t0, t0, t1
    WAIT_UNTIL(zero, t0)

    /* Rotate the colours by one LED for the next frame. */
    la   a3, colors
    lw   t2, 0(a3)
    lw   t0, 4(a3)
    sw   t0, 0(a3)
    lw   t0, 8(a3)
    sw   t0, 4(a3)
    lw   t0, 12(a3)
    sw   t0, 8(a3)
    sw   t2, 12(a3)
    j    frame

    .section .data
    .balign 4
colors:                     /* 0x00GGRRBB */
    .word 0x00FF0000        /* green */
    .word 0x0000FF00        /* red   */
    .word 0x000000FF        /* blue  */
    .word 0x00A5C35A        /* mixed: every bit pattern */
