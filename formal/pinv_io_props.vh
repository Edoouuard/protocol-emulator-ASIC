// Formal properties of the PinV pin/timing unit, included inside pinv_io
// only when PINV_IO_FORMAL is defined (see formal/pinv_io.sby).
// SPDX-License-Identifier: Apache-2.0
//
// The core is replaced by an unconstrained environment that only respects the
// PicoRV32 co-processor (PCPI) handshake; the pins are fully unconstrained.
// SymbiYosys proves every assertion for all reachable states (k-induction),
// not just for the cases a test happens to run.

    wire [2:0]  f3      = funct3;
    wire [6:0]  f7      = funct7;
    wire        f_known = f3 <= F_WAIT_PIN || (f3 == F_TIMER && f7 <= 7'd5)
                       || (f3 == F_SHIFT && (f7 <= 7'd3 || f7 == 7'd4 || f7 == 7'd6));
    wire        f_mine  = pcpi_valid && pcpi_insn[6:0] == 7'b0001011 && f_known;
    wire        pending = f_mine && !pcpi_ready;
    // Instructions that wait for the internal deadline: WAIT.TICK and every SHIFT.
    wire        f_tick  = (f3 == F_TIMER && f7 == 7'd1) || f3 == F_SHIFT;
    wire        f_set   = f3 == F_TIMER && f7 == 7'd0;
    wire        f_limit = f3 == F_TIMER && f7 == 7'd2;
    wire        f_lock  = f3 == F_TIMER && f7 == 7'd3;
    wire        f_wave  = f3 == F_TIMER && f7 == 7'd4;
    wire        f_idle  = f3 == F_TIMER && f7 == 7'd5;
    wire        f_pulse = f3 == F_SHIFT && f7[2];
    // Instructions that write the outputs when they are answered.
    wire        f_wout  = f3 == F_OUT || (f3 == F_SHIFT && !f7[0]);

    function f_before(input [31:0] a, input [31:0] b);
        reg [31:0] d;
        begin d = a - b; f_before = d[31]; end
    endfunction

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;

    // ---------------------------------------------------------------- environment
    // Start in reset. A chip reset always holds the core in reset too (project.v).
    always @(*) if (!f_past) assume (!resetn && !chip_resetn);
    always @(*) if (!chip_resetn) assume (!resetn);

    always @(posedge clk) if (f_past) begin
        // PicoRV32 keeps the instruction and its operands stable while it waits.
        if ($past(pcpi_valid) && pcpi_valid && !$past(pcpi_ready)) begin
            assume (pcpi_insn == $past(pcpi_insn));
            assume (pcpi_rs1  == $past(pcpi_rs1));
            assume (pcpi_rs2  == $past(pcpi_rs2));
        end
        // It does not drop a request we told it to wait for...
        if ($past(resetn) && resetn && $past(pending)) assume (pcpi_valid);
        // ...and it moves on (drops valid) the cycle after our answer.
        if ($past(pcpi_ready)) assume (!pcpi_valid);
    end

    // ---------------------------------------------------------------- properties
    // Ghost state: was the deadline of the pending WAIT_UNTIL still in the future
    // when the instruction was first seen?
    reg        f_busy, f_future;
    reg [31:0] f_start;     // cycle at which the pending instruction was first seen
    reg [23:0] f_lim;       // WAIT.PIN limit in force at that moment
    always @(posedge clk) begin
        if (!resetn || !pending) begin
            f_busy <= 1'b0;
        end else if (!f_busy) begin
            f_busy   <= 1'b1;
            f_future <= f_before(counter, f_tick ? deadline : pcpi_rs1);
            f_start  <= counter;
            f_lim    <= wait_max;
        end
    end

    // Ghost state for W2: width of the pulse in flight, cycles since it started.
    reg [15:0] f_len, f_el;
    always @(posedge clk) begin
        if (!resetn) begin
            f_len <= 16'd0;
            f_el  <= 16'd0;
        end else if (pending && f_pulse && tick_reached) begin
            f_len <= pulse_len;
            f_el  <= 16'd0;
        end else if (fall_on) begin
            f_el  <= f_el + 16'd1;
        end
    end

`ifdef PROPS_CORE
    always @(*) begin
        // The core is told to wait exactly while one of our instructions is pending.
        assert (pcpi_wait == f_mine);
        // A result is written back with every answer, and only then
        // (registers hold arbitrary values before the first reset cycle).
        if (f_past) assert (pcpi_wr == pcpi_ready);
    end

    always @(posedge clk) if (f_past && $past(resetn) && resetn) begin
        // P1. The cycle counter advances by exactly one every cycle.
        assert (counter == $past(counter) + 32'd1);

        // P2. One answer per instruction, never for anything else.
        assert (!(pcpi_ready && $past(pcpi_ready)));
        if (pcpi_ready) assert ($past(pending));

        // P3. Exact completion: an instruction is answered in the cycle right
        // after its condition holds, never earlier and never later.
        if ($past(pending)) begin
            if ($past(f_tick))
                assert (pcpi_ready == !f_before($past(counter), $past(deadline)));
            else case ($past(f3))
                F_WAIT_UNTIL: assert (pcpi_ready == !f_before($past(counter), $past(pcpi_rs1)));
                F_WAIT_PIN:   assert (pcpi_ready == (((($past(pins_in) ^ $past(pcpi_rs2[15:0])) & $past(pcpi_rs1[15:0])) == 16'd0)
                                                     || $past(pin_expired)));
                default:      assert (pcpi_ready);
            endcase
        end

        // P4. Zero jitter: if the deadline was still in the future when WAIT_UNTIL
        // started, the core is released exactly when the counter equals it.
        if (pcpi_ready && $past(f3) == F_WAIT_UNTIL && $past(f_busy) && $past(f_future))
            assert ($past(counter) == $past(pcpi_rs1));
        // Same for the internal deadline (WAIT.TICK and SHIFT).
        if (pcpi_ready && $past(f_tick) && $past(f_busy) && $past(f_future))
            assert ($past(counter) == $past(deadline));

        // P5. WAIT_UNTIL and WAIT_PIN return the cycle at which they were released; TIME the current cycle.
        if (pcpi_ready && ($past(f3) == F_WAIT_UNTIL || $past(f3) == F_WAIT_PIN || $past(f3) == F_TIME
                           || ($past(f3) == F_TIMER && $past(f7) == 7'd1)))
            assert (pcpi_rd == $past(counter));

        // P9. The internal deadline advances by exactly one step at each WAIT.TICK or
        // SHIFT, is set only by SET.TIMER, and never changes otherwise: no drift.
        if (pcpi_ready && $past(f_tick))
            assert (deadline == $past(deadline) + {16'd0, $past(step)} && step == $past(step));
        else if (pcpi_ready && $past(f_set))
            assert (deadline == $past(pcpi_rs1) && step == $past(pcpi_rs2[15:0]));
        else
            assert (deadline == $past(deadline) && step == $past(step));

        // P10. Shift results: the data moves by exactly one bit, the sampled bit
        // comes from the selected pin at the release cycle.
        if (pcpi_ready && $past(f3) == F_SHIFT) case ($past(f7[1:0]))
            2'd0: assert (pcpi_rd == {1'b0, $past(pcpi_rs1[31:1])});
            2'd2: assert (pcpi_rd == {$past(pcpi_rs1[30:0]), 1'b0});
            2'd1: assert (pcpi_rd == {$past(pins_in[pcpi_rs2[3:0]]), $past(pcpi_rs1[31:1])});
            2'd3: assert (pcpi_rd == {$past(pcpi_rs1[30:0]), $past(pins_in[pcpi_rs2[3:0]])});
        endcase

        // P6. PIN_OUT updates exactly the masked bits, one cycle after it is accepted...
        if (pcpi_ready && $past(f3) == F_OUT)
            assert (pins_out == (($past(pins_now) & ~$past(pcpi_rs2[15:0])) | ($past(pcpi_rs1[15:0]) & $past(pcpi_rs2[15:0]))));
        // ...SHIFT.OUT drives exactly one pin, the selected one, with the outgoing bit...
        if (pcpi_ready && $past(f3) == F_SHIFT && !$past(f7[0]) && !$past(f7[2]))
            assert (pins_out == (($past(pins_now) & ~(16'd1 << $past(pcpi_rs2[3:0])))
                                 | ({15'd0, $past(f7[1]) ? $past(pcpi_rs1[31]) : $past(pcpi_rs1[0])} << $past(pcpi_rs2[3:0]))));
        // ...PULSE first ends the pulse in flight, then raises its own pin and
        // arms the falling edge with the width selected by the data bit...
        if (pcpi_ready && $past(f_pulse))
            assert (pins_out == (($past(fall_on) ? $past(pins_now) & ~(16'd1 << $past(fall_pin)) : $past(pins_now))
                                 | (16'd1 << $past(pcpi_rs2[3:0])))
                    && fall_on && fall_pin == $past(pcpi_rs2[3:0])
                    && fall_left == ((($past(f7[1]) ? $past(pcpi_rs1[31]) : $past(pcpi_rs1[0]))) ? $past(t1) : $past(t0)));
        // ...and nothing else changes the outputs, except the falling edge of a pulse.
        if (!(pcpi_ready && $past(f_wout)))
            assert (pins_out == $past(pins_now));

        // W1. The falling edge of a pulse happens by itself: the countdown moves by
        // one every cycle, and the pin drops when it ends, whatever the core does.
        if ($past(fall_now) && !(pcpi_ready && $past(f_pulse) && $past(pcpi_rs2[3:0]) == $past(fall_pin))
                            && !(pcpi_ready && $past(f_wout) && !$past(f_pulse)))
            assert (!pins_out[$past(fall_pin)]);
        if (!(pcpi_ready && $past(f_pulse))) begin
            if ($past(fall_now))     assert (!fall_on);
            else if ($past(fall_on)) assert (fall_on && fall_pin == $past(fall_pin) && fall_left == $past(fall_left) - 16'd1);
            else                     assert (!fall_on);
        end
        // W2. Exact pulse width: a pulse ends exactly t cycles after it started
        // (t = 0 behaves as 1), where t is the width chosen when it started.
        if (fall_on) assert (fall_left + f_el == f_len && f_el <= f_len && (f_len == 16'd0 || fall_left != 16'd0));
        if (fall_now) assert (f_el + 16'd1 == (f_len == 16'd0 ? 16'd1 : f_len));
        // The widths change only through SET.WAVE.
        if (pcpi_ready && $past(f_wave)) assert (t0 == $past(pcpi_rs1[15:0]) && t1 == $past(pcpi_rs1[31:16]));
        else assert (t0 == $past(t0) && t1 == $past(t1));

        // P7. Only PIN_DIR changes the pin directions, and only the masked ones.
        if (pcpi_ready && $past(f3) == F_DIR)
            assert (uio_oe == (($past(uio_oe) & ~$past(pcpi_rs2[15:8])) | ($past(pcpi_rs1[15:8]) & $past(pcpi_rs2[15:8]))));
        if (!(pcpi_ready && $past(f3) == F_DIR))
            assert (uio_oe == $past(uio_oe));
    end

`endif

`ifdef PROPS_BOUND
    always @(posedge clk) if (f_past && $past(resetn) && resetn) begin
        // B1. Bounded waits: a WAIT.PIN started with a limit never waits longer than it,
        // whatever the pins do (a device holding a line forever cannot hang the chip).
        if (pending && f3 == F_WAIT_PIN && f_busy && f_lim != 24'd0)
            assert (counter - f_start <= {8'd0, f_lim});
        // Helper invariant for the induction: the countdown plus the cycles already
        // waited (after the first one) equals the limit.
        if (pending && f3 == F_WAIT_PIN && pin_waiting)
            assert (f_busy && pin_limited == (f_lim != 24'd0)
                    && (!pin_limited || pin_left + (counter[23:0] - f_start[23:0]) == f_lim));
        // A pin wait is only in progress during a pending WAIT.PIN.
        if (pin_waiting) assert (pending && f3 == F_WAIT_PIN);
        // B2. Without a limit, WAIT.PIN only ends when the pins match.
        if (pcpi_ready && $past(f3) == F_WAIT_PIN && !$past(pin_limited))
            assert ((($past(pins_in) ^ $past(pcpi_rs2[15:0])) & $past(pcpi_rs1[15:0])) == 16'd0);
        // B3. The limit changes only through SET.LIMIT.
        if (pcpi_ready && $past(f_limit)) assert (wait_max == $past(pcpi_rs1[23:0]));
        else assert (wait_max == $past(wait_max));
        // B4. The timeout flag: set exactly when a WAIT.PIN gives up, reported and cleared by PIN.IN.
        if (pcpi_ready && $past(f3) == F_IN)
            assert (pcpi_rd == {15'd0, $past(timed_out), $past(pins_in)} && !timed_out);
        else if (pcpi_ready && $past(f3) == F_WAIT_PIN)
            assert (timed_out == ($past(timed_out) || ((($past(pins_in) ^ $past(pcpi_rs2[15:0])) & $past(pcpi_rs1[15:0])) != 16'd0)));
        else
            assert (timed_out == $past(timed_out));
        // K0. LOCK raises the lock request for exactly one cycle, and nothing else does.
        assert (lock_req == (pcpi_ready && $past(f_lock)));
    end

`endif

`ifdef PROPS_CORE
    // P8. Reset puts outputs, directions and the counter in a known state: the
    // idle state during a program reload, all zero after a chip reset.
    always @(posedge clk) if (f_past && !$past(resetn)) begin
        assert (pins_out == ($past(chip_resetn) ? $past(idle_out) : 16'd0));
        assert (uio_oe == ($past(chip_resetn) ? $past(idle_oe) : 8'd0));
        assert (!fall_on);
        assert (counter == 32'd0);
        assert (!pcpi_ready);
        assert (!lock_req);
    end

    // I1. The idle state is cleared by a chip reset, set only by SET.IDLE from a
    // running program, and survives everything else, program reloads included.
    always @(posedge clk) if (f_past) begin
        if (!$past(chip_resetn))
            assert (idle_out == 16'd0 && idle_oe == 8'd0);
        else if ($past(resetn) && $past(pending) && $past(f_idle))
            assert (idle_out == $past(pcpi_rs1[15:0]) && idle_oe == $past(pcpi_rs2[15:8]));
        else
            assert (idle_out == $past(idle_out) && idle_oe == $past(idle_oe));
    end

`endif

    // Covers: show that the interesting situations are reachable (no vacuous proof).
    always @(posedge clk) if (f_past && resetn) begin
        cover (pcpi_ready && $past(f3) == F_WAIT_UNTIL && $past(f_busy) && $past(f_future));
        cover (pcpi_ready && $past(f3) == F_WAIT_PIN);
        cover (pcpi_ready && $past(f3) == F_OUT && pins_out != $past(pins_out));
        cover (pcpi_ready && $past(f3) == F_SHIFT && $past(f_busy) && $past(f_future) && pins_out != $past(pins_out));
        cover (pcpi_ready && $past(f3) == F_SHIFT && $past(f7) == 7'd1);
        cover (pcpi_ready && $past(f3) == F_WAIT_PIN && timed_out && !$past(timed_out));
        cover (lock_req);
        cover ($past(fall_now) && f_len == 16'd3 && !$past(pcpi_ready));   // a full 3-cycle pulse
        cover (pcpi_ready && $past(f_pulse) && $past(fall_on));             // back-to-back pulses
    end
    always @(posedge clk) if (f_past && chip_resetn)
        cover (!resetn && !$past(resetn) && pins_out != 16'd0);             // idle state held in reset
