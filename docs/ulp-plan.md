# ULP Power Optimisation Plan

## Motivation

From the first 8.5-day run (notes.md), average consumption was ~12.6 mA, broken down as:

| Component | Contribution |
|---|---|
| Wake-up overhead (1.5s @ ~40mA every 5s) | ~91% |
| Display refresh (3s @ 50mA, ~1/14 min) | ~7% |
| Deep sleep @ 71µA | ~2% |

The core problem: **waking the main CPU every 5s is hugely wasteful** for a thermometer
where temperature changes on the scale of minutes or hours.

## Expected savings

Model assuming BMP390L + USE_213_M21 (3s refresh):

| Approach | Avg current | Battery life | Effort |
|---|---|---|---|
| Baseline (5s sleep) | ~12.6 mA | ~8.5 days | — |
| 60s sleep only | ~1.9 mA | ~57 days | Trivial |
| ULP, 1 refresh/14 min | ~0.26 mA | ~415 days | High |
| ULP, 1 refresh/hr | ~0.07 mA | ~1500 days | High |

The display refresh rate is the main variable: the ULP approach pays off most in a stable
environment where temperature rarely changes enough to trigger a display update.

---

## Phase 0 — Quick win: increase sleep interval (do this first)

Before touching ULP at all, change one line in `src/Thermometer.cpp:111`:

```cpp
// was: esp_sleep_enable_timer_wakeup(5 * 1000000);
esp_sleep_enable_timer_wakeup(60 * 1000000);  // 60s
```

This alone gives a ~7× improvement (8.5 days → ~57 days) with zero risk.
Run for a few days to get a new power baseline before continuing.

Also: if `DISABLE_SERIAL` isn't set in production builds, set it. The
`while (!Serial)` loop in `setup_serial()` blocks until a USB host is detected
(which never happens on battery), adding unnecessary startup time.

---

## Phase 1 — Verify RTC I2C pin assignment (research before any hardware work)

The ULP FSM's native `I2C_RD`/`I2C_WR` instructions go through the **RTC I2C peripheral**,
which is a separate hardware block from the main I2C (currently on GPIO21/22). Its pins are
**not freely configurable** — they are fixed by the chip.

### What to verify

1. Look up the exact RTC I2C pin mapping in the **ESP32 Technical Reference Manual**,
   section "ULP Coprocessor" (Chapter 29 as of TRM v5). The registers to check are
   `SENS_SAR_I2C_CTRL_REG` and the `RTC_IO` mux table.

   Community sources suggest SCL=GPIO4 and SDA=GPIO0 for the RTC I2C, but **verify
   against the TRM** before wiring anything — there is ambiguity across forum posts.

2. Check for pin conflicts with existing wiring:
   - GPIO0 = D5 = EPD_CS (currently in use!)
   - GPIO4 = D12 = DS18B20 DQ (if DS18B20 path is used; not a concern for BMP390L)
   - GPIO1/GPIO3 = UART TX/RX (used when serial is enabled)

   If GPIO0 conflicts with EPD_CS, the RTC I2C approach requires moving the ePaper CS
   wire. Document the outcome in `docs/wiring.md`.

3. **Alternative if pin conflicts are unresolvable:** bit-bang I2C in ULP assembly using
   GPIO read/write instructions on any two available RTC GPIOs. More assembly to write
   but pin-flexible. RTC GPIOs available on FireBeetle ESP32-E (not currently used):
   GPIO25=D2/EPD_RESET, GPIO26=D3/EPD_BUSY, GPIO27=D4 (touch button), GPIO32, GPIO33.
   GPIO32 and GPIO33 are unused and good candidates.

### Decision gate

Do not proceed to Phase 2 until pin assignment is resolved. The outcome determines
whether to use hardware I2C instructions or bit-banged I2C.

---

## Phase 2 — ULP program

### Architecture

```
Main CPU deep sleep
     │
     ├─ ULP timer fires every N seconds (e.g. 60s)
     │
     ▼
ULP FSM wakes:
  1. Trigger BMP390L forced-mode measurement (I2C write to PWR_CTRL)
  2. Wait ~5ms for conversion (WAIT instruction)
  3. Read 3 raw temperature bytes (DATA_0..2) via I2C
  4. Store in RTC memory
  5. Compare DATA_1 (mid byte, ~0.4°C resolution) with previous value
  6. If |delta| >= threshold: WAKE main CPU
  7. Else: HALT (ULP goes idle until next timer fire)
     │
     └─ Main CPU wakes only to update display, then returns to deep sleep
```

### RTC memory layout

Add to `src/Thermometer.cpp` (alongside existing `RTC_DATA_ATTR` variables):

```cpp
// Shared with ULP program — must be volatile and in RTC slow memory
RTC_DATA_ATTR volatile uint32_t ulp_raw_temp_0;   // DATA_0: bits [7:0]
RTC_DATA_ATTR volatile uint32_t ulp_raw_temp_1;   // DATA_1: bits [15:8]
RTC_DATA_ATTR volatile uint32_t ulp_raw_temp_2;   // DATA_2: bits [23:16]
RTC_DATA_ATTR volatile uint32_t ulp_prev_temp_msb; // reference for delta comparison
RTC_DATA_ATTR volatile uint32_t ulp_wake_reason;   // 0=timer, 1=temp change
```

### ULP assembly (hardware RTC I2C path)

Create `src/thermometer_ulp.S`:

```asm
/* thermometer_ulp.S — ULP FSM program for BMP390L polling
 *
 * Assumptions (verify in Phase 1):
 *   - RTC I2C SCL = GPIO4, SDA = GPIO0
 *   - BMP390L I2C address = 0x77, configured in slave_sel 0
 *   - BMP390L register addresses:
 *       PWR_CTRL = 0x1B  (write 0x13 to trigger forced mode: press+temp enabled)
 *       DATA_0   = 0x07  (temp raw, bits [7:0])
 *       DATA_1   = 0x08  (temp raw, bits [15:8])
 *       DATA_2   = 0x09  (temp raw, bits [23:16])
 *   - RTC slow clock ~150 kHz → 1 WAIT cycle ≈ 6.7µs
 *     5ms wait = ~750 cycles (tune empirically)
 */

#include "soc/rtc_cntl_reg.h"
#include "soc/sens_reg.h"

  .bss
  .global ulp_raw_temp_0
  ulp_raw_temp_0:   .long 0
  .global ulp_raw_temp_1
  ulp_raw_temp_1:   .long 0
  .global ulp_raw_temp_2
  ulp_raw_temp_2:   .long 0
  .global ulp_prev_temp_msb
  ulp_prev_temp_msb: .long 0
  .global ulp_wake_reason
  ulp_wake_reason:  .long 0

  .text
  .global entry
entry:
  /* Trigger BMP390L forced mode measurement:
     PWR_CTRL (0x1B) = 0x13 = 0b00010011
     (temp_en=1, press_en=1, mode=forced) */
  I2C_WR 0x1B, 0x13, 7, 0, 0

  /* Wait for conversion (~5ms for ultra-low precision).
     Tune WAIT count if readings are invalid. */
  WAIT 750

  /* Read raw temperature registers into RTC memory */
  I2C_RD 0x07, 7, 0, 0
  MOVE r1, r0
  ST r1, r2, 0                 /* ulp_raw_temp_0 */

  I2C_RD 0x08, 7, 0, 0
  MOVE r1, r0
  ST r1, r2, 4                 /* ulp_raw_temp_1 */

  I2C_RD 0x09, 7, 0, 0
  MOVE r1, r0
  ST r1, r2, 8                 /* ulp_raw_temp_2 */

  /* Delta check on DATA_1 (middle byte, ~0.4°C per count).
     If |current - previous| >= 1 count, wake main CPU.
     Adjust threshold for desired sensitivity. */
  LD r0, r2, 4                 /* current DATA_1 */
  LD r1, r2, 12                /* ulp_prev_temp_msb */
  SUB r0, r0, r1
  JUMP negative_delta, OV      /* branch if subtraction overflowed (result negative) */
  JUMPR no_wake, 1, LT         /* if delta < 1, skip */
  JUMP do_wake

negative_delta:
  /* Absolute value: 0 - r0 */
  MOVE r1, 0
  SUB r0, r1, r0
  JUMPR no_wake, 1, LT

do_wake:
  /* Update stored reference */
  LD r0, r2, 4
  ST r0, r2, 12                /* ulp_prev_temp_msb = current DATA_1 */
  MOVE r0, 1
  ST r0, r2, 16                /* ulp_wake_reason = 1 (temp change) */
  WAKE

no_wake:
  HALT
```

### Main CPU initialisation changes

When `boot_count == 1` (first boot), after NTP sync, configure and start the ULP:

```cpp
#include "esp32/ulp.h"
#include "driver/rtc_io.h"
#include "driver/i2c.h"  // or rtc_i2c.h for RTC I2C

void start_ulp()
{
  // 1. Configure RTC I2C peripheral
  //    (exact API: check esp-idf rtc_i2c.h — may need esp_idf_component_register)
  //    Set slave address 0 = BMP390L = 0x77
  //    Set clock speed (BMP390L supports up to 3.4 MHz; use 100kHz for reliability)

  // 2. Load ULP binary
  extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
  extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");
  ulp_load_binary(0, ulp_main_bin_start,
                  (ulp_main_bin_end - ulp_main_bin_start) / sizeof(uint32_t));

  // 3. Set ULP wakeup period
  ulp_set_wakeup_period(0, 60 * 1000000ULL); // 60s in microseconds

  // 4. Start ULP
  ulp_run(&ulp_entry - RTC_SLOW_MEM);
}
```

On subsequent boots (woken by ULP), skip the full sensor read path and go straight
to display update using the raw bytes already in RTC memory:

```cpp
// In setup(), after boot_count++:
esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
if (cause == ESP_SLEEP_WAKEUP_ULP) {
  // ULP detected temp change — read pre-computed raw bytes,
  // apply BMP390L compensation formula, update display, sleep
  float temp = bmp390l_compensate(ulp_raw_temp_0, ulp_raw_temp_1, ulp_raw_temp_2);
  // ... update display ...
  // Re-enable ULP timer and sleep (don't re-init ULP, it keeps running)
  esp_sleep_enable_ulp_wakeup();
  esp_deep_sleep_start();
}
```

### BMP390L compensation

The raw 24-bit value from DATA_0..2 needs the BMP390L temperature compensation
formula applied (same as the DFRobot library does internally). Extract this from
`DFRobot_BMP3XX.cpp` so the main CPU can apply it without re-initialising the
sensor on every ULP-triggered wake. Store the calibration coefficients (read once
on first boot) in RTC memory.

---

## Phase 3 — Daily display clear handling

The existing `periodic_display_clear()` logic uses `time()` which requires the main
CPU to be awake. Two options:

**Option A (simple):** ULP counts wakeup cycles in RTC memory. After
`86400 / ulp_period` cycles (i.e. one day), set `ulp_wake_reason = 2` and WAKE.
Main CPU checks `ulp_wake_reason` to decide whether to clear or refresh.

**Option B (accurate):** Keep the existing logic unchanged. On a ULP-triggered wake,
the main CPU runs `periodic_display_clear()` as today. This adds a small CPU wake
for time-checking, which is negligible if wakes are infrequent.

Option B is simpler to implement and correct enough to start with.

---

## Power measurement with the PPK2

Use the Nordic Semiconductor Power Profiler Kit II throughout all phases to get precise
current measurements. The PPK2's 100 kHz sampling rate captures short spikes (ULP wake,
display refresh) that the UT61E+ misses, and computes true average current over a window.

### PPK2 connection

Use **ampere meter mode** (PPK2 in series with the power supply) to measure real operating
conditions on battery:

```
Battery+ → PPK2 VOUT+ → FireBeetle VCC
Battery- → FireBeetle GND → PPK2 GND
```

Alternatively, use **source meter mode** to replace the battery entirely with a regulated
supply from the PPK2 — set output voltage to 3.7 V (nominal Li-ion). This is more
convenient on the bench and avoids battery depletion during long test sessions.

In nRF Connect Power Profiler:
- Set **sample duration** long enough to capture at least 5 full sleep/wake cycles
- Use the **average window** tool to measure true average current over a representative
  period (exclude the first boot WiFi/NTP phase, which is not representative)
- Use **markers** to isolate and label specific events (ULP wake pulse, main CPU boot,
  display refresh)
- Export raw CSV for offline analysis if needed

### Target measurements per phase

**Phase 0 baseline (5s sleep, before any changes)**

| Event | Expected | Measure |
|---|---|---|
| Deep sleep floor | ~27–71 µA | Zoom in on flat region between wakeups |
| Wake pulse height | ~40 mA | Peak of each active phase |
| Wake pulse width | ~1.5 s | Width at half-peak |
| Display refresh height | ~50 mA | Peak during display update |
| Display refresh width | ~3 s (213_M21) | Width during display update |
| **True average (5 min window)** | **~12.6 mA** | Compare against notes.md baseline |

> If true average differs significantly from 12.6 mA, re-examine the model before
> continuing. The baseline is the reference for all subsequent comparisons.

**Phase 0 after (60s sleep)**

| Metric | Model prediction | Measure |
|---|---|---|
| Deep sleep floor | same as above | Should be unchanged |
| Wake pulse | same shape | Should be unchanged |
| **True average (10 min window)** | **~1.9 mA** | Record actual value |
| Implied battery life | ~57 days | `2600 mAh / measured_avg / 24` |

**Phase 2 — ULP idle (ULP loaded, no main CPU wakes)**

To isolate ULP+BMP390L baseline current, temporarily modify the ULP program to never
issue `WAKE` (replace `WAKE` with `NOP`), then measure:

| Metric | Expected | Measure |
|---|---|---|
| ULP idle floor | ~6 µA | Flat region between ULP timer fires |
| ULP + BMP390L active pulse | ~4 µA avg, ~5 ms wide | Zoom in; may be near noise floor |
| **True average** | **~10–15 µA** | Confirm this is the new deep sleep baseline |

> The PPK2 can resolve this — the UT61E+ cannot. This measurement validates whether
> the ULP + BMP390L combination actually reaches the expected current floor.

**Phase 2 — Full ULP integration**

Restore `WAKE` in the ULP program and run in a representative environment:

| Metric | Expected | Measure |
|---|---|---|
| ULP idle floor | ~10–15 µA | Flat region |
| Main CPU wake (display refresh) | ~40 mA peak, ~1.5 s + ~3 s display | Per wakeup |
| Wakeup frequency | depends on temp stability | Count wakes per hour |
| **True average (1 hr window)** | **~0.07–0.26 mA** | Record, compare to model |
| Implied battery life | 415–1500 days | `2600 / measured_avg / 24` |

### Interpreting the waveform

A healthy ULP trace should look like this (not to scale):

```
mA
40 |          ┌──┐                              ┌──┐
   |          │  │                              │  │
   |          │  └──┐                           │  └──┐
 0 |──────────┘     └──────────────────────────┘     └─────
   t=0       wake  display                    wake  display
             (CPU)  (3s)                      (CPU)  (3s)
µA
15 |  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐  ┐
   |  │  │  │  │  │  │  │  │  │  │  │  │  │   ← ULP measurement pulses (~5ms each)
 5 |──┘  └──┘  └──┘  └──┘  └──┘  └──┘  └──┘   ← ULP idle floor
   t=0   60s  120s  180s  ...
```

Red flags to investigate:
- **Higher-than-expected idle floor**: peripheral not sleeping, GPIO leakage, I2C
  pullup resistors drawing current, or `ESP_PD_DOMAIN_RTC_PERIPH` not configured
- **No ULP pulses visible**: ULP timer not running or program HALTing immediately
- **Spurious main CPU wakes**: ULP delta threshold too sensitive, or noise on I2C

---

## Phase 4 — Validation sequence

1. **Logic-only test first:** Add a `#define ULP_SIMULATION` path where the main CPU
   runs the same read-and-compare loop at 60s intervals without actually loading ULP.
   Confirm display refresh behaviour matches expectations before involving ULP at all.

2. **PPK2 baseline capture (Phase 0 before):** Measure with current firmware at 5s sleep.
   Record true average — this is the reference against which all improvements are judged.

3. **PPK2 Phase 0 after:** Apply the 60s sleep change. Measure again. Confirm ~7× reduction.
   If not achieved, investigate serial init delay (`while (!Serial)`) or other startup cost.

4. **ULP connectivity test:** Short ULP program that just reads one BMP390L register
   and stores it in RTC memory. Verify from main CPU that the value is correct.
   Use PPK2 to confirm the ULP pulse is visible and ~5ms wide.

5. **PPK2 ULP idle baseline:** Run ULP with `WAKE` disabled. Measure floor current.
   Must be ≤ 15 µA before proceeding — if higher, find and fix the leakage source.

6. **Full integration + PPK2 long capture:** Run full ULP program in a representative
   environment for at least 1 hour. Export PPK2 data and compute:
   - True average current
   - Wakeup frequency (display refreshes per hour)
   - Implied battery life

7. **Stress test:** Leave running for multiple days; verify:
   - Display updates when temperature changes
   - Daily clear fires correctly
   - No spurious wakeups
   - Battery level tracking still works (still read on main CPU wakeup)

---

## Open questions / things to verify before starting

- [ ] **Exact RTC I2C pin mapping** on ESP32 (SCL/SDA) — check TRM Chapter 29
- [ ] **Pin conflict with EPD_CS (GPIO0)** if RTC I2C SDA is GPIO0 — may need to move
      EPD_CS to a different GPIO
- [ ] **RTC I2C API in current esp-idf** — `rtc_i2c_init()` in older IDFs; check what's
      available in the Arduino-ESP32 v3.x wrapping of esp-idf 5.x
- [ ] **BMP390L compensation coefficients** — confirm they can be read once and stored
      in RTC memory (they're factory-calibrated, so yes, but verify the DFRobot library
      exposes them)
- [ ] **WAIT cycle count** for 5ms delay — measure empirically; RTC slow clock varies
      with temperature (nominally 150 kHz but can drift ±10%)
- [ ] **ulptool vs raw assembly** — ulptool provides convenience macros and a PlatformIO
      build integration that handles the `.S` → `.bin` compilation step automatically;
      worth evaluating vs hand-rolling the build step

---

---

## Appendix — Alternative boards

A board upgrade is not required for the ULP plan above, but may be worth considering
alongside it since newer chips make the ULP work easier (C-programmable LP core instead
of FSM assembly) and some boards have lower deep sleep current without any hardware
modification.

### Chip variant deep sleep comparison

| Chip | Deep sleep (chip) | ULP type | WiFi |
|---|---|---|---|
| ESP32 (current) | ~10 µA | FSM assembly only | WiFi 4 |
| ESP32-S2 | ~22 µA | RISC-V + FSM | WiFi 4, no BLE |
| ESP32-S3 | ~7–8 µA | RISC-V + FSM | WiFi 4 + BLE 5 |
| ESP32-C3 | ~5 µA | **None** | WiFi 4 + BLE 5 |
| ESP32-C6 | ~7 µA | LP core (RISC-V, C) | WiFi 6 + BLE 5.3 |

The ESP32-C3 has no ULP whatsoever — disqualified. The ESP32-S2 has a higher sleep
current than the original ESP32 — not worth it. The ESP32-C6 LP core is the most
capable for sensor polling in sleep (dedicated LP I2C, LP UART, LP GPIO).

### Board shortlist

| Board | Board deep sleep | ULP | Battery charging | Price | Notes |
|---|---|---|---|---|---|
| **FireBeetle 2 ESP32-E** (current) | 11.6 µA (after pad cut) | FSM assembly | Yes, PH2.0 | $8.90 | Requires hardware mod |
| **FireBeetle 2 ESP32-S3** | ~12 µA (estimated) | RISC-V + FSM (C) | Yes, PH2.0 | $9.90 | Drop-in replacement, same footprint and connectors |
| **FireBeetle 2 ESP32-C6** v1.2 | 36 µA | RISC-V LP core (C) | Yes + solar | $5.90 | **Avoid**: v1.2 regressed vs current board; v1.0 was 16 µA |
| **Beetle ESP32-C6** | 14 µA (v1.0) | RISC-V LP core (C) | Yes | $4.90 | Compact; only 13 IO, may be tight for SPI+I2C+ADC |
| **XIAO ESP32S3** | **~12 µA** | RISC-V + FSM (C) | Yes, solder pads | ~$6.90 | Tiny (21×18 mm); best all-rounder at low cost |
| **XIAO ESP32C6** | **~14 µA** | RISC-V LP core (C) | Yes, solder pads | ~$5.20 | Best value; WiFi 6; LP I2C on GPIO6/7 |
| Adafruit ESP32-C6 Feather | 17 µA (optimised) | RISC-V LP core (C) | Yes, JST + fuel gauge | $14.95 | Over budget; best battery management of any option |

### Battery connectivity

The current setup uses an RS Pro 18650 26H Li-ion pack (2.6 Ah) connected via the
FireBeetle's PH2.0 socket.

| Board | Battery connector | Compatible with existing 18650 pack? |
|---|---|---|
| FireBeetle 2 ESP32-E (current) | PH2.0 | Yes (baseline) |
| FireBeetle 2 ESP32-S3 | PH2.0 | **Yes — plug straight in** |
| FireBeetle 2 ESP32-C6 | PH2.0 | Yes, but v1.2 sleep regression makes it a poor choice |
| Beetle ESP32-C6 | PH2.0 (unconfirmed) | Probably, but only 13 IO — likely too tight |
| XIAO ESP32C6 | **Solder pads only** (BAT+/BAT−) | Requires soldering wires to pads |
| XIAO ESP32S3 | **Solder pads only** (BAT+/BAT−) | Requires soldering wires to pads |

The XIAO boards are electrically compatible with 18650 Li-ion (same 3.7 V nominal /
4.2 V charge chemistry; XIAO charges at up to 380 mA, well within the 18650's safe
rate). But there is no physical connector — you'd solder the pack's leads directly to
the pads. If switching to a small LiPo pouch cell instead, those also connect the same
way and are more natural for the XIAO's compact footprint.

### Recommendations

**Keep the 18650 pack and minimise re-wiring:** FireBeetle 2 ESP32-S3 ($9.90). Same
PH2.0 battery connector, same 25×60 mm footprint, same pin positions. ULP RISC-V is
C-programmable, which simplifies Phase 2 significantly. Likely the lowest-friction
upgrade overall.

**Smallest and cheapest, open to battery change:** XIAO ESP32C6 (~$5.20). Board-level
deep sleep of ~14 µA without any hardware modification. LP RISC-V core with dedicated
LP I2C (SCL=GPIO7, SDA=GPIO6 — no conflicts with current display wiring). Pair with a
small LiPo pouch cell soldered to the BAT+/BAT− pads.

**What to avoid:**
- FireBeetle 2 ESP32-C6 v1.2: 36 µA board sleep is worse than the current board after
  its pad cut — a regression
- Any ESP32-C3 board: no ULP coprocessor at all
- XIAO ESP32C3: 45 µA board sleep (worst in the XIAO family) and no ULP

### ULP I2C pin constraints by chip

The LP/ULP I2C pins are fixed by hardware on all variants:

| Chip | LP/ULP I2C SCL | LP/ULP I2C SDA | Conflicts on current wiring |
|---|---|---|---|
| ESP32 (current) | GPIO4 or GPIO0 (verify TRM) | GPIO0 or GPIO3 (verify TRM) | Possible conflict with EPD_CS (GPIO0) |
| ESP32-S3 | GPIO1 or GPIO3 | GPIO0 or GPIO2 | Possible conflict with EPD_CS (GPIO0) |
| ESP32-C6 | **GPIO7** | **GPIO6** | No conflicts with current display/SPI wiring |

The ESP32-C6 LP I2C pins (GPIO6/7) are the cleanest option — no conflicts with the
ePaper display wiring or UART. This is one practical argument for choosing the C6 family
even if the S3 is otherwise equivalent.

---

## Useful resources

- ESP32 TRM: https://www.espressif.com/sites/default/files/documentation/esp32_technical_reference_manual_en.pdf
  (Chapter 29: ULP Coprocessor, Chapter 30: RTC I2C Controller)
- ESP-IDF ULP FSM programming guide: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/ulp.html
- ulptool (PlatformIO ULP build helper): https://github.com/duff2013/ulptool
- ESP32 ULP 1-Wire example (DS18B20): https://github.com/fhng/ESP32-ULP-1-Wire
- BMP390L datasheet (register map): https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp390-ds002.pdf
- DFRobot BMP3XX library source (compensation formula reference):
  https://github.com/DFRobot/DFRobot_BMP3XX
- PPK2 product page: https://www.nordicsemi.com/Products/Development-hardware/Power-Profiler-Kit-2
- nRF Connect Power Profiler (desktop app for PPK2): https://docs.nordicsemi.com/bundle/nrf-connect-power-profiler/page/index.html
