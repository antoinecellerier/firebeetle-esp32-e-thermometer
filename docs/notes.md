# First long run

|stats         | value               |
|--------------|---------------------|
| first boot   | 2021-10-29 17:14:54 |
| last refresh | 2021-11-08 05:39:40 |
|              |includes +1 hour due to DST|
| seq          | 131014              |
| refresh      | 859                 |
| bat          | 2998 mv             |

bat 2954 mV at 2021-11-08 11:30 ... something's draining current even when shut down

ran for 739486 seconds = 8.5 days

3.2 => 3 V took a few hours only (didn't see the 3.2 V warning display)
battery rated for 2.6Ah (9.62Wh)

=> ~12.6 mA average consumption which is x1000 more than deep sleep target (~10µA)

Assumptions without proper multi-meter measurments
* deep sleep is not measurable probably < 1 mA lets assume ~0.5mA
* each wake up takes 2s at 40mA
* each refresh takes 15s at 50mA
* each screen clear takes 30s at 50mA

* 2s wake-up is 91% of energy budget, deep sleep is 3% of energy budget
* 1s wake-up is 83% of energy budget, deep sleep is 6% of energy budget
* 0.5s wake-up is 72% of energy budget, deep sleep is 10% of energy budget

1.5s wake-up => ~2.5 Ah

First priority: save on wake-up time/energy consumption
- 40 mA is inline with measurements at https://diyi0t.com/reduce-the-esp32-power-consumption/
- Adjust CPU frequency to 80 MHz? (defaults to 240 MHz)
- Use ULP to probe temperature? https://www.youtube.com/watch?v=-QIcUTBB7Ww https://github.com/fhng/ESP32-ULP-1-Wire https://github.com/duff2013/ulptool https://github.com/espressif/arduino-esp32/issues/1491 https://github.com/platformio/platform-espressif32/issues/95 

Other TODOs:
- Use ESP-IDF logging facilities https://thingpulse.com/esp32-logging/
- Use PROGMEM https://www.e-tinkers.com/2020/05/do-you-know-arduino-progmem-demystified/


# Current measurement first soldered prototype Nov 30 2021

https://wiki.dfrobot.com/FireBeetle_Board_ESP32_E_SKU_DFR0654 see "Low Power Pad"

Measurements with UT61E+

Powered at 4V on VCC

Typical powered consumption: ~ 45 mA

With Low Power Pad not cut: ~ 490 µA

With Low Power Pad cut: ~ 71 µA / Sometimes ~125 µA ?!? / and the following day ~39 µA ?!?!?

With setup calling pinMode(2, OUTPUT or 0) and going directly to sleep and all components connected ~ 66 µA

With setup directly going to deep sleep and all components connected ~ 27 µA in deep sleep

With setup directly going to deep sleep and all components connected except DS18B20-PAR's data ping ~ 25 µA deep sleep

Board with no connections other than VCC & GND consumes ~ 14 µA in deep sleep

# Current measurement impact of light sleep during DS18B20 temp measurment

Measurements with UT61E+. The sampling and value refresh rates are a bit slow (a few 100 ms each). Values are in mA.

Wifi was disabled.

DS18B20 temperature measurement last ~750ms

DS18B20 with normal delay during measurement:
![DS18B20 normal delay during measurement](thermometer-normal.jpg)

DS18B20 with light sleep during measurement:
![DS18B20 light sleep during measurement](thermometer-with-light-sleep.jpg)

BMP390L during measurement (no display):
![BMP390L temperature measurement](thermometer-bmp390l.jpg)

# ULP coprocessor power measurements (March 2026)

Setup: FireBeetle ESP32-E with BMP390L sensor and ePaper display connected.
Measured with Nordic PPK2 on VCC. Low Power Pad cut.
Board: dfrobot_firebeetle2_esp32e, PlatformIO + Arduino framework.

## Test conditions

All measurements are 1-minute averages in steady state (excluding initial boot spike).

| Config | Sleep interval | ULP period | CPU wakes? | Avg current | Notes |
|--------|---------------|------------|------------|-------------|-------|
| Bare sleep (no init, straight to sleep) | N/A | N/A | Never | ~510 µA | No serial, sensor, or display init |
| No ULP (indefinite deep sleep) | N/A | N/A | Never | ~560 µA | Normal boot, sensor+display init, then sleep |
| ULP test (counter, no wake) | 5s ULP timer | 5s | Never | ~560 µA | ULP runs every 5s, increments counter, halts |
| ULP test (counter, no I2C) | 5s ULP timer | 5s | Every 15s (3 cycles) | — | Functional test only, not measured in steady state |
| **ULP bit-bang I2C (production)** | **5s** | **5s** | **On ≥0.1°C change** | **~562 µA** | **HULP bit-bang I2C, delta threshold=20** |

**Key findings:**
- ULP bit-bang I2C with full BMP390L temp reading: ~562 µA average deep sleep
- ULP overhead is negligible (~0 µA difference with/without ULP running)
- The ~535 µA above bare-board baseline (562 vs 27 µA) is dominated by `RTC_PERIPH` power domain being forced ON — required for ULP GPIO access during bit-bang I2C
- Hardware RTC I2C peripheral could not be made to work (BUS_BUSY stuck, see docs/rtc-i2c-research.md)
- Sensor+display init adds ~50 µA vs bare sleep (560 vs 510 µA)
- TODO: investigate if RTC_PERIPH can be set to AUTO or if alternative approaches reduce the ~535 µA overhead

## Reference values (from earlier measurements)

- Bare board deep sleep (no connections): ~14 µA
- All components connected, setup goes straight to sleep: ~27 µA
- Previous long-run average (wake every 60s, display refresh): ~12.6 mA

## ULP bit-bang I2C implementation notes

- Uses HULP library (`hulp_i2cbb.h`) for ULP GPIO bit-bang at ~150 kHz
- BMP390L protocol: write PWR_CTRL for forced mode → 7ms delay → read 3 temp bytes
- Delta comparison on DATA_1 (middle byte), threshold=20 (~0.1°C per count)
- Compensation done on main CPU after wake using calibration data cached in RTC memory
- `hulp_peripherals_on()` sets `ESP_PD_DOMAIN_RTC_PERIPH = ESP_PD_OPTION_ON` — this is the main power cost

## Debug GPIO pins

- D10/GPIO17 → PPK2 D0: HIGH while main CPU is active
- D11/GPIO16 → PPK2 D1: HIGH during display refresh
- D13/GPIO12 → PPK2 D2: HIGH while ULP executing (requires `PPK2_DEBUG_ULP_GPIO` flag + RTC periph power)

Note: `PPK2_DEBUG_ULP_GPIO` forces RTC peripherals on during deep sleep, which increases sleep current. Keep disabled for accurate measurements.

## Observations

- ULP GPIO debug (D13) initially didn't show signal — fixed by removing `rtc_gpio_hold_en()` which was blocking ULP register writes
- The 562 µA with ULP bit-bang I2C is ~20x better than old wake-every-cycle (~12.6 mA) but ~20x above bare deep sleep floor (~27 µA)
- The dominant cost is `RTC_PERIPH` power domain, not the ULP execution itself
- Next investigation: try `ESP_PD_OPTION_AUTO` for RTC_PERIPH, or explore hardware approaches (power gating, different I2C method)
