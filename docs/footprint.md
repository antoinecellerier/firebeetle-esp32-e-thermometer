# Firmware footprint ledger — espidf migration

## Summary (migration complete, stages 0→E)

Arduino (baseline) → pure ESP-IDF, both boards, stock platform, no fork:

- **Flash**: ESP32-E release 1196KB → 1014KB (−182KB); C6 release 1265KB → 1072KB
  (−193KB, display enabled). App slot went from 1280KB OTA (~91–97% full) to the
  3968KB single-app slot in partitions.csv (~26% full) — the flash ceiling is gone.
  What remains is the WiFi floor, not framework overhead: radio+wpa_supplicant
  (~380KB) + lwip (~96KB) + crypto (~127KB) + libc (~81KB); the app itself is
  ~139KB, two-thirds of which is generated font data.
- **Static DRAM**: ESP32-E 49.7KB → 38.0KB (−11.7KB); C6 44.0KB → 39.4KB (−4.6KB).
- **Where it came from**: Arduino core + String/Print/HAL statics, Arduino
  WiFi/Network stack (→ esp_wifi direct), DFRobot/Wire (→ I2cBus over
  i2c_master), log level WARN, no OTA second slot.
- **What didn't move (by design)**: RTC slow memory (8KB shared ULP/RTC_DATA_ATTR),
  deep-sleep current path (was already pure IDF sleep code).
- **Build times**: env-switch invalidation eliminated (167s/~2400 files → 3–4s/0);
  same-env no-op 19–30s → 3–4s; one-time ~5min IDF-from-source per clean checkout.

Rows through stage F were measured with the 920x680 + BMP58x config, hand-selected in
`local-secrets.h` as it worked then; later rows name their own rig, which the env now
carries via `custom_rig`. The distinction matters: other panel/sensor selections shift
absolute sizes by tens of KB (font bitmaps dominate app .rodata). The Flash% denominator varies by era: 1280KB
app0 (baseline/A/B), 4MB board flash (** rows — see *** correction), 3968KB
partitions.csv slot (F2). `.bin bytes` is the only apples-to-apples column.

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
| G multi-SSID WiFi (2026-08-09) | esp32e_release | 966704 | 24.4%*** | 52656 | 91163 | 6564 | **+5008 B vs the commit before** (57b050d). Rig `firebeetle` (200x200 Z90 + BMP390L), NOT the 920x680 config stages 0–F used — absolute DRAM/bin are not comparable to the rows above, the delta is. |
| G | c6_release | 1061184 | 26.7%*** | 43524 | 109692 | 6472 | +5232 B. Rig `xiao-bigscreen`. Cost is the scan path (`esp_wifi_scan_*`) plus the network table; the RTC hint itself is 1 byte. |
| D | c6_debug | 1075168 | 25.6%** | 39420 | 127554 | 6428 | display re-enabled (DISABLE_DISPLAY dropped) |
| D | c6_release | 1071664 | 25.5%** | 39420 | 127554 | 6428 | |
| F official platform | all four | ≈D | 25-27%*** | ≈D | ≈D | — | espressif32@~6.13.0 (IDF 5.5.3), sizes within noise of D |
| F2 IDF 6.0.1 | esp32e_debug | — | 26.3%*** | 38344 | — | — | espressif32@^7.0.1, newlib pinned (see sdkconfig.defaults) |
| F2 | esp32e_release | — | 25.8%*** | 38344 | — | — | +42KB vs IDF 5.5 (newlib mode; picolibc blocked by PIO ulp.py) |
| F2 | c6_debug | — | 27.9%*** | 39840 | — | — | |
| F2 | c6_release | — | 27.3%*** | 39840 | — | — | +46KB vs IDF 5.5 |
| G -Os (was -Og) | esp32e_release | 937632 | 22.9%*** | 47604 | — | — | −77KB bin; CONFIG_COMPILER_OPTIMIZATION_SIZE, wake active phase 22.5→20.6mC |
| G | c6_release | 983178 | 24.2%*** | 49460 | — | — | −97KB bin; with skip-validate: refresh 56.25→45.3mC |
| H crash forensics | c6_release | 998400 | 24.6%*** | — | — | — | +15KB bin: espcoredump-to-flash + task-WDT-panic + RTC_NOINIT CrashLog (48B) + on-screen diag |
| I custom board | thermometer_c6_debug | 1193632 | 29.2%*** | — | — | — | THERMOMETER_C6_BOARD variant: real battery ADC + VBUS sense + EPD float + ext-32k sdkconfig |
| I | thermometer_c6_release | 1057552 | 25.9%*** | — | — | — | +11KB vs same-tree c6_release (1046480): ADC curve-fitting cali + variant code |
| J drift telemetry | c6_release | 1041152 | 25.6%*** | 40524 | — | — | measured drift window + ppm history (12B RTC) + wrapped/white-banded status line |
| K flash history | esp32e_release | 1000768 | 47.7%**** | 39576 | — | 6544 | HistoryStore + NTP bootstrap retry |
| K | c6_release | 1053536 | 50.2%**** | 40564 | — | 6456 | +12KB bin vs J; **0 bytes RTC** — the store derives its state from flash so `historical_data` doesn't move (60B of ULP_DATA_BASE headroom left on ESP32-E) |
| L cadence experiment | esp32e_release | 955211 | 45.5% | 44704 | — | — | `! EXP` badge + `REFRESH_EVERY_N_WAKES` + arm byte in the drift record + `git_hash` in the base snapshot. **0 bytes RTC** — the new hash rides in the flash struct, not RTC; `post_build_check_rtc.py` reports **76B of ULP_DATA_BASE headroom**. The delta vs stage K is *not* isolated to this change: many commits separate them. |
| L | c6_release | 1008186 | 48.1% | 45692 | — | — | Same tree. Bench arms build ~600B *smaller* than the default (E arm 1: 954575) — `ULP_ALWAYS_WAKE` drops the FSM's delta-compare block. |
| M upstream GxEPD2 | thermometer_c6_release | 1072544 | 51.1% | 43820 | 109674 | 6472 | Fork retired for stock upstream (`dfbbb6d`), plus the `/PPK2` `/RESYNC` `/REFRESH` lab badges. **The isolated migration delta is −1644 B**, measured same-tree on `thermometer_c6_debug` (1210002 → 1208358) — the only clean number here; the spread against stage L mixes many commits and a different env. **0 bytes RTC** vs stage K's C6 figure: the badges are build-time booleans in `DisplayStats`, which lives on the stack, not in RTC. |
| N host-supplied LUT | thermometer_c6_release | 1065696 | 50.8% | — | — | — | The T81 waveform LUT now takes the BMP581 reading (`3c91183`, `c2d3ad6`, `1fec0e5`, `7bbe97e`), gated off USB, plus the `/LUT` lab badge and the `FORCE_LUT_TEMPERATURE` bench override. **The isolated feature delta is +342 B**, measured same-tree on `thermometer_c6_debug` (1208704 → 1209046) when the include-order fix made the code actually compile in — the drop against stage M is unrelated commits, not this work. DRAM/IRAM/RTC not re-measured; the change adds no state. |

*** Stage F correction: through stages C-D the ACTUAL flashed partition table was
PlatformIO's default 1MB single-app (PIO ignores the sdkconfig partition choice) —
the C6 binaries would have failed the bootloader size check on real hardware. The
official platform's stricter size check exposed it. Fixed with a repo-owned
partitions.csv (3968KB factory app + 64KB coredump) referenced by both PIO
(board_build.partitions) and idf.py (CONFIG_PARTITION_TABLE_CUSTOM). Flash%
figures above marked ** were computed against board flash, not the app slot.

**** Stage K shrank the app slot to 2048KB to make room for the 1920KB `history`
partition, so the Flash% denominator halves here and the jump from ~26% to ~50%
is the denominator moving, not the binary growing. As always, `.bin bytes` is
the only apples-to-apples column. 2048KB still leaves ~2x headroom over a
~1.05MB binary.

Behavioral baseline (2026-07-03): sim screenshots saved (28 PNGs, all scenarios render);
C6 deep-sleep ~15µA (PPK2, prior measurement). Tag: `pre-idf-migration`.

## Hardware validation (2026-07-03, IDF 6.0.1, PPK2)

Migration parity confirmed on both boards — full measurement details live in
docs/notes.md ("Post-espidf-migration power measurements"); figures are
config-specific (panel + sensor + board).

- ESP32-E (Z90 200x200 + BMP390L): release deep-sleep 19-20µA vs ~18µA
  Arduino-era. Z90 "Busy Timeout!" print is pre-existing (refresh exceeds
  GxEPD2's hardcoded 20s cap; print is ungated).
- XIAO C6 (GDEH0576T81 920x680 + BMP581): release deep-sleep 15.5-16µA vs
  ~15µA; temp-refresh wake 3.2s / ~95mC vs ~93mC Arduino-era. USB-Serial-JTAG
  console harmless in deep sleep (old Arduino CDC ~20mA gotcha gone).
- Shim history: per-byte SPI transactions initially made the C6 refresh event
  ~10s and tripped the task WDT; fixed by 64-byte write-buffering +
  16KB-interval yields (commits ef95f72, 9c819d3).
- NTP timed out twice on C6 (30s) while the E synced in ~1s on the same
  network — matches historical C6 flakiness, predates migration. Caveat:
  system time survives reset/reflash (RTC timer), so a correct clock after a
  "sync failed" log does NOT prove the sync worked; power-cycle to test.

## Build times

Wall-clock `pio run`, warm caches. The env-switch row is the pain point: under
Arduino+fork, building one board invalidates the other board's Arduino core build.

**Trust the object counts over the times.** This laptop throttles hard, and
these runs are sequential: stage E's two 1095-object rows are the same work
measured 22s apart (73s then 52s) purely on thermal state. The recompile count
is deterministic and is what the change is judged on.

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
| E (GIT_HASH a global -D) | esp32e_debug no-op, same env | 7.5s | 0 recompiles |
| E | **hash flip, no source change** | 73s | **1095 of 1095 objects** — `-dirty` suffix alone; the everyday cost |
| E | rebuild back to clean hash | 52s | 1095 again; same work as the row above, 22s apart on thermal state |
| E | env switch, both envs at one hash | 4.2s | 0 recompiles — the Arduino-era penalty was already gone |
| F (GIT_HASH a generated header) | esp32e_debug no-op, same env | 6.6s | 0 recompiles, unchanged |
| F | **after a commit (hash flip)** | 17.7s | **3 objects** — the files that read the hash, vs 1095 |
| F | full rebuild, cold cache | 110s | after a project-checksum wipe |
| F (+ build_cache_dir) | rebuild deleted env dir, warm cache | 47s | **0 recompiles**, all objects retrieved; remainder is cmake reconfigure + copy |
