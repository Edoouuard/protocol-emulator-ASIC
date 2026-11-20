#!/bin/sh
# Rebuild every test binary and its proof certificate from firmware/.
# The certificate (<name>.proof.json) is what test.py checks before loading.
set -e
cd "$(dirname "$0")/../../firmware"
out=../test/programs
build() {   # name  program  make-arguments...
    name=$1; prog=$2; shift 2
    rm -rf build
    make -s "$@" build/$prog.bin >/dev/null
    cp build/$prog.bin $out/$name.bin
    cp build/$prog.proof.json $out/$name.proof.json
    echo "$name: $(stat -c %s $out/$name.bin) bytes, $(python3 -c "import json;print(json.load(open('$out/$name.proof.json'))['status'])")"
}
build uart_echo        uart_echo    BIT_CYCLES=64
build uart_echo_locked uart_echo    BIT_CYCLES=64 EXTRA=-DPINV_LOCKED
for m in 0 1 2 3; do
build spi_jedec_mode$m spi_jedec    BIT_CYCLES=64 SPI_HALF=80 SPI_MODE=$m
done
build i2c_read         i2c_read     BIT_CYCLES=64 I2C_Q=60 EXTRA=-DI2C_LIMIT=1000
build ws2812           ws2812
build spi_firewall     spi_firewall BIT_CYCLES=64
rm -rf build
