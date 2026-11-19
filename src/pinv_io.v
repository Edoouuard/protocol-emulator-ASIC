/*
 * PinV I/O and timing unit, attached to PicoRV32 through PCPI.
 * Copyright (c) 2026 Edouard Guillermain
 * SPDX-License-Identifier: Apache-2.0
 *
 * Custom instructions, R-type, opcode custom-0 (0x0B), selected by funct3:
 *
 *   0 PIN.OUT   rd, rs1, rs2   out <= (out & ~rs2) | (rs1 & rs2); rd <= new out
 *   1 PIN.IN    rd             rd  <= {uio_in, ui_in}  (synchronised)
 *   2 PIN.DIR   rd, rs1, rs2   oe  <= (oe & ~rs2) | (rs1 & rs2);   rd <= new oe
 *   3 TIME      rd             rd  <= cycle counter
 *   4 WAIT.UNTIL rd, rs1       stall until counter reaches rs1;    rd <= counter
 *   5 WAIT.PIN  rd, rs1, rs2   stall until (pins & rs1) == (rs2 & rs1); rd <= counter
 *
 * Timer group (funct3 = 6), an internal deadline and step, so a periodic
 * signal costs one instruction per edge:
 *   6/0 SET.TIMER  rs1, rs2    deadline <= rs1; step <= rs2[15:0]
 *   6/1 WAIT.TICK  rd          stall until counter reaches deadline;
 *                              deadline <= deadline + step;      rd <= counter
 *
 * Shift group (funct3 = 7), fused "wait for the deadline, move one bit,
 * advance the deadline", selected by funct7 (bit 0: in, bit 1: MSB first):
 *   7/0 SHIFT.OUT  rd, rs1, rs2   at the deadline: out[rs2[3:0]] <= rs1[0];  rd <= rs1 >> 1
 *   7/2 SHIFT.OUTM rd, rs1, rs2   at the deadline: out[rs2[3:0]] <= rs1[31]; rd <= rs1 << 1
 *   7/1 SHIFT.IN   rd, rs1, rs2   at the deadline: rd <= {pin[rs2[3:0]], rs1[31:1]}
 *   7/3 SHIFT.INM  rd, rs1, rs2   at the deadline: rd <= {rs1[30:0], pin[rs2[3:0]]}
 *   then deadline <= deadline + step.
 *
 * Output bit map (16 bits): [7:0] = uo_out, [15:8] = uio_out.
 * Input bit map  (16 bits): [7:0] = ui_in,  [15:8] = uio_in.
 * Direction (PIN.DIR) only applies to bits [15:8] (uio_oe); the low byte is ignored.
 *
 * Timing model: every effect of PIN.OUT reaches the pins exactly one cycle
 * after the instruction is accepted. WAIT.UNTIL releases the core one cycle
 * after the counter reaches the deadline. A program that anchors each edge
 * on an absolute deadline (WAIT.UNTIL, then PIN.OUT) therefore produces
 * edges with a fixed offset from the deadline, independent of how long the
 * code in between took, as long as it finished before the deadline.
 */

`default_nettype none

module pinv_io (
    input  wire        clk,
    input  wire        resetn,

    input  wire        pcpi_valid,
    input  wire [31:0] pcpi_insn,
    input  wire [31:0] pcpi_rs1,
    input  wire [31:0] pcpi_rs2,
    output reg         pcpi_wr,
    output reg  [31:0] pcpi_rd,
    output wire        pcpi_wait,
    output reg         pcpi_ready,

    input  wire [15:0] pins_in,     // already synchronised
    output reg  [15:0] pins_out,
    output reg  [7:0]  uio_oe
);

    localparam F_OUT        = 3'd0;
    localparam F_IN         = 3'd1;
    localparam F_DIR        = 3'd2;
    localparam F_TIME       = 3'd3;
    localparam F_WAIT_UNTIL = 3'd4;
    localparam F_WAIT_PIN   = 3'd5;
    localparam F_TIMER      = 3'd6;
    localparam F_SHIFT      = 3'd7;

    wire       is_custom0 = pcpi_insn[6:0] == 7'b0001011;
    wire [2:0] funct3     = pcpi_insn[14:12];
    wire [6:0] funct7     = pcpi_insn[31:25];
    wire       known      = funct3 <= F_WAIT_PIN
                         || (funct3 == F_TIMER && funct7[6:1] == 6'd0)
                         || (funct3 == F_SHIFT && funct7[6:2] == 5'd0);
    wire       mine       = pcpi_valid && is_custom0 && known;

    // Tell the core to keep waiting while one of our instructions is pending,
    // so it never times out on a long WAIT.
    assign pcpi_wait = mine;

    reg [31:0] counter;
    always @(posedge clk) begin
        if (!resetn) counter <= 32'd0;
        else         counter <= counter + 32'd1;
    end

    reg  [31:0] deadline;
    reg  [15:0] step;

    wire [15:0] new_out = (pins_out & ~pcpi_rs2[15:0]) | (pcpi_rs1[15:0] & pcpi_rs2[15:0]);
    wire        tick_reached = !counter_before(counter, deadline);
    wire [3:0]  bit_idx   = pcpi_rs2[3:0];
    wire        msb_first = funct7[1];
    wire        out_bit   = msb_first ? pcpi_rs1[31] : pcpi_rs1[0];
    wire        in_bit    = pins_in[bit_idx];
    wire [31:0] shifted   = funct7[0] ? (msb_first ? {pcpi_rs1[30:0], in_bit} : {in_bit, pcpi_rs1[31:1]})
                                      : (msb_first ? {pcpi_rs1[30:0], 1'b0}   : {1'b0, pcpi_rs1[31:1]});
    wire [7:0]  new_oe  = (uio_oe & ~pcpi_rs2[15:8]) | (pcpi_rs1[15:8] & pcpi_rs2[15:8]);
    wire        deadline_reached = !counter_before(counter, pcpi_rs1);
    wire        pins_match = ((pins_in ^ pcpi_rs2[15:0]) & pcpi_rs1[15:0]) == 16'd0;

    // Wrap-safe "a is before b" on a free-running 32-bit counter.
    function counter_before(input [31:0] a, input [31:0] b);
        reg [31:0] d;
        begin
            d = a - b;
            counter_before = d[31];
        end
    endfunction

    always @(posedge clk) begin
        pcpi_ready <= 1'b0;
        pcpi_wr    <= 1'b0;
        if (!resetn) begin
            pins_out <= 16'd0;
            uio_oe   <= 8'd0;
            pcpi_rd  <= 32'd0;
            deadline <= 32'd0;
            step     <= 16'd0;
        end else if (mine && !pcpi_ready) begin
            case (funct3)
                F_OUT: begin
                    pins_out   <= new_out;
                    pcpi_rd    <= {16'd0, new_out};
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_IN: begin
                    pcpi_rd    <= {16'd0, pins_in};
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_DIR: begin
                    uio_oe     <= new_oe;
                    pcpi_rd    <= {24'd0, new_oe};
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_TIME: begin
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_WAIT_UNTIL: if (deadline_reached) begin
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_WAIT_PIN: if (pins_match) begin
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_TIMER: if (!funct7[0]) begin              // SET.TIMER
                    deadline   <= pcpi_rs1;
                    step       <= pcpi_rs2[15:0];
                    pcpi_rd    <= pcpi_rs1;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (tick_reached) begin            // WAIT.TICK
                    deadline   <= deadline + {16'd0, step};
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_SHIFT: if (tick_reached) begin            // SHIFT.OUT/IN
                    if (!funct7[0]) pins_out[bit_idx] <= out_bit;
                    deadline   <= deadline + {16'd0, step};
                    pcpi_rd    <= shifted;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                default: ;
            endcase
        end
    end

`ifdef PINV_IO_FORMAL
`include "pinv_io_props.vh"
`endif

endmodule
