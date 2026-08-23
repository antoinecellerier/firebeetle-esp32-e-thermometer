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
instead. A new file in `ulp/` needs the same guard or it breaks the other board —
**and an entry in `src/CMakeLists.txt`**, whose `ulp_sources` names its files
explicitly. PlatformIO globs the directory, `idf.py` does not, so a file added
without that entry builds under one and silently vanishes under the other.

## There are no headers under `ulp/`, and that is load-bearing

The three sensor programs live inline in `lp_core_main.c`. They used to be
`lp_core_{idle,bmp390l,bmp58x}.h`, and as headers they were **invisible to the
build**: PlatformIO signs the LP object on `lp_core_main.c`'s own content, so
editing a header rebuilt nothing and the previously built `ulp_main.bin` was
embedded again — silently, with a successful build.

Measured 2026-08-23. An `#error` in `lp_core_bmp58x.h` does not fail the build;
the same `#error` in `lp_core_main.c` does. Neither touching the source (the
decider is content, not mtime) nor deleting `esp-idf/src/ulp_main/` helps —
nothing left in the graph needs the artifact. Adding a generated stamp file to
`ulp_sources` does not help either: the stamp recompiles, the stale object is
`lp_core_main.c`'s. **Only a build with `.pio/build_cache` cleared produces a
correct binary.**

This is upstream and long-standing: [platform-espressif32
#517](https://github.com/platformio/platform-espressif32/issues/517), open since
March 2021, reported there as ULP *sources* going unnoticed.

What it cost: an experiment arm was flashed with the wrong wake cadence while the
`! EXP` badge, the ULP word-count check and the baked git hash all reported
success. **None of the existing gates look at the LP binary.**

So:

- **Do not add a header under `ulp/`.** Splitting the sensor programs back out
  would need a header of `extern`s for the eleven shared LP globals, which would
  be stale-able in exactly the same way.
- **When anything the LP program depends on changes, verify the binary rather
  than the build log.** `rm -rf .pio/build_cache`, rebuild, and compare
  `md5sum .pio/build/<env>/esp-idf/src/ulp_main/ulp_main.bin` against a build you
  know is vanilla. A changed LP program that produces an unchanged md5 did not
  reach the flash.
- **One latent case remains**: `lp_core_main.c` includes the generated
  `rig_config.h`, and a rig switch changes which sensor branch compiles without
  changing this file's content. It cannot bite today — every C6 rig selects
  `USE_BMP58x` — but a C6 rig with a different sensor would reintroduce it, and
  the fix then is the cache clear above, not another generated file.

The LP core dispatcher derives its sensor from the `USE_*` macros via a relative
`#include "../include/generated/rig_config.h"` — the LP sub-build inherits
neither `build_flags` nor `build_src_flags`, so config it must see cannot be a
`-D` at all.

It compiles with **`-DIS_ULP_COCPU` and no board macros at all**
(IDF's `IDFULPProject.cmake`), which is why the rig headers' env cross-checks
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
