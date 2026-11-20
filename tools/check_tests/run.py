#!/usr/bin/env python3
"""
Tests of pinv_check itself. SPDX-License-Identifier: Apache-2.0

Each program here is built like a real PinV program and checked. The first
comment line says what the checker must answer:

    EXPECT rejected: <text>    NOT PROVEN, with <text> in an error message
    EXPECT proven              PROVEN
    EXPECT no_deadlines        no timing claim (and not PROVEN)

Most of them are traps: each one exploits a way a checker can accept a
program that misses a deadline. Run:  python3 run.py [--checker other.py]
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FW = HERE.parent.parent / "firmware"
CC = "riscv64-unknown-elf-gcc"
CFLAGS = ["-march=rv32ec", "-mabi=ilp32e", "-nostdlib", "-nostartfiles", "-Os",
          f"-I{FW}", "-T", str(FW / "link.ld"), "-Wl,--no-warn-rwx-segments"]


def outcome(stdout, code):
    if "NO DEADLINE" in stdout:
        return "no_deadlines"
    if "NOT PROVEN" in stdout or code != 0:
        return "rejected"
    if "PROVEN" in stdout:
        return "proven"
    return "unknown"


def cert_tests(tmp, checker):
    """A certificate binds the proof to the exact image: one changed byte, a
    rejected program or another image must all fail verification."""
    sys.path.insert(0, str(pathlib.Path(checker).parent))
    from pinv_check import verify_cert
    elf, img, cert = f"{tmp}/c.elf", f"{tmp}/c.bin", f"{tmp}/c.proof.json"
    subprocess.run([CC, *CFLAGS, "-o", elf, str(HERE / "good_link_t1.S")], check=True)
    subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, img], check=True)
    subprocess.run([sys.executable, checker, elf, "--bin", img, "--cert", cert],
                   check=True, capture_output=True)
    data = open(img, "rb").read()
    cases = [("certificate matches its image", verify_cert(img, cert), True)]
    open(img, "wb").write(data[:-1] + bytes([data[-1] ^ 1]))
    cases.append(("one byte changed: refused", verify_cert(img, cert), False))
    open(img, "wb").write(data + b"\0\0\0\0")
    cases.append(("bytes appended: refused", verify_cert(img, cert), False))
    open(img, "wb").write(data)
    bad = f"{tmp}/bad.elf"
    subprocess.run([CC, *CFLAGS, "-o", bad, str(HERE / "budget_lies.S")], check=True)
    r = subprocess.run([sys.executable, checker, bad, "--cert", f"{tmp}/bad.proof.json"], capture_output=True)
    cases.append(("no certificate for a rejected program", pathlib.Path(f"{tmp}/bad.proof.json").exists(), False))
    fails = 0
    for name, got, want in cases:
        ok = got == want
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} cert: {name}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", default=str(HERE.parent / "pinv_check.py"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for src in sorted(HERE.glob("*.S")):
            m = re.search(r"EXPECT (rejected|proven|no_deadlines)(?::\s*(.+))?", src.read_text())
            want, text = m.group(1), (m.group(2) or "").strip()
            elf = f"{tmp}/{src.stem}.elf"
            subprocess.run([CC, *CFLAGS, "-o", elf, str(src)], check=True)
            r = subprocess.run([sys.executable, a.checker, elf], capture_output=True, text=True)
            got = outcome(r.stdout, r.returncode)
            ok = got == want and (not text or text in r.stdout)
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {src.stem:18s} expected {want:12s} got {got}")
            if not ok or a.verbose:
                print("     " + r.stdout.strip().replace("\n", "\n     ") + r.stderr.strip())
        failures += cert_tests(tmp, a.checker)
    print(f"{failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
