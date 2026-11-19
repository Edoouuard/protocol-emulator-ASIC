# SPDX-FileCopyrightText: © 2026 Edouard Guillermain
# SPDX-License-Identifier: Apache-2.0
#
# End-to-end tests for PinV: load a RISC-V program through the SPI loader,
# run it, and check the protocol it produces on the pins, cycle by cycle.

from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from deadline_monitor import DeadlineMonitor

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
    mon = DeadlineMonitor(dut)
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
        # the echo takes 10 bit periods plus a fixed set-up time in cycles
        await ClockCycles(dut.clk, UART_BIT_CYCLES * 12 + 300)
    echo, widths = decode_uart(rec.edges, UART_BIT_CYCLES, start_index=n_before)
    dut._log.info(f"echo {echo!r}")
    assert echo == b"PinV", f"unexpected echo {echo!r}"
    assert set(widths) == {0}, f"echo edges off the bit grid: {sorted(set(widths))}"
    assert not mon.misses, f"missed deadlines: {mon.misses}"
    dut._log.info(f"deadlines: worst observed segments {mon.segments}")


@cocotb.test()
async def test_reload(dut):
    """Loading again while running restarts the core with the new program."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    image = (PROGRAMS / "uart_echo.bin").read_bytes()
    await load_program(dut, image)
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 15)  # interrupt mid-message

    await load_program(dut, image)
    # Record from the restart: the line is low while the core is in reset,
    # then goes idle (high) when the new program starts.
    rec = EdgeRecorder(dut, 0)
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 10 * 8)
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    assert text.endswith(b"Hello\n"), f"unexpected output after reload {text!r}"


# ---------------------------------------------------------------------------
# SPI: simulated SPI flash answering the JEDEC ID command (0x9F)
# ---------------------------------------------------------------------------

SPI_JEDEC_ID = [0xEF, 0x40, 0x18]  # Winbond W25Q128


class SpiFlash:
    """SPI slave model: SCK = uo[1], MOSI = uo[2], CS_n = uo[3], MISO = ui[1]."""

    def __init__(self, dut, mode, response):
        self.dut = dut
        self.cpol, self.cpha = (mode >> 1) & 1, mode & 1
        self.response = response
        self.received = []
        self.idle_errors = 0
        cocotb.start_soon(self._run())

    def _drive(self, bits, idx):
        set_ui_bit(self.dut, 1, bits[idx] if idx < len(bits) else 1)

    async def _run(self):
        prev = None
        bits, idx, cur, nbits = [], 0, 0, 0
        while True:
            await RisingEdge(self.dut.clk)
            try:
                v = int(self.dut.uo_out.value)
            except ValueError:
                continue
            sck, mosi, cs = (v >> 1) & 1, (v >> 2) & 1, (v >> 3) & 1
            if prev is None:
                prev = (sck, cs)
                continue
            psck, pcs = prev
            if pcs == 1 and cs == 0:  # selected
                bits = [(b >> i) & 1 for b in self.response for i in range(7, -1, -1)]
                idx, cur, nbits = 0, 0, 0
                if self.cpha == 0:  # first bit must be ready before the first edge
                    self._drive(bits, idx)
                    idx += 1
            elif cs == 0 and sck != psck:
                leading = sck != self.cpol
                if leading == (self.cpha == 0):  # sampling edge
                    cur = (cur << 1) | mosi
                    nbits += 1
                    if nbits % 8 == 0:
                        self.received.append(cur & 0xFF)
                else:  # shifting edge
                    self._drive(bits, idx)
                    idx += 1
            elif cs == 1 and pcs == 1 and sck != self.cpol and len(self.received) > 0:
                self.idle_errors += 1  # SCK not at its idle level while deselected
            prev = (sck, cs)


async def run_spi_mode(dut, mode):
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    rec = EdgeRecorder(dut, 0)
    flash = SpiFlash(dut, mode, [0x00] + SPI_JEDEC_ID)
    mon = DeadlineMonitor(dut)
    await load_program(dut, (PROGRAMS / f"spi_jedec_mode{mode}.bin").read_bytes())
    await ClockCycles(dut.clk, 9000)
    text, widths = decode_uart(rec.edges, UART_BIT_CYCLES)
    dut._log.info(f"mode {mode}: MOSI {bytes(flash.received).hex()} UART {text.hex()}")
    assert flash.received == [0x9F, 0, 0, 0], f"bad MOSI bytes {flash.received}"
    assert list(text) == SPI_JEDEC_ID, f"bad ID printed {text.hex()}"
    assert set(widths) == {0}
    assert flash.idle_errors == 0, "SCK not at idle level after deselect"
    assert not mon.misses, f"missed deadlines: {mon.misses}"
    dut._log.info(f"deadlines: worst observed segments {mon.segments}")


@cocotb.test()
async def test_spi_mode0(dut):
    """SPI mode 0: read a flash JEDEC ID and print it on the UART."""
    await run_spi_mode(dut, 0)


@cocotb.test()
async def test_spi_mode1(dut):
    """SPI mode 1."""
    await run_spi_mode(dut, 1)


@cocotb.test()
async def test_spi_mode2(dut):
    """SPI mode 2."""
    await run_spi_mode(dut, 2)


@cocotb.test()
async def test_spi_mode3(dut):
    """SPI mode 3."""
    await run_spi_mode(dut, 3)


# ---------------------------------------------------------------------------
# I2C: simulated device with one register, open-drain bus, clock stretching
# ---------------------------------------------------------------------------

I2C_Q = 56  # must match the I2C_Q the program was built with


class I2cDevice:
    """I2C slave model on the testbench's open-drain bus (tb.sda_bus / tb.scl_bus)."""

    def __init__(self, dut, address, registers, stretch=0):
        self.dut = dut
        self.address = address
        self.registers = registers
        self.stretch = stretch
        self.log = []
        self.scl_edges = []
        dut.sda_dev_low.value = 0
        dut.scl_dev_low.value = 0
        cocotb.start_soon(self._run())

    def _sda(self, level):
        self.dut.sda_dev_low.value = 0 if level else 1

    async def _stretch(self):
        self.dut.scl_dev_low.value = 1
        await ClockCycles(self.dut.clk, self.stretch)
        self.dut.scl_dev_low.value = 0

    async def _run(self):
        prev = None
        state, nbits, cur, ack_bit = "idle", 0, 0, 1
        reading, out, ptr, cycle = False, 0, 0, 0
        while True:
            await RisingEdge(self.dut.clk)
            cycle += 1
            try:
                sda, scl = int(self.dut.sda_bus.value), int(self.dut.scl_bus.value)
            except ValueError:
                continue
            if prev is None:
                prev = (sda, scl)
                continue
            psda, pscl = prev
            prev = (sda, scl)
            if scl != pscl:
                self.scl_edges.append((cycle, scl))
            if scl == 1 and pscl == 1 and sda != psda:
                self._sda(1)
                if sda == 0:
                    self.log.append("START")
                    state, nbits, cur = "addr", 0, 0
                else:
                    self.log.append("STOP")
                    state = "idle"
                continue
            if state == "idle":
                continue
            if scl == 1 and pscl == 0:  # rising edge: sample
                if nbits < 8:
                    cur = ((cur << 1) | sda) & 0xFF
                    nbits += 1
                elif nbits == 9:
                    ack_bit = sda
            elif scl == 0 and pscl == 1:  # falling edge: drive
                if nbits == 8:  # start of the 9th clock
                    nbits = 9
                    if state == "addr":
                        match = (cur >> 1) == self.address
                        reading = bool(cur & 1)
                        self.log.append(("addr", cur, "ACK" if match else "NACK"))
                        self._sda(0 if match else 1)
                        if not match:
                            state = "ignore"
                        elif self.stretch:
                            cocotb.start_soon(self._stretch())
                    elif state in ("write", "ptr"):
                        self.log.append(("write", cur))
                        if state == "ptr":
                            ptr = cur
                        self._sda(0)
                    elif state == "send":
                        self._sda(1)  # master answers ACK/NACK
                elif nbits == 9:  # end of the 9th clock
                    self._sda(1)
                    nbits, cur = 0, 0
                    if state == "addr":
                        state = "send" if reading else "ptr"
                    elif state == "ptr":
                        state = "write"
                    elif state == "send":
                        self.log.append(("read", out, "ACK" if ack_bit == 0 else "NACK"))
                        if ack_bit != 0:
                            state = "ignore"
                    if state == "send":
                        out = self.registers.get(ptr, 0xFF)
                        ptr += 1
                        self._sda((out >> 7) & 1)
                elif state == "send" and 0 < nbits < 8:
                    self._sda((out >> (7 - nbits)) & 1)


@cocotb.test()
async def test_i2c_register_read(dut):
    """I2C: write register pointer, repeated START, read one byte, with clock stretching."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    rec = EdgeRecorder(dut, 0)
    dev = I2cDevice(dut, 0x68, {0x75: 0x71}, stretch=200)
    mon = DeadlineMonitor(dut)
    await load_program(dut, (PROGRAMS / "i2c_read.bin").read_bytes())
    await ClockCycles(dut.clk, 250 * I2C_Q + 2000)  # 4 bytes of 9 clocks, 4 quarters each
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    dut._log.info(f"I2C log {dev.log}, UART {text.hex()}")
    assert dev.log == [
        "START", ("addr", 0xD0, "ACK"), ("write", 0x75),
        "START", ("addr", 0xD1, "ACK"), ("read", 0x71, "NACK"),
        "STOP",
    ], f"unexpected bus transaction {dev.log}"
    assert list(text) == [0x71], f"bad value printed {text.hex()}"
    highs = [b[0] - a[0] for a, b in zip(dev.scl_edges, dev.scl_edges[1:]) if a[1] == 1]
    lows = [b[0] - a[0] for a, b in zip(dev.scl_edges, dev.scl_edges[1:]) if a[1] == 0]
    dut._log.info(f"SCL high {min(highs)}-{max(highs)} cycles, low {min(lows)}-{max(lows)} cycles")
    assert min(highs) >= 2 * I2C_Q, "SCL high time shorter than the requested half period"
    assert not mon.misses, f"missed deadlines: {mon.misses}"
    dut._log.info(f"deadlines: worst observed segments {mon.segments}")


@cocotb.test()
async def test_i2c_nack(dut):
    """I2C: a missing device (no ACK) is detected; the program prints '!' and sends STOP."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    rec = EdgeRecorder(dut, 0)
    dev = I2cDevice(dut, 0x50, {})
    await load_program(dut, (PROGRAMS / "i2c_read.bin").read_bytes())
    await ClockCycles(dut.clk, 6000)
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    assert dev.log == ["START", ("addr", 0xD0, "NACK"), "STOP"], f"unexpected {dev.log}"
    assert text == b"!", f"unexpected output {text!r}"
