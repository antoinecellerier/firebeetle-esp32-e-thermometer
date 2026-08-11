A low power ESP32 based thermometer with an ePaper display

<img src="docs/seeed-xiao-c6-bmp581-GDEH0576T81-prototype.jpg" width="600" />

See [docs/wiring.md](docs/wiring.md) for prototype wiring information and [hardware/thermometer-c6/](hardware/thermometer-c6/README.md) for the custom board.

# Power consumption

Measured with a Nordic PPK2 on pure ESP-IDF firmware; full traces, dates and
methodology in [docs/notes.md](docs/notes.md). Figures are config-specific —
panel, sensor and board all matter.

**Read the node tag on every figure.** `@3V3 rail` is the load alone, with the
board's input tree bypassed; `@4V2 bat` is the whole deployment path, regulator
and charger leakage included. They are not interchangeable, and the battery
figure is not simply the larger one.

| Setup | Deep-sleep floor | Sensor wake | Wake + refresh |
|-------|-----------------|-------------|----------------|
| Firebeetle ESP32-E + BMP390L + GDEH0154Z90 via DESPI-C02 (FDN340P gate) | 19–20 µA `@3V3 rail` | ULP bit-bang I2C every 5 s, avg ≈0 | ~112 mC `@3V3 rail` (was ~600 mC before light sleep — the Z90's ~21 s refresh used to spin-wait) |
| XIAO ESP32-C6 + BMP581 + GDEH0576T81 via DESPI-C02 (FDN340P gate) | 15.5–16 µA `@3V3 rail` | LP core I2C every 60 s: ~1 mA × 3 ms | ~45 mC `@3V3 rail` (was ~93–95 mC before light sleep) |
| XIAO ESP32-C6 + BMP581 + GDEW029I6FD via Seeed ePaper Driver Board (no gate) | ~25 µA `@3V3 rail`<br>**21.7 µA `@4V2 bat`** | LP core I2C every 60 s: ~1 mA × 3 ms | 12.2 mC `@3V3 rail`<br>**10.05 mC `@4V2 bat`** |
| thermometer-c6 rev A + BMP581 + GDEM0154I61 (on-board gated booster) | **18.3 µA `@4V2 bat`** | LP core I2C every 60 s | **~24.3 mC `@4V2 bat`** |

A buck draws *less* current at 4.2 V than its load does at 3.3 V, which is why
~25 µA at the rail reads 21.7 µA at the battery (~90 % efficient). An LDO runs
the other way, ~1.15× the charge for the same work — so the custom board beating
the XIAO by 3 µA at the same 4.2 V is a real win, not a topology artefact. Its
wake figures include LED blinks, left on for observability. Blank cells are
unmeasured, not zero; both are on the PPK2 backlog.

The main CPU only wakes on a ≥0.1 °C delta or a safety-net tick, so a display
refresh is the dominant event on a typical day. At one refresh per hour that puts
long-term averages in the **~16–51 µA band depending on rig and refresh cadence**
— load-only runtime of roughly **1–3 years on a 400 mAh LiPo**. But at this
current level LiPo self-discharge (a few %/month ≈ 15–25 µA equivalent) rivals
the load itself, so **expected runtime is on the order of a year**, and a
2600 mAh 18650 will age out before the load meaningfully drains it. Not yet
confirmed against a full-length run.

Two gotchas worth surfacing (the adapter-leakage ones are under Hardware below):
- **XIAO ESP32-C6 battery operation has a hard floor at ~3.6 V**: its 3.3 V rail is a pure buck (SGM6029C), which below VOUT + ~245 mV starves its bootstrap and lets the rail sag ~a VTH below VBAT — deep sleep survives, but wakes collapse into 0.5–0.9 A brownout-restart storms. Firmware shuts down at 3.7 V (~12–15 % of Li-ion capacity abandoned); full regime map in [docs/notes.md](docs/notes.md). LiFePO₄ cells (3.2 V nominal) are unusable on this board. The custom board uses an LDO and shuts down at 3.5 V instead.
- **Don't use the Seeed ePaper Driver Board's JST battery connector**: its ETA9740 charger/boost idles at ~330–500 µA — ~20× the whole system's sleep floor, flattening a 400 mAh cell in ~7 weeks doing nothing — and it double-converts BAT→5 V→3.3 V. Solder the battery to the XIAO's underside BAT pads instead, JST empty, switch off.

The Arduino-era ~20 mA deep-sleep USB CDC gotcha is gone: the pure-IDF
USB-Serial-JTAG console doesn't hold the port active.

For context: the original 2021 prototype (wake + refresh every 60 s, no ULP) ran a 2600 mAh cell flat in 8.5 days at ~12.6 mA average — the ULP/LP-core redesign is ~700× more efficient.

# Hardware

## Controller boards
- thermometer-c6 — the custom board this project builds towards, replacing the
  dev-board rigs below: ESP32-C6-MINI-1 + BMP581, a universal 24-pin FPC panel
  interface with the Good Display booster on-board and P-FET-gated, USB-C charging,
  an LDO 3.3 V rail, a GPIO-switched battery divider and a 32.768 kHz crystal.
  Schematic, PCB and rationale: [hardware/thermometer-c6/](hardware/thermometer-c6/README.md)
- Firebeetle ESP32-E https://wiki.dfrobot.com/FireBeetle_Board_ESP32_E_SKU_DFR0654
  - ESP32 datasheet https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf
  - ESP32-WROOM-32E datasheet  https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32e_esp32-wroom-32ue_datasheet_en.pdf
  - TP4056 battery charger IC (onboard) https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf https://www.best-microcontroller-projects.com/tp4056.html
- Seeed Studio XIAO ESP32-C6 https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/

- ESP32 getting started https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/index.html
- ESP32 power consumption https://diyi0t.com/reduce-the-esp32-power-consumption/

## Temperature sensor (multiple options)
- DS18B20-PAR OneWire interface
  - datasheet https://datasheets.maximintegrated.com/en/ds/DS18B20-PAR.pdf
- BMP390L I2C interface:
  - datasheet https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp390-ds002.pdf
  - breakout board https://wiki.dfrobot.com/Fermion_BMP390L_Digital_Barometric_Pressure_Sensor_SKU_SEN0423
- BMP581 / BMP585 I2C interface (Bosch next-gen pressure sensors, ~0.5 µA deep-standby)
  - BMP581 https://www.bosch-sensortec.com/products/pressure-sensors/bmp581/
  - BMP585 https://www.bosch-sensortec.com/products/pressure-sensors/bmp585/
  - Fermion breakouts: SEN0667 (BMP581) https://wiki.dfrobot.com/sen0667/ , SEN0666 (BMP585) https://wiki.dfrobot.com/sen0666/

## Display (multiple options)
- Adafruit 1.54" Tri-Color eInk / ePaper 200x200 Display with SRAM - SSD1681 Driver
https://www.adafruit.com/product/4868
https://learn.adafruit.com/adafruit-1-54-eink-display-breakouts?view=all
  - uses Good Display GDEH0154Z90 https://www.good-display.com/product/285.html
- Good Display GDEW0154M09 black and white, 200x200, 1.54" fast full refresh https://www.good-display.com/product/206.html
- Good Display GDEW0213M21 black and white, 212x104, 2.13" DES screen https://www.good-display.com/product/354.html
- Good Display GDEW029I6FD black and white flex, 296x128, 2.9" (UC8151D, partial updates) https://www.good-display.com/product/209.html
- Good Display GDEM0154I61 black and white flex, 200x200, 1.54" (driven via GDEY0154D67 SSD1681 driver) https://www.good-display.com/product/535.html
- Good Display GDEH0576T81 black and white, 920x680, 5.76" HD (SSD2677, partial updates) https://www.good-display.com/product/702.html

Good Display panels are driven through one of two adapters (same Good Display reference booster on both — panel compatibility notes in [docs/wiring.md](docs/wiring.md)):
- Good Display DESPI-C02 (switchable RESE 0.47/3 Ω) https://www.good-display.com/product/516.html
- Seeed ePaper Driver Board for XIAO (fixed RESE 0.47 Ω, ETA9740 charger — see gotcha above) https://www.seeedstudio.com/ePaper-breakout-Board-for-XIAO-V2-p-6374.html — wiki: https://wiki.seeedstudio.com/xiao_eink_expansion_board_v2/

The DESPI-C02's boost converter leaks ~534 µA in deep sleep, which an FDN340P P-channel MOSFET on the adapter's 3.3 V line eliminates; the Seeed board's ungated standby measured only ~9 µA, so it runs without a gate.

## Other components
- FDN340P P-channel MOSFET (SOT-23) — power-gates DESPI-C02 3.3 V during deep sleep
- AO3400A N-channel MOSFET (SOT-23) — switches the XIAO C6 battery voltage divider so it doesn't draw ~10 µA continuously

## Battery
- Current builds: PR502535 single-cell LiPo pouch, 400 mAh https://www.gotronic.fr/art-accu-lipo-3-7-vcc-400-mah-pr502535-5812.htm
- Original prototype: RS Pro 18650 26H Li-ion, 2600 mAh https://fr.rs-online.com/web/p/batteries-taille-speciale/1449406/

## Prototypes in action

### 2026 - ultra low power prototypes
Seed Xiao C6, BMP581, GDEH0576T81 & 400mAH battery

![Seeed Xiao C6, BMP581 & GDEH0576T81 (2026)](docs/seeed-xiao-c6-bmp581-GDEH0576T81-prototype.jpg)

### 2021 - first prototype
Firebeetle ESP32-E, DS18B20, GDEW0213M21 & 2600mAh battery

![Assembled first prototype (2021)](docs/first-prototype.jpg)
