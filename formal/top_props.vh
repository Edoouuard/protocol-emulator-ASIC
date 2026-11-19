// Formal properties of the PinV top level: program loading and core reset.
// Included inside tt_um_edoouuard_protoemu only when PINV_TOP_FORMAL is defined.
// SPDX-License-Identifier: Apache-2.0
//
// All pins are unconstrained: any sequence a board, a bug or an attacker
// could put on LOAD, SCK and MOSI is covered.

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;
    always @(*) if (!f_past) assume (!rst_n);

    always @(posedge clk) if (f_past) begin
        // T1. The loader never writes memory while the program runs:
        // every loader write happens while the core is held in reset.
        if (ld_we) assert (!core_resetn);

        // T2. While LOAD is high (after synchronisation), the core is held in reset.
        if ($past(load)) assert (!core_resetn);

        // T3. When LOAD is low and the chip is out of reset, the core runs.
        if ($past(!load && rst_n)) assert (core_resetn);
    end

    // Covers (reachability, so the proof is not vacuous). Loader writes themselves
    // are covered by formal/pinv_loader.sby.
    always @(posedge clk) if (f_past && rst_n) begin
        cover ($past(load) && !core_resetn);            // held in reset by LOAD
        cover ($past(!core_resetn) && core_resetn);     // core released after loading
    end
