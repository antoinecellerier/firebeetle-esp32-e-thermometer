# Firmware footprint ledger — espidf migration

## Summary (migration complete, stages 0→E)

Arduino (baseline) → pure ESP-IDF, both boards, stock platform, no fork:

- **Flash**: ESP32-E release 1196KB → 1014KB (−182KB); C6 release 1265KB → 1072KB
  (−193KB, display enabled). App slot went from 1280KB OTA (~91–97% full) to a
  4MB single-app partition (~24–26% full) — the flash ceiling is gone.
- **Static DRAM**: ESP32-E 49.7KB → 38.0KB (−11.7KB); C6 44.0KB → 39.4KB (−4.6KB).
- **Where it came from**: Arduino core + String/Print/HAL statics, Arduino
  WiFi/Network stack (→ esp_wifi direct), DFRobot/Wire (→ I2cBus over
  i2c_master), log level WARN, no OTA second slot.
- **What didn't move (by design)**: RTC slow memory (8KB shared ULP/RTC_DATA_ATTR),
  deep-sleep current path (was already pure IDF sleep code).
- **Build times**: env-switch invalidation eliminated (167s/~2400 files → 3–4s/0);
  same-env no-op 19–30s → 3–4s; one-time ~5min IDF-from-source per clean checkout.

Method: `size -A .pio/build/<env>/firmware.elf` (toolchain binutils) + `stat -c%s firmware.bin`.
DRAM = `.dram0.data` + `.dram0.bss` (+ `.noinit`). Flash% is against the 1280KB `app0` slot
of the default OTA partition table (baseline; later stages switch to single-app).
RTC = `.rtc.data` + `.rtc.force_slow` (8KB budget shared with ULP, framework-independent).

| Stage | Env | .bin bytes | Flash% (1280K) | DRAM bytes | IRAM .text | RTC bytes | Notes |
|---|---|---|---|---|---|---|---|
| 0 baseline (Arduino, 21b1055) | esp32e_debug | 1215680 | 92.7% | 49652 | 93663 | 6516 | |
| 0 baseline | esp32e_release | 1195952 | 91.2% | 49652 | 93663 | 6516 | |
| 0 baseline | c6_debug | 1272720 | 97.1%* | 44092 | 101184 | 6428 | *bin incl. padding; PIO reports 93.7% flash |
| 0 baseline | c6_release | 1264896 | 96.5%* | 43980 | 100928 | 6428 | fork platform, Arduino precompiled libs |
| A idf-i2c/helpers | esp32e_debug | 1213344 | 92.0% | 49508 | 92635 | 6516 | DFRobot_BMP3XX + Wire dropped |
| A | esp32e_release | 1193648 | 90.5% | 49508 | 92635 | 6516 | −2.3KB bin vs baseline |
| A | c6_debug | 1273104 | 94.0% | 44012 | 101176 | 6428 | ~flat (Wire→i2c_master, both already in libs) |
| A | c6_release | 1265152 | 93.8% | 43900 | 100916 | 6428 | |
| B esp_wifi/sntp | esp32e_debug | 1152656 | 87.4% | 49008 | 92635 | 6516 | Arduino WiFi/Network libs gone |
| B | esp32e_release | 1138400 | 86.4% | 49008 | 92635 | 6516 | −57KB bin vs stage A |
| B | c6_debug | 1208016 | 89.6% | 43492 | 101176 | 6428 | |
| B | c6_release | 1106528 | 82.3% | 43280 | 90130 | 6428 | −158KB bin vs stage A |
| C pure espidf (C6) | c6_debug | 946816 | 22.6%** | 38164 | 117802 | 6428 | **single-app 4MB partition; −261KB bin vs B; DISABLE_DISPLAY temp. |
| C | c6_release | 943648 | 22.5%** | 38164 | 117802 | 6428 | fork + Arduino layer gone |
| D pure espidf (both) | esp32e_debug | 1017824 | 24.3%** | 37980 | 109199 | 6536 | Arduino layer gone; GxEPD2/GFX via arduino_shim |
| D | esp32e_release | 1014240 | 24.2%** | 37980 | 109199 | 6536 | −124KB bin + −11.5KB DRAM vs B (Arduino) |
| D | c6_debug | 1075168 | 25.6%** | 39420 | 127554 | 6428 | display re-enabled (DISABLE_DISPLAY dropped) |
| D | c6_release | 1071664 | 25.5%** | 39420 | 127554 | 6428 | |
| F official platform | all four | ≈D | 25-27%*** | ≈D | ≈D | — | espressif32@~6.13.0 (IDF 5.5.3), sizes within noise of D |
| F2 IDF 6.0.1 | esp32e_debug | — | 26.3%*** | 38344 | — | — | espressif32@^7.0.1, newlib pinned (see sdkconfig.defaults) |
| F2 | esp32e_release | — | 25.8%*** | 38344 | — | — | +42KB vs IDF 5.5 (newlib mode; picolibc blocked by PIO ulp.py) |
| F2 | c6_debug | — | 27.9%*** | 39840 | — | — | |
| F2 | c6_release | — | 27.3%*** | 39840 | — | — | +46KB vs IDF 5.5 |

*** Stage F correction: through stages C-D the ACTUAL flashed partition table was
PlatformIO's default 1MB single-app (PIO ignores the sdkconfig partition choice) —
the C6 binaries would have failed the bootloader size check on real hardware. The
official platform's stricter size check exposed it. Fixed with a repo-owned
partitions.csv (3968KB factory app + 64KB coredump) referenced by both PIO
(board_build.partitions) and idf.py (CONFIG_PARTITION_TABLE_CUSTOM). Flash%
figures above marked ** were computed against board flash, not the app slot.

Behavioral baseline (2026-07-03): sim screenshots saved (28 PNGs, all scenarios render);
C6 deep-sleep ~15µA (PPK2, prior measurement). Tag: `pre-idf-migration`.

## Build times

Wall-clock `pio run`, warm caches. The env-switch row is the pain point: under
Arduino+fork, building one board invalidates the other board's Arduino core build.

| Stage | Scenario | Time | Notes |
|---|---|---|---|
| B (Arduino+fork) | esp32e_debug no-op, same env | 30s | SCons+LDF overhead only, 0 recompiles |
| B | c6_debug no-op, same env | 19s | |
| B | c6_debug after esp32e build (env switch) | 167s | ~2400 files recompiled, no source change |
| B | c6_debug with framework re-check pass | 229s | fork's Arduino-lib recompile validation pass |
| B | esp32e_debug incremental (1 cpp changed) | 91s | |
| C (C6 pure espidf) | c6_debug no-op, same env | 3.3s | vs 19s under Arduino |
| C | c6_debug no-op after esp32e build (env switch) | 4s | **0 recompiles** — flip-flop eliminated (was 167s / ~2400 files) |
| C | c6 first build (IDF from source) | ~5min | one-time per clean checkout |
| D (both pure espidf) | env-switch no-op, either direction | 3–4s | 0 recompiles; Arduino-era penalty (167s/~2400 files) gone for good |
| D | esp32e_release / c6_release incremental | 24s / 27s | |
