# Instruction timing calibration

`tools/pinv_check.py` needs the cost of every instruction in cycles. These numbers are not taken from documentation: they are measured on the RTL of PinV itself (PicoRV32 as configured in `src/project.v`, plus the pin/timing unit).

```bash
python3 gen_bench.py /tmp/bench          # builds ~170 micro-benchmark programs
make BENCH_DIR=/tmp/bench                 # runs them on the RTL (Icarus + cocotb)
```

Each program reads the cycle counter (`TIME`), runs 16 copies of one instruction, reads the counter again and stores the difference. Every case is measured with the code aligned and misaligned on 4 bytes. `measured.json` holds the raw results (cycles for 16 instructions plus a fixed overhead of 6, or 7 when misaligned).

## Model derived from the measurements

| Class | Cycles |
|---|---|
| ALU with immediate, `lui`, `c.li`, `c.addi`… | 3 |
| ALU register-register, `c.mv`, `c.add`… | 4 |
| Load | 5 |
| Store | 6 |
| Branch not taken / taken | 4 / 6 |
| `jal`, `c.j`, `c.jal` | 3 |
| `jalr`, `c.jr` (return) | 6 |
| PinV custom instruction (no wait) | 6 |
| Shift by k ≥ 1 (immediate) | 4 + k/4 + k mod 4 |
| Shift by a register | worst case (k = 31) + 1 = 15 |
| 32-bit instruction at an address not multiple of 4 | +1 |
| Taken branch or jump to such an instruction | +1 |

## Validation against the RTL

`test/deadline_monitor.py` measures, in every cocotb test, the real number of cycles between each timing anchor and the next `WAIT_UNTIL`, and flags any missed deadline. Results:

| Demo | Checker: smallest proven budget | RTL: at that budget | RTL: one cycle less |
|---|---|---|---|
| UART | 44 cycles per bit | no deadline missed | missed |
| SPI (mode 0) | 77 cycles per half period | no deadline missed | missed |
| I2C | 54 cycles per quarter period | no deadline missed | missed |

Per deadline, the worst segment the RTL showed equals the checker's prediction (UART: 30, 28 and 44 cycles; SPI and I2C: predicted lateness 29 and 22 cycles at the old settings, measured 29 and 22).
