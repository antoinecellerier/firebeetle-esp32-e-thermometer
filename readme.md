A low power FireBeetle ESP32-E based thermometer with an Adafruit ThinkInk 1.54" ePaper display

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
