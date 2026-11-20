// Non-interference of timing in the PinV pin/timing unit (self-composition).
// SPDX-License-Identifier: Apache-2.0
//
// Two copies of the unit run side by side. They receive the same instruction
// stream, the same pins and the same timing operands, but the *data* operands
// (the value of PIN_OUT, the data of SHIFT_OUT/SHIFT_IN) may differ in any way.
// The proof shows that both copies always answer at the same cycles and keep
// identical timing state (counter, deadline, step, limits): when a bit leaves
// the chip does not depend on what the bit is. An observer timing the pins
// learns nothing about the data from the unit.

`default_nettype none

module pinv_io_ni (
    input wire        clk,
    input wire        resetn,
    input wire        pcpi_valid,
    input wire [31:0] pcpi_insn,
    input wire [31:0] rs1_a,
    input wire [31:0] rs1_b,
    input wire [31:0] pcpi_rs2,
    input wire [15:0] pins_in
);
    wire        wr_a, wr_b, wait_a, wait_b, ready_a, ready_b, lock_a, lock_b;
    wire [31:0] rd_a, rd_b;
    wire [15:0] out_a, out_b;
    wire [7:0]  oe_a, oe_b;
    wire [130:0] st_a, st_b;

    pinv_io a (.clk(clk), .resetn(resetn), .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
               .pcpi_rs1(rs1_a), .pcpi_rs2(pcpi_rs2), .pcpi_wr(wr_a), .pcpi_rd(rd_a),
               .pcpi_wait(wait_a), .pcpi_ready(ready_a), .pins_in(pins_in),
               .pins_out(out_a), .uio_oe(oe_a), .lock_req(lock_a), .f_timing_state(st_a));
    pinv_io b (.clk(clk), .resetn(resetn), .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
               .pcpi_rs1(rs1_b), .pcpi_rs2(pcpi_rs2), .pcpi_wr(wr_b), .pcpi_rd(rd_b),
               .pcpi_wait(wait_b), .pcpi_ready(ready_b), .pins_in(pins_in),
               .pins_out(out_b), .uio_oe(oe_b), .lock_req(lock_b), .f_timing_state(st_b));

    wire [2:0] f3 = pcpi_insn[14:12];
    // Instructions whose rs1 is data, not timing: PIN_OUT (value) and every SHIFT.
    wire data_rs1 = f3 == 3'd0 || f3 == 3'd7;
    wire pending  = wait_a && !ready_a;

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;
    always @(*) if (!f_past) assume (!resetn);

    // Same instruction stream and timing operands; data operands are free.
    always @(*) if (!data_rs1) assume (rs1_a == rs1_b);

    // PicoRV32 handshake, as in pinv_io_props.vh.
    always @(posedge clk) if (f_past) begin
        if ($past(pcpi_valid) && pcpi_valid && !$past(ready_a)) begin
            assume (pcpi_insn == $past(pcpi_insn));
            assume (rs1_a == $past(rs1_a) && rs1_b == $past(rs1_b));
            assume (pcpi_rs2 == $past(pcpi_rs2));
        end
        if ($past(resetn) && resetn && $past(pending)) assume (pcpi_valid);
        if ($past(ready_a)) assume (!pcpi_valid);
    end

    // N1. Identical timing behaviour, forever.
    always @(posedge clk) if (f_past) begin
        assert (st_a == st_b);
        assert (ready_a == ready_b && wait_a == wait_b && wr_a == wr_b);
        assert (lock_a == lock_b && oe_a == oe_b);
    end

    // The data really can differ on the pins (the proof is not vacuous).
    always @(posedge clk) if (f_past && resetn) cover (ready_a && out_a != out_b);
endmodule
