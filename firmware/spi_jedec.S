/*
 * SPI master demo: reads the JEDEC ID of an SPI flash (command 0x9F) and
 * prints the 3 ID bytes on the UART.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pins: SCK = uo_out[1], MOSI = uo_out[2], CS_n = uo_out[3], MISO = ui_in[1].
 * SPI_MODE (0-3) selects clock polarity and phase at build time.
 * SPI_HALF = half an SCK period, in clock cycles.
 */
#include "pinv.h"

#ifndef SPI_MODE
#define SPI_MODE 0
#endif
#ifndef SPI_HALF
#define SPI_HALF 48
#endif

#define CPOL ((SPI_MODE >> 1) & 1)
#define CPHA (SPI_MODE & 1)

#define SCK_BIT  2
#define MOSI_BIT 4
#define CS_BIT   8
#define SCK_IDLE   (CPOL * SCK_BIT)
#define SCK_ACTIVE ((1 - CPOL) * SCK_BIT)

    .section .text.start
    .globl _start
_start:
    call uart_init
    /* CS_n high, SCK at its idle level, MOSI low */
    li   a0, CS_BIT | SCK_IDLE
    li   a1, CS_BIT | SCK_BIT | MOSI_BIT
    PIN_OUT(zero, a0, a1)

    li   a1, CS_BIT
    PIN_OUT(zero, zero, a1)       /* select the flash */
    li   a0, 0x9F
    call spi_xfer                 /* command: read JEDEC ID */
    li   s1, 3
1:  li   a0, 0
    call spi_xfer                 /* clock in one ID byte */
    call uart_tx                  /* and print it */
    addi s1, s1, -1
    bnez s1, 1b
    li   a1, CS_BIT
    PIN_OUT(zero, a1, a1)         /* deselect */
2:  j    2b

/*
 * Full-duplex transfer of one byte, MSB first.
 * a0 = byte to send, returns the byte received in a0.
 * Clobbers a1, a3, a4, a5, t0, t1.
 */
spi_xfer:
    li   t1, SPI_HALF
    li   a5, 8
    li   a4, 0
    TIME(t0)
    addi t0, t0, 32
3:  srli a3, a0, 7
    andi a3, a3, 1
    slli a3, a3, 2                /* MOSI position */
#if CPHA == 0
    /* Data changes with SCK at idle (trailing edge of the previous bit)... */
    ori  a3, a3, SCK_IDLE
    li   a1, SCK_BIT | MOSI_BIT
    WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a3, a1)
    add  t0, t0, t1
    /* ...and is sampled on the leading edge. */
    li   a3, SCK_ACTIVE
    li   a1, SCK_BIT
    WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a3, a1)
    PIN_IN(a3)
    add  t0, t0, t1
#else
    /* Data changes on the leading edge... */
    ori  a3, a3, SCK_ACTIVE
    li   a1, SCK_BIT | MOSI_BIT
    WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a3, a1)
    add  t0, t0, t1
    /* ...and is sampled on the trailing edge. */
    li   a3, SCK_IDLE
    li   a1, SCK_BIT
    WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a3, a1)
    PIN_IN(a3)
    add  t0, t0, t1
#endif
    srli a3, a3, 1                /* MISO = ui_in[1] */
    andi a3, a3, 1
    slli a4, a4, 1
    or   a4, a4, a3
    slli a0, a0, 1
    addi a5, a5, -1
    bnez a5, 3b
#if CPHA == 0
    li   a3, SCK_IDLE             /* final trailing edge */
    li   a1, SCK_BIT
    WAIT_UNTIL(zero, t0)
    PIN_OUT(zero, a3, a1)
    add  t0, t0, t1
#endif
    WAIT_UNTIL(zero, t0)
    mv   a0, a4
    ret
