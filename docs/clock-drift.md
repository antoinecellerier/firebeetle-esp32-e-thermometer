# Clock drift logbook

Deep-sleep timekeeping error measured at NTP resync. One row per observed
resync — append as datapoints show up, don't rewrite old rows.

## How the number is produced

`maybe_ntp_resync()` (`src/Thermometer.cpp`) reads the clock just before a
fresh SNTP exchange and again right after:

```
last_drift_ms = (before_sync - after_sync) * 1000   // + = clock ahead, - = behind
last_resync_interval_s = resync_interval_s          // observation window
```

Surfaced four ways:

- serial: `NTP resync: drift was <n> ms over <n> s` and `NTP resync: rate <n> ppm`
- display: `! DRIFT -9559s/21d -5265ppm n4 +-3%` badge in the status line, only
  when |drift| ≥ 60s (`src/DisplayRenderer.cpp`) — signed drift over the
  measured window, then the mean rate, sample count, and dispersion (see below)
- display: `! NOSYNC x2 14d` when resync attempts are failing (count in a row,
  age since the clock was last set)
- footer `s<N><m|h|d>` token = age of the last successful sync

The on-screen copy lives in `RTC_DATA_ATTR` and is still lost on power-cycle,
flash, or panic reset, and the device only retains the last
`DRIFT_PPM_HIST_SIZE` (6) rates. **Every observation is also journaled to the
`history` flash partition**, which survives all three and is not capped at 6:

```
~/.platformio/penv/bin/python3 tools/history.py backup
python3 tools/history.py dump hist-*.bin --drift
```

That emits this table's columns directly — drift, window, ppm, the mean ambient
over the window, and the boot/refresh deltas — so transcribing off the screen is
now a cross-check rather than the only record. Keep appending rows here anyway:
this file is where the interpretation lives.

### What the rate summary means

Windows are not uniform — the resync interval is adaptive and every failed
attempt stretches the next window by a whole interval — so the summary is
computed to be comparable across them:

- each sample is stored as a **rate** (ppm = drift ÷ its own window), which is
  what makes a 1-day and a 21-day observation the same kind of number;
- the mean is **window-weighted**, i.e. total drift ÷ total observed time, so a
  short noisy window can't pull as hard as a long one;
- `+-N%` is the **widest single deviation from that mean**, as a share of it —
  not a standard deviation and not the peak-to-peak range. Every retained
  sample sits within N% of the quoted rate;
- samples from windows under `DRIFT_MIN_WINDOW_S` (6h) are dropped rather than
  averaged in: drift comes from a whole-second clock, so a sample's noise floor
  is ~1s/window — 12ppm over a day, but 280ppm over an hour, which is the same
  size as the dispersion being measured. The 1-day resync floor keeps real
  windows well clear of this.

What it can't control for: the samples aren't independent of temperature or of
each other, so a tight `+-N%` over a few days of stable room temperature is
evidence the rate is *locally* constant, not that it holds across seasons.

The interval is adaptive: `< 60s` drift doubles it (cap 28d), `≥ 60s` targets
`60s` of drift at the next resync, clamped to `[1d, 28d]`. It starts at the 1d
floor after a cold boot so the first datapoint arrives the next day; a clock
good enough to need no correction climbs back to the 28d cap in five resyncs.

## Clock source per board

| Env | RTC slow clock | Expected error |
|-----|----------------|----------------|
| `dfrobot_firebeetle2_esp32e_*` | `CONFIG_RTC_CLK_SRC_INT_RC` (150kHz RC) | %-level, temperature-dependent |
| `seeed_xiao_esp32c6_*` | `CONFIG_RTC_CLK_SRC_INT_RC` | %-level, temperature-dependent |
| `thermometer_c6` (custom board) | `CONFIG_RTC_CLK_SRC_EXT_CRYS` (FC-135 32.768kHz) | ~20ppm (~2s/day) |

Neither stock board carries a 32.768kHz crystal, so `EXT_CRYS` is not an option
on them; the custom rev A board adds one deliberately.

## Observations

| Date | Board / build | Window | Drift | Rate | Next interval | Notes |
|------|---------------|--------|-------|------|---------------|-------|
| 2026-07-25 | FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `95c7b04`/`95de00c` (2026-07-03) | **21d** (badge said 7d) | −9559s (−2h39m) | **−5265ppm** (−0.53%, −7.6min/day) | 1d (clamped) | First resync with the drift badge on screen; clock running slow. Uptime 21d and the badge's 7d interval together mean the day-7 and day-14 attempts both failed — a success at day 7 would have re-armed to 1d (or 14d on negligible drift). So the window is the whole uptime, and the naive 7d reading (−15806ppm) is 3× too large. Ambient over the window swung 21–32°C (read off the device's own 30-day chart), so this rate is a temperature-weighted average, not a fixed-temperature measurement. |

Rate = drift / window, in ppm. Sign convention matches the badge: negative =
device clock behind real time.

### Collection run started 2026-07-25

FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `49202b8`,
`dfrobot_firebeetle2_esp32e_release` (`DISABLE_SERIAL`, 60s interval), **on
battery**, flash erased immediately before flashing so nothing synthetic from
the bench tests remains. Planned duration ~1 week; at the 1-day interval floor
that is ~7 samples.

Two things changed since the datapoint above, and both matter for how this run
is read:

- **Samples now survive.** Each successful resync journals a `REC_DRIFT` to the
  `history` partition, so `tools/history.py dump --drift` retrieves the whole
  run — no daily transcription off the screen, and a reflash or panic no longer
  destroys it. `DRIFT_PPM_HIST_SIZE` is still 6, so the *badge* shows only the
  last six; flash holds all of them.
- **Battery, not USB**, deliberately. The rate above is a temperature-weighted
  average and self-heating is a suspected covariate, so the run should reflect
  deployed conditions. `ambient_mean_x10` and `ambient_hours` ride along in each
  record for exactly that correlation.

Retrieve with `history.py backup --full` then `dump --drift`; the CSV already
computes the day-over-day `d_boot` / `d_refresh` duty-cycle deltas the decision
rules below ask for.

### Reading a datapoint

- Drift accumulates since the clock was last *set* — boot or the last
  successful resync — not since the last resync attempt. The badge's window is
  that measured span.
- **On builds before 2026-07-25 the badge showed the interval setting, not
  elapsed time.** A failed resync (WiFi down, SNTP timeout) re-armed
  `next_resync_time` and returned before recording anything, so the true window
  was a multiple of what was displayed. On those builds, cross-check the footer
  uptime token (`Nd Nh`): a badge still reading the 7d cold-boot default means
  every attempt since boot failed and uptime *is* the window.
- **The hash clips on the 200x200 panel**, which is why the status line repeats
  it (only on panels where the footer can't show it). On an older build,
  resolve the prefix with `git log --pretty='%h %ad %s' | grep -E '^<prefix>'`
  and rule out anything predating `1ad746a` (2026-05-25), before which resyncs
  measured ~0 drift and the badge never appeared.

## Open questions

- **Is the rate stable?** A single point can't tell drift from a one-off (RC
  recalibration, a long WiFi stall, a missed resync). See the collection
  protocol below — this is the question the daily samples exist to answer.
- **Temperature coefficient.** The RC oscillator is temperature-dependent and
  this device sits in the room whose temperature it plots, which is the
  cheapest experiment available: ambient swung 21–32°C over the first window,
  so if the tempco dominates, the daily rates should track each day's mean
  temperature instead of scattering.
- **The loop can't converge at this rate.** −5265ppm needs a ~3.2h interval to
  keep drift under a minute, but `RESYNC_INTERVAL_MIN` is 1 day. So the device
  resyncs daily and still shows up to ~7.6min of error just before each sync,
  at the cost of a daily WiFi wake.
- **Why did 2 of 3 resyncs fail?** (2026-07-25) Open. The `! NOSYNC xN` badge
  now makes a run of failures visible while it is happening, but not whether
  the cause is the AP, the 30s SNTP timeout, or something else — the serial log
  distinguishes them (`WiFi failed` vs `sync failed`). This is the dominant
  energy risk (see below), not the successful resync.

## Compensation: analysis and decision (2026-07-25)

Decision: **no compensation code**, and no extra RTC diagnostic fields, until
several daily samples exist. Recorded here so the reasoning isn't re-derived.

### What compensation could buy

A constant-ppm correction leaves a residual equal to the rate's instability.
At R = 5265ppm = 455s/day:

| Rate stability | Residual | Error @1d sync | @7d | @28d |
|---|---|---|---|---|
| ±1% | 4.5 s/day | 5 s | 32 s | 2.1 min |
| ±2% | 9 s/day | 9 s | 64 s | 4.2 min |
| ±5% | 23 s/day | 23 s | 2.7 min | 10.6 min |
| ±10% | 46 s/day | 46 s | 5.3 min | 21 min |
| none (today) | 455 s/day | 7.6 min | 53 min | 3.5 h |

Staying under 60s of error needs ±13% stability at daily sync, ±1.9% weekly,
±0.47% at the 28-day cap. **Because the resync floor is 1 day, a stability
worse than ~±10% buys nothing at all** — the interval cannot shrink to
compensate.

The payoff is not really display accuracy (7.6min on an e-paper thermometer
whose reading is already minutes stale). It is:

1. **Energy.** Floor is 19.4µA = 1.68 C/day; refreshes add ~5.4 C/day at the
   **measured** rate of ~2/hour (1077 refreshes over 21d17h = 49.6/day; 860 over
   18d17h = 46.0/day — this section originally assumed one per hour, i.e. half).
   A successful WiFi+NTP wake is **unmeasured anywhere in this repo**
   — the only defensible construction is 20.6mC (measured active phase) plus
   radio-on time. A *failed* attempt burns 15s (association timeout) or 45s
   (SNTP timeout too), i.e. 1.5–4.5 C — a fifth to two thirds of a day's ~7.1
   C budget. With 2 of 3 attempts failing here, going from 365 attempts/year to
   13 is the real prize.

   This number is also what sets the first-sync retry policy in
   `maybe_ntp_resync()`: retrying a never-set clock on every hourly safety-net
   wake would cost 36–108 C/day and flatten the battery in a day or two, so the
   bootstrap retries hard *within* one session (where the radio is already up
   and the marginal cost is small) and then backs off to ~1 attempt/day.
2. **The RTC-rendezvous design** in [multi-device-research.md](multi-device-research.md)
   (master wakes 200ms early, listens 500ms) is impossible at 455s/day. At ±1%
   residual the error after an hour is 0.16s, which fits.

### What ESP-IDF already provides

Checked before designing anything custom: **IDF has no frequency/drift
compensation.** What exists:

| Lever | Verdict |
|---|---|
| `CONFIG_RTC_CLK_SRC_INT_8MD256` (ESP32 only) — "internal 8.5MHz oscillator ÷256 (~33kHz)… better frequency stability than the internal 150kHz oscillator… higher deep sleep current (by 5µA)" (`esp_hw_support/port/esp32/Kconfig.rtc`) | **Try this before writing code.** One sdkconfig line, zero application logic. +5µA on a 19.4µA floor = +0.43 C/day, against a daily-resync regime that plausibly costs ~1 C/day given the failure rate. Not available on the C6 (INT_RC / EXT_CRYS / EXT_OSC only). Verify ULP FSM timing survives the slow-clock change (`ULP_WAKEUP_PERIOD_US`). |
| `CONFIG_RTC_CLK_CAL_CYCLES` (1024 today, range to 32766) | Improves calibration precision at boot-time cost. Won't fix a systematic awake-vs-asleep offset; cheap second arm. |
| `SNTP_SYNC_MODE_SMOOTH` / `adjtime()` (`esp_libc/src/time.c`) | **Rejected.** Slews a one-shot *offset*, not a frequency; only engages under 35min of error (ours steps); and its slew state is plain `static`, not RTC — it does not survive deep sleep, and this device sleeps seconds after syncing. |
| `CONFIG_RTC_CLK_SRC_EXT_CRYS` | Needs a 32.768kHz crystal the WROOM-32E module doesn't have. This is how the custom board avoids the problem entirely. |

### Why the clock is slow (mechanism)

`esp_clk_init()` → `select_rtc_slow_clk()` recalibrates the RC against the
40MHz crystal on **every** boot including each deep-sleep wake;
`sleep_modes.c` recalibrates again at sleep entry; `esp_rtc_get_time_us()`
converts only ticks-since-its-last-call using the calibration current at that
moment. Calibration is therefore fresh at both ends of every sleep window, so
a persistent one-directional error is most likely the RC running at a
different frequency **asleep** than **awake being calibrated** (power state,
self-heating). That predicts the rate tracks wake/sleep duty cycle rather than
ambient — which would make the 21–32°C first window an adversarial worst case,
not a typical one.

Corollary, and a correction to an earlier note here: **biasing the deep-sleep
duration cannot work.** Wall clock is `boot_time + ticks × cal`; it advances
whether or not the CPU is asleep and regardless of what the sleep timer was
programmed to. Changing the sleep duration only changes *when* wakes happen.

### Collection protocol

The interval is pinned at the 1-day floor, so a sample lands daily. Record per
reading, all from the screen — no firmware support needed:

| From | Token | Why |
|---|---|---|
| status line | `! DRIFT ±Ns/<window>` | the raw measurement |
| status line | `±ppm nN +-M%` | mean rate, sample count, dispersion |
| footer | `#N` boot count | **delta vs the previous day = HP wakes that day** — the duty-cycle correlate |
| footer | `rN` refresh count | refresh-heavy days are the high-self-heating days |
| footer | `s<age>`, uptime `NdNh` | confirms the sample is fresh and the window is real |
| 30-day chart | that day's min/max | the temperature correlate |

Every one of those correlates is now also journaled per resync, so the run no
longer depends on catching each day: `tools/history.py dump <backup> --drift`
emits the same columns with the boot/refresh deltas already differenced, and it
is not capped at `DRIFT_PPM_HIST_SIZE` (6) the way the on-screen ring is. The
archive also survives a reflash or a panic, so the run is no longer destroyed by
one.

Reading it back does cost the device its in-progress hour — entering download
mode resets the chip — so harvest at the end of the run, or on days you were
going to read the screen anyway. Stay on battery meanwhile: tethering for serial
changes charger and regulator dissipation, hence die temperature, perturbing the
thing being measured.

### Decision rules once ~6 samples exist

- **`+-M%` ≤ ~2%, uncorrelated with both correlates** → constant-rate model; a
  single ppm constant, interval out to 7–28d.
- **Tracks daily temperature** → `R(T) = R0 + k(T−Tref)`, integrated over the
  device's own hourly history.
- **Tracks the boot-count delta** → duty-cycle model, confirming the
  awake-vs-asleep asymmetry above; correction needs a per-wake term.
- **`+-M%` > ~10%** → compensation is futile at the 1-day floor. Drop it and
  spend the effort on the resync failure path instead.

### If compensation is built (design held ready)

`settimeofday()` at each HP wake, placed right after `boot_count++` so every
consumer — crash breadcrumb, `update_hourly_history()`, the 04:00 clear
schedule, the rendered `%H:%M` — sees one consistent clock. Correcting via
`esp_clk_slowclk_cal_set()` is foreclosed: `sleep_modes.c` overwrites it at
sleep entry, and the sleep window is already converted to wall-clock before
`app_main` runs.

The critical detail: once armed, the resync measures the **residual**. Store
`residual + applied_ppm` into `drift_ppm_hist` so the history keeps meaning the
raw oscillator rate — otherwise the ring collapses toward zero and the model
re-fits itself to nothing. Log the `raw ≈ residual + applied` identity at every
resync as a self-check. Keep `! DRIFT` as the ≥60s alarm and add a footer token
for "compensation armed", so a working correction doesn't hide its own
existence.

Note the RTC constraint: on the ESP32-E only **60 bytes** separate the app's
RTC sections from `ULP_DATA_BASE` (the build prints the headroom every time —
see `scripts/post_build_check_rtc.py`). Per-sample covariate arrays would not
fit today without raising the base.
