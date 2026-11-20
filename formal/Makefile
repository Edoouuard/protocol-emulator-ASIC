# Formal proofs of PinV with SymbiYosys (sby or yowasp-sby) and the Yices solver
# (pip install yices-solver).
#   make            -> run every proof and cover
SBY ?= $(shell command -v sby || command -v yowasp-sby)

all: pinv_io pinv_io_ni pinv_loader top

pinv_io pinv_io_ni pinv_loader top:
	$(SBY) -f $@.sby

clean:
	rm -rf pinv_io pinv_io_core pinv_io_bound pinv_io_cover pinv_io_ni pinv_io_ni_prove pinv_io_ni_cover \
	       pinv_loader pinv_loader_prove pinv_loader_cover top top_prove top_cover

.PHONY: all clean pinv_io pinv_io_ni pinv_loader top
