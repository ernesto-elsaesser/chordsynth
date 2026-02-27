#!/bin/bash

# -O3 \
# -ftree-vectorize \
./aarch64--glibc--stable-2024.05-1/bin/aarch64-linux-gcc \
    -march=armv8-a \
    -mcpu=cortex-a53 \
    -mtune=cortex-a53 \
    -lSDL2 \
    -lm \
    synth.c -o synth-arm
