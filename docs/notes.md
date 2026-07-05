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
- **With EPD VCC disconnected: ~28 µA** — essentially bare-board baseline
- **The DESPI-C02 ePaper adapter board draws ~534 µA quiescent** — this is the dominant power consumer
- ULP + RTC_PERIPH + BMP390L adds only ~1 µA above the 27 µA bare-board baseline
- Hardware RTC I2C peripheral could not be made to work (BUS_BUSY stuck, see docs/rtc-i2c-research.md)
- GPIO pin isolation (hold RST LOW, float SPI) does not reduce the DESPI-C02 draw — it's a hardware issue

## DESPI-C02 quiescent current (known hardware issue)

The ~534 µA overhead is a known issue with the DESPI-C02 adapter board. The board's boost converter
capacitors leak current even after the display controller is put into deep sleep (command 0x07).

- **Confirmed by other users**: https://github.com/ZinggJM/GxEPD2/discussions/142
  (same symptoms: ~500 µA in deep sleep, drops to ~50 µA when removing DESPI-C02 3.3V)
- **DESPI-C02 manual §4.6**: "The high current in deep sleep mode may be due to the larger
  capacitance in the boost part."
- **PPK2 trace** shows ~10ms oscillating spikes to 4-5 mA — characteristic of a boost converter
  periodically charging even in standby.
- **Software mitigations tested and ineffective**: holding RST LOW via gpio_hold_en,
  floating SPI/CS/DC pins, calling SPI.end() — none reduced the current.

### Possible fixes (all hardware)
1. **Power-gate the DESPI-C02** with a P-channel MOSFET (e.g., Si2301, AO3401) on its 3.3V line,
   controlled by a GPIO + 10kΩ pull-up. GPIO HIGH = off (sleep), GPIO LOW = on (refresh).
   FireBeetle ESP32-E has no built-in controllable 3.3V output, so this requires an external MOSFET.
2. **Replace the DESPI-C02** with direct panel wiring using the panel's spec capacitors
3. **Use a different adapter board** with better sleep characteristics

### Fix implemented: FDN340P power gate (March 2026)

P-channel MOSFET (FDN340P, SOT-23) on the DESPI-C02 3.3V line, gate driven by GPIO13/D7
with 10kΩ pull-up to 3.3V. See `docs/wiring.md` for circuit details.

- **Deep sleep with power gate: ~18 µA average** (down from ~562 µA)
- MOSFET cuts all power to DESPI-C02 during deep sleep (GPIO goes high-Z, pull-up holds gate at VCC)
- Software: `EPD_POWER_GATE` define in `local-secrets.h` enables power control in `Display.cpp`
- `epd_power_on()` drives GPIO13 LOW + 10ms delay before display init
- `epd_power_off()` drives GPIO13 HIGH after display hibernate

![BMP390L + ULP + P-FET temperature measurement](thermometer-deepsleep-pfet.png)

### Adafruit 1.54" eInk breakout — tested and rejected

The Adafruit 1.54" Tri-Color eInk breakout (ThinkInk, product #3625) was tested as an alternative.
Despite having an onboard LDO with an Enable pin, it performed **much worse**:

- **With EN floating (default):** ~3 mA average, 21 mA spikes — display controller in active state
- **With EN tied directly to GND:** ~5.5 mA average, 20 mA spikes — still drawing heavily
- Current likely back-feeds through SPI pin ESD diodes and/or microSD + SRAM components
- The board's additional components (SPI SRAM, microSD socket) create parasitic current paths
  that bypass the LDO even when disabled
- **Conclusion:** Adafruit board is ~10x worse than DESPI-C02 for deep sleep. Not suitable.

## Reference values (from earlier measurements)

- Bare board deep sleep (no connections): ~14 µA
- All components connected, setup goes straight to sleep: ~27 µA
- Previous long-run average (wake every 60s, display refresh): ~12.6 mA

## ULP bit-bang I2C implementation notes

- Uses HULP library (`hulp_i2cbb.h`) for ULP GPIO bit-bang at ~150 kHz
- BMP390L protocol: write PWR_CTRL for forced mode → 7ms delay → read 3 temp bytes
- Delta comparison on DATA_1 (middle byte), threshold=20 (~0.1°C per count)
- Compensation done on main CPU after wake using calibration data cached in RTC memory
- `hulp_peripherals_on()` sets `ESP_PD_DOMAIN_RTC_PERIPH = ESP_PD_OPTION_ON` — adds negligible current (~1 µA)

## Debug GPIO pins

- D10/GPIO17 → PPK2 D0: HIGH while main CPU is active
- D11/GPIO16 → PPK2 D1: HIGH during display refresh
- D13/GPIO12 → PPK2 D2: HIGH while ULP executing (requires `PPK2_DEBUG_ULP_GPIO` flag + RTC periph power)

Note: `PPK2_DEBUG_ULP_GPIO` forces RTC peripherals on during deep sleep, which increases sleep current. Keep disabled for accurate measurements.

## Observations

- ULP GPIO debug (D13) initially didn't show signal — fixed by removing `rtc_gpio_hold_en()` which was blocking ULP register writes
- The 562 µA with ULP bit-bang I2C is ~20x better than old wake-every-cycle (~12.6 mA) but ~20x above bare deep sleep floor (~27 µA)
- The dominant cost was the DESPI-C02 ePaper adapter board (~534 µA quiescent, known hardware issue — see section above)
- With EPD disconnected, total sleep current is ~28 µA (ULP + BMP390L + RTC_PERIPH ≈ 1 µA overhead)
- **Resolved:** FDN340P power gate on DESPI-C02 VCC brings deep sleep to ~18 µA — below bare-board baseline (pull-up likely reduces leakage paths)

# XIAO ESP32C6 power measurements (March 2026)

Setup: Seeed XIAO ESP32C6, bare board (no peripherals connected).
Measured with Nordic PPK2 on 3.3V pin (bypassing onboard LDO). Source voltage 3320 mV.
Board: seeed_xiao_esp32c6, PlatformIO + pioarduino (Arduino Core 3.x / ESP-IDF 5.x).

## Critical finding: ARDUINO_USB_CDC_ON_BOOT

The XIAO ESP32C6 board definition sets `ARDUINO_USB_CDC_ON_BOOT=1` by default, which keeps
the ESP32-C6's built-in USB Serial/JTAG controller active during deep sleep. This draws ~20 mA
constantly, completely masking deep sleep savings.

**Fix:** Add to platformio.ini env:
```ini
build_unflags = -DARDUINO_USB_CDC_ON_BOOT=1
build_flags = ... -DARDUINO_USB_CDC_ON_BOOT=0
```

Note: `-UARDUINO_USB_CDC_ON_BOOT` in build_flags alone doesn't work — PlatformIO's board
`extra_flags` are applied separately. Must use `build_unflags` to remove the board flag.

## Test results

| Config | Sleep interval | Avg current (steady state) | Deep sleep floor | Notes |
|--------|---------------|---------------------------|-----------------|-------|
| USB CDC ON (default board config) | 5s | ~20.65 mA | ~20 mA | USB Serial/JTAG stays active — unusable |
| USB CDC OFF, no WiFi, no LEDs, no display | 5s | ~415 µA | ~14 µA | Bare minimum config, DummySensor |
| USB CDC OFF, WiFi on first boot, no display | 5s | ~428 µA | ~16 µA | WiFi.disconnect(true,true) fully powers down radio |

## LP Core ULP (LP_CORE_IDLE mode, March 2026)

Setup: Bare XIAO ESP32C6, no BMP390L connected. USB CDC OFF. LP core running in idle mode
(no I2C, simulates sensor timing with 7ms delay). LP timer wakeup source. PPK2 at 3320 mV.

| Config | LP timer interval | WAKE_EVERY | HP wakes every | Deep sleep floor | Notes |
|--------|------------------|------------|----------------|-----------------|-------|
| LP_CORE_IDLE | 5s | 6 | 30s | ~15 µA | LP spikes ~1mA, HP spikes 20-50mA |

**Key findings:**
- 15 µA deep sleep baseline — LP core timer + shared memory adds negligible overhead
- LP core wakeup spikes: ~1 mA (7ms simulated sensor read time)
- HP (main CPU) wakeup spikes: 20-50 mA (DummySensor, no WiFi, no display)
- 1-minute average: ~90 µA (dominated by HP wakeups every 30s)
- In production with BMP390L I2C mode + 60s LP timer, HP wakes only on ≥0.1°C temp change

### Pending: BMP390L mode testing
- Awaiting soldering station to connect BMP390L to C6 board
- Switch `ulp/lp_core_main.c` from `#define LP_CORE_IDLE` to BMP390L I2C mode
- Verify LP I2C reads work (GPIO6=SDA, GPIO7=SCL, LP_I2C_NUM_0)
- Measure LP core power with real I2C transactions vs idle delay
- Tune TEMP_DELTA_THRESHOLD (currently 20 ≈ 0.1°C) and SLEEP_INTERVAL_S (60s for production)

## Pending: BMP58x mode testing (April 2026)

Current C6 production setup uses BMP58x (BMP581/BMP585) via LP core, not BMP390L.
Code complete; hardware validation queued.

**Context — forced-mode fix applied 2026-04-19:** `ODR_CONFIG` previously wrote `0x01`
which is `BMP5_POWERMODE_NORMAL` per Bosch's `bmp5_defs.h`, not forced. Sensor was
sampling continuously at default ODR 240 Hz between wakes (~200 µA continuous).
Now writes `0x02` (`BMP5_POWERMODE_FORCED`) — sensor runs one measurement then
auto-returns to standby. All deep-standby entry conditions now hold (deep_dis=0,
FIFO off, IIR off, ODR=0), so the sensor auto-enters deep standby (~0.5 µA)
between wakes without any extra code.

Hardware preparation:
- Solder BMP581 or BMP585 to XIAO C6 (SDA=GPIO6, SCL=GPIO7, I2C addr `0x47`)
- Switch `ulp/lp_core_main.c` from `#define LP_CORE_IDLE` to `#define LP_CORE_BMP58X`
- Set `SLEEP_INTERVAL_S=60` and `WAKE_EVERY=1` (60s LP timer, HP wake on delta only)
- Confirm `USE_BMP58x` in `local-secrets.h`

### Measurements needed to confirm full C6 operation

Baseline / correctness:
- [x] **Deep sleep floor with BMP58x connected, steady temperature.** Measured ~14 µA on 2026-04-21 (SLEEP_INTERVAL_S=5, no HP wakes in window) — matches the 15–16 µA expectation, well below the 200 µA forced-mode-broken threshold.
- [ ] **Confirm sensor is in deep standby between wakes.** Between LP core spikes, sensor contribution should be ~0.5 µA (not ~1 µA standby). If the measurement can't resolve that, alternative check: read `ODR_CONFIG` back via HP I2C right after deep-sleep exit — `pwr_mode` bits [1:0] should read `00` (standby). (Indirectly supported by the 14 µA floor, but not directly verified.)

LP core wake characterisation:
- [x] **LP core spike duration.** Measured ~3 ms on 2026-04-21 — matches the predicted 3.5–4 ms window and confirms the OSR-write removal shortened the spike vs the 7 ms LP_CORE_IDLE baseline.
- [x] **LP core spike amplitude.** Measured ~1 mA peak; stepped shape from sensor conversion not separately resolved at this zoom.
- [ ] **Charge per LP wake** (integrate current × time). Use PPK2 area measurement. Multiply by wakes/hour (3600/60 = 60) to project hourly load. (Rough estimate from spike shape: ~3 µC/wake → ~180 µC/hour ≈ 50 nA avg at 60s interval.)

HP wake characterisation:
- [ ] **HP wake duration with BMP58x** — expected shorter than DummySensor (no sensor bring-up overhead since sensor is already in deep standby). No display refresh if temp delta small.
- [ ] **Delta-wake trigger.** Heat sensor with finger; confirm HP wake fires when LP-core delta ≥25 counts (~0.1 °C). Measure HP spike shape during a real delta-triggered wake.
- [ ] **Safety-net HP wake** — confirm the periodic safety wake fires at the configured cadence (for hourly/daily bucket finalisation).

Averages:
- [ ] **1-minute average at steady state** (no delta wakes): should be ~15 µA baseline + (LP wake charge) × 1/min. Target **<30 µA**.
- [ ] **1-hour average at steady state** — dominated by 60 × LP wakes + occasional safety-net HP wake.
- [ ] **1-hour average under slow drift** (e.g., room temp drifting 1 °C/hour → ~10 delta wakes/hour) — characterises typical indoor use.

Regression checks vs prior measurements:
- [x] Compare C6 BMP58x deep sleep floor against C6 LP_CORE_IDLE floor (~15 µA). Measured 14 µA on 2026-04-21 — within 1 µA, no regression.
- [ ] Compare against ESP32-E BMP390L production (~562 µA with DESPI-C02 attached, ~28 µA without). C6 has no DESPI-C02, so C6 floor should track bare-board baseline.

PPK2 GPIO markers (reuse existing scheme from ESP32-E): tag LP-core-active and HP-active pins so the trace can be segmented automatically.

### Measured 2026-04-21 (BMP581 on XIAO C6, LP_CORE_BMP58X, SLEEP_INTERVAL_S=5)

Setup: XIAO ESP32-C6 + BMP581 (I2C on GPIO6/7, addr 0x47) + GDEH0576T81 e-paper, `seeed_xiao_esp32c6_release` env (USB CDC off, DISABLE_SERIAL). PPK2 at 3.32 V.

- Deep sleep floor: **~14 µA** (steady room temp, no HP wakes in window).
- LP core wake spike: **~3 ms at ~1 mA** (see `docs/xiao-seeed-esp32c6-bmp581-deep-sleep-i2c-lp-core-read.png`) — matches the expected 3.5–4 ms window (shorter than the 7 ms LP_CORE_IDLE baseline, as predicted after dropping the per-wake OSR write).
- Screen refresh (GDEH0576T81 full update): **~3.2 s at ~29 mA avg, ~322 mA peak, ~93 mC charge** per refresh (see `docs/xiao-seeed-esp32c6-bmp581-GDEH0576T81-screen-refresh.png`). Dominates the energy budget whenever it fires — at one refresh/hour this alone averages to ~26 µA.
- Gotcha: after a warm reset (reflash or HP restart), PPK2 briefly showed extra ~200 ms spikes on top of the LP-core cadence. They **did not reappear after a full cold boot** (power cycle). Suspected leftover PMU/LP-clock state from the previous run; not investigated further since it's self-clearing.


# Post-espidf-migration power measurements (July 2026, IDF 6.0.1, PPK2)

All figures are config-specific — panel + sensor + board matter.

## XIAO ESP32-C6 + BMP581 + GDEH0576T81 (920x680), release build

- Deep sleep: **15.5-16 µA** (Arduino-era baseline ~15 µA — parity).
  USB-Serial-JTAG console (CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG) confirmed
  harmless in deep sleep; the Arduino-era ARDUINO_USB_CDC_ON_BOOT ~20 mA
  gotcha no longer exists.
- Temp-refresh wake (render + SPI push + full panel refresh): **3.2 s,
  ~95 mC** per event (Arduino-era: 3.2 s, ~93 mC — parity). At one
  refresh/hour this event alone averages ~26 µA, dominating the budget.
- Trace shape: ~1.5 s flat ~35 mA (boot + render + SPI push), then panel
  waveform bursts (~465 mA peak observed).

## FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90 (200x200 3-color), release build

- Deep sleep with FDN340P gate + ULP FSM polling: **19-20 µA** (Arduino-era
  ~18 µA on the same rig — parity within measurement variance).
- Z90 full refresh exceeds GxEPD2's hardcoded 20 s busy timeout → benign
  "Busy Timeout!" print every refresh (pre-existing; the print is ungated
  by the diag flag). Each refresh keeps the CPU awake the full ~21 s on
  this panel — refresh-rate limiting matters most here.

## Light sleep during EPD busy-wait (added after the above measurements)

- GxEPD2 setBusyCallback → esp_light_sleep_start() with GPIO wake on BUSY
  (level-agnostic) + 500 ms timer backstop; wake sources fully disarmed
  after each slice so nothing leaks into deep sleep.
- Needed three companions to work at all: gpio_sleep_sel_dis on
  CS/DC/RST/SCK/MOSI **and the EPD power-gate pin** (pins otherwise switch to
  their sleep config each slice — panel saw RST/power glitches: symptom was
  a started refresh ending in faint noise), plus keeping the C6's TOP power
  domain ON during slices (GPSPI register state), restored to AUTO after.
- **Measured (C6/GDEH0576T81, release): 95.4 → 56.25 mC per refresh event,
  −41%** — better than the ~27% estimate because light sleep covers the
  power-on/off busy waits too. Event wall-time 3.2→~3.8 s (backstop
  granularity; energy is what matters). Deep sleep unaffected (~15.5 µA).
  Evidence: xiao-seeed-esp32c6-bmp581-GDEH0576T81-screen-refresh-light-sleep.png
  vs the pre-light-sleep xiao-seeed-esp32c6-bmp581-GDEH0576T81-screen-refresh.png
  (Arduino-era-equivalent, ~93-95 mC).
- At 1 refresh/hour: refresh contribution ~26.5 → ~15.6 µA; total average
  ~42 → ~31 µA. Now ~40% below the Arduino-era firmware on this metric.
- **Measured (ESP32-E/GDEH0154Z90, release): 600 → 139 mC per refresh event,
  −77%** — the Z90's ~21 s busy window went from a solid ~24 mA spin-wait band
  to ~6.4 mA average (≈40 mC active phase: boot + ULP read + render + push;
  ≈100 mC panel drive + light-sleep floor). At 1 refresh/hour the refresh
  contribution drops ~167 → ~39 µA; total rig average ~186 → ~58 µA ≈ 3×
  battery life at that cadence. Evidence:
  firebeetle2-esp32e-bmp390l-GDEH0154Z90-screen-refresh.png (before) /
  -light-sleep.png (after). Savings scale with busy duration — slow panels
  gain most; tiny/fast panels gain less.
- Backstop raised 100→500 ms after the measurements above (free
  latency-wise — the GPIO level wake ends each wait instantly):
  **confirmed ~129 mC/event on the Z90 rig** (down from 139 at 100 ms),
  negligible difference expected on the C6.

## ULP wake latch — refresh trains (July 2026)

Symptom (PPK2, E/Z90 release): bursts of ~3 back-to-back refresh events with
~2 s gaps, then a clean 60 s sleep, repeating. Cause: the ULP FSM programs
called I_WAKE unconditionally; a wake signalled while the host was still awake
(Z90 renders ~21 s, easily overlapping a 60 s poll) latches in RTC_CNTL and
fires the moment deep sleep is entered. Pre-existing (same trains visible in
Arduino-era-equivalent debug logs); NOT caused by the light-sleep change.

Fix: gate I_WAKE on RTC_CNTL_RDY_FOR_WAKEUP and skip without updating the
delta reference — the delta re-detects at the next poll, so wakes happen at
most once per poll interval.

Verified on hardware (E/Z90 release, PPK2): single refresh per wake episode,
wakes correctly spaced at the 60 s poll cadence from the end of the previous
refresh, no cold-boot phantom refresh. Sibling fixes from the same episode:
ULP delta reference seeded on first run (cold boots used to double-refresh,
masked pre-gating by the wake latch), ULP program size now checked at BUILD
time (scripts/check_ulp_size.py, exact — validated 127/128 == on-device count,
and proven to fail the build on the old 129-word regression) with a graceful
runtime fallback (log + safety-net wakes) instead of an abort loop.

Open: the C6 LP-core program (ulp/lp_core_bmp58x.h) has the same unconditional
ulp_lp_core_wakeup_main_processor() calls, but the 5.76" rig is only awake
~3.8 s per cycle (~6% collision chance at 60 s polls). Gating needs a PMU
HP-sleep-state check from LP-core C code — do if trains are ever observed on
the C6.

## Skip app image validation on deep-sleep wake (July 2026)

`CONFIG_BOOTLOADER_SKIP_VALIDATE_IN_DEEP_SLEEP=y` (sdkconfig.defaults, both
boards): the 2nd-stage bootloader no longer re-hashes the ~1MB app image over
DIO/40MHz flash on every deep-sleep wake — that SHA256 pass recurred on 100%
of wakes, including no-refresh safety-net wakes. Power-on/reset boots still
validate. Uses the bootloader RTC-FAST retain area (16 bytes); ULP +
RTC_DATA_ATTR live in RTC slow memory, layout unchanged (overlap check OK).

- **Measured (ESP32-E/GDEH0154Z90, release, confirmed on 2 wakes):**
  - Active phase (boot + ULP read + render + push, before panel drive):
    **~40 → 22.5 mC** — 710 ms at ~32 mA avg (was ~1.7 s). The skipped
    validation was ~1 s of wall time, more than the ~250-400 ms estimate.
  - Full refresh event: **~129 → 114.5 mC** (19.0 s at 6.01 mA avg).
  - Evidence: firebeetle2-esp32e-bmp390l-GDEH0154Z90-wake-active-phase-skip-validate.png,
    firebeetle2-esp32e-bmp390l-GDEH0154Z90-screen-refresh-skip-validate.png.
- Deep-sleep floor re-confirmed with the retain area powered: **~19.4 µA**
  (within the pre-change 19-20 µA) — the sub-µA expectation held.
- C6 re-measured below (see "C6 measurements" section).

## Flash QIO/80MHz — tried and reverted (July 2026)

With deep-sleep image validation skipped, flash speed no longer matters:
QIO/80MHz (vs the board-default DIO/40MHz) shrank the active phase by only
~13 ms (710.5 → 697.3 ms) while raising its average draw ~4.4 mA
(31.7 → 36.1 mA) — net **22.5 → 25.2 mC, WORSE**. Full refresh event ~116 mC
(vs 114.5). Faster flash clocking costs current across the whole window; the
post-skip-validate active phase is CPU-bound, not flash-read-bound. Reverted
to DIO/40MHz. (Would have been the wrong experiment order pre-Stage-1: with
the ~1 s SHA256 pass still present, QIO would likely have won.)

## Compile at -Os (July 2026)

IDF builds default to -Og regardless of PlatformIO's build_type=release —
verified via compile_commands.json: all 908 app TUs were -Og. Now
`CONFIG_COMPILER_OPTIMIZATION_SIZE=y` in sdkconfig.defaults (both boards,
debug envs too — they exist for serial logs, not JTAG stepping).

- **Measured (ESP32-E/GDEH0154Z90, release):** active phase
  **22.5 → 20.6 mC** (710 → 640 ms at ~32 mA); full refresh event
  **114.5 → 112 mC**. Binary 1014 → 938 KB (also speeds any future
  power-on validation).
- Zoomed active-phase trace (1 s window): ~90 ms ROM+bootloader, one-sample
  ~405 mA spike at EPD power-gate turn-on (boost inrush), then a flat
  ~33 mA band to ~620 ms (IDF bring-up + render + SPI push ≈ 12.5 mC —
  the bulk of what's left), then panel drive takes over.
- Evidence: firebeetle2-esp32e-bmp390l-GDEH0154Z90-wake-active-phase-Os.png,
  firebeetle2-esp32e-bmp390l-GDEH0154Z90-screen-refresh-Os.png.
- Running total for the day (E/Z90 rig, per refresh event):
  600 mC (spin-wait era) → 129 (busy-wait light sleep) → 114.5 (skip
  validation) → **112 mC**; pre-refresh active phase 40 → 22.5 → **20.6 mC**.

## C6 measurements: skip-validate + -Os combined (July 2026)

Same two changes measured together on the XIAO C6 + BMP581 + GDEH0576T81
rig (release; the two effects were only separated on the ESP32-E above):

- Active phase (boot + render + SPI push): **28.5 → 18.3 mC**
  (1.08 s @ 26.4 mA → 0.80 s @ 22.9 mA).
- Full refresh event: **56.25 → 45.3 mC** (−19%). At 1 refresh/hour the
  refresh contribution drops ~15.6 → ~12.6 µA.
- Binary 1080 → 983 KB.
- Evidence: xiao-seeed-esp32c6-bmp581-GDEH0576T81-wake-active-phase-pre-skip-validate.png
  (before) / -wake-active-phase-skip-validate-Os.png /
  -screen-refresh-skip-validate-Os.png (after).
- Deep-sleep floors re-confirmed with the skip-validate retain area powered:
  **~15.8 µA C6, ~19.4 µA E** — both within their pre-change ranges
  (15.5-16 / 19-20 µA); no measurable floor cost.
- Bench gotcha from this session: a wrong screen/sensor local-secrets.h
  config panic-looped at ~600 ms cadence and read as a "~670 µA floor with
  25 mA pings" — the e-paper retaining a stale frame (old GIT_HASH + time
  on screen) was the tell that no boot ever reached render.

## Seeed XIAO ePaper Driver Board, first measurements (2026-07-05)

XIAO C6 + BMP581 + Seeed ePaper Driver Board (fixed RESE 0.47Ω, no power
gate) + GDEW029I6FD (2.9" 296x128), release build,
`seeed_xiao_esp32c6_epaper_release`. PPK2 source-meter 3.3 V into the 3V3
rail — the ETA9740 battery path is UNPOWERED in this setup (5V rail dead),
so these numbers exclude it.

- Deep-sleep floor: **~25.1 µA** avg (24.5–26 µA band). vs the 15.8 µA
  DESPI-gated baseline that's **+~9.3 µA for the ungated shield standby**
  (booster + hibernated panel + FPC) — nothing like the DESPI-C02's ~534 µA
  ungated, so a power-gate mod is likely not worth it here
  (+9.3 µA ≈ 0.8 C/day; one refresh/hour ≈ 3.4 µA-equivalent at this panel).
- Full refresh event: **12.21 mC over 3.57 s**, 43.3 mA peak. First I6FD
  datapoint — panel-specific, not comparable to the T81's 45.3 mC.
- The ±0.7 µA fuzz on the floor at 100 ksps is normal PPK2 low-range noise,
  not a wiring problem; the average is the meaningful number.
- Evidence: xiao-seeed-esp32c6-seeed-epd-board-GDEW029I6FD-screen-refresh.png
  / -deep-sleep-floor.png / -1min-overview.png.
- Still open (see docs/wiring.md checklist): ETA9740 quiescent via the JST
  battery path, ETA9740 leakage when battery-direct on the XIAO BAT pads.

### Battery path via shield JST (ETA9740) — measured, ruled out (2026-07-05)

Same rig, PPK2 as battery into the shield's JST (source-meter at 3.3 V,
confirmed; a second run at 4.2 V follows below).

- Floor: **~499 µA average** (settling from ~900 µA after plug-in) vs 25.1 µA
  on the 3V3 rail — ~20× the whole rest of the system; would drain the
  400 mAh pouch in ~a month at idle. The DESPI-C02's ~534 µA problem,
  relocated to the battery side.
- Signature: 20–83 mA pulses every ~2 s (ETA9740 load-detect/boost-refresh —
  the sleeping system sits below its load threshold, so it pulses forever)
  over continuous mA-scale pulse-skipping fuzz.
- Refresh at the battery node: **17.13 mC / 3.24 s** vs 12.21 mC at the rail.
  At 3.3 V: 56.5 mJ vs 40.3 mJ; net of ~5.3 mJ ETA9740 idle in the window,
  double conversion (boost→5 V→XIAO LDO) is ~75–80% efficient — fine, and
  irrelevant next to the idle draw.
- Verdict: **JST/ETA9740 path is a non-starter for deployment** — go battery
  direct on the XIAO BAT pads. Decisive remaining measurement: ETA9740
  leakage in that config (JST empty, switch off).
- Evidence:
  xiao-seeed-esp32c6-seeed-epd-board-GDEW029I6FD-eta9740-battery-path-floor.png
  / -eta9740-battery-path-refresh.png.

Second run at 4.2 V (full-charge voltage):

- Floor: ~483 µA avg over the first minute, settling to **~327 µA** in the
  second. The settling is the ETA9740 relaxing after plug-in (900 µA at
  connect → dense pulse-skipping fuzz band → fuzz stops ~t+65 s leaving only
  discrete load-detect bursts every ~2-5 s, some with ~100 mA restart
  inrush). The transition roughly coincides with the first LP-core wake
  (~60 s) but is almost certainly the IC's own standby transition — a µA/ms
  LP read can't lower the boost duty. Even settled: ~7.9 mAh/day, verdict
  unchanged.
- Wake+refresh: **12.31 mC / 3.34 s at 4.2 V = 51.7 mJ** vs 40.3 mJ at the
  3.3 V rail → ~78% double-conversion efficiency, consistent with the 3.3 V
  battery run. The mC figure matching the rail's 12.21 mC is the higher
  voltage compensating — compare in mJ.
- Evidence: xiao-seeed-esp32c6-seeed-epd-board-GDEW029I6FD-eta9740-4V2-settling.png
  / -eta9740-4V2-settled-floor.png / -eta9740-4V2-refresh.png.

### Battery direct on XIAO BAT pads — voltage sweep (2026-07-05)

Same rig, PPK2 as battery on the XIAO's underside BAT pads (shield JST
empty, switch off). Key fact from the XIAO C6 v1.0 schematic
(`hardware/XIAO ESP32-C6 v1.0 SCH.pdf`): the 3.3 V rail is a **SGM6029C
synchronous buck** (0.47 µH), NOT an LDO — VBAT feeds it through a P-FET
power path (LP0404N3), VBUS through a Schottky; charger is a separate
SGM40567-4.2 (120 mA). A pure buck making 3.3 V from a Li-ion explains the
strong voltage dependence:

| VBAT | settled floor | input power | signature |
|------|--------------|-------------|-----------|
| 4.2 V | 22.0 µA | 92.4 µW | clean PFM, sparse 2-8 mA narrow spikes |
| 3.8 V | 24.3 µA | 92.3 µW | clean, same character |
| 3.5 V | "10.75 µA" | 37.6 µW (!) | quiet sag phase, then burst storm to 0.88 A |
| 3.3 V | 121 µA | 400 µW | continuous ~30 Hz sawtooth bursts to 480 µA |

- ≥3.8 V: healthy. Input power constant at ~92 µW vs 82.9 µW at the rail →
  **~90% buck efficiency at a 25 µA load**; battery current is LOWER than
  rail current (the switcher giveaway).
- 3.3 V: buck in dropout — ~100% duty with periodic high-side
  bootstrap-refresh bursts (sag → 480 µA burst → decay, ~30 Hz), ~5× floor.
- 3.5 V: same sag/refresh cycle stretched to ~a minute. The 10.75 µA quiet
  phase is BELOW the sleeping system's output power — steady-state
  impossible, so the 3V3 rail must be sagging (system coasting on output
  caps / degraded); the 0.88 A bursts are current-limit recovery, likely
  with brownout restarts if a wake lands there. UNVERIFIED detail: probe
  the 3V3 rail (or check display/serial alive) during the quiet phase.
- Deployment: **battery-direct is the config — 22 µA/92 µW floor — but the
  usable window ends ~3.6-3.7 V**. Below that: dropout pathology, and
  0.88 A bursts into a weak battery's ESR likely boot-loop during refreshes.
  Cost of a 3.6 V shutdown is SMALL at our drain: at µA load (C/18000
  floor, ~0.11C refresh peaks, ~10-20 mV sag) VBAT rides the OCV curve,
  and standard LCO LiPo OCV stays ≥3.6 V until ~5-8% SoC — so we abandon
  only ~20-30 mAh of the 400 mAh pack (~4-7% in energy; ~3-6 weeks of a
  ~1.5 yr load-only life, comparable to what self-discharge would have
  eaten anyway). Chemistry-generic for 3.7 V LiPo; would NOT hold for
  LiFePO4 (3.2 V nominal — whole curve below the buck's cliff, unusable).
  Caveat: cold raises ESR several-fold — sample VBAT during sleep, not
  mid-refresh, or a 45 mA refresh at ~0°C sags below threshold early.
- Reproducibility: the 3.5 V sag state (10.75 µA quiet phase + burst storm)
  reproduced twice — deterministic mode-boundary behavior, not a glitch.
  Exact edge between 3.5 V (bad) and 3.8 V (clean) unmeasured; bisect at
  ~3.65 V to place the firmware shutdown threshold just above it.

Fine sweep (same evening) — full regime map, input-power lens (I×VIN):

| VIN | floor | input power | regime |
|-----|-------|-------------|--------|
| 4.2 | 22.0 µA | 92 µW | healthy PSM |
| 3.9 | 22.9 µA | 89 µW | healthy PSM |
| 3.8 | 24.3 µA | 92 µW | healthy PSM |
| 3.7 | 22.9 µA | 85 µW | healthy PSM — lowest verified-good point |
| 3.6 | 19.2 µA | 69 µW | SAG band: quiet + recovery storms to 0.53 A |
| 3.5 | 10.75 µA | 38 µW | deep sag + 0.88 A storms (2× repro) |
| 3.4 | 26.2 µA | 89 µW | continuous-burst dropout: dense 5-13 mA µs-spikes, rail held, functional |
| 3.3 | 121 µA | 400 µW | 30 Hz sag/burst sawtooth, system alive |
| 3.2 | 304 µA | 970 µW | 0.54 A boot-loop on entry, then system dead; flat converter churn (max 320 µA, no LP spikes) |

Physics: the SGM6029's NMOS high-side needs a bootstrap cap that only
recharges when the low-side switches. Near VIN≈VOUT the hysteretic mode
logic decides it barely needs to switch — starving the bootstrap; the
high-side degenerates to a source follower (VOUT ≈ VIN − VTH ≈ sag to
~2.9-3.1 V). A sagged rail LOWERS the sleeping load (leakage falls with
VDD), which is why sag-band input power reads BELOW healthy — the load is
being starved, not saved. Deep sleep tolerates it; any wake demanding tens
of mA collapses the follower → brownout → restart storms at the current
limit (di/dt ≈ VIN/0.47 µH ≈ 7 A/µs → cycle-by-cycle 0.5-0.9 A combs).
At 3.4 V duty demand (97%) forces continuous bursting — every burst
refreshes the bootstrap, so it's loud but healthy (89 µW). At ≤3.3 V
conversion is impossible and the sag/burst cycle runs continuously.
Non-monotonic vs VIN because each step lands in a different limb of the
hysteretic "do I need to switch?" state machine.

Consequence: 3.6 V is INSIDE the sag band → C6 shutdown threshold raised
3650 → 3700 mV (lowest verified-healthy), warn 3750 → 3800 mV. Costs
~12-15% of capacity by OCV instead of 5-8% — the real price of the pure
buck. Evidence: xiao-c6-bat-pads-3V7-clean-floor.png, -3V9-floor-after-
boot.png, -3V6-sag-with-storm.png, -3V4-continuous-burst.png,
-3V2-bootloop-then-dead.png (plus earlier 4V2/3V8/3V5/3V3 shots).

10 mV bisect of the sag edge (2026-07-05, short captures, floors stable):
3.51 V = 7.98 µA, 3.52 V = 6.89 µA, 3.53 V = 7.91 µA, 3.54 V = 8.07 µA
(all ~24-29 µW deep sag), 3.55 V = 25.13 µA (89 µW, regulating). The
deep-sag/regulating transition is a razor-sharp comparator threshold at
**3.545 ± 0.005 V ≈ VOUT + 245 mV** — the SGM6029's "VIN close to VOUT"
mode detector. 3.55 V still showed one storm in a minute and 3.6 V dwells
intermittently sagged (69 µW), so ~3.55-3.65 V is a bistable hysteresis
band — 3700 mV shutdown stands.
- SGM6029 datasheet vs reality: spec advertises "100% Duty Cycle Operation
  Capability" (high-side held on as battery approaches/falls below VOUT,
  VIN range 1.95-5.5 V, UVLO ~1.9 V) — no VIN>VOUT margin requirement
  stated. Measured behavior at the mode boundary is far less graceful than
  the prose. 3.8 V appears in the datasheet only as a typical-plot test
  condition, not a recommended minimum. Iq spec 2.3 µA (not switching) /
  ~8.5 µA (switching, PSM) brackets the measured floors.
- Firmware gap: C6 `read_battery_level()` is stubbed (returns 4321) and
  low/no-battery thresholds (3200/3000 mV) sit below where the hardware
  already misbehaves — needs a real VBAT read + ~3500 mV shutdown threshold
  on this board. Shield leaves no free ADC pin (see wiring.md checklist).
- ETA9740 leakage in this config: none observed — the 22 µA @ 4.2 V floor
  with the shield attached matches the rail baseline within buck efficiency.
- Evidence: xiao-c6-bat-pads-4V2-floor(-zoom).png, -3V8-floor.png,
  -3V5-sag-and-burst-storm.png, -3V3-dropout-sawtooth(-zoom).png.
