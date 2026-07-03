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

Behavioral baseline (2026-07-03): sim screenshots saved (28 PNGs, all scenarios render);
C6 deep-sleep ~15µA (PPK2, prior measurement). Tag: `pre-idf-migration`.
