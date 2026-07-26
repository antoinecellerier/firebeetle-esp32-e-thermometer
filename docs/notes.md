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

## Flash history archive: base snapshot cost (2026-07-25, ESP32-E)

FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, PPK2 source-meter **3300 mV**,
`dfrobot_firebeetle2_esp32e_debug` built with
`-DPPK2_DEBUG -DHISTORY_BASE_EVERY_WAKE` (forces one snapshot per wake, which
is the only way to catch one — normal cadence is ~1/day). Measured on a
non-refresh wake, so no EPD current is involved; `epd_power_off()` has already
gated the panel rail by the time this runs anyway.

The write is bracketed on D1 by a 3x50ms preamble, so it can be found zoomed
out and selected exactly.

| | measured |
|---|---|
| duration | **170.2 ms** |
| average current | **41.94 mA** (46.83 mA peak) |
| **charge** | **7.14 mC** (23.6 mJ at 3.3 V) |
| baseline during preamble | ~29 mA |

So the flash operation itself adds **~13 mA** over simply being awake: 2.2 mC
is flash, 4.9 mC is the 170 ms of awake time it forces. There is no way to
avoid the latter — the write requires the CPU up with the cache disabled.

On-device timing of the flash calls alone (`ms_now()` either side) reads
erase 104-125 ms, program 25 ms, verify 7-8 ms. The ~13 ms the marker sees on
top is the CRC32 pass over the 6.4 KB payload plus the malloc/memcpy, which sit
inside the bracket but outside the timed calls.

Erase time drifted 104 -> 117 -> 125 ms over ~75 snapshots on the same two
ping-ponged sectors. Probably temperature or noise rather than wear at ~37
cycles per sector, but it is a 20% spread on the dominant term and worth
re-checking if it keeps climbing.

**Cadence implications**, against the ~7.1 C/day budget for this rig
(1.68 C floor + ~48 refreshes at 112 mC):

| base snapshot cadence | cost | share of budget |
|---|---|---|
| ~1/day (current) | 7.1 mC/day | **0.1%** |
| hourly | 171 mC/day | 2.4% |
| every wake (~72/day) | 514 mC/day | 7.2% |

The current cadence is free. Going hourly to keep the 24h sparkline no more
than an hour stale after a reflash would cost 2.4% — affordable but not
obviously worth it, since the sparkline rolls over daily anyway.

Journal appends (one 16-byte page program per hour) are not separately
resolvable and were not chased: ~1 ms against a 170 ms snapshot.

### Can the base snapshot overlap other work? No (considered 2026-07-25)

4.9 mC of the 7.14 mC is just awake time, so overlapping it with something the
CPU is doing anyway looks attractive. It doesn't work:

- **No parallelism exists.** `esp_flash_erase/write` disable the cache and
  busy-poll the status register, so the CPU cannot execute cached code while
  they run. IDF has no async/DMA flash API. The write blocks by construction.
- **The EPD busy-wait is the worst candidate, not the best.**
  `epd_busy_light_sleep()` calls `esp_light_sleep_start()` — the chip is halted
  at ~1-2 mA, which is why a ~20 s Z90 refresh averages only ~5.6 mA. Writing
  flash there means staying awake instead: ~27 mA x 170 ms = ~4.7 mC added
  against ~4.9 mC saved. Net zero, and `epd_pin_sleep_hold()` exists because the
  panel aborts its waveform if the control lines glitch mid-refresh — a
  cache-disabled 125 ms erase in the middle of that is a corrupted frame
  waiting to happen.
- The SNTP wait is the only genuinely idle-awake window, but the ordering is
  wrong: the snapshot has to capture the drift block the resync produces.

The lever that does exist is **duration**, dominated by erasing two sectors
(104-125 ms of 170). The payload is 6388 B, just over one 4 KB sector. Dropping
the hourly ring (4320 B) from the base leaves ~2 KB, so one sector:
erase ~53 ms, total ~76 ms, **~3.2 mC — a 55% cut**.

Not done, because at ~1 snapshot/day this saves 4 mC/day out of ~7.1 C/day and
costs: restore would have to walk the journal backwards across base generations
to rebuild the 720-hour ring (the `base_seq` filter that makes replay trivial
only works forwards), and the base would no longer be able to restore 30 days
on its own if the journal were damaged. Revisit only if the cadence goes hourly.

## C6 archive + time-sync budget: what is measured vs estimated (2026-07-25)

The FireBeetle numbers are PPK2-measured; the C6 equivalents are currently
**scaled from them**, so the C6 budget below is a projection, not a measurement.
Recorded here so a future session with a C6 on the bench can close the gaps
rather than re-deriving the estimates.

Projected daily budget, `seeed_xiao_esp32c6_release` (BMP58x + GDEH0576T81):

| Term | mC/day | Share | Basis |
|---|---|---|---|
| Sleep floor (15.8 µA) | 1365 | 32% | measured |
| ~48 refreshes @ 45.3 mC | 2174 | 52% | per-event measured; **rate assumed from the E rig** |
| ~24 non-refresh CPU wakes | ~360 | 8.6% | estimated ~15 mC each |
| NTP resync, 1/day | ~300 | 7.1% | estimated |
| Flash archive | ~7 | 0.17% | scaled from the E's measured 7.14 mC |
| **Total** | **~4.2 C/day** | | ±20%, dominated by the refresh-rate assumption |

### To measure on a C6

Archive (build with `-DPPK2_DEBUG -DHISTORY_BASE_EVERY_WAKE`; the triple 50 ms
D1 preamble brackets the write — see the ESP32-E section above for the trace):
- [ ] **Base snapshot charge.** Projected ~5-6 mC. The 170 ms measured on the E
  is erase-bound (~53 ms/sector × 2) so it should carry across; what changes is
  the CPU riding along — C6 single-core RISC-V ~20 mA vs the E's ~29 mA, over
  the flash's ~13 mA either way. Confirms or kills the 0.17% claim.
- [ ] **Journal append charge.** Assumed ~0.04 mC on BOTH boards and never
  actually measured on either. 25 appends/day, so even a 10× error is <2% of
  budget — but it is the number the "appends are free" argument rests on.
- [ ] **Ring sector erase.** Assumed ~2 mC, fires once per ~10 days.
- [ ] **One-time format.** 480 sectors, extrapolated to ~26 s / ~1 C from the E's
  erase rate. Only observable on the first boot after a partition-table change.

Time sync — the term worth the most attention, since it is ~40× the archive:
- [x] **Successful resync charge. MEASURED 2026-07-26: 120.7 mC over 1.80 s**
  (67.05 mA mean), ~84 mC of that incremental over the ~20.5 mA CPU baseline it
  runs on top of. **2-3× cheaper than the 200-400 mC projection.** C6 ePaper rig
  at 4.2 V battery-direct, `4c0bbef`, first-boot NTP bootstrap — which is the
  same `wifi_connect()` + `sntp_sync_once()` work a resync does. Shape: baseline
  to t+0, radio on with a 198 mA spike (PA/calibration inrush), sustained
  70-80 mA for 1.3 s, two short TX bursts for SNTP and teardown, done at 1.8 s.
  Combined with the ~1.5 d interval the C6's +452 ppm implies, the term is
  **~78 mC/day**, not the ~195 projected.
- [ ] **Failed resync charge on C6.** The 1.5 C (association timeout) and 4.5 C
  (plus SNTP timeout) figures are ESP32-E measurements assumed to transfer. On
  the C6 a failed attempt is ~36% of a day's budget versus ~21% on the E — same
  radio cost, half the budget — so the retry cadence matters more here.
- [x] **Actual resync interval reached.** Answered by inference, not by a soak:
  the C6's RC measured **+452ppm** over ~20d (`docs/clock-drift.md` 2026-07-26),
  which puts the adaptive rule at **~1.5 days**, not the 1-day floor — the
  interval converges where drift over it reaches the 60s threshold, 60s/452ppm
  ≈ 1.5d. That cuts this term to ~195 mC/day (4.6%) *where there is WiFi*. Where there
  isn't, it is worse than the projection, not better: failed attempts re-arm at
  `+resync_interval_s` with no backoff, so the interval stays pinned at 1 day
  forever. A crystal-equipped board should climb toward the 28-day cap, which
  drops this term to ~10 mC/day (0.25%) — the quantitative case for the FC-135 on
  `thermometer_c6`, now weaker than it looked, since the stock RC already buys
  ~2 days by itself.

Base rates:
- [x] **Refresh rate on a C6 rig.** **~10.8/day measured** — 216 refreshes over
  19d23h, XIAO C6 + BMP581 + Seeed ePaper hat on a 400mAh pack, `1ed89a3`, in a
  basement holding 21.5–24.5°C (2026-07-26). That is ~4.5× *below* the ~48/day
  borrowed from the FireBeetle (1077 over 21d17h, 860 over 18d17h). Both are
  real: refresh cadence is delta-triggered, so it measures how volatile the room
  is, and a basement is the stable end of the spread while the E rig sat in a
  flat with the windows open in a heatwave. Treat 10–50/day as the operating
  range — the term stays the table's largest error bar, but its floor is now
  measured rather than assumed. Same run gives **~20 non-refresh CPU wakes/day**
  (621 boots − 216 refreshes over 19d23h), close to the assumed 24.
- [ ] **Non-refresh CPU wake charge.** Projected ~15 mC (the E's is ~21 mC).

Rendering, on the 920x680 panel specifically (`tools/sim` covers the geometry,
but not the real panel's contrast and ghosting):
- [ ] **`! NOARCH` badge.** Trigger by flashing a build with `HS_FORMAT` bumped,
  then reverting. Verifies the archive-disabled warning is legible on the large
  layout, where the status line uses FreeSans12pt7b rather than Org_01.
- [ ] **`HOURLY_NO_DATA` gap.** The large layout draws the min/max envelope with
  `draw_spline_dotted`; confirm a multi-day gap reads as a gap rather than as a
  dotted line through it.

### C6 ePaper rig, marker-driven measurement (2026-07-26)

XIAO ESP32-C6 + BMP581 + Seeed ePaper driver board (GDEW029I6FD), `4c0bbef`,
`seeed_xiao_esp32c6_epaper_release` + `-DPPK2_DEBUG`, PPK2 source meter at
**4.2 V on the XIAO's soldered BAT pads** (shield switch off), USB detached.
144 s capture, 14.4 M samples, analysed with `tools/ppk2.py` — regions bounded by
the firmware's own D0/D1 edges rather than a dragged selection. Note the harness
crossed the lanes relative to the header's convention (PPK2 D0 on XIAO D6/GPIO16
= DISPLAY, D1 on D7/GPIO17 = CPU_ACTIVE), hence `--cpu-ch 1 --display-ch 0`.

| Term | Measured | Against |
|---|---|---|
| Sleep floor | **26.4 / 26.9 / 29.7 µA** (three windows) | 22.0 µA, same config, 2026-07-05 |
| Successful NTP resync | **120.7 mC / 1.80 s** | projected 200-400 mC |
| Panel refresh alone | **7.56 / 7.80 / 8.39 mC**, ~3.03-3.06 s | no prior decomposition |
| Delta wake + refresh | **12.97 / 13.21 mC**, 3.33 s | 12.31 mC / 3.34 s via JST at 4.2 V |
| Archive base snapshot | **0.54 mC / 24.4 ms**; 0.73 mC / 24.2 ms ×2 | 7.14 mC / 170 ms on the E |
| First boot, total | **356.7 mC / 12.29 s** | — |

What this settles and what it does not:

- **The 12.21/12.31 mC "refresh" figures were wake+refresh, not the panel.**
  Marker separation splits them: the panel itself is ~7.7 mC and the wake
  overhead around it ~5.4 mC. The totals agree with the earlier lump to within
  5%, which is the cross-check that makes the decomposition trustworthy.
- **The base snapshot here is ~10× cheaper than the E's, and that is probably not
  the steady state.** A freshly formatted archive still has erased sectors, so a
  24 ms flush is the no-erase case. The E's 170 ms is erase-bound (104-125 ms of
  it). Needs a snapshot that has to erase before this number means anything.
- **`PPK2_CPU_ACTIVE_HIGH()` runs after `ppk2_selftest()`, so the marker misses
  the boot preamble** — ROM bootloader, IDF startup and the selftest itself,
  ~450 ms at 10-20 mA (~5-9 mC) before D0 asserts. Every marker-bounded wake
  figure above therefore *understates* the true wake cost by roughly that much.
  Moving the marker ahead of the selftest would close it.
- **The one-time archive format was not isolated.** It sits inside the first
  boot's 12.29 s but does not present as a distinct erase plateau at 250 ms
  resolution — CPU-active current and flash current are the same order here, so
  it is not separable the way the E's was. Unresolved.
- The floor's spikiness is normal PFM: 11.6 µA between spikes plus ~0.16% duty
  of ~9 mA, 50-60 µs wide. Not a wiring fault, and not the ETA9740 — that path's
  signature is millisecond-scale 20-83 mA bursts every ~2 s, which is absent.

### Live capture cross-check, and the format by difference (2026-07-26)

Second capture of the same rig on `f07d2c9`, this time via `tools/ppk2.py live`
(`ppk2-api`, source meter 4.2 V, `--power-cycle` so sampling is already running
when the DUT powers up). Sustained **100.0 kSps with no dropped samples**
(4,499,456 in 45.00 s), which is what makes the reconstructed time axis valid —
live mode has no per-sample timestamps, so any drop would silently compress time
and under-report every charge figure.

**The two acquisition paths agree.** The NTP bootstrap over the same 1.8 s window
integrates to **113.4 mC** live against **120.7 mC** from the nRF app's CSV — 6%
apart, on different firmware and different acquisition code. Take the successful
resync as **~117 mC ±5%**, still 2-3x under the 200-400 mC projection.

| Term | `f07d2c9` (no format) | `4c0bbef` (with format) |
|---|---|---|
| Awake phase | 10.10 s, 280.2 mC | 12.29 s, 356.7 mC |
| Panel refresh | 3.058 s, 9.23 mC | 3.03-3.06 s, 7.56-8.39 mC |
| First floor window | 48.5 µA / 28.8 s | 26.4-29.7 µA |

**One-time archive format, derived by difference: ~2.19 s and ~76.5 mC.** The two
boots differ substantively only in whether the archive had to be formatted, and
that lands in the single-digit seconds the 1.7 s full-chip erase implied rather
than the ~26 s the sector-rate extrapolation projected. Derived, not measured —
the firmware also changed between the two boots — so it wants a direct capture
before it goes in the budget table.

Two things this run did **not** settle:

- **The CPU_ACTIVE marker fix is unconfirmed.** On a first boot the selftest still
  runs and pulses the lane, so the long span still begins after it; the fix only
  shows on wakes that skip the selftest. At 45 s against a 60 s sleep interval
  this capture never reached a second wake. Needs ~150 s.
- **The 48.5 µA floor is unexplained** against 26-30 µA on the previous capture.
  Single 29 s window straight after a cold boot; not investigated.

### Marker fix confirmed, and an unexplained floor (2026-07-26, 150 s live capture)

`f07d2c9`, 150 s at 100.0 kSps with no drops, boot plus two safety-net wakes.

**The CPU_ACTIVE marker now covers the wake.** Unmarked preamble on wake 2 went
from **445 ms to 45 ms** (`4c0bbef` first activity 74.047 → span 74.492;
`f07d2c9` 74.958 → 75.003). The span did not lengthen, because the 400 ms it
would have absorbed *was* the selftest, which no longer runs after the first
boot — so a PPK2_DEBUG wake also got ~7 mC cheaper. Retroactively: the old
marker-bounded figures were accidentally production-representative, since the
selftest sat outside the marker, but the old *sleep* windows were contaminated
by it.

| Wake | Span | Charge |
|---|---|---|
| Boot (with NTP, no format) | 12.36 s | 346.5 mC |
| Safety-net wake + refresh | 3.333 s | **14.05 mC** (45 ms unmarked) |

**Panel refresh across five observations:** 7.56, 7.80, 8.39, 9.23, 8.69 mC over
3.03-3.06 s. Mean ~8.3 mC, spread ±10%. That spread is the figure's real
precision — a single observation would have implied more.

**Open: the sleep floor is not reproducible.** 26.4-29.7 µA (nRF app capture,
`4c0bbef`), then 48.5 µA, then **141.2 µA falling to 75.7 µA within one capture**
(duty above 2x mean 4.3% → 2.4%). The settling trend inside a single run is the
strongest clue and points at something relaxing over 1-2 minutes rather than at a
constant leak. Not the ETA9740 — the shield switch is off and that path's
signature is ms-scale 20-83 mA bursts every ~2 s, absent here. Deliberately not
explained; it wants a dedicated long capture with no refreshes to find where it
asymptotes. At 76 µA the floor would be ~3x the recorded 22.0 µA and would matter
for battery life; at 26 µA it does not.

**Tool gap:** `--raw-out` writes a stream that cannot be re-analysed later,
because decoding needs the calibration modifiers read from the device at connect
time. Either save them in a sidecar or keep `--out`.

### Sleep floor resolved: 22 µA settled, 28 µA per cycle (2026-07-26)

`91f08eb`, production build (no `PPK2_DEBUG`, no markers, GPIO16/17 untouched),
PPK2 at 4.2 V on the XIAO BAT pads, board propped in air.

| Window | Mean |
|---|---|
| Settled tail, t=105-139 s | **22.75 µA** |
| Full wake-to-wake cycle, t=85-139 s | **28.06 µA → 2.42 C/day** |

**The elevated floors chased all afternoon were a post-wake transient**, not a
leak and not a measurement fault. After each wake the floor is elevated for
~20-25 s and then decays to 22 µA and stays flat until the next wake. The
logbook's 22.0 µA stands as the settled figure; **28 µA is the number the battery
sees**, since a real deployment pays the transient once per wake.

Budget: 2.42 C/day floor + ~0.45 C/day of measured events ≈ **2.9 C/day, ~500
days** on the 400 mAh pack. The floor is ~84% of it.

Why the earlier readings scattered so badly (26, 48, 52, 76, 141 µA): every one
was a mean over a window that included a different amount of transient, and the
short windows sat right after boot, whose 12-28 s awake phase produces the
largest transient of all. **A floor figure is only meaningful averaged over whole
wake-to-wake cycles.**

Not established: the 52.25 µA measured on fabric versus 28.06 µA in air is **not**
a matched comparison — the fabric window is post-boot and the air window is a
steady cycle, and the 92 s fabric capture never reached a second wake. The
transient does scale with the preceding awake phase, which is consistent with
self-heating raising leakage, but the fabric-vs-air gap is mostly window
selection. A 5-minute capture on fabric would settle it.

**Separate anomaly worth chasing:** one propped-in-air capture
(`ppk-20260726T121809.csv`) floors at **4.3-4.8 µA** with ~350 µA excursions
every ~50 s. That is below the 14 µA bare-board baseline, which suggests the LP
core was not running — no sensor polling, so no delta wakes and a panel that only
refreshes on the hourly safety net. Intermittent, and more concerning than
anything about the floor.

The post-wake transient is **not** caused by the `PPK2_DEBUG` marker/selftest
code: `91f08eb` is a production build with all of it compiled out (binary 300 B
smaller) and shows the same transient. The one flat capture (`4c0bbef`, 22-33 µA
across 57 s) is an outlier — a single well-cooled instance of a thermally
sensitive effect — not evidence that the marker change regressed anything.

On the 4.3 µA capture: it also contains **8 samples reading 17-20 A**, at two
moments, as bit-identical quartets. The PPK2 tops out near 1 A, so those are
range/decode artifacts, and four such samples inside a 500k-sample bin add
~160 µA to its mean — which manufactures two of that capture's apparent
excursions. The excursion ~55 s into sleep has no glitch near it and is real,
consistent with the LP core running. So the genuine anomaly is only the 4.3 µA
baseline, still below the 14 µA bare-board figure.
