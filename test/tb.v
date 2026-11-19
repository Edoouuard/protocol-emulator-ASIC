`default_nettype none
`timescale 1ns / 1ps

/* This testbench just instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // Wire up the inputs and outputs:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  // I2C bus on uio[0] (SDA) and uio[1] (SCL): open drain with pull-ups.
  // A line is low if the chip drives it low (output enabled, value 0) or
  // the simulated device (sda_dev_low / scl_dev_low) pulls it low.
  reg sda_dev_low = 1'b0;
  reg scl_dev_low = 1'b0;
  wire sda_bus = ~((uio_oe[0] & ~uio_out[0]) | sda_dev_low);
  wire scl_bus = ~((uio_oe[1] & ~uio_out[1]) | scl_dev_low);
  wire [7:0] uio_in_bus = {uio_in[7:2], scl_bus, sda_bus};

  // Replace tt_um_edoouuard_protoemu with your module name:
  tt_um_edoouuard_protoemu user_project (
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in_bus),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
