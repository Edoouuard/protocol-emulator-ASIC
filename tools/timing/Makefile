# Run the instruction-timing micro-benchmarks on the RTL (Icarus Verilog + cocotb).
#   python3 gen_bench.py /tmp/bench && make BENCH_DIR=/tmp/bench
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../../src
VERILOG_SOURCES += $(SRC_DIR)/project.v $(SRC_DIR)/pinv_io.v $(SRC_DIR)/pinv_loader.v $(SRC_DIR)/picorv32.v $(PWD)/../../test/tb.v
COMPILE_ARGS += -I$(SRC_DIR)
COCOTB_TOPLEVEL = tb
COCOTB_TEST_MODULES = bench_test
export BENCH_DIR
include $(shell cocotb-config --makefiles)/Makefile.sim
