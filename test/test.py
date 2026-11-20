# SPDX-FileCopyrightText: © 2026 Edouard Guillermain
# SPDX-License-Identifier: Apache-2.0
#
# End-to-end tests for PinV: load a RISC-V program through the SPI loader,
# run it, and check the protocol it produces on the pins, cycle by cycle.

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from deadline_monitor import GATE_LEVEL, DeadlineMonitor

PROGRAMS = Path(__file__).parent / "programs"
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from pinv_check import verify_cert  # noqa: E402


def proven_image(name):
    """The image of a test program, only if its proof certificate matches it
    byte for byte (same SHA-256, made by this version of pinv_check)."""
    image, cert = PROGRAMS / f"{name}.bin", PROGRAMS / f"{name}.proof.json"
    assert verify_cert(image, cert), f"{name}.bin has no valid proof certificate: run programs/build.sh"
    return image.read_bytes()

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
    image = proven_image("uart_echo")
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
    image = proven_image("uart_echo")
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
    await load_program(dut, proven_image(f"spi_jedec_mode{mode}"))
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

I2C_Q = 60  # must match the I2C_Q the program was built with


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
    await load_program(dut, proven_image("i2c_read"))
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
    await load_program(dut, proven_image("i2c_read"))
    await ClockCycles(dut.clk, 6000)
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    assert dev.log == ["START", ("addr", 0xD0, "NACK"), "STOP"], f"unexpected {dev.log}"
    assert text == b"!", f"unexpected output {text!r}"


@cocotb.test()
async def test_i2c_stuck_bus(dut):
    """Security: a device that holds SCL low forever cannot hang the chip.
    Every wait on SCL is bounded; the program finishes and reports '#'."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    rec = EdgeRecorder(dut, 0)
    dev = I2cDevice(dut, 0x68, {0x75: 0x71})
    await load_program(dut, proven_image("i2c_read"))
    # let the address byte go through, then hold SCL low for good
    await ClockCycles(dut.clk, 60 * I2C_Q)
    dut.scl_dev_low.value = 1
    await ClockCycles(dut.clk, 60000)
    text, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    dut._log.info(f"I2C log {dev.log}, UART {text!r}")
    assert text == b"#", f"expected the stuck-bus report, got {text!r}"


@cocotb.test()
async def test_lock(dut):
    """Security: once the program has executed LOCK, the LOAD pin is ignored:
    the program can neither be replaced nor stopped from outside."""
    await reset(dut)
    set_ui_bit(dut, 0, 1)
    await load_program(dut, proven_image("uart_echo_locked"))
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 10 * 8)   # "Hello\n" sent

    # Try to load another program; watch that the core is never held in reset.
    stopped = []

    async def watch():
        while True:
            await RisingEdge(dut.clk)
            if int(dut.user_project.core_resetn.value) == 0:
                stopped.append(1)

    if not GATE_LEVEL:   # internal signals only exist in RTL simulation
        w = cocotb.start_soon(watch())
    await load_program(dut, proven_image("i2c_read"))
    if not GATE_LEVEL:
        w.cancel()
        assert not stopped, "LOAD stopped the core although the chip is locked"
        assert int(dut.user_project.locked.value) == 1

    # The original program still runs: it echoes.
    rec = EdgeRecorder(dut, 0)
    await send_uart_byte(dut, ord("K"), UART_BIT_CYCLES)
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 12 + 300)
    echo, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    assert echo == b"K", f"locked program no longer echoes: {echo!r}"

    # A reset unlocks the chip.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    if not GATE_LEVEL:
        assert int(dut.user_project.locked.value) == 0


# ---------------------------------------------------------------------------
# WS2812 LEDs: the PULSE waveform serializer
# ---------------------------------------------------------------------------

WS_PERIOD, WS_T0, WS_T1, WS_RESET = 50, 16, 32, 12000   # firmware defaults
WS_COLORS = [0xFF0000, 0x00FF00, 0x0000FF, 0xA5C35A]    # 0xGGRRBB, as in ws2812.S


def decode_ws2812(edges):
    """Split the line into frames of (rise cycle, high time) pulses."""
    pulses, rise = [], None
    for cycle, v in edges:
        if v == 1:
            rise = cycle
        elif rise is not None:
            pulses.append((rise, cycle - rise))
            rise = None
    frames, cur = [], []
    for p in pulses:
        if cur and p[0] - cur[-1][0] > WS_RESET // 2:
            frames.append(cur)
            cur = []
        cur.append(p)
    if cur:
        frames.append(cur)
    return frames


@cocotb.test()
async def test_ws2812(dut):
    """WS2812 LED chain: one PULSE per bit, both edges exact to the cycle."""
    await reset(dut)
    rec = EdgeRecorder(dut, 1)
    mon = DeadlineMonitor(dut)
    await load_program(dut, proven_image("ws2812"))
    await ClockCycles(dut.clk, 2 * (24 * 4 * WS_PERIOD + WS_RESET) + 3000)

    frames = decode_ws2812(rec.edges)
    assert len(frames) >= 2, f"expected two frames, got {len(frames)}"
    colors = WS_COLORS
    for n, frame in enumerate(frames[:2]):
        assert len(frame) == 96, f"frame {n}: {len(frame)} bits instead of 96"
        widths = {w for _, w in frame}
        assert widths <= {WS_T0, WS_T1}, f"frame {n}: pulse widths {sorted(widths)}"
        periods = {b[0] - a[0] for a, b in zip(frame, frame[1:])}
        assert periods == {WS_PERIOD}, f"frame {n}: bit periods {sorted(periods)}"
        bits = [1 if w == WS_T1 else 0 for _, w in frame]
        words = [int("".join(map(str, bits[i:i + 24])), 2) for i in range(0, 96, 24)]
        dut._log.info(f"frame {n}: {[f'{w:06x}' for w in words]}")
        assert words == colors, f"frame {n}: {[hex(w) for w in words]}"
        colors = colors[1:] + colors[:1]   # the program rotates by one LED
    gap = frames[1][0][0] - (frames[0][-1][0] + frames[0][-1][1])
    assert gap >= WS_RESET, f"latch time {gap} < {WS_RESET}"
    assert not mon.misses, f"missed deadlines: {mon.misses}"


@cocotb.test()
async def test_idle_state(dut):
    """SET.IDLE: during a program reload the outputs hold the idle state the
    program chose (here UART TX high), not zero; a chip reset clears it."""
    await reset(dut)
    await load_program(dut, proven_image("uart_echo"))
    await ClockCycles(dut.clk, 200)
    set_ui_bit(dut, LOAD, 1)                    # reload: core held in reset
    await ClockCycles(dut.clk, 20)
    assert int(dut.uo_out.value) == 0x00, "without SET.IDLE the outputs reset to 0"
    set_ui_bit(dut, LOAD, 0)

    await load_program(dut, proven_image("ws2812"))
    await ClockCycles(dut.clk, 200)             # SET.IDLE executed
    set_ui_bit(dut, LOAD, 1)
    await ClockCycles(dut.clk, 20)
    assert int(dut.uo_out.value) == 0x01, f"idle state not applied: {int(dut.uo_out.value):#x}"
    await ClockCycles(dut.clk, 2000)            # held for the whole reload
    assert int(dut.uo_out.value) == 0x01
    set_ui_bit(dut, LOAD, 0)

    dut.rst_n.value = 0                         # chip reset clears it
    await ClockCycles(dut.clk, 5)
    assert int(dut.uo_out.value) == 0x00, "chip reset must clear the idle state"
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


# ---------------------------------------------------------------------------
# SPI bus firewall: host <-> PinV <-> flash
# ---------------------------------------------------------------------------

FW_HALF = 600   # host SCK half period, cycles (see spi_firewall.S)


class FlashMemory:
    """SPI flash model (mode 0) behind the firewall: SCK = uo[1], MOSI = uo[2],
    CS_n = uo[3], MISO = ui[1]. Executes READ, JEDEC ID, WREN, PAGE PROGRAM,
    SECTOR ERASE, so a command that got through would really change it."""

    def __init__(self, dut, size=256):
        self.dut = dut
        self.mem = bytearray((i * 7 + 3) & 0xFF for i in range(size))
        self.wel = False
        self.commands = []      # every opcode the flash received
        cocotb.start_soon(self._run())

    def _respond(self, cmd_bytes):
        op = cmd_bytes[0]
        if op == 0x9F:
            return SPI_JEDEC_ID
        if op == 0x03 and len(cmd_bytes) >= 4:
            a = (cmd_bytes[1] << 16) | (cmd_bytes[2] << 8) | cmd_bytes[3]
            return [self.mem[(a + i) % len(self.mem)] for i in range(64)]
        return []

    async def _run(self):
        prev_sck, prev_cs = 0, 1
        cur, nbits, rx, out = 0, 0, [], []
        while True:
            await RisingEdge(self.dut.clk)
            try:
                v = int(self.dut.uo_out.value)
            except ValueError:
                continue
            sck, mosi, cs = (v >> 1) & 1, (v >> 2) & 1, (v >> 3) & 1
            if cs == 1:
                if prev_cs == 0 and rx:
                    self._execute(rx)
                cur, nbits, rx, out = 0, 0, [], []
                set_ui_bit(self.dut, 1, 0)
            elif sck and not prev_sck:          # rising: sample MOSI
                cur = ((cur << 1) | mosi) & 0xFF
                nbits += 1
                if nbits % 8 == 0:
                    rx.append(cur)
                    if len(rx) == 1:
                        self.commands.append(cur)
                    if not out:
                        out = [(b >> i) & 1 for b in self._respond(rx) for i in range(7, -1, -1)]
            elif not sck and prev_sck and out:  # falling: shift out the next bit
                set_ui_bit(self.dut, 1, out.pop(0))
            prev_sck, prev_cs = sck, cs

    def _execute(self, rx):
        op = rx[0]
        if op == 0x06:
            self.wel = True
        elif op == 0x02 and self.wel and len(rx) >= 4:
            a = (rx[1] << 16) | (rx[2] << 8) | rx[3]
            for i, b in enumerate(rx[4:]):
                self.mem[(a + i) % len(self.mem)] &= b
            self.wel = False
        elif op == 0x20 and self.wel and len(rx) >= 4:
            a = ((rx[1] << 16) | (rx[2] << 8) | rx[3]) & ~0xFF
            for i in range(256):
                self.mem[(a + i) % len(self.mem)] = 0xFF
            self.wel = False


async def host_transfer(dut, tx, nread=0):
    """SPI host, mode 0: SCK = ui[2], MOSI = ui[3], CS_n = ui[4], MISO = uo[4]."""
    out = []
    set_ui_bit(dut, 4, 0)
    await ClockCycles(dut.clk, FW_HALF)
    for byte in list(tx) + [0] * nread:
        val = 0
        for i in range(7, -1, -1):
            set_ui_bit(dut, 3, (byte >> i) & 1)
            await ClockCycles(dut.clk, FW_HALF)
            set_ui_bit(dut, 2, 1)
            val = (val << 1) | ((int(dut.uo_out.value) >> 4) & 1)
            await ClockCycles(dut.clk, FW_HALF)
            set_ui_bit(dut, 2, 0)
        out.append(val)
    await ClockCycles(dut.clk, FW_HALF)
    set_ui_bit(dut, 4, 1)
    await ClockCycles(dut.clk, FW_HALF)
    return out[len(tx):]


@cocotb.test()
async def test_spi_firewall(dut):
    """Cyber demo: reads reach the flash, write and erase commands from the
    host are dropped before the flash sees them, and logged on the UART."""
    await reset(dut)
    set_ui_bit(dut, 4, 1)                       # host CS_n idle
    rec = EdgeRecorder(dut, 0)
    flash = FlashMemory(dut)
    before = bytes(flash.mem)
    await load_program(dut, proven_image("spi_firewall"))
    await ClockCycles(dut.clk, 200)

    jedec = await host_transfer(dut, [0x9F], 3)
    assert jedec == SPI_JEDEC_ID, f"JEDEC ID through the firewall: {jedec}"
    data = await host_transfer(dut, [0x03, 0x00, 0x00, 0x10], 4)
    assert data == list(before[0x10:0x14]), f"READ through the firewall: {data}"

    # Attack: write enable, page program, sector erase.
    await host_transfer(dut, [0x06])
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 25)
    await host_transfer(dut, [0x02, 0x00, 0x00, 0x10, 0x00, 0x00])
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 25)
    await host_transfer(dut, [0x20, 0x00, 0x00, 0x00])
    await ClockCycles(dut.clk, UART_BIT_CYCLES * 25)

    assert bytes(flash.mem) == before, "the flash was modified through the firewall"
    assert flash.commands == [0x9F, 0x03], f"commands that reached the flash: {flash.commands}"
    log, _ = decode_uart(rec.edges, UART_BIT_CYCLES)
    dut._log.info(f"firewall log {log!r}")
    assert log == b"!\x06!\x02!\x20", f"firewall log {log!r}"

    # Still serving reads after the attack.
    data = await host_transfer(dut, [0x03, 0x00, 0x00, 0x20], 2)
    assert data == list(before[0x20:0x22]), f"READ after the attack: {data}"

    # The host cannot reload PinV to remove the firewall: LOAD is ignored.
    set_ui_bit(dut, LOAD, 1)
    await ClockCycles(dut.clk, 50)
    assert (int(dut.uo_out.value) >> 3) & 1 == 1, "flash deselected"
    set_ui_bit(dut, LOAD, 0)
    data = await host_transfer(dut, [0x9F], 3)
    assert data == SPI_JEDEC_ID, "firewall stopped by the LOAD pin"
