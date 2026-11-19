# SPDX-FileCopyrightText: © 2026 Edouard Guillermain
# SPDX-License-Identifier: Apache-2.0
#
# End-to-end tests for PinV: load a RISC-V program through the SPI loader,
# run it, and check the protocol it produces on the pins, cycle by cycle.

from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

PROGRAMS = Path(__file__).parent / "programs"

# Must match the BIT_CYCLES the program was built with (see programs/README.md).
UART_BIT_CYCLES = 64

LOAD, SCK, MOSI = 7, 6, 5
SCK_HALF = 4  # loader SCK half period, in clock cycles (SCK = clk / 8)


_ui_shadow = {}


def set_ui_bit(dut, bit, value):
    # Keep our own copy: writes in the same simulation step are not visible
    # when reading dut.ui_in back, so read-modify-write on the signal loses bits.
    v = _ui_shadow.get(id(dut), 0)
    v = (v | (1 << bit)) if value else (v & ~(1 << bit))
    _ui_shadow[id(dut)] = v
    dut.ui_in.value = v


async def reset(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    dut.ena.value = 1
    _ui_shadow[id(dut)] = 0
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


async def load_program(dut, image: bytes):
    """Shift the program in through the loader (SPI mode 0, MSB first)."""
    set_ui_bit(dut, LOAD, 1)
    await ClockCycles(dut.clk, 8)
    for byte in image:
        for i in range(7, -1, -1):
            set_ui_bit(dut, MOSI, (byte >> i) & 1)
            await ClockCycles(dut.clk, SCK_HALF)
            set_ui_bit(dut, SCK, 1)
            await ClockCycles(dut.clk, SCK_HALF)
            set_ui_bit(dut, SCK, 0)
    await ClockCycles(dut.clk, 8)
    set_ui_bit(dut, LOAD, 0)


class EdgeRecorder:
    """Records (cycle, value) every time one output bit changes."""

    def __init__(self, dut, bit):
        self.dut, self.bit = dut, bit
        self.cycle = 0
        self.edges = []
        cocotb.start_soon(self._run())

    async def _run(self):
        last = None
        while True:
            await RisingEdge(self.dut.clk)
            self.cycle += 1
            try:
                v = (int(self.dut.uo_out.value) >> self.bit) & 1
            except ValueError:
                continue
            if v != last:
                self.edges.append((self.cycle, v))
                last = v


def decode_uart(edges, bit_cycles, start_index=0):
    """Decode 8N1 frames from recorded edges. Returns (bytes, bit_widths)."""
    def level_at(c):
        level = 1
        for (t, v) in edges:
            if t > c:
                break
            level = v
        return level

    out, widths = [], []
    i = start_index
    # At the very start, ignore the reset state until the line first goes idle (high).
    if start_index == 0:
        while i < len(edges) and edges[i][1] != 1:
            i += 1
    while i < len(edges):
        t, v = edges[i]
        if v == 0:  # start bit
            byte = 0
            for b in range(8):
                byte |= level_at(t + bit_cycles * (b + 1) + bit_cycles // 2) << b
            stop = level_at(t + bit_cycles * 9 + bit_cycles // 2)
            assert stop == 1, f"missing stop bit after byte 0x{byte:02x}"
            out.append(byte)
            frame_end = t + bit_cycles * 10
            # every edge inside the frame must sit on an exact multiple of the bit period
            for (te, _) in edges[i:]:
                if te >= frame_end:
                    break
                widths.append((te - t) % bit_cycles)
            while i < len(edges) and edges[i][0] < frame_end:
                i += 1
        else:
            i += 1
    return bytes(out), widths


async def send_uart_byte(dut, byte, bit_cycles, bit=0):
    for level in [0] + [(byte >> b) & 1 for b in range(8)] + [1]:
        set_ui_bit(dut, bit, level)
        await ClockCycles(dut.clk, bit_cycles)


@cocotb.test()
async def test_uart_hello_and_echo(dut):
    """UART TX at an exact bit period, then RX -> TX echo, all in firmware."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)  # RX idle high
    image = (PROGRAMS / "uart_echo.bin").read_bytes()
    dut._log.info(f"loading {len(image)} bytes")

    rec = EdgeRecorder(dut, 0)
    await load_program(dut, image)

    # 6 characters + start-up margin: wait for the whole message to finish.
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 10 * 9)
    text, widths = decode_uart(rec.edges, UART_BIT_CYCLES)
    dut._log.info(f"received {text!r}")
    assert text == b"Hello\n", f"unexpected output {text!r}"
    assert set(widths) == {0}, f"edges off the bit grid: {sorted(set(widths))}"

    n_before = len(rec.edges)
    # The echo loop is single-threaded: it cannot receive while it transmits,
    # so each byte is sent once the previous echo has finished (like typing).
    for byte in b"PinV":
        await send_uart_byte(dut, byte, UART_BIT_CYCLES)
        await ClockCycles(dut.clk, UART_BIT_CYCLES * 12)
    echo, widths = decode_uart(rec.edges, UART_BIT_CYCLES, start_index=n_before)
    dut._log.info(f"echo {echo!r}")
    assert echo == b"PinV", f"unexpected echo {echo!r}"
    assert set(widths) == {0}, f"echo edges off the bit grid: {sorted(set(widths))}"


@cocotb.test()
async def test_reload(dut):
    """Loading again while running restarts the core with the new program."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    image = (PROGRAMS / "uart_echo.bin").read_bytes()
    await load_program(dut, image)
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 15)  # interrupt mid-message

    rec = EdgeRecorder(dut, 0)
    await load_program(dut, image)
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 10 * 7)
    # Skip edges recorded before the core restarted (line forced low by reset).
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    assert text.endswith(b"Hello\n"), f"unexpected output after reload {text!r}"
