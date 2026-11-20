// Formal properties of the PinV top level: program loading and core reset.
// Included inside tt_um_edoouuard_protoemu only when PINV_TOP_FORMAL is defined.
// SPDX-License-Identifier: Apache-2.0
//
// All pins are unconstrained: any sequence a board, a bug or an attacker
// could put on LOAD, SCK and MOSI is covered.

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;
    // The chip is reset for at least 3 cycles at power-up (the Tiny Tapeout
    // board holds rst_n low far longer): enough for every register that feeds
    // the reset logic to settle.
    reg [1:0] f_age = 2'd0;
    always @(posedge clk) if (f_age != 2'd3) f_age <= f_age + 2'd1;
    always @(*) if (f_age != 2'd3) assume (!rst_n);

    always @(posedge clk) if (f_past) begin
        // T1. The loader never writes memory while the program runs:
        // every loader write happens while the core is held in reset.
        if (ld_we) assert (!core_resetn);

        // T2. While LOAD is high (after synchronisation), the core is held in reset.
        if ($past(load)) assert (!core_resetn);

        // T3. When LOAD is low, a program has been loaded and the chip is out of
        // reset, the core runs.
        if ($past(!load && rst_n && loaded)) assert (core_resetn);
        // T4. The core never runs before a program has been loaded (after power-up
        // the memory holds random values, which must never execute).
        if (core_resetn) assert ($past(loaded));
        if (!$past(rst_n)) assert (!loaded);

        // K1. Once locked, the chip stays locked until it is reset.
        if ($past(locked) && $past(rst_n)) assert (locked);
        if (!$past(rst_n)) assert (!locked);
        // K2. Once locked, the LOAD pin has no effect: whatever it does, the loader
        // never writes and the core is never stopped. The program can neither be
        // replaced nor halted from outside until the next reset.
        if ($past(locked)) assert (!ld_we);
        if ($past(locked) && $past(rst_n)) assert (core_resetn);
        // Locking is only possible once a program runs.
        if (locked) assert (loaded);
    end

    // Covers (reachability, so the proof is not vacuous). Loader writes themselves
    // are covered by formal/pinv_loader.sby.
    always @(posedge clk) if (f_past && rst_n) begin
        cover ($past(load) && !core_resetn);            // held in reset by LOAD
        cover ($past(!core_resetn) && core_resetn);     // core released after loading
        cover (locked && $past(in_s2[7]) && core_resetn); // LOAD high but ignored
    end
