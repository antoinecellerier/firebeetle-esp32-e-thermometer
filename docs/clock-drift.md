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

All of it lives in `RTC_DATA_ATTR`, so it is lost on power-cycle, flash, or
panic reset — hence this file. The device retains the last
`DRIFT_PPM_HIST_SIZE` (6) rates, enough to see stability at a glance without
catching each resync, but not enough to survive the battery coming out.

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
  recalibration, a long WiFi stall, a missed resync). Two or three consecutive
  windows at a similar ppm would justify compensation.
- **Temperature coefficient.** The RC oscillator is temperature-dependent and
  this device sits in the room whose temperature it plots — which is also the
  cheapest experiment available: ambient swung 21–32°C over the first window,
  so if the tempco matters, the daily rates should track each day's mean
  temperature instead of scattering. The device already holds 30 days of hourly
  temperature in RTC, so the mean ambient over each drift window could be
  stored beside its rate (1 byte per sample) and the correlation read straight
  off the screen. Worth doing once a few daily samples exist to correlate
  against.
- **The loop can't converge at this rate.** −1.58% needs a ~63min interval to
  keep drift under a minute, but `RESYNC_INTERVAL_MIN` is 1 day. So the device
  now resyncs daily and still shows up to ~23min of error just before each
  sync, at the cost of a daily WiFi wake.
- **Compensation** (deferred until the rate looks stable): persist a ppm figure
  and correct at wake, or bias the deep-sleep duration. Would also let the
  resync interval grow back out and drop the daily WiFi wake.
- **Why did 2 of 3 resyncs fail?** (2026-07-25) Open. The `! NOSYNC xN` badge
  now makes a run of failures visible while it is happening, but not whether
  the cause is the AP, the 30s SNTP timeout, or something else — the serial log
  distinguishes them (`WiFi failed` vs `sync failed`).
