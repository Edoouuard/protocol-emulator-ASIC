/*
 * I2C master demo: reads one register of an I2C device and prints it on
 * the UART. Prints '!' if the device does not acknowledge its address.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pins (open drain, external pull-ups): SDA = uio[0], SCL = uio[1].
 * The output value of both pins stays 0; PIN_DIR drives the line low
 * (output enabled) or releases it (input). After releasing SCL the master
 * waits until the line is really high (clock stretching) and re-anchors
 * its deadlines on that moment.
 *
 * Every wait for SCL to rise is bounded (SET_LIMIT): a device that holds SCL
 * low forever cannot hang the chip. The transaction then completes in bounded
 * time and the program prints '#' instead of the value.
 *
 * I2C_Q = a quarter of an SCL period, in clock cycles. Measured in
 * simulation: SCL high = 2*I2C_Q + about 14 cycles; SCL low is at least
 * about 77 cycles (code time).  I2C_Q = 94 gives about 100 kHz at 40 MHz;
 * the smallest setting the timing checker proves is I2C_Q = 54
 * (about 160 kHz at 40 MHz).
 */
#include "pinv.h"

#ifndef I2C_Q
#define I2C_Q 94
#endif
#ifndef I2C_ADDR
#define I2C_ADDR 0x68
#endif
#ifndef I2C_REG
#define I2C_REG 0x75
#endif
#ifndef I2C_LIMIT
#define I2C_LIMIT 4000              /* max clock stretching, cycles (100 us at 40 MHz) */
#endif

#define SDA 0x100
#define SCL 0x200

/* Wait for the next quarter-period deadline. */
.macro TICK n=1
    .rept \n
    add  s0, s0, s1
    .endr
    WAIT_UNTIL(zero, s0)
.endm
.macro SDA_LOW
    li   a1, SDA
    PIN_DIR(zero, a1, a1)
.endm
.macro SDA_REL
    li   a1, SDA
    PIN_DIR(zero, zero, a1)
.endm
.macro SCL_LOW
    li   a1, SCL
    PIN_DIR(zero, a1, a1)
.endm
/* Release SCL, wait until it is high, re-anchor the deadline on that edge. */
.macro SCL_REL
    li   a1, SCL
    PIN_DIR(zero, zero, a1)
    WAIT_PIN(s0, a1, a1)
.endm
/* Start a new timing anchor now; the next TICK is one quarter period later. */
.macro ANCHOR
    TIME(s0)
.endm

    .section .text.start
    .globl _start
_start:
    call uart_init
    li   s1, I2C_Q
    li   a0, I2C_LIMIT
    SET_LIMIT(a0)
    PIN_IN(zero)                  /* clear the timeout flag */

    call i2c_start
    li   a0, (I2C_ADDR << 1) | 0  /* address + write */
    call i2c_write
    bnez a0, nack
    li   a0, I2C_REG              /* register pointer */
    call i2c_write
    bnez a0, nack
    call i2c_rstart
    li   a0, (I2C_ADDR << 1) | 1  /* address + read */
    call i2c_write
    bnez a0, nack
    li   a0, 1                    /* last byte: answer with NACK */
    call i2c_read
    mv   a2, a0
    call i2c_stop
    PIN_IN(a0)                    /* did any wait on SCL give up? */
    li   a1, PIN_TIMED_OUT
    and  a0, a0, a1
    bnez a0, stuck
    mv   a0, a2
    call uart_tx
    j    done
stuck:
    li   a0, '#'
    call uart_tx
    j    done
nack:
    call i2c_stop
    PIN_IN(a0)                    /* a stuck bus can look like a NACK */
    li   a1, PIN_TIMED_OUT
    and  a0, a0, a1
    bnez a0, stuck
    li   a0, '!'
    call uart_tx
done:
    j    done

/* START: SDA falls while SCL is high. Bus assumed idle (both released). */
i2c_start:
    PINV_BUDGET(I2C_Q)
    ANCHOR
    TICK
    SDA_LOW
    TICK 2
    SCL_LOW
    ret

/* Repeated START, from SCL low after an ACK. */
i2c_rstart:
    PINV_BUDGET(I2C_Q)
    ANCHOR
    TICK
    SDA_REL
    TICK
    SCL_REL
    TICK
    SDA_LOW
    TICK
    SCL_LOW
    ret

/* STOP: SDA rises while SCL is high. Called with SCL low. */
i2c_stop:
    PINV_BUDGET(I2C_Q)
    ANCHOR
    TICK
    SDA_LOW
    TICK
    SCL_REL
    TICK 2
    SDA_REL
    ret

/*
 * One SCL clock. a3 = SDA level to present (1 = release, 0 = drive low).
 * Returns a3 = SDA sampled while SCL is high. Called with SCL low and a
 * valid anchor in s0. Return address in t1 (so callers keep ra).
 */
i2c_bit:
    PINV_BUDGET(I2C_Q)
    TICK                          /* middle of SCL low: change SDA */
    xori a3, a3, 1                /* level 0 -> output enable 1 */
    slli a3, a3, 8
    li   a1, SDA
    PIN_DIR(zero, a3, a1)
    TICK
    SCL_REL
    PIN_IN(a3)
    srli a3, a3, 8
    andi a3, a3, 1
    TICK 2
    SCL_LOW
    jr   t1

/* Write the byte in a0. Returns a0 = 0 on ACK, 1 on NACK. Called with SCL low. */
i2c_write:
    PINV_BUDGET(I2C_Q)
    ANCHOR
    li   a5, 8
1:  srli a3, a0, 7
    andi a3, a3, 1
    jal  t1, i2c_bit
    slli a0, a0, 1
    addi a5, a5, -1
    bnez a5, 1b
    li   a3, 1                    /* 9th clock: release SDA, read ACK */
    jal  t1, i2c_bit
    mv   a0, a3
    ret

/* Read a byte into a0. Argument a0 = 1 to answer NACK (last byte), 0 for ACK. */
i2c_read:
    PINV_BUDGET(I2C_Q)
    mv   t2, a0
    ANCHOR
    li   a4, 0
    li   a5, 8
1:  li   a3, 1                    /* release SDA, let the device drive it */
    jal  t1, i2c_bit
    slli a4, a4, 1
    or   a4, a4, a3
    addi a5, a5, -1
    bnez a5, 1b
    mv   a3, t2                   /* 9th clock: ACK (0) or NACK (1) */
    jal  t1, i2c_bit
    mv   a0, a4
    ret
