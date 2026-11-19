// Formal properties of the PinV pin/timing unit, included inside pinv_io
// only when PINV_IO_FORMAL is defined (see formal/pinv_io.sby).
// SPDX-License-Identifier: Apache-2.0
//
// The core is replaced by an unconstrained environment that only respects the
// PicoRV32 co-processor (PCPI) handshake; the pins are fully unconstrained.
// SymbiYosys proves every assertion for all reachable states (k-induction),
// not just for the cases a test happens to run.

    wire [2:0]  f3      = funct3;
    wire        f_mine  = pcpi_valid && pcpi_insn[6:0] == 7'b0001011 && f3 <= F_WAIT_PIN;
    wire        pending = f_mine && !pcpi_ready;

    function f_before(input [31:0] a, input [31:0] b);
        reg [31:0] d;
        begin d = a - b; f_before = d[31]; end
    endfunction

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;

    // ---------------------------------------------------------------- environment
    // Start in reset.
    always @(*) if (!f_past) assume (!resetn);

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
    reg f_busy, f_future;
    always @(posedge clk) begin
        if (!resetn || !pending) begin
            f_busy <= 1'b0;
        end else if (!f_busy) begin
            f_busy   <= 1'b1;
            f_future <= f_before(counter, pcpi_rs1);
        end
    end

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
            case ($past(f3))
                F_WAIT_UNTIL: assert (pcpi_ready == !f_before($past(counter), $past(pcpi_rs1)));
                F_WAIT_PIN:   assert (pcpi_ready == ((($past(pins_in) ^ $past(pcpi_rs2[15:0])) & $past(pcpi_rs1[15:0])) == 16'd0));
                default:      assert (pcpi_ready);
            endcase
        end

        // P4. Zero jitter: if the deadline was still in the future when WAIT_UNTIL
        // started, the core is released exactly when the counter equals it.
        if (pcpi_ready && $past(f3) == F_WAIT_UNTIL && $past(f_busy) && $past(f_future))
            assert ($past(counter) == $past(pcpi_rs1));

        // P5. WAIT_UNTIL and WAIT_PIN return the cycle at which they were released; TIME the current cycle.
        if (pcpi_ready && ($past(f3) == F_WAIT_UNTIL || $past(f3) == F_WAIT_PIN || $past(f3) == F_TIME))
            assert (pcpi_rd == $past(counter));

        // P6. PIN_OUT updates exactly the masked bits, one cycle after it is accepted...
        if (pcpi_ready && $past(f3) == F_OUT)
            assert (pins_out == (($past(pins_out) & ~$past(pcpi_rs2[15:0])) | ($past(pcpi_rs1[15:0]) & $past(pcpi_rs2[15:0]))));
        // ...and nothing else ever changes the outputs.
        if (!(pcpi_ready && $past(f3) == F_OUT))
            assert (pins_out == $past(pins_out));

        // P7. Only PIN_DIR changes the pin directions, and only the masked ones.
        if (pcpi_ready && $past(f3) == F_DIR)
            assert (uio_oe == (($past(uio_oe) & ~$past(pcpi_rs2[15:8])) | ($past(pcpi_rs1[15:8]) & $past(pcpi_rs2[15:8]))));
        if (!(pcpi_ready && $past(f3) == F_DIR))
            assert (uio_oe == $past(uio_oe));
    end

    // P8. Reset puts outputs, directions and the counter in a known state.
    always @(posedge clk) if (f_past && !$past(resetn)) begin
        assert (pins_out == 16'd0);
        assert (uio_oe == 8'd0);
        assert (counter == 32'd0);
        assert (!pcpi_ready);
    end

    // Covers: show that the interesting situations are reachable (no vacuous proof).
    always @(posedge clk) if (f_past && resetn) begin
        cover (pcpi_ready && $past(f3) == F_WAIT_UNTIL && $past(f_busy) && $past(f_future));
        cover (pcpi_ready && $past(f3) == F_WAIT_PIN);
        cover (pcpi_ready && $past(f3) == F_OUT && pins_out != $past(pins_out));
    end
