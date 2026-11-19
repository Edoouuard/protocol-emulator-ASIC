"""Generate micro-benchmark programs that time one instruction class with the cycle counter.

Each program: TIME(t0); <body repeated N times>; TIME(t1); a0 = t1 - t0; store a0 at 0x1F0; spin.
Body cost = (measure - baseline of the same layout) / N.
"""
import os, subprocess, json, sys

N = 16
CC = "riscv64-unknown-elf-gcc"
FW = os.path.join(os.path.dirname(__file__), "..", "..", "firmware")

R32 = ".option push\n.option norvc\n{}\n.option pop"   # force a 32-bit encoding

# name -> (setup, body). Body is repeated N times. Registers: t0/t1 reserved.
CASES = {
    "c.addi":        ("", "c.addi a1, 1"),
    "addi":          ("", R32.format("addi a1, a1, 1")),
    "c.add":         ("", "c.add a1, a2"),
    "add":           ("", R32.format("add a1, a1, a2")),
    "c.li":          ("", "c.li a1, 5"),
    "lui":           ("", R32.format("lui a1, 0x12345")),
    "c.lui":         ("", "c.lui a1, 0x12"),
    "slt":           ("", R32.format("slt a1, a2, a3")),
    "c.lw":          ("li a2, 0x100", "c.lw a1, 0(a2)"),
    "lw":            ("li a2, 0x100", R32.format("lw a1, 0(a2)")),
    "lbu":           ("li a2, 0x100", R32.format("lbu a1, 1(a2)")),
    "c.sw":          ("li a2, 0x100", "c.sw a1, 0(a2)"),
    "sw":            ("li a2, 0x100", R32.format("sw a1, 0(a2)")),
    "sb":            ("li a2, 0x100", R32.format("sb a1, 1(a2)")),
    "c.beqz_nt":     ("li a1, 1", "c.beqz a1, 9f"),
    "beq_nt":        ("li a1, 1", R32.format("beq a1, zero, 9f")),
    "c.beqz_t":      ("li a1, 0", "c.beqz a1, 1f\n1:"),
    "beq_t":         ("li a1, 0", R32.format("beq a1, zero, 1f") + "\n1:"),
    "c.j":           ("", "c.j 1f\n1:"),
    "jal":           ("", R32.format("jal zero, 1f") + "\n1:"),
    "call_ret":      ("", R32.format("jal ra, 8f")),
    "c.mv":          ("", "c.mv a1, a2"),
    "PIN_OUT":       ("", "PIN_OUT(zero, zero, zero)"),
    "PIN_IN":        ("", "PIN_IN(a1)"),
    "PIN_DIR":       ("", "PIN_DIR(zero, zero, zero)"),
    "TIME":          ("", "TIME(a1)"),
    "WAIT_UNTIL":    ("", "WAIT_UNTIL(zero, zero)"),
    "WAIT_PIN":      ("", "WAIT_PIN(zero, zero, zero)"),
}
for k in [0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 31]:
    CASES[f"c.slli{k}"] = ("", f"c.slli a1, {k}") if k else ("", "nop")  # c.slli 0 is a hint; skip
    CASES[f"slli{k}"] = ("", R32.format(f"slli a1, a1, {k}"))
    CASES[f"c.srli{k}"] = ("", f"c.srli a1, {k}") if k else ("", "nop")
    CASES[f"srai{k}"] = ("", R32.format(f"srai a1, a1, {k}"))
    CASES[f"sll_reg{k}"] = (f"li a2, {k}", R32.format("sll a1, a1, a2"))

TEMPLATE = """#include "pinv.h"
    .section .text.start
    .globl _start
_start:
    li   a1, 0
    li   a2, 0
    li   a3, 0
    {setup}
    .balign 4
    {misalign}
    TIME(t0)
    .rept {n}
    {body}
    .endr
    TIME(t1)
    sub  a0, t1, t0
    sw   a0, 0x1F0(zero)
7:  j    7b
8:  ret
9:  j    9b
"""

def build(name, setup, body, misalign, n, outdir):
    src = TEMPLATE.format(setup=setup, body=body.replace("\n", "\n    "),
                          misalign="c.nop" if misalign else "", n=n)
    s = os.path.join(outdir, name + ".S")
    open(s, "w").write(src)
    elf = s[:-2] + ".elf"
    r = subprocess.run([CC, "-march=rv32ec", "-mabi=ilp32e", "-nostdlib", "-nostartfiles",
                        "-I", FW, "-T", os.path.join(FW, "link.ld"), "-o", elf, s],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{name}: {r.stderr}")
    subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, elf[:-4] + ".bin"], check=True)
    return elf[:-4] + ".bin"

if __name__ == "__main__":
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    jobs = []
    for mis in (0, 1):
        tag = "_mis" if mis else ""
        jobs.append({"name": "base" + tag, "bin": build("base" + tag, "", "", mis, 0, outdir), "n": 0, "case": "base", "mis": mis})
        for name, (setup, body) in CASES.items():
            jobs.append({"name": name + tag, "bin": build(name + tag, setup, body, mis, N, outdir),
                         "n": N, "case": name, "mis": mis})
    json.dump(jobs, open(os.path.join(outdir, "jobs.json"), "w"), indent=1)
    print(len(jobs), "programs")
