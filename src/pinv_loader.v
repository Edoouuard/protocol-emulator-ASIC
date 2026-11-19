/*
 * PinV program loader: a write-only SPI slave (mode 0, MSB first).
 * Copyright (c) 2026 Edouard Guillermain
 * SPDX-License-Identifier: Apache-2.0
 *
 * While LOAD is high the core is held in reset. Each byte shifted in on
 * MOSI (sampled on SCK rising edges) is written to program memory at the
 * next byte address, starting from 0 every time LOAD goes high. When LOAD
 * returns low the core starts executing from address 0.
 *
 * Inputs are synchronised to clk, so SCK must run at most clk/4.
 */

`default_nettype none

module pinv_loader (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        load,      // synchronised
    input  wire        sck,       // synchronised
    input  wire        mosi,      // synchronised

    output reg         we,
    output reg  [15:0] byte_addr,
    output reg  [7:0]  byte_data
);

    reg       sck_q;
    reg       load_q;
    reg [2:0] bit_cnt;
    reg [7:0] shift;

    always @(posedge clk) begin
        we <= 1'b0;
        if (!rst_n) begin
            sck_q     <= 1'b0;
            load_q    <= 1'b0;
            bit_cnt   <= 3'd0;
            shift     <= 8'd0;
            byte_addr <= 16'd0;
            byte_data <= 8'd0;
        end else begin
            sck_q  <= sck;
            load_q <= load;
            if (load && !load_q) begin
                bit_cnt   <= 3'd0;
                byte_addr <= 16'd0;
            end else if (load && sck && !sck_q) begin
                shift   <= {shift[6:0], mosi};
                bit_cnt <= bit_cnt + 3'd1;
                if (bit_cnt == 3'd7) begin
                    byte_data <= {shift[6:0], mosi};
                    we        <= 1'b1;
                end
            end
            if (we) byte_addr <= byte_addr + 16'd1;
        end
    end

endmodule
