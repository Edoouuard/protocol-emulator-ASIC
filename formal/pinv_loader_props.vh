// Formal properties of the PinV program loader.
// Included inside pinv_loader only when PINV_LOADER_FORMAL is defined.
// SPDX-License-Identifier: Apache-2.0

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;
    always @(*) if (!f_past) assume (!rst_n);

    always @(posedge clk) if (f_past && $past(rst_n) && rst_n) begin
        // L1. A byte is written only in load mode, after its 8th SCK rising edge.
        if (we) assert ($past(load) && $past(sck && !sck_q) && $past(bit_cnt) == 3'd7);
        // L2. Every new load starts writing at address 0.
        if ($past(load && !load_q)) assert (byte_addr == 16'd0 && bit_cnt == 3'd0);
        // L3. Addresses advance by exactly one after each written byte, never otherwise.
        if (!$past(load && !load_q))
            assert (byte_addr == $past(byte_addr) + ($past(we) ? 16'd1 : 16'd0));
        // L4. The written byte is the 8 bits shifted in, most significant first.
        if (we) assert (byte_data == {$past(shift[6:0]), $past(mosi)});
    end

    always @(posedge clk) if (f_past && rst_n) cover (we && byte_addr == 16'd1);  // second byte written
