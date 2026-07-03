# Firmware footprint ledger — espidf migration

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
