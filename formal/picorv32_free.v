// Unconstrained stand-in for PicoRV32, used only by formal/top.sby.
// SPDX-License-Identifier: Apache-2.0
//
// Every output is a free value that can change arbitrarily every cycle, so the
// top-level proof covers any behaviour of the core, including a buggy or
// compromised program. Properties proven with it hold for the real core too.

module picorv32 #(
    parameter [0:0]  ENABLE_COUNTERS = 1, ENABLE_COUNTERS64 = 1, ENABLE_REGS_16_31 = 1,
    parameter [0:0]  ENABLE_REGS_DUALPORT = 1, COMPRESSED_ISA = 0, CATCH_MISALIGN = 1,
    parameter [0:0]  CATCH_ILLINSN = 1, ENABLE_PCPI = 0,
    parameter [31:0] PROGADDR_RESET = 32'h0, STACKADDR = 32'hffff_ffff
) (
    input  wire        clk, resetn,
    output wire        trap,
    output wire        mem_valid, mem_instr,
    input  wire        mem_ready,
    output wire [31:0] mem_addr, mem_wdata,
    output wire [3:0]  mem_wstrb,
    input  wire [31:0] mem_rdata,
    output wire        mem_la_read, mem_la_write,
    output wire [31:0] mem_la_addr, mem_la_wdata,
    output wire [3:0]  mem_la_wstrb,
    output wire        pcpi_valid,
    output wire [31:0] pcpi_insn, pcpi_rs1, pcpi_rs2,
    input  wire        pcpi_wr,
    input  wire [31:0] pcpi_rd,
    input  wire        pcpi_wait, pcpi_ready,
    input  wire [31:0] irq,
    output wire [31:0] eoi,
    output wire        trace_valid,
    output wire [35:0] trace_data
);
    (* anyseq *) reg        f_trap, f_mem_valid, f_mem_instr, f_la_read, f_la_write, f_pcpi_valid, f_trace_valid;
    (* anyseq *) reg [31:0] f_mem_addr, f_mem_wdata, f_la_addr, f_la_wdata, f_pcpi_insn, f_pcpi_rs1, f_pcpi_rs2, f_eoi;
    (* anyseq *) reg [3:0]  f_mem_wstrb, f_la_wstrb;
    (* anyseq *) reg [35:0] f_trace_data;
    assign trap = f_trap; assign mem_valid = f_mem_valid; assign mem_instr = f_mem_instr;
    assign mem_addr = f_mem_addr; assign mem_wdata = f_mem_wdata; assign mem_wstrb = f_mem_wstrb;
    assign mem_la_read = f_la_read; assign mem_la_write = f_la_write; assign mem_la_addr = f_la_addr;
    assign mem_la_wdata = f_la_wdata; assign mem_la_wstrb = f_la_wstrb;
    assign pcpi_valid = f_pcpi_valid; assign pcpi_insn = f_pcpi_insn;
    assign pcpi_rs1 = f_pcpi_rs1; assign pcpi_rs2 = f_pcpi_rs2;
    assign eoi = f_eoi; assign trace_valid = f_trace_valid; assign trace_data = f_trace_data;
endmodule
