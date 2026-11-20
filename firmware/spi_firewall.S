/*
 * SPI bus firewall demo. PinV sits between an SPI host (a microcontroller,
 * possibly compromised) and an SPI flash that holds its firmware. Read
 * commands go through; every other command (write enable, page program,
 * erase, status write...) is dropped before the flash sees a single bit,
 * and logged on the UART as '!' followed by the opcode.
 * SPDX-License-Identifier: Apache-2.0
 *
 *   host side:  SCK = ui[2], MOSI = ui[3], CS_n = ui[4], MISO = uo[4]
 *   flash side: SCK = uo[1], MOSI = uo[2], CS_n = uo[3], MISO = ui[1]
 *   log:        UART TX = uo[0]
 *
 * SPI mode 0. The firewall receives the opcode itself (the flash stays
 * deselected), checks it against the allowlist, then replays it to the flash
 * and mirrors the rest of the transaction in software. The host SCK must
 * leave the firewall time to replay the opcode after the 8th bit: a half
 * period of at least 600 cycles (33 kHz at 40 MHz): replaying the opcode
 * takes about 550 cycles. A hardware filter would run at full speed; this
 * demo shows the policy and the hardening, in 350 bytes of software.
 *
 * Hardening:
 *   - the program locks itself (LOCK): the host cannot reload PinV;
 *   - idle state (SET.IDLE): flash CS_n stays high even during a reload;
 *   - bounded waits (SET.LIMIT): a host that stops mid-byte cannot hang it.
 */
#include "pinv.h"

#ifndef FW_LIMIT
#define FW_LIMIT 100000     /* cycles: longest wait for a host edge */
#endif

#define HSCK  (1 << 2)      /* inputs */
#define HMOSI (1 << 3)
#define HCS   (1 << 4)
#define FMISO (1 << 1)
#define TX    (1 << 0)      /* outputs */
#define FSCK  (1 << 1)
#define FMOSI (1 << 2)
#define FCS   (1 << 3)
#define HMISO (1 << 4)
#define NALLOW 5            /* entries in the allowlist below */

/* Abort the transaction if the last WAIT_PIN gave up. */
#define CHECK_TIMEOUT       PIN_IN(t0) ; srli t0, t0, 16 ; bnez t0, idle

    .section .text.start
    .globl _start
_start:
#ifndef PINV_UNLOCKED
    LOCK
#endif
    li   t0, TX | FCS
    SET_IDLE(t0, zero)                  /* flash deselected, even during a reload */
    li   t1, TX | FSCK | FMOSI | FCS | HMISO
    PIN_OUT(zero, t0, t1)
    li   t0, FW_LIMIT
    SET_LIMIT(t0)
    li   s0, HSCK | HCS
    li   s1, HSCK
    li   a1, HCS
    li   a2, (HSCK | HMOSI) >> 1
    li   a4, FSCK | FMOSI | HMISO

idle:
    li   t1, FSCK | FCS | HMISO
    li   t0, FCS
    PIN_OUT(zero, t0, t1)               /* flash deselected, SCK low */
    WAIT_PIN(zero, a1, a1)              /* host deselected */
    CHECK_TIMEOUT
    WAIT_PIN(zero, a1, zero)            /* host selects */
    CHECK_TIMEOUT

    /* Receive the opcode from the host; the flash sees nothing yet. */
    li   a3, 0
    li   a5, 8
rx:
    WAIT_PIN(zero, s0, s1)              /* SCK high, CS_n still low */
    CHECK_TIMEOUT
    PIN_IN(t0)
    srli t0, t0, 3                      /* MOSI */
    andi t0, t0, 1
    slli a3, a3, 1
    or   a3, a3, t0
    WAIT_PIN(zero, s0, zero)            /* SCK low, CS_n still low */
    CHECK_TIMEOUT
    addi a5, a5, -1
    bnez a5, rx

    /* Allowlist. */
    la   t1, allow
    li   t2, NALLOW
1:  lbu  t0, 0(t1)
    beq  t0, a3, pass
    addi t1, t1, 1
    addi t2, t2, -1
    bnez t2, 1b

blocked:
    WAIT_PIN(zero, a1, a1)              /* let the host finish, flash untouched */
    li   a0, '!'
    call uart_tx
    mv   a0, a3
    call uart_tx
    j    idle

pass:
    li   t1, FCS
    PIN_OUT(zero, zero, t1)             /* select the flash */
    slli t1, a3, 24                     /* opcode MSB in bit 31 */
    li   a5, 8
    li   t2, FSCK | FMOSI
2:  srli t0, t1, 29                     /* MSB -> bit 2 (FMOSI), SCK low */
    andi t0, t0, FMOSI
    PIN_OUT(zero, t0, t2)
    li   t0, FSCK
    PIN_OUT(zero, t0, t0)               /* rising edge: the flash samples */
    slli t1, t1, 1
    addi a5, a5, -1
    bnez a5, 2b
    li   t0, FSCK
    PIN_OUT(zero, zero, t0)

    /* Mirror the rest of the transaction until the host deselects. */
mirror:
    PIN_IN(t0)
    and  t1, t0, a1
    bnez t1, idle                       /* host CS_n high: done */
    srli t1, t0, 1                      /* host SCK, MOSI -> flash SCK, MOSI */
    and  t1, t1, a2
    slli t2, t0, 3                      /* flash MISO -> host MISO */
    andi t2, t2, HMISO
    or   t1, t1, t2
    PIN_OUT(zero, t1, a4)
    j    mirror

    .section .rodata
allow:                                  /* commands that cannot change the flash */
    .byte 0x03                          /* READ */
    .byte 0x0B                          /* FAST READ */
    .byte 0x05                          /* READ STATUS */
    .byte 0x9F                          /* JEDEC ID */
    .byte 0x90                          /* MANUFACTURER/DEVICE ID */

