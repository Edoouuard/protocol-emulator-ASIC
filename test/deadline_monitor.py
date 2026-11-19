# SPDX-License-Identifier: Apache-2.0
"""Watches the pin/timing unit and records, for every WAIT_UNTIL, how many cycles
the code took since the previous timing anchor and whether the deadline was missed.

A deadline is missed when, the first time the WAIT_UNTIL is evaluated, the cycle
counter is already past it: the edge that follows will come late.
"""
import cocotb
from cocotb.triggers import RisingEdge

F_TIME, F_WAIT_UNTIL, F_WAIT_PIN, F_TIMER, F_SHIFT = 3, 4, 5, 6, 7


def _s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class DeadlineMonitor:
    def __init__(self, dut):
        self.dut = dut
        self.io = dut.user_project.io
        self.core = dut.user_project.core
        self.misses = []            # (pc, cycles late)
        self.segments = {}          # pc of WAIT_UNTIL -> max observed cycles since anchor
        cocotb.start_soon(self._run())

    async def _run(self):
        io = self.io
        active = False
        anchor = None
        while True:
            await RisingEdge(self.dut.clk)
            try:
                mine = int(io.mine.value)
                ready = int(io.pcpi_ready.value)
                f3 = int(io.funct3.value)
                counter = int(io.counter.value)
                rs1 = int(io.pcpi_rs1.value)
                f7 = int(io.funct7.value)
                dl = int(io.deadline.value)
            except ValueError:
                continue
            if not int(self.dut.user_project.core_resetn.value):
                active, anchor = False, None
                continue
            tick = (f3 == F_TIMER and (f7 & 1)) or f3 == F_SHIFT
            if mine and not ready:
                if not active and (f3 == F_WAIT_UNTIL or tick):   # first evaluation
                    pc = int(self.core.reg_pc.value)
                    late = _s32(counter - (dl if tick else rs1))
                    if late > 0:
                        self.misses.append((pc, late))
                    if anchor is not None:
                        x = counter - anchor
                        self.segments[pc] = max(self.segments.get(pc, 0), x)
                active = True
                # the edge at which an anchor completes: TIME immediately, waits when satisfied
                if f3 == F_TIME or (f3 == F_WAIT_UNTIL and int(io.deadline_reached.value)) \
                        or (tick and int(io.tick_reached.value)) \
                        or (f3 == F_WAIT_PIN and int(io.pins_match.value)):
                    anchor = counter
            else:
                active = False
