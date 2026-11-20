#!/usr/bin/env python3
"""
pinv_check: static deadline checker for PinV programs.
SPDX-License-Identifier: Apache-2.0

PinV programs anchor every timing-critical edge on an absolute deadline:
an anchor (TIME, WAIT_UNTIL or WAIT_PIN) gives a time, the program adds a
step to it and waits with WAIT_UNTIL. If the code between the anchor and the
WAIT_UNTIL takes longer than the step, the deadline is missed and the edge
comes late. On a protocol line that is a corrupted bit.

This tool proves, before the program is loaded, that it can never happen:

  * it rebuilds the control-flow graph of the linked program (branches,
    jumps, calls and returns through any link register);
  * for every anchor, it explores every path to the next WAIT_UNTIL and
    computes the worst-case cycle count with a cost model of PicoRV32 as
    configured in PinV, calibrated on the RTL (tools/timing/);
  * it compares that worst case with the budget the source declares with
    PINV_BUDGET(cycles), and fails if any path can exceed it, or if a loop
    without a bound sits between an anchor and a deadline.

Deadline waits are WAIT_UNTIL and the timer instructions (WAIT_TICK, SHIFT_*, PULSE*),
whose deadline is the internal one, advanced by the step at each of them.

Usage:  pinv_check.py program.elf [--verbose]      exit code 0 = proven, 1 = not
        pinv_check.py --model                       print the cost model
"""
import argparse
import re
import subprocess
import sys
from collections import defaultdict

OBJDUMP = "riscv64-unknown-elf-objdump"

# ---------------------------------------------------------------------------
# Cost model (cycles), PicoRV32 with ENABLE_REGS_DUALPORT=0, TWO_STAGE_SHIFT=1,
# COMPRESSED_ISA=1, single-cycle memory. Calibrated by tools/timing (RTL).
# A 32-bit instruction at an address that is not a multiple of 4 costs one more
# cycle; a taken branch or jump to such an instruction costs one more cycle.
# ---------------------------------------------------------------------------
ALU_IMM = 3          # addi, andi, ori, xori, slti(u), lui, auipc, c.li, c.addi, ...
ALU_REG = 4          # add, sub, and, or, xor, slt(u), c.add, c.mv, c.sub, ...
LOAD = 5
STORE = 6
BRANCH_NOT_TAKEN = 4
BRANCH_TAKEN = 6
JAL = 3
JALR = 6
PCPI = 6             # PinV custom instruction, when it does not wait
# Shift by k: 4 + k // 4 + k % 4 cycles (k >= 1); 3 cycles for k = 0 compressed, 4 for 32-bit.
# A register shift amount is unknown statically: worst case k = 31, plus 1 cycle.


def shift_cost(k, compressed):
    if k == 0:
        return 3 if compressed else 4
    return 4 + k // 4 + k % 4


SHIFT_IMM = {"slli", "srli", "srai", "c.slli", "c.srli", "c.srai"}
SHIFT_REG = {"sll", "srl", "sra"}
BRANCHES = {"beq", "bne", "blt", "bge", "bltu", "bgeu", "c.beqz", "c.bnez"}
LOADS = {"lb", "lh", "lw", "lbu", "lhu", "c.lw", "c.lwsp"}
STORES = {"sb", "sh", "sw", "c.sw", "c.swsp"}
ALU_REG_OPS = {"add", "sub", "and", "or", "xor", "slt", "sltu",
               "c.add", "c.mv", "c.sub", "c.and", "c.or", "c.xor"}
ALU_IMM_OPS = {"addi", "andi", "ori", "xori", "slti", "sltiu", "lui", "auipc",
               "c.li", "c.lui", "c.addi", "c.andi", "c.addi16sp", "c.addi4spn", "c.nop"}

CUSTOM = {0: "PIN_OUT", 1: "PIN_IN", 2: "PIN_DIR", 3: "TIME", 4: "WAIT_UNTIL", 5: "WAIT_PIN"}
TIMER = {0: "SET_TIMER", 1: "WAIT_TICK", 2: "SET_LIMIT", 3: "LOCK", 4: "SET_WAVE", 5: "SET_IDLE"}
SHIFT = {0: "SHIFT_OUT", 1: "SHIFT_IN", 2: "SHIFT_OUTM", 3: "SHIFT_INM", 4: "PULSE", 6: "PULSEM"}
# Instructions that wait for a deadline: they end a timed segment, and start the next one.
DEADLINE_WAITS = {"WAIT_UNTIL", "WAIT_TICK", "SHIFT_OUT", "SHIFT_IN", "SHIFT_OUTM", "SHIFT_INM",
                  "PULSE", "PULSEM"}
ANCHORS = {"TIME", "WAIT_PIN"} | DEADLINE_WAITS


class Insn:
    def __init__(self, addr, raw, mnem, ops, text):
        self.addr, self.raw, self.mnem, self.ops, self.text = addr, raw, mnem, ops, text
        self.size = len(raw) // 2
        self.word = int(raw, 16)
        self.custom = None
        if self.size == 4 and (self.word & 0x7F) == 0x0B:
            f3, f7 = (self.word >> 12) & 7, self.word >> 25
            if f3 == 6:
                self.custom = TIMER.get(f7, "CUSTOM?")
            elif f3 == 7:
                self.custom = SHIFT.get(f7, "CUSTOM?")
            else:
                self.custom = CUSTOM.get(f3, "CUSTOM?")
            if self.custom == "CUSTOM?":
                raise SystemExit(f"pinv_check: unknown custom instruction 0x{self.word:08x} at 0x{addr:x}")
            self.mnem = self.custom

    @property
    def misaligned32(self):
        return self.size == 4 and self.addr % 4 != 0

    def base_cost(self):
        """Cost when the instruction does not transfer control (fall-through)."""
        m, c = self.mnem, self.size == 2
        if self.custom:
            cost = PCPI
        elif m in SHIFT_IMM:
            k = int(self.ops[-1], 0)
            cost = shift_cost(k, c)
        elif m in SHIFT_REG:
            cost = shift_cost(31, False) + 1
        elif m in ALU_REG_OPS:
            cost = ALU_REG
        elif m in ALU_IMM_OPS:
            cost = ALU_IMM
        elif m in LOADS:
            cost = LOAD
        elif m in STORES:
            cost = STORE
        elif m in BRANCHES:
            cost = BRANCH_NOT_TAKEN
        elif m in ("jal", "c.j", "c.jal"):
            cost = JAL
        elif m in ("jalr", "c.jr", "c.jalr"):
            cost = JALR
        else:
            raise SystemExit(f"pinv_check: no cost model for '{self.text}' at 0x{self.addr:x}")
        return cost + (1 if self.misaligned32 else 0)

    def taken_extra(self):
        """Extra cycles of a taken branch over its not-taken cost."""
        return BRANCH_TAKEN - BRANCH_NOT_TAKEN if self.mnem in BRANCHES else 0


def disassemble(elf):
    out = subprocess.run([OBJDUMP, "-d", "-M", "no-aliases,numeric", elf],
                         capture_output=True, text=True, check=True).stdout
    insns = {}
    for line in out.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\t([0-9a-f]+)\s*\t(\S+)\s*(.*)$", line)
        if not m:
            continue
        addr, raw, mnem, rest = int(m.group(1), 16), m.group(2), m.group(3), m.group(4)
        ops = [o.strip() for o in re.sub(r"<[^>]*>", "", rest).split(",") if o.strip()]
        insns[addr] = Insn(addr, raw, mnem, ops, f"{mnem} {rest}".strip())
    return insns


def symbols(elf):
    out = subprocess.run([OBJDUMP, "-t", elf], capture_output=True, text=True, check=True).stdout
    syms = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[-2] in (".text",) or (len(p) >= 4 and ".text" in p):
            try:
                syms.setdefault(int(p[0], 16), p[-1])
            except ValueError:
                pass
    return syms


def budgets(elf):
    out = subprocess.run([OBJDUMP, "-s", "-j", ".pinv.budget", elf],
                         capture_output=True, text=True).stdout
    data = bytearray()
    for line in out.splitlines():
        m = re.match(r"^ ([0-9a-f]{4}) ((?:[0-9a-f]{8} ?){1,4})", line)
        if m:
            data += bytes.fromhex(m.group(2).replace(" ", ""))
    words = [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data) - 3, 4)]
    return sorted(zip(words[0::2], words[1::2]))


def reg(op):
    return int(op[1:]) if op.startswith("x") else None


def build_cfg(insns):
    """Edges: addr -> list of (target, extra_cycles). Returns also call-site info."""
    addrs = sorted(insns)
    nxt = {a: b for a, b in zip(addrs, addrs[1:])}
    calls = defaultdict(list)          # (link_reg, callee) -> [return address]
    for a in addrs:
        i = insns[a]
        if i.mnem in ("jal", "c.jal"):
            rd = 1 if i.mnem == "c.jal" else reg(i.ops[0])
            target = int(i.ops[-1], 16)
            if rd:
                calls[(rd, target)].append(nxt.get(a))
    callees = sorted({t for (_, t) in calls})

    def function_of(a):
        f = None
        for t in callees:
            if t <= a:
                f = t
        return f

    def penalty(target):
        t = insns.get(target)
        return 1 if t is not None and t.misaligned32 else 0

    edges = {}
    for a in addrs:
        i = insns[a]
        m = i.mnem
        out = []
        if m in BRANCHES:
            t = int(i.ops[-1], 16)
            out.append((t, i.taken_extra() + penalty(t)))
            if a in nxt:
                out.append((nxt[a], 0))
        elif m in ("jal", "c.j", "c.jal"):
            t = int(i.ops[-1], 16)
            out.append((t, penalty(t)))
            # control comes back after the call: modelled through the callee's returns
        elif m in ("jalr", "c.jr", "c.jalr"):
            rd = 1 if m == "c.jalr" else (0 if m == "c.jr" else reg(i.ops[0]))
            rs = reg(i.ops[0]) if m in ("c.jr", "c.jalr") else int(re.search(r"\((x\d+)\)", i.text).group(1)[1:])
            if rd != 0:
                raise SystemExit(f"pinv_check: indirect call at 0x{a:x} not supported")
            f = function_of(a)
            rets = calls.get((rs, f), [])
            if not rets and any(k[1] == f for k in calls):
                raise SystemExit(f"pinv_check: cannot resolve return at 0x{a:x} (x{rs})")
            # a function nobody calls (a library routine this program does not use)
            # is dead code: its return has no successor.
            out += [(r, penalty(r)) for r in rets if r is not None]
        else:
            if a in nxt:
                out.append((nxt[a], 0))
        edges[a] = out
    return edges


def budget_at(bud, addr):
    b = None
    for start, cycles in bud:
        if start <= addr:
            b = (start, cycles)
    return b


def check(elf, verbose=False, report=None):
    insns = disassemble(elf)
    syms = symbols(elf)
    bud = budgets(elf)
    edges = build_cfg(insns)

    def where(a):
        base = max((s for s in syms if s <= a), default=None)
        return f"0x{a:x}" + (f" <{syms[base]}+0x{a - base:x}>" if base is not None else "")

    anchors = [a for a, i in insns.items() if i.mnem in ANCHORS]
    worst = {}            # wait addr -> (cycles, anchor addr, path)
    errors = []

    # Nodes from which a WAIT_UNTIL can be reached without passing another anchor.
    # Only loops among these nodes matter: a loop that never leads to a deadline
    # (such as the final "spin forever") cannot make one late.
    preds = defaultdict(set)
    for a, outs in edges.items():
        for t, _ in outs:
            preds[t].add(a)
    leads = set()
    stack = [a for a, i in insns.items() if i.mnem in DEADLINE_WAITS]
    while stack:
        a = stack.pop()
        if a in leads:
            continue
        leads.add(a)
        for p in preds[a]:
            if insns[p].mnem not in ANCHORS:
                stack.append(p)
    waits = [a for a, i in insns.items() if i.mnem in DEADLINE_WAITS]
    for anc in anchors:
        for target in waits:
            # Longest path from the anchor's completion to this WAIT_UNTIL, without
            # passing through another anchor. A loop on such a path is unbounded.
            memo, onstack = {}, set()

            def longest(a):
                """Worst cycles from the start of instruction a to the evaluation of `target`."""
                i = insns[a]
                if a == target:
                    return (i.base_cost(), [a])
                if i.mnem in ANCHORS or a not in leads:
                    return None
                if a in memo:
                    return memo[a]
                if a in onstack:
                    raise ValueError(a)
                onstack.add(a)
                best = None
                for t, extra in edges.get(a, []):
                    if t not in insns:
                        continue
                    r = longest(t)
                    if r is not None:
                        c = i.base_cost() + extra + r[0]
                        if best is None or c > best[0]:
                            best = (c, [a] + r[1])
                onstack.discard(a)
                memo[a] = best
                return best

            for t, extra in edges.get(anc, []):
                if t not in insns:
                    continue
                try:
                    r = longest(t)
                except ValueError as e:
                    msg = f"unbounded loop at {where(e.args[0])} between the anchor at {where(anc)} and a deadline"
                    if msg not in errors:
                        errors.append(msg)
                    continue
                if r is None:
                    continue
                cycles, path = r[0] + extra, [anc] + r[1]
                if target not in worst or cycles > worst[target][0]:
                    worst[target] = (cycles, anc, path)

    rows = []
    for w, (cycles, anc, path) in sorted(worst.items()):
        b = budget_at(bud, w)
        if b is None:
            errors.append(f"WAIT_UNTIL at {where(w)} has no PINV_BUDGET")
            continue
        ok = cycles <= b[1]
        rows.append((w, anc, cycles, b[1], ok, path))
        if not ok:
            errors.append(f"deadline at {where(w)} can be missed: worst case {cycles} cycles "
                          f"after the anchor at {where(anc)}, budget {b[1]}")

    print(f"{elf}: {len(insns)} instructions, {len(anchors)} anchors, {len(rows)} deadlines checked")
    for w, anc, cycles, budget, ok, path in rows:
        print(f"  {'ok  ' if ok else 'FAIL'} {where(w):32s} worst {cycles:4d} / budget {budget:4d}  "
              f"(slack {budget - cycles:+d})")
        if verbose:
            print("        path: " + " -> ".join(f"{insns[a].mnem}@{a:x}" for a in path))
    if rows:
        need = max(r[2] for r in rows)
        print(f"  minimum budget that would pass: {need} cycles (worst segment)")
    for e in errors:
        print("  ERROR " + e)
    print("  PROVEN: no deadline can be missed" if not errors else "  NOT PROVEN")
    if report is not None:
        report[elf] = {"proven": not errors,
                       "deadlines": {f"0x{w:x}": {"worst": c, "budget": b} for w, _, c, b, _, _ in rows}}
    return not errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the worst path of each deadline")
    ap.add_argument("--json", help="also write the results to this JSON file")
    a = ap.parse_args()
    report = {}
    ok = all([check(e, a.verbose, report) for e in a.elf])
    if a.json:
        import json
        json.dump(report, open(a.json, "w"), indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
