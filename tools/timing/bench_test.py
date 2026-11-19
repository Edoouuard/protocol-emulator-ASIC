"""cocotb runner: load each micro-benchmark, read the measured cycle count from memory word 0x1F0."""
import json, os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

JOBS = os.environ["BENCH_DIR"]
LOAD, SCK, MOSI = 7, 6, 5


async def load(dut, image):
    ui = 1 << LOAD
    dut.ui_in.value = ui
    await ClockCycles(dut.clk, 4)
    for byte in image:
        for i in range(7, -1, -1):
            ui = (ui & ~(1 << MOSI)) | (((byte >> i) & 1) << MOSI)
            dut.ui_in.value = ui
            await ClockCycles(dut.clk, 2)
            dut.ui_in.value = ui | (1 << SCK)
            await ClockCycles(dut.clk, 2)
            dut.ui_in.value = ui
    await ClockCycles(dut.clk, 4)
    dut.ui_in.value = 0


@cocotb.test()
async def bench(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.ena.value = 1
    dut.uio_in.value = 0
    jobs = json.load(open(os.path.join(JOBS, "jobs.json")))
    results = {}
    for job in jobs:
        dut.rst_n.value = 0
        dut.ui_in.value = 0
        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 2)
        img = open(job["bin"], "rb").read()
        img = img + bytes(max(0, 0x1F4 - len(img)))[: max(0, 0x1F4 - len(img))]  # clear result word
        await load(dut, img)
        val = 0
        for _ in range(200):
            await ClockCycles(dut.clk, 20)
            try:
                val = int(dut.user_project.mem[0x1F0 // 4].value)
            except ValueError:
                val = 0
            if val:
                break
        results[job["name"]] = val
    json.dump(results, open(os.path.join(JOBS, "results.json"), "w"), indent=1)
