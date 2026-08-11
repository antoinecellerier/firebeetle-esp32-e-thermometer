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
  - Fermion: BMP390L Digital Barometric Pressure Sensor (Breakout, SEN0423)
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

# BMP58x (BMP581/BMP585) + ePaper setup (ULP-capable)

Drop-in replacement for BMP390L — same pins, same wiring. Only the I2C address
differs (0x47 vs 0x77), so both sensors can coexist on the same bus.

- Sensor:
  - Fermion: BMP581 Digital Barometric Pressure Sensor (SEN0667), or
  - Fermion: BMP585 Digital Barometric Pressure Sensor (SEN0666)

| ESP32   | BMP58x breakout |
|---------|-----------------|
| 3V3     | VCC             |
| GND     | GND             |
| 0/D5    | SDA             |
| 4/D12   | SCL             |

Set `#define USE_BMP58x` in the rig header (`include/rigs/<name>.h`). The LP
core derives `LP_CORE_BMP58X` from the same selector, so there is no second
place to change.

## DESPI-C02 power gate (FDN340P)

The DESPI-C02 adapter board draws ~534 µA quiescent due to its boost converter.
A P-channel MOSFET on the 3.3V line cuts power during deep sleep.

```
3.3V ──────┬──────── FDN340P Source (pin 2)
           │
          10kΩ
           │
13/D7 ─────┴──────── FDN340P Gate (pin 1)

DESPI-C02 3.3V ───── FDN340P Drain (pin 3)
DESPI-C02 GND ────── GND (direct)
```

GPIO LOW → display powered on. GPIO HIGH / high-Z (deep sleep) → display off.

# Xiao Seed ESP32C6 + BMPxxx

- Xiao Seed ESP32C6
- Sensor:
  - Fermion BMP581
- Display + DESPI-CO2 + FDN340P
- Battery JST-2 PH-2P connectors on BAT - / +
- Current measurement - https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/#reading-battery-voltage

## Sensor

| Xiao ESP32C6      | BMP581 breakout |
|-------------------|-----------------|
| 3V3               | VCC             |
| GND               | GND             |
| LP I2C SDA (MTCK) | SDA             |
| LP I2C SCL (MTDO) | SCL             |

## Display

D9 (GPIO20) is also SPI MISO — SPI.begin() must be called with MISO=-1 before
GxEPD2 init to avoid the SPI peripheral stealing the D/C pin (e-paper is
write-only so MISO is not needed). Similarly D3 (GPIO21) is SPI SS; passing
SS=-1 prevents it claiming the BUSY pin.

| Xiao ESP32C6   | DESPI-C02 |
|-----------------|-----------|
| 3.3V            | 3.3V      |
| GND             | GND       |
| MOSI/D10 (GP18) | SDI       |
| SCK/D8 (GP19)   | SCK       |
| D6 (GP16)       | CS        |
| D9 (GP20)       | D/C       |
| D2 (GP2)        | RES       |
| D3 (GP21)       | BUSY      |

D7 (GP17) for the MOSFET Gate

## Battery voltage divider (GPIO-switched)

Seeed documents a 200kΩ/200kΩ (or 220kΩ) always-on divider, but that draws
~10µA continuously — almost doubles the deep sleep floor. A GPIO-switched
divider with an N-channel MOSFET eliminates quiescent draw entirely.

**Components:** 2× 100kΩ resistors + AO3400A (N-channel MOSFET, SOT-23)

```
Bat+ ─── 100kΩ ─── A0 (D0) ─── 100kΩ ─── AO3400A Drain
                                                │
                                             Source ─── GND
                                                │
                                        Gate ←── D1 (GP1)
```

- D1 HIGH → MOSFET on, divider active, A0 reads Vbat/2
- D1 LOW / deep sleep → MOSFET off, zero divider current
- R_source = 50kΩ → ADC settles in ~2µs, minimal averaging needed
- When MOSFET off, A0 floats toward Vbat through 100kΩ; leakage through
  the ADC's ESD clamp is ~(4.2−3.9V)/100kΩ ≈ 3µA — but only through the
  internal protection diode, negligible in practice

**Read sequence:** set D1 HIGH, delayMicroseconds(100), analogRead(A0) a
few times for noise averaging, set D1 LOW. Total on-time <1ms.

**Why 100kΩ, not 1MΩ:** with 1MΩ/1MΩ (R_source = 500kΩ), the ESP32 SAR
ADC sample window (~300ns) is far too short for the RC to settle — readings
are biased low, not just noisy, and averaging doesn't fix bias. 100kΩ/100kΩ
settles in ~2µs which is still longer than the sample window but close enough
that a few back-to-back reads converge. Adding a 100nF buffer cap at A0 would
allow higher resistance values (charges in 5×R_source×100nF) but adds a
component for no real benefit when the divider is switched off during sleep.

## Unused pins

Breakout:
VBUS
D4
D5

Under board:
MTDI
GND
EN
MTMS
3V3
BOOT

![Seeed Xiao C6, BMP581 & GDEH0576T81 (2026)](seeed-xiao-c6-bmp581-GDEH0576T81-prototype.jpg)

# Seeed ePaper Driver Board for XIAO vs DESPI-C02 (compatibility notes)

Researched 2026-07-04. The Seeed board
([wiki](https://wiki.seeedstudio.com/xiao_eink_expansion_board_v2/), schematic in
`hardware/Seeed ePaper Driver Board for XIAO SCH v1.0.pdf`) is a faithful copy of
Good Display's reference booster, so Good Display panels are what it's implicitly
built for (Seeed's own panels are rebranded GD units).

**Identical to DESPI-C02:** 24-pin 0.5mm FPC with the standard Good Display
pinout, 3.3V logic/supply, same boost circuit down to the recommended parts
(10µH inductor, Si1304BDL MOSFET, MBR0530-class Schottkys — B0540WS on the
Seeed board, 4.7µF/50V boost cap).

**The one real difference — RESE:** DESPI-C02 has a 0.47Ω/3Ω select switch;
the Seeed board has a **fixed 0.47Ω** (R2, no alternate footprint). Good
Display warns a wrong RESE "will cause the e-paper cannot be refreshed"
(in practice a 3Ω panel on 0.47Ω often still refreshes, but with a stressed
booster / degraded image — out of spec). Per the DESPI-C02 spec
(`hardware/DESPI-C02 Connector Board for E-paper Display V1.1.pdf`):

- **0.47Ω (fine on Seeed board):** GDEW/GDEY series (UC81xx-driven), most
  newer panels, four-color panels — e.g. GDEW042T2, GDEW075T7
- **3Ω (mismatched on Seeed board):** mostly older GDEH/GDEM SSD16xx panels —
  GDEH0154D67, GDEH0213B73, GDEH029A1 — plus oddballs GDEW0583T7, GDEW075T8

Naming is not a reliable guide (two GDEW panels need 3Ω) — check the
panel datasheet's peripheral/reference circuit page for the RESE value
before plugging in.

Our panels, against that fixed 0.47Ω:

| Panel | Wants | On the Seeed board |
|---|---|---|
| GDEW029I6FD | 0.47Ω | fine — verified working 2026-07-05, first flash |
| GDEH0154Z90 | 3Ω (GDEH/SSD1681) | mismatched |
| GDEH0576T81 | 2.2Ω + 47µH inductor | out of spec (board is 0.47Ω + 10µH), untested |

**Don't use the JST battery connector.** The board carries an ETA9740 charger
(0.5A) + JST-PH + power switch, and that path was measured and ruled out —
solder the cell to the XIAO's underside BAT pads instead, leave the JST empty
and the switch off (`docs/notes.md`, 2026-07-05). The switch does **not**
isolate the ETA9740 from VDD_5V: its OUT pin is hardwired to the XIAO 5V pin,
so the IC powers up whenever USB is plugged in, whatever the switch position.

The board has no power gate (3V3 is hardwired to the booster and FPC), unlike
the DESPI-C02 which needs one. Measured, it doesn't want one either — its
ungated standby is single-digit µA, not the DESPI's ~534µA.

**Fixed pin mapping** (firmware must match; DESPI-C02 wiring is free-form):

| Signal | XIAO pin |
|--------|----------|
| RST    | D0       |
| CS     | D1       |
| BUSY   | D2       |
| DC     | D3       |
| SCK    | D8       |
| MOSI   | D10      |

This takes D0/D1, which the C6 battery divider above uses. Nothing ADC-capable
is left on the header — but the **underside pads are**: C6 ADC1 covers
GPIO0–6, so MTMS (GPIO4, ADC1_CH4) and MTDI (GPIO5, ADC1_CH5) are both free
here, since LP I2C sits on the other two pads (MTCK/MTDO = GPIO6/7).

So a battery divider is still possible on this board: sense on the MTDI pad,
AO3400A gate on D4 or D5 (free header pins), wired as the 100k/100k
GPIO-switched divider above. Not built. Firmware thresholds are board-split in
`Thermometer.cpp`; the XIAO's are 3800/3700 mV, finalised by the 2026-07-05
fine sweep — 3.7V is the lowest verified-healthy point and 3.6V is already
inside the buck's sag band.

## What was measured on this board

The 2026-07-04 verification list is closed. All of it — the ETA9740 JST path,
the battery-direct BAT-pads sweep and its buck-dropout regime map, the ungated
booster standby, and the three-way rail/JST/BAT-pads comparison — is in
[`docs/notes.md`](notes.md), 2026-07-05, with the source voltage recorded per
figure. The conclusions that change how you wire the thing are already above.

Two cautions from it worth carrying here:

- **Compare in mJ, not mC.** These three configs meter at different node
  voltages, so charge alone makes the wrong one look cheapest.
- **The buck's usable window ends around 3.6–3.7V**, which is a firmware
  threshold, not a wiring choice. Below it the XIAO's rail sags and wakes
  collapse into brownout storms.

Still open, both on the custom board rather than this one: a cold (~0°C) run
and a refresh on a real cell, which together decide the final shutdown
threshold — [`hardware/thermometer-c6/BRINGUP.md`](../hardware/thermometer-c6/BRINGUP.md)
Phase 3.

# Custom board (thermometer-c6 rev A)

Not covered here — this file is the dev-board prototype wiring. The rev A pin
map, jumper tables and bench procedures live in
[`hardware/thermometer-c6/README.md`](../hardware/thermometer-c6/README.md).

