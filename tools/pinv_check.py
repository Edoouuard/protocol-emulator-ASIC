#!/usr/bin/env python3
"""
pinv_check: static deadline checker for PinV programs.
SPDX-License-Identifier: Apache-2.0

PinV programs anchor every timing-critical edge on an absolute deadline:
an anchor (TIME, WAIT_UNTIL or WAIT_PIN) gives a time, the program adds a
step to it and waits with WAIT_UNTIL. If the code between the anchor and the
WAIT_UNTIL takes longer than the step, the deadline is missed and the edge
comes late. On a protocol line that is a corrupted bit.

This tool proves, before the program is loaded, that it can never happen.
What it checks, and what it refuses:

  * Control flow. It rebuilds the control-flow graph of the code reachable
    from address 0, where PinV starts. A return is accepted only as
    `jalr x0, 0(rs)` (or `c.jr rs`) inside a function that every caller
    enters with `jal rs`, and whose body never writes rs. Any other indirect
    jump is refused, as is a jump to an address that is not an instruction of
    the program, or code that runs off its end.
  * Deadlines, from the code. An abstract interpretation of the registers
    computes each deadline as "anchor time + constant" on every path (TIME,
    WAIT_UNTIL and WAIT_PIN return the counter when they decide; a met
    deadline is the next anchor). A deadline it cannot pin down is refused.
    PINV_BUDGET(cycles) is only an assertion, checked against the real value.
  * Worst case. For every anchor, it explores every path to the next deadline
    and computes the worst-case cycle count with a cost model of PicoRV32 as
    configured in PinV, calibrated on the RTL (tools/timing/). A loop without
    a bound between an anchor and a deadline is refused.
  * Coverage. A deadline reachable from the start without any anchor before
    it is refused. The report gives deadlines found, analysed, not covered.
  * The loaded image. It proves the exact bytes the loader writes (--bin),
    refuses stores that could overwrite the code (including aliases modulo
    the 512-byte memory), and writes a certificate (--cert) with the image's
    SHA-256. Loaders check it (--verify) and refuse anything else.

PROVEN is printed only when at least one deadline was analysed and nothing
was refused. A program without deadlines gets "NO DEADLINE", not a proof.

Deadline waits are WAIT_UNTIL and the timer instructions (WAIT_TICK, SHIFT_*,
PULSE*), whose deadline is the internal one, advanced by the step at each.

Not covered: the cost model itself (validated on the RTL, see tools/timing),
and hardware faults. Interrupts do not exist in PinV.

Usage:  pinv_check.py program.elf [--verbose] [--bin image --cert proof.json]
                                                    exit code 0 = proven or no deadline, 1 = refused
        pinv_check.py --verify image proof.json     check a certificate before loading
        pinv_check.py --model                       print the cost model
"""
import argparse
import hashlib
import json
import re
import tempfile
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
        rest = rest.split("#")[0]                 # objdump comments ("# 2ee0 <sym>")
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


class CheckError(Exception):
    pass


def link_reg(i):
    """Register written by a jump (the link register), 0 if none."""
    m = i.mnem
    if m in ("c.jal", "c.jalr"):
        return 1
    if m in ("c.j", "c.jr"):
        return 0
    return reg(i.ops[0])


def writes(i):
    """Register an instruction writes, or None."""
    if i.custom:
        rd = (i.word >> 7) & 31
        return rd or None
    m = i.mnem
    if m in STORES or m in BRANCHES or m in ("c.j", "c.jr", "c.nop"):
        return None
    if m in ("jal", "jalr", "c.jal", "c.jalr"):
        return link_reg(i) or None
    r = reg(i.ops[0]) if i.ops else None
    return r or None


def jalr_parts(i):
    """(rs, offset) of an indirect jump."""
    if i.mnem in ("c.jr", "c.jalr"):
        return reg(i.ops[0]), 0
    m = re.search(r"(-?\w+)\((x\d+)\)", i.text)
    if m:
        return int(m.group(2)[1:]), int(m.group(1), 0)
    return reg(i.ops[1]), int(i.ops[2], 0)        # jalr rd,rs,imm


def build_cfg(insns, entry, errors):
    """Control-flow graph of the code reachable from `entry`.

    Returns are accepted only in one form: `jalr x0, 0(rs)` (or `c.jr rs`)
    inside the body of a function that every caller enters with `jal rs`,
    where no instruction of that body writes rs. Every other indirect jump
    is rejected. A jump to an address that is not the start of an
    instruction, or code that runs off the end of the program, is rejected.
    """
    addrs = sorted(insns)
    nxt = {a: a + insns[a].size for a in addrs}

    def target(i):
        return int(i.ops[-1], 16)

    # Intra-procedural successors: a call continues at its return address.
    def intra(a):
        i = insns[a]
        m = i.mnem
        if m in BRANCHES:
            return [target(i), nxt[a]]
        if m in ("jal", "c.j", "c.jal"):
            return [nxt[a]] if link_reg(i) else [target(i)]
        if m in ("jalr", "c.jr", "c.jalr"):
            return []
        return [nxt[a]]

    def body(f):
        seen, stack = set(), [f]
        while stack:
            a = stack.pop()
            if a in seen or a not in insns:
                continue
            seen.add(a)
            stack += intra(a)
        return seen

    # Calls, found by exploring from the entry; callees are explored in turn.
    calls = defaultdict(list)          # callee -> [(link reg, return address, call site)]
    funcs, todo = {}, [entry]
    while todo:
        f = todo.pop()
        if f in funcs:
            continue
        funcs[f] = body(f)
        for a in funcs[f]:
            i = insns[a]
            if i.mnem in ("jal", "c.jal") and link_reg(i):
                t = target(i)
                if (link_reg(i), nxt[a], a) not in calls[t]:
                    calls[t].append((link_reg(i), nxt[a], a))
                todo.append(t)

    def owners(a):
        return [f for f in funcs if a in funcs[f]]

    edges = {}
    for f in funcs:
        for a in funcs[f]:
            if a in edges:
                continue
            i = insns[a]
            m = i.mnem
            out = []
            if m in BRANCHES:
                out = [(target(i), i.taken_extra(), True), (nxt[a], 0, False)]
            elif m in ("jal", "c.j", "c.jal"):
                out = [(target(i), 0, True)]     # a call goes to the callee; it comes back by its return
            elif m in ("jalr", "c.jr", "c.jalr"):
                if link_reg(i):
                    errors.append(f"indirect call at 0x{a:x}: not supported")
                    continue
                rs, off = jalr_parts(i)
                if off != 0:
                    errors.append(f"indirect jump at 0x{a:x} with offset {off}: not a return")
                    continue
                for g in owners(a):
                    if g == entry:
                        errors.append(f"indirect jump at 0x{a:x} through x{rs} is reachable from the "
                                      f"entry without a call: not a proven return")
                        continue
                    links = {lr for lr, _, _ in calls[g]}
                    if links != {rs}:
                        errors.append(f"return at 0x{a:x} goes through x{rs}, but the function at 0x{g:x} "
                                      f"is called with link register(s) {sorted('x%d' % l for l in links)}")
                        continue
                    clobber = [b for b in funcs[g] if writes(insns[b]) == rs]
                    if clobber:
                        errors.append(f"return at 0x{a:x} goes through x{rs}, which the function at 0x{g:x} "
                                      f"overwrites at 0x{clobber[0]:x}")
                        continue
                    out += [(r, 0, True) for _, r, _ in calls[g]]
            else:
                out = [(nxt[a], 0, False)]
            for t, _, _ in out:
                if t not in insns:
                    what = "runs off the end of the program" if t == nxt[a] \
                        else f"jumps to 0x{t:x}, which is not an instruction of the program"
                    errors.append(f"0x{a:x} ({i.text}) {what}")
            # A taken branch, a jump or a return to a misaligned 32-bit instruction costs one
            # more cycle; falling through to it is already counted in its own cost.
            out = [(t, e + (1 if jump and insns[t].misaligned32 else 0)) for t, e, jump in out if t in insns]
            edges[a] = out
    reach, stack = set(), [entry]
    while stack:
        a = stack.pop()
        if a in reach or a not in edges:
            continue
        reach.add(a)
        stack += [t for t, _ in edges[a]]
    return edges, reach


# ---------------------------------------------------------------------------
# Deadline values. An abstract interpretation of the registers proves where
# each deadline is relative to its anchor, from the code itself. A value is
#   ("C", {v, ...})  one of these constants
#   ("R", {c, ...})  the time of the most recent anchor + one of these offsets
#   None             unknown
# TIME, WAIT_UNTIL and WAIT_PIN return the counter at the cycle they decide,
# which is the anchor time; a deadline wait that is met decides exactly at its
# deadline, so after it every relative time is rebased by that deadline. When
# a deadline can take several values, the smallest one is the worst case.
# ---------------------------------------------------------------------------
NREGS = 32
MAXSET = 8


def mk(kind, vals):
    vals = frozenset(vals)
    return (kind, vals) if 0 < len(vals) <= MAXSET else None


def to_signed(v):
    return v - (1 << 32) if v & 0x80000000 else v


def v_add(a, b):
    if a is None or b is None:
        return None
    if a[0] == "C" and b[0] == "C":
        return mk("C", ((x + y) & 0xFFFFFFFF for x in a[1] for y in b[1]))
    if a[0] == "C":
        a, b = b, a
    if a[0] == "R" and b[0] == "C":
        return mk("R", (x + to_signed(y) for x in a[1] for y in b[1]))
    return None


def v_sub(a, b):
    if a is None or b is None:
        return None
    if a[0] == "C" and b[0] == "C":
        return mk("C", ((x - y) & 0xFFFFFFFF for x in a[1] for y in b[1]))
    if a[0] == "R" and b[0] == "C":
        return mk("R", (x - to_signed(y) for x in a[1] for y in b[1]))
    if a[0] == "R" and b[0] == "R":
        return mk("C", ((x - y) & 0xFFFFFFFF for x in a[1] for y in b[1]))
    return None


def v_join(a, b):
    if a == b:
        return a
    if a is None or b is None or a[0] != b[0]:
        return None
    return mk(a[0], a[1] | b[1])


def v_const(v):
    return ("C", frozenset([v & 0xFFFFFFFF]))


R0 = ("R", frozenset([0]))

FOLD = {"andi": lambda x, y: x & y, "ori": lambda x, y: x | y, "xori": lambda x, y: x ^ y,
        "and": lambda x, y: x & y, "or": lambda x, y: x | y, "xor": lambda x, y: x ^ y,
        "c.andi": lambda x, y: x & y, "c.and": lambda x, y: x & y, "c.or": lambda x, y: x | y,
        "c.xor": lambda x, y: x ^ y,
        "slli": lambda x, y: x << (y & 31), "c.slli": lambda x, y: x << (y & 31),
        "srli": lambda x, y: x >> (y & 31), "c.srli": lambda x, y: x >> (y & 31)}


class State:
    __slots__ = ("r", "td", "ts")

    def __init__(self, r=None, td=None, ts=None):
        self.r = r if r is not None else [v_const(0)] + [None] * (NREGS - 1)
        self.td, self.ts = td, ts            # timer deadline and step

    def copy(self):
        return State(list(self.r), self.td, self.ts)

    def key(self):
        return (tuple(self.r), self.td, self.ts)

    def join(self, o):
        return State([v_join(x, y) for x, y in zip(self.r, o.r)], v_join(self.td, o.td), v_join(self.ts, o.ts))

    def rebase(self, d):
        """A new anchor at time d (an ("R", ...) value, or None if unknown)."""
        if d is not None and d[0] == "R":
            f = lambda v: mk("R", (x - c for x in v[1] for c in d[1])) if v and v[0] == "R" else v
        else:
            f = lambda v: None if v and v[0] == "R" else v
        self.r = [f(v) for v in self.r]
        self.td = f(self.td)

    def set(self, rd, v):
        if rd:
            self.r[rd] = v


def operands(i):
    """Register numbers of rs1, rs2 of a custom instruction."""
    return (i.word >> 15) & 31, (i.word >> 20) & 31


def transfer(i, st, store_check):
    """State after instruction i (state before: st, not modified)."""
    s = st.copy()
    m, ops = i.mnem, i.ops
    if i.custom:
        rd = (i.word >> 7) & 31
        r1, r2 = operands(i)
        c = i.custom
        if c in ("TIME", "WAIT_PIN"):
            s.rebase(None)
            s.set(rd, R0)
        elif c == "WAIT_UNTIL":
            d = st.r[r1]
            s.rebase(d)
            if d is not None and d[0] == "R":
                s.set(r1, R0)              # the deadline register now holds the anchor time
            s.set(rd, R0)
        elif c == "SET_TIMER":
            s.td = st.r[r1]
            step = st.r[r2]
            s.ts = mk("C", (x & 0xFFFF for x in step[1])) if step and step[0] == "C" else None
            s.set(rd, None)
        elif c in DEADLINE_WAITS:          # WAIT_TICK, SHIFT_*, PULSE*
            d = st.td
            s.rebase(d)
            s.td = mk("R", st.ts[1]) if (d is not None and d[0] == "R" and st.ts) else None
            s.set(rd, None)
        else:
            s.set(rd, None)
        return s
    rd = writes(i)
    val = lambda o: st.r[reg(o)] if reg(o) is not None else None
    v = None
    try:
        if m in ("add", "c.add"):
            v = v_add(val(ops[1]), val(ops[2])) if m == "add" else v_add(val(ops[0]), val(ops[1]))
        elif m in ("sub", "c.sub"):
            v = v_sub(val(ops[1]), val(ops[2])) if m == "sub" else v_sub(val(ops[0]), val(ops[1]))
        elif m == "addi":
            v = v_add(val(ops[1]), v_const(int(ops[2], 0)))
        elif m == "c.addi":
            v = v_add(val(ops[0]), v_const(int(ops[1], 0)))
        elif m == "c.li":
            v = v_const(int(ops[1], 0))
        elif m in ("lui", "c.lui"):
            v = v_const(int(ops[1], 0) << 12)
        elif m == "auipc":
            v = v_const(i.addr + (int(ops[1], 0) << 12))
        elif m == "c.mv":
            v = val(ops[1])
        elif m in ("jal", "jalr", "c.jal", "c.jalr"):
            v = v_const(i.addr + i.size)
        elif m in FOLD:
            if m.startswith("c."):
                a, b = val(ops[0]), (v_const(int(ops[1], 0)) if reg(ops[1]) is None else val(ops[1]))
            else:
                a, b = val(ops[1]), (v_const(int(ops[2], 0)) if reg(ops[2]) is None else val(ops[2]))
            if a and b and a[0] == "C" and b[0] == "C":
                v = mk("C", (FOLD[m](x, y) & 0xFFFFFFFF for x in a[1] for y in b[1]))
    except (ValueError, IndexError):
        v = None
    if m in STORES:
        store_check(i, st)
    s.set(rd, v)
    return s


def check(elf, verbose=False, report=None, image=None, cert=None):
    errors = []
    insns = disassemble(elf)
    syms = symbols(elf)
    bud = budgets(elf)

    def where(a):
        base = max((s for s in syms if s <= a), default=None)
        return f"0x{a:x}" + (f" <{syms[base]}+0x{a - base:x}>" if base is not None else "")

    # ---- the image that will be loaded --------------------------------------
    img = loaded_image(elf)
    if image is not None and open(image, "rb").read() != img:
        errors.append(f"{image} is not the image of {elf}: the proof would not apply to it")
    if len(img) > MEM_BYTES:
        errors.append(f"the image is {len(img)} bytes; PinV memory holds {MEM_BYTES}")
    entry = 0
    if entry not in insns:
        errors.append("no instruction at address 0, where PinV starts")
        insns[entry] = None
    code_end = text_end(elf)

    edges, reach = build_cfg(insns, entry, errors) if insns.get(entry) else ({}, set())

    # ---- deadline values, from the code ------------------------------------
    def store_check(i, st):
        m = re.search(r"(-?\w+)\((x\d+)\)", i.text)
        base = st.r[int(m.group(2)[1:])] if m else None
        width = 4 if i.mnem in ("sw", "c.sw", "c.swsp") else 2 if i.mnem == "sh" else 1
        if not base or base[0] != "C":
            errors.append(f"store at {where(i.addr)} ({i.text}): address not known statically; it could "
                          f"overwrite the proven code")
            return
        for addr in sorted((x + int(m.group(1), 0)) & 0xFFFFFFFF for x in base[1]):
            if any((b % MEM_BYTES) < code_end for b in range(addr, addr + width)):
                errors.append(f"store at {where(i.addr)} writes 0x{addr:x}, which is (or aliases, "
                              f"modulo {MEM_BYTES}) the program's code")
                return

    state_in = {entry: State()}
    work = [entry]
    while work:
        a = work.pop()
        if a not in reach:
            continue
        out = transfer(insns[a], state_in[a], lambda i, st: None)
        for t, _ in edges[a]:
            new = out if t not in state_in else state_in[t].join(out)
            if t not in state_in or new.key() != state_in[t].key():
                state_in[t] = new
                work.append(t)
    for a in sorted(reach):                 # stores, on the final states
        if insns[a].mnem in STORES:
            store_check(insns[a], state_in[a])

    def deadline_of(w):
        i, st = insns[w], state_in[w]
        d = st.r[operands(i)[0]] if i.mnem == "WAIT_UNTIL" else st.td
        return min(d[1]) if d and d[0] == "R" else None

    # ---- coverage -------------------------------------------------------
    all_waits = sorted(a for a, i in insns.items() if i and i.mnem in DEADLINE_WAITS)
    waits = [w for w in all_waits if w in reach]
    unreachable = [w for w in all_waits if w not in reach]
    free, stack = set(), [entry]                # reachable from the entry before any anchor
    while stack:
        a = stack.pop()
        if a in free or a not in reach:
            continue
        free.add(a)
        if insns[a].mnem not in ANCHORS:
            stack += [t for t, _ in edges[a]]
    uncovered = [w for w in waits if w in free]
    for w in uncovered:
        errors.append(f"deadline at {where(w)} is reachable from the program start without any anchor")

    # ---- worst case from each anchor to each deadline ------------------
    anchors = sorted(a for a in reach if insns[a].mnem in ANCHORS)
    preds = defaultdict(set)
    for a in reach:
        for t, _ in edges[a]:
            preds[t].add(a)
    leads, stack = set(), list(waits)
    while stack:
        a = stack.pop()
        if a in leads:
            continue
        leads.add(a)
        stack += [p for p in preds[a] if insns[p].mnem not in ANCHORS]
    worst = {}
    for anc in anchors:
        for target in waits:
            memo, onstack = {}, set()

            def longest(a):
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
                for t, extra in edges[a]:
                    r = longest(t)
                    if r is not None and (best is None or i.base_cost() + extra + r[0] > best[0]):
                        best = (i.base_cost() + extra + r[0], [a] + r[1])
                onstack.discard(a)
                memo[a] = best
                return best

            for t, extra in edges[anc]:
                try:
                    r = longest(t)
                except ValueError as e:
                    msg = f"unbounded loop at {where(e.args[0])} between the anchor at {where(anc)} and a deadline"
                    if msg not in errors:
                        errors.append(msg)
                    continue
                if r is not None and (target not in worst or r[0] + extra > worst[target][0]):
                    worst[target] = (r[0] + extra, anc, [anc] + r[1])

    rows = []
    for w in waits:
        if w in uncovered:
            continue
        if w not in worst:
            errors.append(f"deadline at {where(w)}: no anchor reaches it")
            continue
        cycles, anc, path = worst[w]
        dl = deadline_of(w)
        declared = budget_at(bud, w)
        declared = declared[1] if declared else None
        if dl is None:
            errors.append(f"deadline at {where(w)}: the code does not fix how far it is from its anchor "
                          f"(it must be the anchor time plus constants, on every path)")
            continue
        ok = cycles <= dl
        rows.append((w, anc, cycles, dl, declared, ok, path))
        if not ok:
            errors.append(f"deadline at {where(w)} can be missed: worst case {cycles} cycles after the "
                          f"anchor at {where(anc)}, deadline {dl} cycles after it")
        if declared is not None and declared > dl:
            errors.append(f"deadline at {where(w)} is {dl} cycles after its anchor, less than the "
                          f"{declared} declared by PINV_BUDGET")

    # ---- report ------------------------------------------------------------
    print(f"{elf}: {len(img)} bytes, {len(reach)} reachable instructions, {len(anchors)} anchors")
    print(f"  deadlines: {len(waits)} found, {len(rows)} analysed, {len(uncovered)} not covered"
          + (f" ({len(unreachable)} in unreachable code, ignored)" if unreachable else ""))
    for w, anc, cycles, dl, declared, ok, path in rows:
        print(f"  {'ok  ' if ok else 'FAIL'} {where(w):32s} worst {cycles:5d} / deadline {dl:5d}  "
              f"(slack {dl - cycles:+d})" + (f"  declared {declared}" if declared is not None else ""))
        if verbose:
            print("        path: " + " -> ".join(f"{insns[a].mnem}@{a:x}" for a in path))
    for e in errors:
        print("  ERROR " + e)
    if errors:
        status = "not_proven"
        print("  NOT PROVEN")
    elif not rows:
        status = "no_deadlines"
        print("  NO DEADLINE: this program makes no timing claim, nothing was proven")
    else:
        status = "proven"
        need = max(r[2] for r in rows)
        print(f"  PROVEN: all {len(rows)} deadlines met on every path (tightest segment: {need} cycles)")
    result = {"format": "pinv-proof-1", "elf": elf, "status": status,
              "image_size": len(img), "image_sha256": hashlib.sha256(img).hexdigest(),
              "checker_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
              "deadlines": {"found": len(waits), "analysed": len(rows), "not_covered": len(uncovered),
                            "unreachable": len(unreachable),
                            "list": [{"at": f"0x{w:x}", "anchor": f"0x{anc:x}", "worst": c, "deadline": dl,
                                      "declared": dec} for w, anc, c, dl, dec, _, _ in rows]},
              "errors": errors}
    if report is not None:
        report[elf] = result
    if cert and not errors:
        with open(cert, "w") as f:
            json.dump(result, f, indent=1)
    return not errors


MEM_BYTES = 512


def budget_at(bud, addr):
    """The PINV_BUDGET region an address falls in: (start, cycles) or None."""
    b = None
    for start, cycles in bud:
        if start <= addr:
            b = (start, cycles)
    return b


def loaded_image(elf):
    """The bytes the loader writes: the ELF's loadable sections, from address 0."""
    with tempfile.NamedTemporaryFile(suffix=".bin") as t:
        subprocess.run([OBJDUMP.replace("objdump", "objcopy"), "-O", "binary", elf, t.name], check=True)
        return open(t.name, "rb").read()


def text_end(elf):
    out = subprocess.run([OBJDUMP, "-h", elf], capture_output=True, text=True, check=True).stdout
    end = 0
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[1] == ".text":
            end = int(p[3], 16) + int(p[2], 16)
    return end


def verify_cert(image, cert, same_checker=True):
    """True if `cert` is a passing proof for exactly these bytes (used by loaders).
    With same_checker, the proof must also come from this version of the checker."""
    try:
        c = json.load(open(cert))
        data = open(image, "rb").read()
    except (OSError, ValueError):
        return False
    return (c.get("format") == "pinv-proof-1" and c.get("status") in ("proven", "no_deadlines")
            and not c.get("errors")
            and c.get("image_sha256") == hashlib.sha256(data).hexdigest()
            and c.get("image_size") == len(data) <= MEM_BYTES
            and (not same_checker
                 or c.get("checker_sha256") == hashlib.sha256(open(__file__, "rb").read()).hexdigest()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the worst path of each deadline")
    ap.add_argument("--json", help="also write the results to this JSON file")
    ap.add_argument("--bin", help="the image that will be loaded: must be exactly the ELF's image")
    ap.add_argument("--cert", help="write a proof certificate (only when the check passes)")
    ap.add_argument("--verify", nargs=2, metavar=("IMAGE", "CERT"),
                    help="only check that CERT is a passing proof for IMAGE (for loaders)")
    a = ap.parse_args()
    if a.verify:
        ok = verify_cert(*a.verify)
        print(f"{a.verify[0]}: {'certificate valid' if ok else 'NO VALID PROOF CERTIFICATE'}")
        sys.exit(0 if ok else 1)
    if len(a.elf) != 1 and (a.bin or a.cert):
        ap.error("--bin and --cert take one ELF")
    report = {}
    ok = all([check(e, a.verbose, report, a.bin, a.cert) for e in a.elf])
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
