/*
 * PinV: a RISC-V protocol emulator for Tiny Tapeout.
 * Copyright (c) 2026 Edouard Guillermain
 * SPDX-License-Identifier: Apache-2.0
 *
 * PicoRV32 (RV32EC) + on-chip program/data memory + pin/timing unit + loader.
 *
 * Pins:
 *   ui_in[7]   LOAD  (high: core in reset, loader active)
 *   ui_in[6]   SCK   loader clock    (free for programs when LOAD is low)
 *   ui_in[5]   MOSI  loader data     (free for programs when LOAD is low)
 *   ui_in[4:0], uo_out[7:0], uio[7:0]: general purpose, driven by the program.
 */

`default_nettype none

module tt_um_edoouuard_protoemu #(
    parameter MEM_WORDS = 128       // 512 bytes of program + data memory
) (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam AW = $clog2(MEM_WORDS);

    // ---- Input synchronisers -------------------------------------------
    reg [15:0] in_s1, in_s2;
    always @(posedge clk) begin
        in_s1 <= {uio_in, ui_in};
        in_s2 <= in_s1;
    end
    wire load = in_s2[7];

    // ---- Core reset ----------------------------------------------------
    reg core_resetn;
    always @(posedge clk) core_resetn <= rst_n && !load;

    // ---- Loader --------------------------------------------------------
    wire        ld_we;
    wire [15:0] ld_addr;
    wire [7:0]  ld_data;

    pinv_loader loader (
        .clk(clk), .rst_n(rst_n),
        .load(load), .sck(in_s2[6]), .mosi(in_s2[5]),
        .we(ld_we), .byte_addr(ld_addr), .byte_data(ld_data)
    );

    // ---- Core ----------------------------------------------------------
    wire        mem_valid, mem_instr;
    wire [31:0] mem_addr, mem_wdata, mem_rdata;
    wire [3:0]  mem_wstrb;

    wire        pcpi_valid;
    wire [31:0] pcpi_insn, pcpi_rs1, pcpi_rs2, pcpi_rd;
    wire        pcpi_wr, pcpi_wait, pcpi_ready;

    picorv32 #(
        .ENABLE_COUNTERS     (0),
        .ENABLE_COUNTERS64   (0),
        .ENABLE_REGS_16_31   (0),      // RV32E
        .ENABLE_REGS_DUALPORT(0),
        .COMPRESSED_ISA      (1),
        .CATCH_MISALIGN      (0),
        .CATCH_ILLINSN       (0),
        .ENABLE_PCPI         (1),
        .PROGADDR_RESET      (32'h0000_0000),
        .STACKADDR           (MEM_WORDS * 4)
    ) core (
        .clk(clk), .resetn(core_resetn),
        .trap(),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_valid),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_rdata(mem_rdata),
        .mem_la_read(), .mem_la_write(), .mem_la_addr(),
        .mem_la_wdata(), .mem_la_wstrb(),
        .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
        .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
        .pcpi_wr(pcpi_wr), .pcpi_rd(pcpi_rd),
        .pcpi_wait(pcpi_wait), .pcpi_ready(pcpi_ready),
        .irq(32'd0), .eoi(),
        .trace_valid(), .trace_data()
    );

    // ---- Memory (single-cycle, byte-writable) --------------------------
    reg [31:0] mem [0:MEM_WORDS-1];
    wire [AW-1:0] core_word = mem_addr[AW+1:2];
    assign mem_rdata = mem[core_word];

    always @(posedge clk) begin
        if (ld_we) begin
            case (ld_addr[1:0])
                2'd0: mem[ld_addr[AW+1:2]][7:0]   <= ld_data;
                2'd1: mem[ld_addr[AW+1:2]][15:8]  <= ld_data;
                2'd2: mem[ld_addr[AW+1:2]][23:16] <= ld_data;
                2'd3: mem[ld_addr[AW+1:2]][31:24] <= ld_data;
            endcase
        end else if (mem_valid) begin
            if (mem_wstrb[0]) mem[core_word][7:0]   <= mem_wdata[7:0];
            if (mem_wstrb[1]) mem[core_word][15:8]  <= mem_wdata[15:8];
            if (mem_wstrb[2]) mem[core_word][23:16] <= mem_wdata[23:16];
            if (mem_wstrb[3]) mem[core_word][31:24] <= mem_wdata[31:24];
        end
    end

    // ---- Pin / timing unit ---------------------------------------------
    wire [15:0] pins_out;
    wire [7:0]  oe;

    pinv_io io (
        .clk(clk), .resetn(core_resetn),
        .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
        .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
        .pcpi_wr(pcpi_wr), .pcpi_rd(pcpi_rd),
        .pcpi_wait(pcpi_wait), .pcpi_ready(pcpi_ready),
        .pins_in(in_s2), .pins_out(pins_out), .uio_oe(oe)
    );

    assign uo_out  = pins_out[7:0];
    assign uio_out = pins_out[15:8];
    assign uio_oe  = oe;

    wire _unused = &{ena, mem_instr, mem_addr[31:AW+2], mem_addr[1:0], ld_addr[15:AW+2], 1'b0};

endmodule
