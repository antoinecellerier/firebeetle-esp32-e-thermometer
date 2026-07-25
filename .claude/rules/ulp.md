---
paths:
  - "ulp/**"
  - "src/UlpProgram*.cpp"
  - "include/UlpProgram.h"
  - "src/sensors/**"
  - "components/hulp/**"
  - "scripts/check_ulp_size.py"
---

# ULP / LP core rules

Two entirely different coprocessors behind one feature:

- **ESP32-E** — ULP FSM, driven by the HULP library, bit-banged I2C
  (GPIO0=SDA, GPIO4=SCL). Guard with `SOC_ULP_FSM_SUPPORTED`.
- **ESP32-C6** — LP RISC-V core with hardware LP I2C (GPIO6=SDA, GPIO7=SCL),
  built natively via `ulp_embed_binary` in `src/CMakeLists.txt`. Guard with
  `SOC_LP_CORE_SUPPORTED`.

`HAS_ULP_SUPPORT` is the unified macro for "there is a coprocessor at all".
Sensor drivers have three compile paths — ULP FSM, LP core, no-ULP — see
`src/sensors/BMP390LSensor.cpp` and `BMP58xSensor.cpp`.

## PlatformIO feeds every file in `ulp/` to the active ULP toolchain

That is why `ulp/lp_core_main.c` is wrapped in `#ifdef __riscv`: on ESP32-E the
FSM pass preprocesses it to nothing, and HULP builds the FSM program at runtime
instead. A new file in `ulp/` needs the same guard or it breaks the other board.

The LP core dispatcher derives its sensor from the `USE_*` macros via a relative
`#include "../include/local-secrets.h"` — the LP sub-build does not inherit the
main build's include paths.

## The FSM word budget is checked at build time

`scripts/check_ulp_size.py` preprocesses the program arrays with the real
toolchain and fails the build past `CONFIG_ULP_COPROC_RESERVE_MEM/4` = 128 words.
**Currently 127/128** — one spare word. The runtime loader also logs the count and
degrades to safety-net wakes rather than aborting if it ever misfits.

## ULP data and `RTC_DATA_ATTR` share the same 8KB

Both live at `0x50000000`. `ULP_DATA_BASE` must be past all `.rtc.data` /
`.rtc.force_slow` sections — **60 bytes spare on ESP32-E**. Adding an
`RTC_DATA_ATTR` variable eats that headroom; see `.claude/rules/rtc-state.md`.

`scripts/post_build_check_rtc.py` verifies this at build time and
`ulp_check_data_overlap()` aborts at runtime on overlap. On ESP32-E,
`CONFIG_ULP_COPROC_RESERVE_MEM=512` preserves the layout `ULP_DATA_BASE` assumes.

## Counters

LP-core counters (`lp_wake_count`, `lp_error_count`, `last_lp_error`,
`last_lp_op`, `sample_count`) live in the LP core's `.bss` in LP RAM, **not** in
`RTC_DATA_ATTR`. `ulp_lp_core_load_binary()` does not touch `.bss`, so
`InitializeUlp()` zeroes them explicitly. On the ESP32-E FSM path there is no
cumulative wake counter at all — `lp_wake_count` renders as 0 on FireBeetle.
