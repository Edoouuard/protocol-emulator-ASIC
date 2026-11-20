// Unconstrained stand-in for the pin/timing unit, used only by formal/top.sby.
// SPDX-License-Identifier: Apache-2.0
// The top-level properties (loading, core reset) do not depend on it; with
// free outputs the proof covers any behaviour of the unit. The unit itself
// is proven separately (formal/pinv_io.sby).

module pinv_io (
    input  wire        clk, resetn, chip_resetn,
    input  wire        pcpi_valid,
    input  wire [31:0] pcpi_insn, pcpi_rs1, pcpi_rs2,
    output wire        pcpi_wr,
    output wire [31:0] pcpi_rd,
    output wire        pcpi_wait, pcpi_ready,
    input  wire [15:0] pins_in,
    output wire [15:0] pins_out,
    output wire [7:0]  uio_oe,
    output wire        lock_req
);
    (* anyseq *) reg        f_wr, f_wait, f_ready;
    (* anyseq *) reg [31:0] f_rd;
    (* anyseq *) reg [15:0] f_out;
    (* anyseq *) reg [7:0]  f_oe;
    (* anyseq *) reg        f_lock;
    // The real unit only raises lock_req when out of reset (proven in
    // pinv_io_props.vh, P8 and K0): free otherwise.
    reg lock_q = 1'b0;
    always @(posedge clk) lock_q <= resetn && f_lock;
    assign lock_req = lock_q;
    assign pcpi_wr = f_wr; assign pcpi_rd = f_rd; assign pcpi_wait = f_wait;
    assign pcpi_ready = f_ready; assign pins_out = f_out; assign uio_oe = f_oe;
endmodule
