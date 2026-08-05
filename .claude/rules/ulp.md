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

- **ESP32-E** — ULP FSM, driven by the HULP library, over **bit-banged** I2C.
  Guard with `SOC_ULP_FSM_SUPPORTED`.
- **ESP32-C6** — LP RISC-V core with **hardware** LP I2C, built natively via
  `ulp_embed_binary` in `src/CMakeLists.txt`. Guard with `SOC_LP_CORE_SUPPORTED`.

Pin assignments are per-board and live in `include/app_common.h` — read them
there rather than from any doc, this one included.

`HAS_ULP_SUPPORT` is the unified macro for "there is a coprocessor at all".
Sensor drivers have three compile paths — ULP FSM, LP core, no-ULP — see
`src/sensors/BMP390LSensor.cpp` and `BMP58xSensor.cpp`.

## PlatformIO feeds every file in `ulp/` to the active ULP toolchain

That is why `ulp/lp_core_main.c` is wrapped in `#ifdef __riscv`: on ESP32-E the
FSM pass preprocesses it to nothing, and HULP builds the FSM program at runtime
instead. A new file in `ulp/` needs the same guard or it breaks the other board.

The LP core dispatcher derives its sensor from the `USE_*` macros via a relative
`#include "../include/generated/rig_config.h"` — the LP sub-build inherits
neither `build_flags` nor `build_src_flags`, so config it must see cannot be a
`-D` at all.

It compiles with **`-DIS_ULP_COCPU` and no board macros at all**
(`IDFULPProject.cmake:107,159`), which is why the rig headers' env cross-checks
are wrapped in `#if !defined(IS_ULP_COCPU)`. Drop that guard and every C6 build
fails.

## The FSM word budget is checked at build time

`scripts/check_ulp_size.py` preprocesses the program arrays with the real
toolchain and fails the build past `CONFIG_ULP_COPROC_RESERVE_MEM/4`. It prints
`ULP size check: <file> = N/BUDGET words` on every build — **read the actual
margin there before adding an instruction**, it has run close to full. The
runtime loader also logs the count and degrades to safety-net wakes rather than
aborting if it ever misfits.

It preprocesses with `build_src_flags` applied on top of the global env,
because that is what the ULP sources are compiled with. A bench macro that
changes the program (`ULP_ALWAYS_WAKE` swaps the whole wake body:
127/128 words without it, 110/128 with) must reach the check, or it reports a
count for a program the build never compiled.

## ULP data and `RTC_DATA_ATTR` share the same 8KB

Both live at `0x50000000`. `ULP_DATA_BASE` (`include/UlpProgram.h`) must sit past
all `.rtc.data` / `.rtc.force_slow` sections, and the gap between them has been
small. Adding an `RTC_DATA_ATTR` variable eats that headroom; see
`.claude/rules/rtc-state.md`.

`scripts/post_build_check_rtc.py` reports both ends of the area at build time —
take the margin from its output, not from a figure quoted elsewhere.
`ulp_check_data_overlap()` also aborts at runtime on overlap. The reserve size is
authored per target in `sdkconfig.defaults.<target>`; on ESP32-E that value is
what `ULP_DATA_BASE` assumes, so changing one means revisiting the other.

## Counters

LP-core counters (`lp_wake_count`, `lp_error_count`, `last_lp_error`,
`last_lp_op`, `sample_count`) live in the LP core's `.bss` in LP RAM, **not** in
`RTC_DATA_ATTR`. `ulp_lp_core_load_binary()` does not touch `.bss`, so
`InitializeUlp()` zeroes them explicitly. On the ESP32-E FSM path there is no
cumulative wake counter at all — `lp_wake_count` renders as 0 on FireBeetle.
