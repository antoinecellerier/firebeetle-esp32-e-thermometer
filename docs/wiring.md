# First complete prototype

- Firebeetle ESP32-E
- Display:
  - DESPI-C02
  - GDEW0213M21
- Sensor:
  - DS18B20-PAR
  - 4.7 kOhm resistance
- Battery:
  - RS Pro 18650 26H Li-ion Battery Pack (2.6 Ah)

| ESP32 | DESPI-C02 |
|-------|-----------|
| 3.3V  | 3.3V      |
| GND   | GND       |
| MOSI  | SDI       |
| SCK   | SCK       |
| 14/D6 | CS        |
| 2/D9  | D/C       |
| 25/D2 | RES       |
| 26/D3 | BUSY      |

| ESP32 |          | DS18B20-PAR                          |
|-------|----------|--------------------------------------|
| 4/D12 |          | DQ (middle pin)                      |
| 3.3V  | 4.7 kOhm | DQ (middle pin)                      |
| GND   |          | GND (left when looking at flat face) |

![Assembled first prototype](first-prototype.jpg)

# BMP390L + ePaper setup (ULP-capable)

- Firebeetle ESP32-E
- Sensor:
  - Fermion: BMP390L Digital Barometric Pressure Sensor (Breakout)
- Display:
  - DESPI-C02 + GDEW0213M21 (or 1.54" Z90c tricolor)

BMP390L is wired to GPIO0/GPIO4 (RTC I2C pins) so the ULP coprocessor
can read the sensor during deep sleep.

| ESP32   | BMP390L breakout |
|---------|------------------|
| 3V3     | 3V3              |
| GND     | GND              |
| 0/D5    | SDA              |
| 4/D12   | SCL              |
