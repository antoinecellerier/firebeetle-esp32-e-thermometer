A low power FireBeetle ESP32-E based thermometer with an ePaper display

![Assembled first prototype](docs/first-prototype.jpg)

See [docs/wiring.md](docs/wiring.md) for wiring information.

# Power consumption

Measured with a Nordic PPK2; full traces and methodology in [docs/notes.md](docs/notes.md).

| Setup | Deep-sleep floor | Sensor wake | Display refresh |
|-------|-----------------|-------------|-----------------|
| ESP32-E + BMP390L + DESPI-C02 ePaper (FDN340P power gate) | ~18 µA | ULP bit-bang I2C every 5 s, avg ≈0 | — |
| XIAO ESP32-C6 + BMP581 + GDEH0576T81 ePaper | ~14 µA | LP core I2C every 60 s: ~1 mA × 3 ms | ~93 mC (3.2 s × 29 mA avg, 322 mA peak) |

The main CPU only wakes on a ≥0.1 °C delta or a safety-net tick, so a display refresh is the dominant event on a typical day. Long-term average stays in the 15–40 µA band, which works out to roughly **1–3 years on a 400 mAh LiPo** depending on how often the display refreshes (and probably longer in practice — Li-ion self-discharge starts to compete with the load at that level). A 2600 mAh 18650 is well past the self-discharge limit and effectively ages out before the load flattens it.

Two gotchas worth surfacing:
- **DESPI-C02 ePaper adapter** leaks ~534 µA from its boost converter even with the panel hibernated. A P-channel MOSFET (FDN340P) on its 3.3 V line eliminates it.
- **XIAO C6 USB Serial/JTAG** stays on in deep sleep by default (~20 mA), masking all savings. Disabled via `ARDUINO_USB_CDC_ON_BOOT=0` plus matching `build_unflags`.

For context: the original 2021 prototype (wake + refresh every 60 s, no ULP) ran a 2600 mAh cell flat in 8.5 days at ~12.6 mA average — the ULP/LP-core redesign is ~700× more efficient.

# Hardware

## Controller board
- Firebeetle ESP32-E https://wiki.dfrobot.com/FireBeetle_Board_ESP32_E_SKU_DFR0654
- ESP32 datasheet https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf
- ESP32-WROOM-32E datasheet  https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32e_esp32-wroom-32ue_datasheet_en.pdf
- TP4056 battery charger IC https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
 https://www.best-microcontroller-projects.com/tp4056.html

- ESP32 getting started https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/index.html
- ESP32 power consumption https://diyi0t.com/reduce-the-esp32-power-consumption/

## Temperature sensor (multiple options)
- DS18B20-PAR OneWire interface
  - datasheet https://datasheets.maximintegrated.com/en/ds/DS18B20-PAR.pdf
- BMP390L I2C interface:
  - datasheet https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp390-ds002.pdf
  - breakout board https://wiki.dfrobot.com/Fermion_BMP390L_Digital_Barometric_Pressure_Sensor_SKU_SEN0423

## Display (multiple options)
- Adafruit 1.54" Tri-Color eInk / ePaper 200x200 Display with SRAM - SSD1681 Driver
https://www.adafruit.com/product/4868
https://learn.adafruit.com/adafruit-1-54-eink-display-breakouts?view=all
  - uses Good Display GDEH0154Z90
- Good Display GDEW0154M09 black and white, 200x200, 1.54" fast full refresh
- Good Display GDEW0213M21 black and white, 212x104, 2.13" DES screen

## Battery
- RS Pro 18650 26H Li-ion Battery Pack https://fr.rs-online.com/web/p/batteries-taille-speciale/1449406/
