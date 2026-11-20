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
 *   6/2 SET.LIMIT  rs1         wait_max <= rs1[23:0]: a WAIT.PIN gives up after
 *                              wait_max cycles (0 = wait forever, the reset value)
 *   6/3 LOCK                   request the program lock (see project.v): from now
 *                              on the LOAD pin is ignored until the chip is reset
 *   6/4 SET.WAVE   rs1         pulse widths for PULSE: t0 <= rs1[15:0], t1 <= rs1[31:16]
 *   6/5 SET.IDLE   rs1, rs2    idle state: idle_out <= rs1[15:0], idle_oe <= rs2[15:8].
 *                              Outputs and directions take this state whenever the
 *                              core is held in reset (program reload). Only a chip
 *                              reset (rst_n) clears it, back to all zero.
 *
 * PIN.IN returns {15'b0, timed_out, pins}: timed_out is set when a WAIT.PIN
 * gave up, and cleared when PIN.IN reads it.
 *
 * Shift group (funct3 = 7), fused "wait for the deadline, move one bit,
 * advance the deadline", selected by funct7 (bit 0: in, bit 1: MSB first):
 *   7/0 SHIFT.OUT  rd, rs1, rs2   at the deadline: out[rs2[3:0]] <= rs1[0];  rd <= rs1 >> 1
 *   7/2 SHIFT.OUTM rd, rs1, rs2   at the deadline: out[rs2[3:0]] <= rs1[31]; rd <= rs1 << 1
 *   7/1 SHIFT.IN   rd, rs1, rs2   at the deadline: rd <= {pin[rs2[3:0]], rs1[31:1]}
 *   7/3 SHIFT.INM  rd, rs1, rs2   at the deadline: rd <= {rs1[30:0], pin[rs2[3:0]]}
 *   7/4 PULSE      rd, rs1, rs2   at the deadline: out[rs2[3:0]] <= 1, and the unit
 *                                 drives it back to 0 by itself t cycles later, with
 *                                 t = rs1[0] ? t1 : t0;  rd <= rs1 >> 1
 *   7/6 PULSEM     rd, rs1, rs2   same, MSB first: t = rs1[31] ? t1 : t0; rd <= rs1 << 1
 *   then deadline <= deadline + step.
 *
 * PULSE is a waveform serializer: one instruction per bit, and both edges of
 * the bit are placed by the hardware, so a pulse-width code (WS2812 LEDs,
 * 1-Wire-like lines, IR remotes) needs no software timing inside a bit.
 * The pulse lasts exactly t cycles (t >= 1; t = 0 behaves as 1). One pulse is
 * in flight at a time: a new PULSE ends the previous one first.
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
    input  wire        resetn,      // core reset (also held during a program load)
    input  wire        chip_resetn, // chip reset (rst_n): clears the idle state

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
    output reg  [7:0]  uio_oe,
    output reg         lock_req     // one-cycle pulse when LOCK executes
`ifdef PINV_IO_NI
    , output wire [138:0] f_timing_state   // for the non-interference proof only
`endif
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
                         || (funct3 == F_TIMER && funct7[6:3] == 4'd0 && funct7[2:0] <= 3'd5)
                         || (funct3 == F_SHIFT && funct7[6:3] == 4'd0 && !(funct7[2] && funct7[0]));
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
    reg  [23:0] wait_max;       // WAIT.PIN limit in cycles, 0 = no limit
    reg         pin_waiting;    // a WAIT.PIN has started waiting
    reg         pin_limited;    // ...with a limit
    reg  [23:0] pin_left;       // ...cycles left before it gives up
    reg         timed_out;      // sticky: a WAIT.PIN gave up (cleared by PIN.IN)
    reg  [15:0] t0, t1;         // PULSE widths for a 0 and a 1
    reg         fall_on;        // a PULSE is high and waits for its falling edge
    reg  [3:0]  fall_pin;       // ...on this pin
    reg  [15:0] fall_left;      // ...in this many cycles (falls when it reaches 1)
    reg  [15:0] idle_out;       // state of the outputs while the core is in reset
    reg  [7:0]  idle_oe;        // state of the directions while the core is in reset

    // The falling edge of a pulse happens by itself, whatever the core does.
    // Every instruction below starts from pins_now, so an edge is never lost.
    wire        fall_now = fall_on && fall_left <= 16'd1;
    wire [15:0] pins_now = fall_now ? pins_out & ~(16'd1 << fall_pin) : pins_out;

    wire [15:0] new_out = (pins_now & ~pcpi_rs2[15:0]) | (pcpi_rs1[15:0] & pcpi_rs2[15:0]);
    wire        tick_reached = !counter_before(counter, deadline);
    wire [3:0]  bit_idx   = pcpi_rs2[3:0];
    wire        msb_first = funct7[1];
    wire        out_bit   = msb_first ? pcpi_rs1[31] : pcpi_rs1[0];
    wire        is_pulse  = funct7[2];
    wire [15:0] pulse_len = out_bit ? t1 : t0;
    // A new pulse first ends the one in flight, then raises its own pin.
    wire [15:0] pulse_base = fall_on ? pins_now & ~(16'd1 << fall_pin) : pins_now;
    wire        in_bit    = pins_in[bit_idx];
    wire [31:0] shifted   = funct7[0] ? (msb_first ? {pcpi_rs1[30:0], in_bit} : {in_bit, pcpi_rs1[31:1]})
                                      : (msb_first ? {pcpi_rs1[30:0], 1'b0}   : {1'b0, pcpi_rs1[31:1]});
    wire [7:0]  new_oe  = (uio_oe & ~pcpi_rs2[15:8]) | (pcpi_rs1[15:8] & pcpi_rs2[15:8]);
    wire        deadline_reached = !counter_before(counter, pcpi_rs1);
    wire        pins_match = ((pins_in ^ pcpi_rs2[15:0]) & pcpi_rs1[15:0]) == 16'd0;
    wire        pin_expired = pin_waiting && pin_limited && pin_left == 24'd0;

    // Wrap-safe "a is before b" on a free-running 32-bit counter.
    function counter_before(input [31:0] a, input [31:0] b);
        reg [31:0] d;
        begin
            d = a - b;
            counter_before = d[31];
        end
    endfunction

    // The idle state survives a program reload; only a chip reset clears it.
    always @(posedge clk) begin
        if (!chip_resetn) begin
            idle_out <= 16'd0;
            idle_oe  <= 8'd0;
        end else if (resetn && mine && !pcpi_ready && funct3 == F_TIMER && funct7[2:0] == 3'd5) begin
            idle_out <= pcpi_rs1[15:0];
            idle_oe  <= pcpi_rs2[15:8];
        end
    end

    always @(posedge clk) begin
        pcpi_ready <= 1'b0;
        pcpi_wr    <= 1'b0;
        lock_req   <= 1'b0;
        if (!resetn) begin
            pins_out <= chip_resetn ? idle_out : 16'd0;
            uio_oe   <= chip_resetn ? idle_oe  : 8'd0;
            t0       <= 16'd0;
            t1       <= 16'd0;
            fall_on  <= 1'b0;
            fall_pin <= 4'd0;
            fall_left <= 16'd0;
            pcpi_rd  <= 32'd0;
            deadline <= 32'd0;
            step     <= 16'd0;
            wait_max <= 24'd0;
            pin_waiting  <= 1'b0;
            pin_limited  <= 1'b0;
            pin_left     <= 24'd0;
            timed_out    <= 1'b0;
        end else begin
          // Autonomous falling edge of a pulse (an instruction below may override).
          pins_out <= pins_now;
          if (fall_now)     fall_on   <= 1'b0;
          else if (fall_on) fall_left <= fall_left - 16'd1;
          if (mine && !pcpi_ready) begin
            case (funct3)
                F_OUT: begin
                    pins_out   <= new_out;
                    pcpi_rd    <= {16'd0, new_out};
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_IN: begin
                    pcpi_rd    <= {15'd0, timed_out, pins_in};
                    timed_out  <= 1'b0;
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
                F_WAIT_PIN: if (pins_match || pin_expired) begin
                    if (!pins_match) timed_out <= 1'b1;
                    pin_waiting <= 1'b0;
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (!pin_waiting) begin
                    // first cycle without a match: start the countdown
                    pin_waiting  <= 1'b1;
                    pin_limited  <= wait_max != 24'd0;
                    pin_left     <= wait_max - 24'd1;
                end else begin
                    pin_left     <= pin_left - 24'd1;
                end
                F_TIMER: if (funct7[2:0] == 3'd4) begin     // SET.WAVE
                    t0         <= pcpi_rs1[15:0];
                    t1         <= pcpi_rs1[31:16];
                    pcpi_rd    <= pcpi_rs1;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (funct7[2:0] == 3'd5) begin     // SET.IDLE (register above)
                    pcpi_rd    <= pcpi_rs1;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (funct7[1:0] == 2'd0) begin     // SET.TIMER
                    deadline   <= pcpi_rs1;
                    step       <= pcpi_rs2[15:0];
                    pcpi_rd    <= pcpi_rs1;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (funct7[1:0] == 2'd2) begin     // SET.LIMIT
                    wait_max   <= pcpi_rs1[23:0];
                    pcpi_rd    <= pcpi_rs1;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (funct7[1:0] == 2'd3) begin     // LOCK
                    lock_req   <= 1'b1;
                    pcpi_rd    <= 32'd0;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end else if (tick_reached) begin            // WAIT.TICK
                    deadline   <= deadline + {16'd0, step};
                    pcpi_rd    <= counter;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                F_SHIFT: if (tick_reached) begin            // SHIFT.OUT/IN, PULSE
                    if (is_pulse) begin
                        pins_out  <= pulse_base | (16'd1 << bit_idx);
                        fall_on   <= 1'b1;
                        fall_pin  <= bit_idx;
                        fall_left <= pulse_len;
                    end else if (!funct7[0]) begin
                        pins_out  <= (pins_now & ~(16'd1 << bit_idx)) | ({15'd0, out_bit} << bit_idx);
                    end
                    deadline   <= deadline + {16'd0, step};
                    pcpi_rd    <= shifted;
                    pcpi_wr    <= 1'b1;
                    pcpi_ready <= 1'b1;
                end
                default: ;
            endcase
          end
        end
    end

`ifdef PINV_IO_NI
    // Everything that decides *when* the unit answers and moves the deadline.
    assign f_timing_state = {counter, deadline, step, wait_max, pin_waiting, pin_limited,
                             pin_left, pcpi_ready, idle_oe};
`endif

`ifdef PINV_IO_FORMAL
`include "pinv_io_props.vh"
`endif

endmodule
