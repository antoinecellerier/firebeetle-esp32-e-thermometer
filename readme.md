A low power FireBeetle ESP32-E based thermometer with an ePaper display

![Assembled first prototype](docs/first-prototype.jpg)

See [docs/wiring.md](docs/wiring.md) for wiring information.

# Power consumption

Measured with a Nordic PPK2; full traces and methodology in [docs/notes.md](docs/notes.md).

| Setup | Deep-sleep floor | Sensor wake | Display refresh |
|-------|-----------------|-------------|-----------------|
| ESP32-E + BMP390L + DESPI-C02 ePaper (FDN340P power gate) | ~18 µA | ULP bit-bang I2C every 5 s, avg ≈0 | — |
| XIAO ESP32-C6 + BMP581 + GDEH0576T81 ePaper | ~14 µA | LP core I2C every 60 s: ~1 mA × 3 ms | ~93 mC (3.2 s × 29 mA avg, 322 mA peak) |

The main CPU only wakes on a ≥0.1 °C delta or a safety-net tick, so a display refresh is the dominant event on a typical day. Long-term average stays in the 15–40 µA band, which gives a load-only runtime of roughly **1–3 years on a 400 mAh LiPo** depending on how often the display refreshes. At this current level LiPo self-discharge (a few %/month ≈ 15–25 µA equivalent) is comparable to the load itself, so **expected runtime is on the order of a year** — to be confirmed against real long-run measurements. A 2600 mAh 18650 sits near the self-discharge floor and is expected to age out before the load meaningfully drains it.

Two gotchas worth surfacing:
- **DESPI-C02 ePaper adapter** leaks ~534 µA from its boost converter even with the panel hibernated. A P-channel MOSFET (FDN340P) on its 3.3 V line eliminates it.
- **XIAO C6 USB Serial/JTAG** stays on in deep sleep by default (~20 mA), masking all savings. Disabled via `ARDUINO_USB_CDC_ON_BOOT=0` plus matching `build_unflags`.

For context: the original 2021 prototype (wake + refresh every 60 s, no ULP) ran a 2600 mAh cell flat in 8.5 days at ~12.6 mA average — the ULP/LP-core redesign is ~700× more efficient.

# Hardware

## Controller boards
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
  - Fermion breakouts: SEN0667 (BMP581), SEN0666 (BMP585)

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

Good Display panels are driven through a DESPI-C02 adapter. Its boost converter leaks ~534 µA in deep sleep, which an FDN340P P-channel MOSFET on the adapter's 3.3 V line eliminates — see [docs/wiring.md](docs/wiring.md).

## Other components
- FDN340P P-channel MOSFET (SOT-23) — power-gates DESPI-C02 3.3 V during deep sleep
- AO3400A N-channel MOSFET (SOT-23) — switches the XIAO C6 battery voltage divider so it doesn't draw ~10 µA continuously

## Battery
- Current builds: single-cell LiPo pouch, ~400 mAh, JST-PH connector
- Original prototype: RS Pro 18650 26H Li-ion, 2600 mAh https://fr.rs-online.com/web/p/batteries-taille-speciale/1449406/
