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
python3 tools/history.py dump local/archives/hist-*.bin --drift
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

### The FC-135 arms, started 2026-08-12 — t=0 record

**The ~20ppm row above has never been measured.** It is what
`CONFIG_RTC_CLK_SRC_EXT_CRYS` and the FC-135's spec imply, and every observation
in this file comes from a crystal-less rig (+5066 / +305 / +1259ppm). These are
the runs that put a number on it.

| Board | MAC | Build | Started | Placement |
|---|---|---|---|---|
| 4 | `10:bd:a3:a8:d3:64` | `thermometer_c6_release`, rig `revA-bigscreen`, git `753afbc`, no flags | 2026-08-12, 3996mV | **paired, ~10cm** |
| 2 | `98:88:e0:75:48:10` | same env/rig/flags, git `11cd8dd` | 2026-08-11 22:49Z, 3998mV | **paired, ~10cm** |
| 3 | `98:88:e0:75:47:94` | same env/rig/flags, git `52cf257`; **different WiFi network list** | 2026-08-12 18:27, 4188mV | apart, **different AP** |

**The fleet is sealed.** Board 3 was the last board reachable on USB; from here
every number comes off a panel or out of an archive at harvest.

All three: GDEH0576T81, 400mAh pack, `esptool erase_flash` immediately before
flashing so the archive starts empty and the first base snapshot is unambiguous.
Boards 2 and 4 hold a static DHCP lease, so their resyncs take the fast path and
the NTP term is consistent between them; **board 3 is on a different AP and is
expected to hold a dynamic lease for the run**, so its resync path carries a DHCP
exchange the pair does not. That term was deliberately not measured before the
run: it is a property of that AP and its RF path rather than of the board, a
bench figure would describe the wrong network, and nothing in
`HistoryDriftSample` persists connect duration, so capturing it in situ would
have meant an on-flash layout change to a fleet already sharing one. What the
archive does record per arm is `resync_fail_count` plus the absolute
`boot_count`/`refresh_count`, which is the term that actually costs charge — a
failed resync burns a full association where a slow DHCP round does not.

Boards 2 and 4 each confirmed a complete cycle on battery before being left
alone — board 4 `#2 r2 lp1 w:ULP` at 3996mV, board 2 a ULP-woken refresh at
**3998mV on its second render (4004mV on the first)**. Take the second reading
as t=0.

**That rule outlived its stated reason.** The 6mV step between board 2's two
renders was put down to surface charge decaying off a freshly-charged pack —
which cannot be right, because **boards 2 and 4 were never charged at all**.
What the step actually is remains open; first-render load relaxation is the
obvious candidate and nothing here tests it. Prefer the second reading anyway,
now on the evidence that the first one moves rather than on a mechanism.

**Board 3 starts ~190mV above the pair because it is the only one that was
charged.** Boards 2 and 4 run their packs **as ordered, never charged at all**;
board 3's went on the charger until the light went out. Two candidates died on
the way to that:

- **Not surface charge.** The board ruled it out itself — **the fourth render
  read 4186mV, a 2mV step** off the 4188mV t=0, where board 2's own
  first-to-second step was 6mV. Board 3 is flatter than the decay the pair
  showed, not steeper; the pack really is sitting at ~4.19V.
- **Not divider spread.** Every pack read **~4000mV on its own board when
  plugged in before charging** — same nominal state, same reading, across
  different boards. That agreement bounds per-board divider spread at the
  resolution of the observation (tens of mV), which is nowhere near 190mV. It is
  not a characterisation, but it is enough to retire the question, and it is the
  only cross-board divider check the fleet will offer until a board comes off.

**The consequence is run length, and it favours board 3.** Both thresholds are
`low_battery_mv = 3550` / `no_battery_mv = 3500` on this board, so board 3 has
688mV of span against the pair's ~497mV, and an as-shipped cell near 4.00V is
roughly three-quarters charged — an estimate from the LiPo curve, not measured
here. **Expect boards 2 and 4 to reach cutoff appreciably before board 3**, which
bounds the control pair's drift run, not merely its battery figure: a board that
shuts down stops producing drift samples. Plan the harvest around the pair
ending first. Discharge comparisons across arms stay rate-based over a common
window — with different starting states of charge, "days to reach X mV" is now
meaningless rather than merely unsafe.

**Board 3's clock was NTP-synced at first boot**, so its drift window is anchored
at 2026-08-12 18:27 and the panel timestamp above is a real time rather than a
free-running one. The new AP was therefore reachable from where it booted. The
first drift *sample* lands one resync interval after that anchor, not at t=0.

**The arms do not share a t=0**, so compare rates and not elapsed drift: board 3
starts roughly a day behind the pair, and the adaptive resync interval means its
sample count will lag by more than that day alone implies.

**Board 2's hash differs but its firmware does not.** It was flashed after the
BOD probe released the rig, by which time three documentation-only commits had
landed; `git diff 753afbc..11cd8dd -- src include ulp components platformio.ini
sdkconfig.defaults*` is empty, so the only difference on the wire is the string
the panel prints.

**Board 3 is the inverse, and it is the one that needs saying.** It was flashed
at `52cf257` on a clean tree — `git diff 753afbc..52cf257` over the firmware
paths is likewise empty — so by the tracked tree it too is board 4's build. But
its `include/local-secrets.h` carries a different `MY_WIFI_NETWORKS` list, and
that file is gitignored: **same hash, different binary, and git cannot show the
difference.** The divergence is confined to which SSID the board associates with.
Read the three arms as one build everywhere except the WiFi path, where board 3
is deliberately its own thing.

**The placement column is the experimental design, not an incidental detail.**
Boards 2 and 4 sit ~10cm apart and board 3 goes elsewhere, which makes this a
controlled pair plus a treatment rather than three parallel arms:

- **2 vs 4 — same room, same firmware.** Any difference between them is
  part-to-part: crystal spread, BMP581 spread, board spread. This is the control
  the earlier arms never had, and it is what tells a good FC-135 from a lucky
  one. A single arm reporting ~20ppm would be unfalsifiable.
- **3 vs the pair — same firmware, different room.** With 2/4 establishing how
  much of a gap is board-to-board, a gap *beyond* that is the room. This is the
  only way to get at the refresh-cadence term, which the `docs/notes.md` budget
  currently transfers from the XIAO runs and which is its weakest number:
  refreshes are delta-triggered, so cadence measures how volatile the room is.
- **2 and 4 also run two calibrated sensors in the same air for ten days**, which
  nothing in this project has ever done. Their hourly records should overlay; the
  residual is BMP581 part-to-part agreement in situ, free, from the same journals.
  Mutual heating is not a confound — each board sleeps at ~90µW.

One asymmetry to carry: board 2 has by far the most bench history of the fleet —
every power figure in the T81 budget was measured on it, through a brownout
bootloop and a full sweep to 3.0V. If it diverges from 4, the co-location means
the room is already excluded, and the first hypothesis should be a board the
campaign quietly damaged rather than ordinary spread.

Harvest from the journal (`tools/history.py`), not from the badge — the badge
shows the last window only, and the 2026-08-05 harvest found ten samples where
the badge said six. Do not attach USB mid-soak: it enters download mode and
wipes the RTC drift window.

## Observations

| Date | Board / build | Window | Drift | Rate | Next interval | Notes |
|------|---------------|--------|-------|------|---------------|-------|
| 2026-07-25 | FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `95c7b04`/`95de00c` (2026-07-03) | **21d** (badge said 7d) | −9559s (−2h39m) | **−5265ppm** (−0.53%, −7.6min/day) | 1d (clamped) | First resync with the drift badge on screen; clock running slow. Uptime 21d and the badge's 7d interval together mean the day-7 and day-14 attempts both failed — a success at day 7 would have re-armed to 1d (or 14d on negligible drift). So the window is the whole uptime, and the naive 7d reading (−15806ppm) is 3× too large. Ambient over the window swung 21–32°C (read off the device's own 30-day chart), so this rate is a temperature-weighted average, not a fixed-temperature measurement. |
| 2026-07-26 | XIAO ESP32-C6 + BMP581 + Seeed ePaper hat (GDEW029I6FD), `1ed89a3` (2026-07-06), `seeed_xiao_esp32c6_epaper_release`, 400mAh pack | **19d22h47m** (uptime 19d23h less the drift; the clock was set once, at install) | **+780s** (+13min), ±60s | **+452ppm** (+0.045%, ≈ +39s/day), +418…+487ppm | 1d (never reached — see notes) | **First C6 datapoint, and not device-measured**: this build never got a successful resync to sample from, and with `DISABLE_SERIAL` and no `history` partition there was nothing else to read, so the figure comes from a **forced refresh** — panel `11:54` against `11:41` real, frame fresh, both clocks to the minute (hence ±60s → ±35ppm). Cross-checked against a photo taken 13min earlier: EXIF 11:30:17 (phone on network time, verified against laptop NTP within 50s) against a panel reading `11:40`, which at a constant +13min means that frame was ~3min stale — consistent with the 1-2min refresh cadence it was running while being carried upstairs (counters moved +3 boots/+3 refreshes in 4 LP ticks). The photo alone bounds drift at ≥+338ppm, since staleness can only *increase* it; the forced read lands above that, as it must. Clock **fast**, i.e. opposite in sign to the FireBeetle row above and ~12× smaller. Ambient was 21.5–24.5°C over the window (off the device's own 30-day chart) versus 21–32°C for the E, so thermal stability explains part of the magnitude gap but not the sign. Deployed in a basement with **no WiFi**: every resync attempt failed, so `resync_interval_s` sat at its 1d floor for 20 days (failures re-arm, they don't back off — fixed 2026-08-09, `2fccb5f`: absent-network failures now escalate the retry) and the footer read `s19d`. Had it had WiFi, +452ppm implies the interval settles where drift over the interval hits the 60s threshold — 60s/452ppm ≈ **1.5d** — so neither the 1d floor nor the 28d cap: day 1 sees 39s (<60s → doubles to 2d), 2d sees 78s (≥60s → targets ~1.5d), and it holds there. Note this build divides by the interval *setting* rather than the measured window, so the first resync after a failure run reads the rate 20× high and clamps the next interval to the 1d floor; master computes `target` from `last_drift_window_s` instead. |
| 2026-07-26 .. 2026-08-04 | FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `44ba5ba` (2026-07-25), `dfrobot_firebeetle2_esp32e_release`, on battery | **1d** × 10 resyncs, 10.11d total | +421s .. +459s (4424s total) | **+5066ppm** window-weighted (+4839…+5247, ±4.5%) | 1d (clamped) | **The collection run, harvested from the journal** — ten samples, not the badge's six, with per-window ambient and duty-cycle deltas. 10 of 10 attempts succeeded. Rate tracks **wakes/day at r=−0.900** and not mean ambient (r=+0.457, collapsing to +0.275 once wakes are controlled for). But wakes are delta-triggered and correlate with room volatility at +0.93…+0.98, so duty cycle and a movement-sensitive tempco are not separable here — a tempco in temperature *level* is ruled out, the mechanism is not. Full CSV and analysis: [below](#harvest-2026-08-05-the-runs-ten-samples). |
| 2026-07-27 .. 2026-08-02 | XIAO ESP32-C6 + BMP581 + Seeed ePaper hat (GDEW029I6FD), `431b7b0` (2026-07-26), `seeed_xiao_esp32c6_epaper_release`, 400mAh pack, open space at ~1.4m | 1.011d, **4.017d**, 1.737d (6.76d observed) | +22s, +139s, +17s | **+305ppm** window-weighted (+113…+400, **±63%**) | 3.47d and climbing | **Same board as the 2026-07-26 row, reharvested from its journal** — and ~17× smaller than the FireBeetle but ~14× less stable, so the adaptive interval hunts in a 1.7–3.5d band instead of pinning to the floor. Only three records because the interval is *working*: the run reconstructs the algorithm exactly, including one **failed attempt** on ~2026-07-29 visible only as a 4.017d window against a 2d setting. Not monotone in wakes/day, so the FireBeetle's duty-cycle relation does not reproduce at n=3. [Below](#c6-epaper-hat-harvested-2026-08-05). |
| 2026-07-29 .. 2026-08-04 | XIAO ESP32-C6 + BMP581 + DESPI-C02 + GDEH0576T81, `44e56b6` (2026-07-06), 400mAh pack | **1d** × 5 observed resyncs | +96s .. +116s | **+1259ppm** window-weighted (+1111…+1343, ±12%) | 1d (pinned) | **Five samples, all transcribed off photographs** — this build predates the `history` partition (`8b57f33`, 2026-07-25), so the panel is the only record and there is nothing to harvest. Per-sample table and the reasoning that the displayed `/1d` really is the window: [below](#photo-transcribed-run-c6--despi-c02-2026-07-29--2026-08-04). Clock **fast**, same sign as the other C6 row above and ~2.8× larger. The panel's `4321mV` is not a measurement — `read_battery_level()` returns a literal `4321` on the stock XIAO (`src/Thermometer.cpp`), so this run says nothing about the pack's state at 28d18h. |
| 2026-08-12 .. 2026-08-19 | **thermometer-c6 rev A board 2** + BMP581 + GDEH0576T81, `11cd8dd` (2026-08-11), `thermometer_c6_release`, rig `revA-bigscreen`, 400mAh pack, **`CONFIG_RTC_CLK_SRC_EXT_CRYS` (FC-135)** | 1.03d, 2.01d, 4.03d (7.07d observed) | −3s, −5s, −4s (−12s total) | **−19.7ppm** window-weighted (−33.6…−11.5, ±71%) | 8d | **The first measured FC-135 rate in this project** — the ~20ppm row in [Clock source per board](#clock-source-per-board) had never been anything but a spec quote. Clock runs **slow**, where all three crystal-less rigs ran fast. The ±71% is almost entirely whole-second quantization on short windows (±11.2ppm on the 1d sample), not instability. All three records are usable: the discard-the-first rule applies to a restored `resync_interval_s`, and this board was `erase_flash`'d immediately before its soak flash. [Below](#fc-135-first-harvest-2026-08-23--three-boards-and-the-first-crystal-numbers). |
| 2026-08-12 .. 2026-08-19 | **thermometer-c6 rev A board 4**, same panel/sensor/pack/env, `753afbc` (2026-08-12), co-located with board 2 at ~10cm | 1.04d, 2.02d, 4.00d (7.06d observed) | −1s, 0s, −3s (−4s total) | **−6.6ppm** window-weighted (−11.2…0.0) | 8d | **The control half of the pair, and it is 13.1±4.0ppm (3.3σ) away from board 2** — same room, same air, same firmware, same windows, so that gap is part-to-part crystal spread and nothing else. Both boards sit inside the FC-135's ~20ppm spec in magnitude and both run slow. This is the falsifiability the design note argued for: board 4 alone reads "comfortably inside spec", board 2 alone reads "right at it". [Below](#fc-135-first-harvest-2026-08-23--three-boards-and-the-first-crystal-numbers). |
| 2026-08-01 .. 2026-08-15 | **thermometer-c6 rev A board 1** + BMP581 + GDEM0154I61 (200x200), `711c3a4` (2026-07-31), `thermometer_c6_release`, rig `revA-smallscreen`, 400mAh pack, FC-135 | 1.00d, 2.01d, 4.03d, **8.01d** (15.04d observed) | −3s, −1s, −2s, −5s (−11s total) | **−8.5ppm** window-weighted, ±1.5 | 16d | **The longest and tightest FC-135 run** — four samples over 23 days of soak, and the 8d window alone carries only ±1.4ppm of quantization, the tightest single drift sample this project has taken. Agrees with board 4 to **0.6σ** while board 2 sits 3.5σ away, so the fleet reads as two boards at ~−7ppm and one at ~−19.7ppm. Different panel, different room, never through the BOD campaign. [Below](#fc-135-first-harvest-2026-08-23--three-boards-and-the-first-crystal-numbers). |
| 2026-08-05 .. 2026-08-23 | XIAO ESP32-C6 + BMP581 + DESPI-C02 + GDEH0576T81, `f5e1749`, `seeed_xiao_esp32c6_release`, **phase-2 arm 5** (vanilla control, resync pinned to 12h), 400mAh pack | 12h × 32 resyncs (17.85d observed; 3 windows carry a failed attempt) | +14s .. +112s (+1354s total) | **+878ppm** window-weighted (+324…+1721, **±96%**) | 12h (pinned) | **The control arm answers phase 2's primary question on its own.** Over a **12× range of wakes/day (31–364)** and 9.4°C of ambient, the per-sample rate correlates with **nothing**: wakes r=+0.026, refreshes r=+0.013, ambient r=−0.058, intra-hour spread r=+0.044. Phase 1's `r=−0.900` duty-cycle relation does not reproduce at n=32 over a wider range. The one covariate that does correlate is **elapsed time** (r=+0.487, Spearman +0.401), i.e. the rate wanders on a timescale no per-window average captures. [Below](#arm-5-harvested-2026-08-23--the-vanilla-control-kills-the-duty-cycle-reading). |
| 2026-08-05 .. 2026-08-23 | FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `1ea3cd7`, `dfrobot_firebeetle2_esp32e_release`, **phase-2 arm 1** (pinned: 1440 wakes/day, repaint every 60th, resync 12h), on battery | 12h × 35 resyncs (18.01d observed) | +445s .. +219s (+7975s total) | **+5124.6ppm** window-weighted (+5041…+5229, **±2.0%**) | 12h (pinned) | **The duty-cycle model's headstone.** Phase 1 fitted `ppm ≈ 5339 − 1.342 × wakes/day` and predicted **+3385ppm** at this arm's 1453 wakes/day. Measured +5124.6, a **1740ppm miss**, while the rate moved only **+1.1%** from phase 1's +5066ppm across a 7× increase in wake rate. Dispersion did tighten, ±4.5% → ±2.0%. The same image still holds phase 1's ten `arm`=0 records and they re-decode to **+5066.3ppm, ±4.5%** — the published figure to the digit, 18 days and one reflash later. [Below](#arm-1-harvested-2026-08-23--the-pre-registered-test-and-what-it-actually-found). |
| 2026-08-08 .. 2026-08-23 | XIAO ESP32-C6 + BMP581 + Seeed ePaper hat (GDEW029I6FD), `2fa3750`, `seeed_xiao_esp32c6_epaper_release`, **phase-2 arm 3** (vanilla, resync pinned to 12h), 400mAh pack | 12h × 16 resyncs (14.41d observed, **12 failed attempts** stretching windows to 24–49h) | +1s .. +158s | **+607ppm** window-weighted (+23…+1184, **±96%**) | 12h (pinned) | Doubled from phase 1's **+305ppm** (n=3, ±63%) on the same board, though neither figure is tight enough to call that a change. Its three pre-experiment `arm`=0 records re-decode to **+304.5ppm** against a published +305 — the second published figure this session round-trips out of an archive. Covariate structure matches arm 1's (ambient +0.577, spread −0.558, wakes −0.550) and **collapses the same way under partial correlation**. **43% of resync attempts failed**, against `resync_fail_count == 0` at the day-4 gate check. [Below](#arm-3-harvested-2026-08-23--the-covariate-signature-repeats-and-still-collapses). |

Rate = drift / window, in ppm. Sign convention matches the badge: negative =
device clock behind real time.

### FC-135 first harvest, 2026-08-23 — three boards, and the first crystal numbers

Boards 2 and 4 came off soak at day 11.6 and were read out; **board 3 is at
another location and was not reachable**, so the room arm contributes nothing
here and everything in its t=0 record above remains unmeasured. Both images are
full-partition and restorable: `local/archives/hist-revA-board{2,4}-20260823.bin`.

**Panel readings taken before any cable touched either board.** Pack voltage is
journaled nowhere — `include/HistoryStore.h` has no battery field — and USB runs
the MCP73831 into the cell, so a photo not taken first is a datapoint destroyed.

| | board 2 | board 4 |
|---|---|---|
| footer | `#498 r347 lp16737 11d14h w:ULP mx4.0V 11cd8dd Aug12'26 s4d` | `#504 r341 lp16747 11d15h w:ULP mx4.0V 753afbc Aug12'26 s4d` |
| pack | 3998 → **3964mV**, −2.93mV/day | 3996 → **3962mV**, −2.92mV/day |
| ambient at read | 23.0°C | 22.9°C |
| wakes/day, refreshes/day | 43.0, 30.0 | 43.4, 29.3 |
| badges | none | none |

No `! DRIFT` on either, as the arithmetic predicted: at ~20ppm the badge's 60s
threshold needs ~50 days. `s4d` on both is the doubling interval working —
successes at ~d1, d3, d7, next due ~d15. **`lp/day` is again the clean number**:
1444.9 and 1440.6 here, 1442.3 on board 1, agreeing to 0.3% across three boards.

**The rates.** Three drift records each, identical window structure.

| window | board 2 | board 4 | ±quantization |
|---|---|---|---|
| ~1.03d | −3s → **−33.6ppm** | −1s → **−11.2ppm** | ±11.2ppm |
| ~2.01d | −5s → **−28.9ppm** | 0s → **0.0ppm** | ±5.8ppm |
| ~4.02d | −4s → **−11.5ppm** | −3s → **−8.7ppm** | ±2.9ppm |
| **window-weighted** | **−19.7ppm** | **−6.6ppm** | ±2.8ppm on each mean |

Drift is read off a whole-second clock, so every sample carries ±1s of pure
rounding — 11.2ppm over a day, 2.9ppm over four. That is what the wide per-sample
spread is, and it is why the *means* are the numbers to quote: three samples of
±1s combine to ±2.8ppm on each board's total.

**The part-to-part gap is real.** −13.1 ± 4.0ppm is 3.3σ, and the two boards sat
~10cm apart running the same binary over the same windows, so room, firmware and
schedule are all excluded by construction. Both land inside the FC-135's ~20ppm
spec in magnitude, and **both run slow** — the opposite sign to every crystal-less
rig measured here (+5066 / +305 / +1259ppm), which is what changing the clock
source is supposed to do.

**A single arm would have been unfalsifiable, exactly as the design note said.**
Board 4 on its own reads "6.6ppm, comfortably inside spec"; board 2 on its own
reads "19.7ppm, right at it". Neither reading is wrong and neither is checkable
without the other.

**The duty-cycle slope does not survive the control.** Board 2's three samples
fall in |ppm| as their window's wake rate falls (77 → 30 → 29/day), the same sign
as phase 1's FireBeetle fit. Board 4's windows carry that same wake-rate
structure and its rates go −11.2, 0.0, −8.7 — no trend at all. With a co-located
control on the same windows showing nothing, board 2's apparent slope is noise,
and the confound is visible in the table above: the short window is both the
noisiest estimate and the highest-wake one. This is the cheapest kill of a
duty-cycle reading this project has managed, and it cost no extra hardware.

**BMP581 part-to-part, in situ.** The pairing's free result, from the same two
journals: 279 overlapping hourly rows over 2026-08-11 22:00Z .. 2026-08-23 12:00Z,
mean ambient 26.9°C across a 20.3–30.1°C range.

- board 2 − board 4 hourly average: **mean +0.003°C, median 0.000, sd 0.055°C**
- **278 of 279 hours agree within ±0.1°C**; the histogram is 13.3% at −0.1,
  70.6% at 0.0, 15.8% at +0.1, and a single hour at +0.2
- Hourly temperatures are stored as `int16` ×10, so **0.1°C is the storage
  resolution**: this bounds agreement at ≤0.1°C and cannot resolve finer. What it
  does establish is that the systematic offset between two calibrated parts in
  the same air is far below that.
- Mean intra-hour spread 0.08°C on both, so the volatility covariate is live.

**One correction to the t=0 record.** Board 4's archive was created 2026-08-11
22:24:26Z and its first drift window opens ~22:29Z, against board 2's ~22:47Z —
so the pair started **~20 minutes apart, not the day** the "2026-08-12" date in
the table above suggests. That date is local time. Board 3 does start roughly a
day later; the pair does not.

**One provenance note.** Both packs were plugged in for a few minutes of the USB
session before being pulled, so each took ≲5mAh of charge — about 1% of a 400mAh
cell. The "as ordered, never charged" description of packs 2 and 4 holds for the
soak it describes, but no longer describes the cells as they sit now.

#### Board 1 joins, and it puts board 2 in the minority

Harvested the same session at day 23.0. Its firmware predates the `last snapshot
written by` field, so the header omits it — the elastic-forwards
`HistoryDriftState` working as designed, not a fault.

| window | drift | ppm | ±quant | wakes/day | ambient |
|---|---|---|---|---|---|
| 1.00d | −3s | −34.7 | ±11.6 | 104.9 | 25.3°C |
| 2.01d | −1s | −5.8 | ±5.8 | 65.2 | 25.3°C |
| 4.03d | −2s | −5.7 | ±2.9 | 74.0 | 26.0°C |
| **8.01d** | −5s | **−7.2** | **±1.4** | 48.7 | 26.3°C |
| **window-weighted** | −11s / 15.04d | **−8.5** | ±1.5 | | |

| pair | gap | σ |
|---|---|---|
| board 1 − board 4 | −1.9 ± 3.2ppm | **0.6 — indistinguishable** |
| board 1 − board 2 | +11.2 ± 3.2ppm | 3.5 |
| board 2 − board 4 | −13.1 ± 4.0ppm | 3.3 |

**Two boards agree and board 2 is the outlier.** The t=0 record above says that if
2 and 4 diverge, "the first hypothesis should be a board the campaign quietly
damaged rather than ordinary spread". Board 1 is a third, independent arm —
different panel, different room, never through the BOD probe or the 3.0V sweep —
and it lands on board 4. That makes board 2 the odd one of three. **It does not
make it damaged**: a 13ppm spread across three parts is exactly what a crystal
sold on ~20ppm initial tolerance produces, so nothing here *requires* the damage
hypothesis, and nothing here excludes it either. Board 2's rate is stable across
its own three windows, which is not what a hurt oscillator usually looks like.

#### All three run slow, and that points at the board, not three unlucky parts

The three rates are −8.5, −19.7 and −6.6ppm — **every one negative**, mean
−11.6ppm. A symmetric ±20ppm initial tolerance should scatter the sign; 3 of 3
one way is a common-mode term on top of the scatter.

The mechanism the layout offers: rev A fits **2×20pF for a CL=12.5pF FC-135**
(`hardware/thermometer-c6/SCHEMATIC-VERIFICATION.md`), which budgets ~2.5pF of
stray. Two 20pF caps in series present 10pF, so the design lands on 12.5pF only
if stray really is 2.5pF. If it is nearer 5pF, the crystal sees CL≈15pF and is
pulled **slow**:

    Δf/f = (C1/2) × [1/(C0+CL_nom) − 1/(C0+CL_act)]
         = (2.5fF/2) × [1/13.7pF − 1/16.2pF] ≈ 14ppm slow

**That arithmetic uses typical tuning-fork motional values (C1≈2.5fF, C0≈1.2pF),
not the FC-135 datasheet's** — it is an order-of-magnitude argument for why the
sign is shared, not a measurement of these boards.

Two things follow, and both are now cheap because boards 1, 2 and 4 are off soak:

- **A bench test that settles the mechanism before any respin.** Add a few pF
  across one crystal leg on a retired board and re-measure the rate. If the
  fleet's shared offset is load-capacitance pulling, the rate moves further
  negative, by a slope the formula above predicts. Nothing else on the board
  responds to that stimulus that way.
- **A rev B candidate**: trim the load caps to re-centre the fleet. Filed
  alongside the D2 and crystal-variant candidates in `BRINGUP.md`.

#### The first record of every run is biased negative — discard it here too

Comparing each board's first (1d) sample against the rate its *remaining* windows
settle at:

| | measured | settled rate predicts | excess |
|---|---|---|---|
| board 1 | −3s | −0.57s | **−2.43s** |
| board 2 | −3s | −1.54s | **−1.46s** |
| board 4 | −1s | −0.52s | **−0.48s** |

**Same sign on 3 of 3**, and on board 1 the excess is well beyond the ±1s a
whole-second clock can explain. The mechanism is *not* the one the phase-2 arms
have: that one needs a `resync_interval_s` restored from the archive, and all
three of these boards were `erase_flash`'d immediately before their soak flash.
It is not the supply handover either, at least on board 1 — its first window
opens 2026-07-31 13:08:07Z, ~18 min after the ~12:50Z USB-out/pack-in swap, so no
unpowered gap sits inside it. Left open, with the candidates being a cold-path
first SNTP exchange (the anchor is the sync taken right after boot) and bench
handling during the first day.

Settled rates excluding the first sample — **the figures to quote from now on**:

| board 1 | board 2 | board 4 |
|---|---|---|
| **−6.6ppm** / 14.04d | **−17.3ppm** / 6.03d | **−5.8ppm** / 6.02d |

which tightens boards 1 and 4 to **0.8ppm apart**.

#### The adaptive interval confounds window length with wake rate

Worth stating because it invalidates a correlation this file has chased twice.
In all three runs the first window is simultaneously the **shortest** and the
**busiest** — 105, 77 and 77 wakes/day against 30–74 in the later windows — because
the interval starts at the 1d floor and doubles, while the first days after a
flash are the ones with bench handling and a settling room in them.

So in a doubling-interval run, "ppm falls as wakes/day falls" is confounded by
construction, *and* the busiest window is also the noisiest one. Board 1 shows the
apparent slope (104.9 wakes/day → −34.7ppm, 48.7 → −7.2ppm) as clearly as board 2
does, and board 4 refuses to reproduce it. **The phase-2 arms pin the interval at
12h precisely to break this**, which is now an argument from data rather than
from design intent.

#### Board 1's discharge, and why it is not comparable to the pair's

4086mV at day 23.0 against a start the 2026-07-31 soak row records only as "fully
charged" — **no first-render mV was ever logged**, so the ~4200mV start is assumed
and the resulting ~−4.9mV/day is bounded, not measured. It also sits on a
different part of the LiPo curve from the pair's −2.9mV/day: board 1 began at the
steep top, boards 2 and 4 at ~4.00V on the plateau. Its panel drives 200x200
pixels against the pair's 920x680, and it wakes 60.6 times a day against their
43. Four differences at once — quote the rates, never the comparison.

### Arm 5, harvested 2026-08-23 — the vanilla control kills the duty-cycle reading

Arm 5 ran untouched from 2026-08-05 to 2026-08-23 with only the resync interval
pinned at 12h, and it is the arm nobody expected to carry the headline. **32 drift
records, 17.85d of observed window, 435 hourly rows.** Image
`local/archives/hist-arm5-xiao-t81-20260823.bin`; `arm` = 5 on every record.

Panel before the park: `! EXP 5 60s`, footer
`#1763 r1596 lp26499 18d2h w:ULP mx4.3V f5e1749 Aug5'26 s6h`, 23.5°C. Against the
day-4 gate check that is 97.5 wakes/day lifetime versus 174 then — **74.9/day
across days 4–18**, with the refresh/wake ratio falling 0.986 → 0.905. The room
quietened by more than half, which is exactly the volatility swing the pinned arms
were built to remove and this one was built to keep.

**Rate: +877.9ppm window-weighted, ±3.7ppm of quantization.** Per-sample spread
+324…+1721ppm — 96% widest deviation, against a per-sample quantization of only
±11…23ppm at these window lengths. **The scatter is real, 15–70× the rounding.**

**Every mechanistic covariate reads zero.**

| covariate | range across the 32 windows | r vs ppm |
|---|---|---|
| wakes/day | **31 … 364** (a 12× range) | **+0.026** |
| refreshes/day | 4 … 364 | +0.013 |
| mean ambient | 20.7 … 30.1°C | −0.058 |
| intra-hour spread | 0.00 … 0.95°C | +0.044 |
| window length | 0.50 … 1.04d | +0.110 |

Phase 1 fitted `ppm ≈ 5339 − 1.342 × wakes/day` on the FireBeetle at r=−0.900 from
**ten** samples over 84–332 wakes/day. This is thirty-two samples over a wider
range on a C6, and the relation is not merely weaker — it is absent. Together with
arm 1's level miss at day 4 and board 4's refusal to reproduce board 2's apparent
slope, **the duty-cycle reading is dead three independent ways**, and the arm that
killed it needed no manipulation at all.

**What does correlate is elapsed time**, and it is the only thing that does:

| | Pearson | Spearman |
|---|---|---|
| all 32 samples | **+0.487** | +0.401 |
| dropping the 3 windows containing a failed attempt | +0.498 | +0.400 |

The 5% critical |r| at n=32 is ~0.349 and the 1% ~0.449, so this survives at 1%
on Pearson and 5% on Spearman, and it does not depend on the failed-attempt
windows. Least-squares slope **+28.7ppm/day**; the first half of the run averages
**+742ppm** and the second **+1005ppm**.

**The mechanism is not identifiable from this archive, and the reason is worth
recording**: the obvious monotone candidate over 18 days is the pack draining, and
**supply voltage is journaled nowhere**. This rig cannot even see its own battery
— `read_battery_level()` returns a literal 4321 on a stock XIAO — but no board can
settle it either, because `HistoryDriftSample` carries ambient and counters and no
mV. Ambient is not the driver (r=−0.058, and it was not monotone over the run:
25.6 → 30 → 23°C). Die temperature during sleep, which is not ambient over the
window, is the other candidate and is equally unjournaled.

Adding mV per drift record would settle it and is **not** free: the record's one
spare byte now carries `EXPERIMENT_ARM`, so it needs an `HS_FORMAT` bump, which
leaves every deployed archive inert until it is backed up and erased. Filed as an
open question rather than a proposal.

**For the compensation decision this is decisive.** The rules in [Decision rules
once ~6 samples exist](#decision-rules-once-6-samples-exist) put ±M% > ~10% at
"compensation is futile — drop it and spend the effort on the resync failure path
instead". Arm 5 reads **±96%** with no correlate to model against and a rate that
moves +28.7ppm/day. A constant-ppm correction fitted on this run's first half
would be ~260ppm wrong by its second.

### Arm 1, harvested 2026-08-23 — the pre-registered test, and what it actually found

Panel before the cable: `! EXP 1 60s`, `! DRIFT +221s/12h +5085ppm n6 ±0%`,
`1ea3cd7`, 4029mV, footer `#26274 r453 lp0 18d2h w:ULP mx4.2V`. **Both gates still
pass at day 18** — 1452.9 wakes/day against a 1440 target, 25.05 refreshes/day
against 25, and `#÷r = 58.00` against the 57.6 the two overrides imply.

Image `local/archives/hist-arm1-firebeetle-20260823.bin`: **691 hourly, 320
sparkline, 45 drift**, spanning 2026-07-25 19:00Z .. 2026-08-23 13:00Z — nearly a
month, and **one reflash**. `formatted by 44ba5ba` with `last snapshot written by
1ea3cd7`, which is the pair of stamps doing exactly what they were added for.

#### The archive round-trips a published result

The 45 records split **10 at `arm`=0 and 35 at `arm`=1**, and the phase-1 subset
re-decodes to **+5066.3ppm over 10.11d, range +4840…+5248, ±4.5%**. The
[2026-08-05 harvest](#harvest-2026-08-05-the-runs-ten-samples) published +5066ppm
(+4839…+5247, ±4.5%) from a different image taken 18 days and one reflash earlier.
**The per-record arm byte, the no-erase reflash and the decoder all round-trip a
published figure to the digit** — the strongest evidence to date that the archive
is a durable record rather than a convenience.

The first `arm`=1 record is the contaminated one the design predicted: a **24.0h
window against a 12h setting**, and `d_boot = −658` — the boot counter running
backwards across the RTC wipe, which is the reflash's fingerprint. Dropping it
moves the mean by 1.4ppm (+5124.6 → +5123.2), so the contamination is real in
mechanism and immaterial in size here. Everything below drops it anyway.

#### The prediction, and the answer

Recorded before the data existed: *"arm 1's residual ±1% (~±51ppm) should
correlate with the window's volatility covariate now that wakes/day is flat...
If the residual correlates with nothing, neither mechanism survives and it is
oscillator noise."*

The residual sd is **46.5ppm** — the ±51ppm guess was good. The raw correlations
look like a hit:

| covariate | range over 34 windows | raw r | **partial r** |
|---|---|---|---|
| intra-hour spread | 0.03 … 0.81°C | −0.443 | **−0.045** (controlling ambient) |
| mean ambient | 21.4 … 29.7°C | +0.476 | **+0.200** (controlling spread) |
| wakes/day | 1433.3 … 1456.2 (±0.8%) | −0.476 | **−0.005** (controlling ambient) |
| refreshes/day | 23.97 … 26.00 | +0.081 | — |
| elapsed days | 0 … 16.4 | −0.079 | — |

**The volatility reading is refuted.** Its raw −0.443 collapses to −0.045 once
ambient is held: the covariates are near-perfectly collinear, and ambient is the
one carrying whatever signal exists. Ambient's own partial is +0.200, which at
n=34 (5% critical |r| ≈ 0.34) is **not significant**. So the pre-registered fork
lands closer to "correlates with nothing" than to the volatility hypothesis, on a
residual that is only 0.9% of the rate.

#### Pinning the cadence turned `d_boot` into a thermometer

The finding nobody asked for, out of the cross-correlation matrix:

| | ppm | spread | ambient | wakes/day |
|---|---|---|---|---|
| **ppm** | +1.000 | −0.443 | +0.476 | −0.476 |
| **spread** | −0.443 | +1.000 | −0.893 | +0.887 |
| **ambient** | +0.476 | −0.893 | +1.000 | **−0.999** |
| **wakes/day** | −0.476 | +0.887 | −0.999 | +1.000 |

**Ambient and wakes/day correlate at −0.999.** On a vanilla rig `d_boot` measures
room volatility, which is why the phase-1 analysis could never separate duty cycle
from temperature. `ULP_ALWAYS_WAKE` makes the cadence timer-driven, and the timer
is the RTC slow clock — so on a *pinned* rig the same counter becomes **a direct
readout of that oscillator's temperature dependence**, free, in every archive.
That is a new instrument the pinning created as a side effect, and it is far more
sensitive than the drift measurement: it resolves 21.4–29.7°C at r=0.999 from a
counter that costs nothing.

#### The two readouts disagree about the sign, and that is the sharpest open question here

The wake counter and the NTP drift are two independent measurements of one
oscillator, and over the same 34 windows they say opposite things:

- **wakes/day falls as the room warms** (r=−0.999). Fewer 60s sleeps completed per
  window means each sleep took longer in real time, i.e. **the RC slow clock slows
  down when warm** — textbook for this oscillator.
- **measured drift rises as the room warms** (r=+0.476). A clock that ran slower
  should fall further *behind*, not further ahead.

Both cannot describe the same path. The obvious suspect is the **awake-vs-asleep
asymmetry** this file already flags under [Why the clock is
slow](#why-the-clock-is-slow-mechanism): the wake counter samples only the sleep
path, while the resync measures the whole duty cycle including awake time, and if
the awake-path error carries the opposite tempco and is large enough, the two
diverge exactly like this. **Not established** — ambient explains only 23% of the
drift residual's variance, so the +0.476 leg is the weak one, and n=34 over 8°C
cannot carry much more than the direction.

The cheap discriminator, recorded before anyone tries it: arm 2 runs the same
pinned wake cadence with **12× the refresh count**, so it multiplies awake time
while holding the sleep path fixed. If the awake path carries the opposite tempco,
arm 2's `ppm`-vs-ambient slope should move measurably against arm 1's while its
`d_boot`-vs-ambient stays at −0.999. That is a question the crossover was not
designed to ask and can now answer for free.

### Arm 3, harvested 2026-08-23 — the covariate signature repeats, and still collapses

Panel before the park: `! EXP 3 60s`, footer
`#1808 r1621 lp26405 18d3h w:ULP mx4.3V 2fa3750`. The 296x128 panel drops the `s`
token off its edge, so resync health is not readable here — which matters more
than it did at day 4, see below.

| | day 4 | day 18 (lifetime) | days 4–18 alone |
|---|---|---|---|
| wakes/day | 135.1 | 99.8 | **89.2** |
| refreshes/day | 132.0 | 89.4 | **76.7** |
| `#÷r` | 1.024 | 1.115 | |
| lp/day | 1462.1 | 1456.8 | |

**The room quietened by a third**, independently confirmed by arm 5 over the same
calendar days (135 → 89 here, 174 → 75 there). Two vanilla rigs agreeing on the
environment is the covariate the pinned arms exist to remove, and it is large.

Image `local/archives/hist-arm3-xiao-hat-20260823.bin`: **667 hourly, 320
sparkline, 20 drift**, span 2026-07-26 19:00Z .. 2026-08-23 13:00Z. Header reads
`formatted by 8712f72 (!! unknown to this repo)` — the orphaned pre-squash commit
this file already documents, with `last snapshot written by 2fa3750` alongside it,
which is exactly the pair of stamps that fossil motivated.

#### A second published figure round-trips

The 20 records split **3 at `arm`=0 and 17 at `arm`=3**, and the pre-experiment
subset re-decodes to **+304.5ppm over 6.76d, ±63%** against the
[2026-08-05 harvest](#c6-epaper-hat-harvested-2026-08-05)'s +305ppm (+113…+400,
±63%). With arm 1's +5066.3 against +5066, that is two independently published
results reproduced out of re-read archives, on two different rigs.

**The straddled first record is textbook here**, and unlike the rev A boards the
documented mechanism is the one that fired: this archive was deliberately *not*
erased at the arm-3 flash, so `drift_state_load()` restored the pre-flash
`resync_interval_s` of 3.47d and the first attempt scheduled off the old cadence —
a **3.49d window against a 12h setting**, carrying `d_boot = −893` from the RTC
wipe. Dropped from everything below.

#### The rate, and the failures

**+607.2ppm window-weighted over 14.41d, n=16, ±96%.** Phase 1 put this board at
+305ppm from three samples at ±63%; the level has doubled, but neither figure is
tight enough to call that a change rather than a resampling.

**12 failed attempts across 16 successes.** Every failure stretches the next
window by a whole interval, which is why windows run 24h, 36h, 37h and 49h against
a 12h setting — the failures are readable straight out of the window lengths
without any separate counter. At day 4 this arm was recorded as
`resync_fail_count == 0` and "its resync is healthy". Over the full run it is a
**43% failure rate**, which is the single worst WiFi record in the fleet and was
invisible on a panel too small to show the `s` token.

#### The signature repeats on a different oscillator, and dies the same way

| | arm 3 (C6 hat, vanilla, n=16) | arm 1 (E, pinned, n=34) |
|---|---|---|
| raw r(ppm, ambient) | **+0.577** | **+0.476** |
| raw r(ppm, intra-hour spread) | **−0.558** | **−0.443** |
| raw r(ppm, wakes/day) | −0.550 | −0.476 |
| partial r(ppm, spread \| ambient) | **−0.229** | **−0.045** |
| partial r(ppm, ambient \| spread) | +0.287 | +0.200 |
| partial r(ppm, wakes \| ambient) | −0.290 | −0.005 |

Two rigs 8× apart in rate — an ESP32-E at +5100ppm and a C6 at +600ppm — produce
the **same raw covariate signature and the same collapse**: hold ambient, and the
volatility term loses most or all of its signal, while ambient's own partial stays
weak and positive and never reaches significance at either n (5% critical |r| is
~0.51 at n=16 and ~0.34 at n=34).

**And arm 5 shows neither**: ambient −0.058, spread +0.044 across 32 samples and a
12× range of wakes/day, with elapsed time (+0.487) the only thing that correlates
at all. So of the three arms, two hint weakly at ambient with matching signs and
the third rules it out while pointing somewhere else entirely.

**The conclusion phase 2 was built to reach, reached:** no mechanism survives on
any arm. Duty cycle is dead three ways over. Volatility is an artefact of its
correlation with ambient. Ambient itself never clears significance and one arm
contradicts it outright. What is left is an oscillator whose rate wanders on a
timescale none of the per-window covariates capture — which is what arm 5's time
correlation is measuring, and what no compensation model in
[Compensation](#compensation-analysis-and-decision-2026-07-25) can correct for.

### Photo-transcribed run: C6 + DESPI-C02, 2026-07-29 .. 2026-08-04

XIAO ESP32-C6 + BMP581 + DESPI-C02 + GDEH0576T81, `44e56b6` (2026-07-06),
`seeed_xiao_esp32c6_release`, 400mAh pack, booted ~2026-07-06 22:40 (uptime
28d18h at the last reading, consistent with the `Jul6'26` build stamp in the
footer). Every column below is read off a photograph of the panel — no serial,
no archive, and **no way to re-read any of it**, because the build predates the
flash partition. Transcription errors are possible and unfalsifiable here.

Capture times are EXIF `DateTimeOriginal` (+02:00, phone on network time) from
the source frames, which is a different clock from the one being measured and
therefore the useful one:

| Captured (EXIF) | Source | Panel time | Frame age | Drift | ppm | `#boot` | `r` | `lp` | Uptime | `s` age | 24h chart range (eyeballed) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-29 12:19:56 | `DSC_5977` | 11:14 | ~67 min | +115s/1d | +1331 | 1572 | 1341 | 32652 | 22d13h | 12h | 23.7–26.3 °C |
| 2026-07-30 06:34:40 | `DSC_5987` | 06:34 | ~0–1 min | +102s/1d | +1181 | 1640 | 1399 | 33820 | 23d8h  | 7h  | 24.8–27.3 °C |
| 2026-07-31 13:07:48 | `DSC_6021` | 13:05 | ~4 min | +96s/1d  | +1111 | 1993 | 1749 | 35669 | 24d15h | 14h | 21.0–26.5 °C |
| 2026-08-02 14:25:02 | `DSC_6092` | 13:59 | ~27 min | +116s/1d | +1343 | 2334 | 2085 | 38638 | 26d16h | 14h | 21.5–25.1 °C |
| 2026-08-04 17:04:20 | `DSC_6108` | 16:42 | ~24 min | +115s/1d | +1331 | 2451 | 2188 | 41704 | 28d18h | 16h | 24.5–27.0 °C |

**Frame age is derived, not read**: `staleness = drift_at_render − (panel −
real)`, with `drift_at_render` prorated from the badge by the `s` age (a sample
7h into a 1-day window has accrued ~7/24 of it). All five land in 0–67 min,
i.e. under the hourly safety-net refresh, with one sitting right at that bound —
an independent confirmation the safety net is the thing setting the ceiling.

What the EXIF check can and cannot settle. `panel − real = drift − staleness`,
and staleness is unsigned and up to an hour, so a photograph **bounds drift from
below and nothing more** — it confirms sign and order of magnitude, never the
badge's value. Here it does confirm both, on all five. It also settles the
timezone question outright: on 2026-07-30 the panel read `06:34` against an EXIF
`06:34:40`, so the device is on the same local time as the phone and the whole
run is not a `MY_TZ` artefact.

**The `/1d` is the interval setting, not a measured window** — this build is on
the wrong side of the 2026-07-25 change described under [Reading a
datapoint](#reading-a-datapoint). It is nevertheless the true window here, and
the `s` column is what proves it: every reading is 7–16h old, so no attempt in
the run failed, and a succeeding daily resync makes setting and window the same
number. The ages are also self-consistent with a cadence anchored near 23:00–00:40
local, which is what a 1-day interval re-armed at each success produces.

The interval is pinned rather than adaptive: at +1331ppm the rule targets
60s of drift, i.e. a 12.5h interval, which clamps back up to the 1-day floor.

What the five points say, and don't:

- **Dispersion is ±12%** by the badge's own metric (widest deviation from the
  window-weighted mean). That lands just the wrong side of the ±10% line in
  [Decision rules](#decision-rules-once-6-samples-exist) — at the 1-day resync
  floor, a constant-ppm correction of +1259ppm would leave ~±150ppm ≈ 13s/day of
  residual, against 60s of allowed error. So it would *work*, but only barely,
  and only because this oscillator is 4× better than the FireBeetle's.
- **No temperature signal, and none was recoverable.** The five 24h ranges span
  21–27.3 °C with no monotone relation to rate (the highest and lowest rates sit
  at 23.3 °C and 23.7 °C mean). But the chart window is offset from the drift
  window by the sync age, the ranges are eyeballed off photos, and 5 points over
  ~3 °C of mean ambient cannot resolve a tempco anyway. Not evidence of absence.
- **`lp` is the clean number in the table.** It advances 1450–1457 per day across
  all four gaps (1168/19.3h, 1849/30.5h, 2969/48.9h, 3066/50.7h) — a far tighter
  figure than boots or refreshes, which swing 55–278/day on how volatile the room
  was. That is the ULP tick, and it is the one counter here that is not
  delta-triggered.

### Collection run started 2026-07-25

FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90, `44ba5ba`,
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

#### Screen readings taken before the harvest (2026-08-05)

Photographs, recorded before either archive was read. The FireBeetle's archive
has since been harvested and it reproduces both badges **exactly** (see below),
so these stand as a validated cross-check rather than a superseded guess.
EXIF `DateTimeOriginal` (+02:00) again; frame age is bounded rather than derived,
because the 200x200 panel drops the `s` token so drift-at-render is unknown
within its window.

| Captured (EXIF) | Source | Rig | Panel | Frame age | Status line | Footer | Batt |
|---|---|---|---|---|---|---|---|
| 2026-08-02 14:25:28 | `DSC_6093` | FireBeetle, `44ba5ba` | 14:09 | 17–24 min | `! DRIFT +421s/1d` `+5063ppm n6 +-4%` | `#1820 r1295 lp0 7d16h w:ULP mx4.2V 44b` | 4052mV |
| 2026-08-05 11:35:29 | `DSC_6111` | FireBeetle, `44ba5ba` | 11:30 | 6–13 min | `! DRIFT +450s/1d` `+5037ppm n6 +-4%` | `#2335 r1634 lp0 10d13h w:ULP mx4.2V 44b` | 4020mV |
| 2026-08-05 11:35:01 | `DSC_6110` | C6 + Seeed ePaper hat, `431b7b0` | 11:17 | ~18 min | *no badge* | `#1846 r1797 lp13938 9d13h w:ULP mx4.3V 431b7b0 Jul26'26 s…` | `4.32V` (stub) |

The FireBeetle's mV is a real ADC read; both C6 rigs print the hardcoded `4321`
that `read_battery_level()` returns on a stock XIAO, and `mx4.3V` is its
running maximum, so it is the same constant. Ignore both.

The FireBeetle panel reads *behind* real time in both frames (−16.5 and −5.5 min)
even though its clock runs fast. That is staleness, not a contradiction, and it
is the reason a photo cannot be used to check a drift figure — only to bound it.
The C6 hat's missing badge bounds it too: no `! DRIFT` and no `! NOSYNC` means
resyncs are landing and the last one measured under 60s, i.e. under 694ppm at
the 1-day floor. Its archive is unharvested.

#### Harvest 2026-08-05: the run's ten samples

`history.py backup --full` over the CH340 at 921600, 10d13h into the run. **Ten
drift records, not six** — the badge's ring is capped, the journal is not.

```
sync_time,drift_s,window_s,ppm,ambient_c,ambient_hours,boot_count,d_boot,refresh_count,d_refresh
2026-07-26 19:49:54Z,426.0,86696,4913,22.9,24,388,,297,
2026-07-27 19:50:16Z,453.0,86875,5214,24.3,24,506,118,373,76
2026-07-28 20:16:51Z,459.0,88454,5189,23.7,24,650,144,451,78
2026-07-29 20:26:11Z,447.0,87407,5114,25.5,24,757,107,506,55
2026-07-30 20:47:06Z,443.0,88098,5028,25.4,24,1033,276,724,218
2026-07-31 20:41:36Z,432.0,86502,4994,24.4,24,1318,285,924,200
2026-08-01 20:44:19Z,421.0,86984,4839,23.3,24,1650,332,1174,250
2026-08-02 20:47:48Z,434.0,87043,4986,23.9,24,1848,198,1302,128
2026-08-03 20:57:54Z,459.0,87465,5247,25.5,24,1932,84,1348,46
2026-08-04 21:11:56Z,450.0,87692,5131,26.2,24,2109,177,1465,117
```

**+5066 ppm** window-weighted (4424 s of drift over 873216 s = 10.11 d), spread
4839…5247, widest deviation **±4.5%**. Every figure below is computed from the
CSV above and nothing else — no serial log, no screen reading.

##### The 2026-07-25 row's sign is wrong, and its magnitude is right

Ten journaled samples put this oscillator solidly **fast**, 4839–5247 ppm, with
no sample within 4000 ppm of zero, let alone negative. The first row in the
table above reports −5265 ppm for the same board in the same room. Its
*magnitude* sits comfortably inside this run's own spread; only the sign
disagrees.

It is not a convention change: `last_drift_ms = (before_sync - after_sync) *
1000` has read that way since `346d27f` (2026-04-05), and `git log -S` on both
orderings finds one commit — the one that introduced it. So the candidates are
a transcription error off a clipped 200x200 status line, or a real reversal.

The duty-cycle model rules out the reversal arithmetically. At
`ppm ≈ 5339 − 1.342 × wakes/day`, reaching −5265 ppm needs ~7900 wakes/day —
one every 11 s, against a 60 s sleep interval. No duty cycle this firmware can
reach produces a negative rate, so the mechanism that explains everything else
in this run cannot explain that row's sign.

Conclusion: **read the 2026-07-25 row as +5265 ppm.** Left as-written above per
this file's append-only rule, flagged here instead. It also means the two
FireBeetle observations agree rather than contradict, and the "opposite in sign
to the FireBeetle" remark in the 2026-07-26 C6 row is wrong — all three rigs
run fast.

**The badge is exact.** Recomputing the window-weighted mean of the last six
samples as `DisplayRenderer.cpp` does gives 5063 ppm ±4% at the 2026-08-02 photo
and 5038 ppm ±4% at the 2026-08-05 one, against `+5063ppm n6 +-4%` and
`+5037ppm n6 +-4%` read off the panels (the 1 ppm is integer truncation). Panel
transcription is therefore trustworthy to the digit on this rig — which matters,
because the DESPI-C02 run above has no other source.

**All ten windows are one interval long** (86502–88454 s). A failed attempt
stretches the next window by a whole interval, so **10 of 10 resyncs succeeded**
over 10 days on battery. The 2-of-3 failure rate that opened the run did not
recur, and nothing here is a stretched-window artefact.

##### The rate tracks wake count — which on this firmware *is* room volatility

| Correlate | r (n=9) | p | Partial r, controlling for mean ambient |
|---|---|---|---|
| **wakes/day (`d_boot`)** | **−0.900** | **0.001** | **−0.881** |
| mean ambient °C | +0.457 | 0.22 | +0.275 |

More wakes, *lower* rate: `ppm ≈ 5339 − 1.342 × wakes/day`, spanning 5226 ppm on
the quietest day (84 wakes) down to 4894 ppm on the busiest (332).

**What this rules out** is the second decision rule: a tempco in *mean*
temperature, `R(T) = R0 + k(T−Tref)`. It does not survive controlling for wakes
(+0.457 → +0.275, p=0.22), and mean ambient is itself anti-correlated with wake
count (−0.385) — warm days were stable days — which is where its apparent signal
was borrowed from.

**What it does not rule in** is the duty-cycle model, and an earlier version of
this section wrongly said it did. Wakes are *delta-triggered*, so wakes/day is
not an independent variable — it is a measurement of how volatile the room was.
Recomputing the window's temperature statistics from the 254 hourly records in
the same archive:

| Volatility measure over the drift window | r with ppm | r with wakes/day |
|---|---|---|
| total variation of the hourly mean | −0.806 | **+0.926** |
| window swing (max−min) | −0.780 | **+0.861** |
| mean intra-hour spread | −0.867 | **+0.981** |

Wake count and room volatility are the same variable to within the resolution of
9 points. So the correlation admits at least two readings that this data cannot
separate:

1. **Duty cycle** — more wakes, more time at a calibrated frequency, per the
   awake-vs-asleep asymmetry in [Why the clock is slow](#why-the-clock-is-slow-mechanism).
2. **Thermal** — a rate that responds to temperature *movement* rather than
   temperature level, with the wake count merely reporting that movement.

Both predict the observed sign. Only a controlled run decides it: pin the wake
cadence so it stops tracking the room (delta-trigger off, fixed interval) and
see whether ppm still moves with volatility. Until then the honest statement is
**the rate tracks room volatility and/or wake count, and not mean temperature**.

`d_boot` and `d_refresh` correlate at **+0.993**, so they are one proxy, not two.
And none of them is an awake-duration: a Z90 refresh is a ~21 s busy window that
`epd_busy_light_sleep()` spends in *light sleep*, not awake (`docs/notes.md`), so
no ppm-per-second-awake figure can be derived here without inventing the
denominator.

##### What it means for compensation

| Model | Residual | Interval it supports | Attempts/year |
|---|---|---|---|
| none (today) | ±5066 ppm = 438 s/day | 1d floor, 7.3 min of error | 365 |
| constant +5066 ppm | ±227 ppm = **±19.6 s/day** | ~3d | ~120 |
| + per-wake term | ±87 ppm = ±7.5 s/day *(in-sample)* | ~8d | ~46 |

A constant correction now clears the 60 s bar with room to spare, which the
single first datapoint could not say — and it is the one row here that does not
depend on which mechanism is right, because it fits no covariate at all. Neither
model reaches the 28d cap, which needs ±0.47%.

The second-order term is the one to hold off on. It roughly halves the residual,
but that is a 2-parameter fit scored on the same 9 points it was fitted to, so
±7.5 s/day is a ceiling on how good it looks rather than a prediction — and
"per-wake" presumes the duty-cycle reading. If the effect is thermal instead,
the term should key off the hourly history the device already keeps, which is a
different correction with the same fit quality on this data. Build the constant
first; it is unconditional, and the pinned-cadence run decides the rest.

The prize is still the one the [analysis](#what-compensation-could-buy) names:
not display accuracy but WiFi wakes, 365/yr → ~120. Smaller than the 365 → 13
that section hoped for, because that assumed a stability this oscillator does
not have.

### C6 ePaper hat, harvested 2026-08-05

XIAO ESP32-C6 + BMP581 + Seeed ePaper driver board (GDEW029I6FD), running
`431b7b0`, `seeed_xiao_esp32c6_epaper_release`, on a 400mAh pack. Booted
2026-07-26 ~19:00Z. **Deployed in the middle of a wide open space at ~1.4 m,
windows open** — chosen for a less thermally stable spot than the FireBeetle's.
Caught by polling `/dev/serial/by-id` for the enumeration; a sleeping C6 is not
on the bus at all, and it took a manual BOOT+RST park after 229 s of waiting.

```
sync_time,drift_s,window_s,ppm,ambient_c,ambient_hours,boot_count,d_boot,refresh_count,d_refresh
2026-07-27 19:46:33Z,22.0,87338,251,24.4,24,88,,73,
2026-07-31 20:08:53Z,139.0,347079,400,24.7,96,821,733,787,714
2026-08-02 13:49:44Z,17.0,150068,113,23.2,41,1431,610,1395,608
```

**+305 ppm** window-weighted (178 s over 584485 s = 6.76 d of observed window),
range 113…400, widest deviation **±63%**. Roughly **17× smaller than the
FireBeetle in magnitude and 14× worse in relative stability.** Quantisation is
not the explanation: at ±1 s per sample the noise floor is 11.4/2.9/6.7 ppm
against rates of 251/400/113, so the spread is real. But n=3 — the dispersion
figure is itself barely constrained.

**Why only three records in 9d13h: the adaptive interval is working.** This is
the first end-to-end demonstration of it on hardware, and it reconstructs exactly:

| Sync | Interval setting | Window observed | Verdict | Next interval |
|---|---|---|---|---|
| 2026-07-27 19:46Z | 1.00d (cold-boot floor) | 1.011d | on schedule | 22s < 60s → **doubles to 2d** |
| 2026-07-31 20:08Z | 2.00d | **4.017d** | **one failed attempt** | 139s ≥ 60s → **targets 60s: 1.736d** |
| 2026-08-02 13:49Z | 1.74d | 1.737d | on schedule | 17s < 60s → doubles to 3.47d |

The third window matches the target computed from the second to **1 part in
1000** (150068 s observed against 150000 s targeted), which is also proof this
build derives `target` from `last_drift_window_s` rather than the interval
setting. Next attempt was due ~2026-08-06 01:00Z, after the harvest — so the
run ends cleanly on three.

**A failed resync is recoverable from the archive even though it is not
journaled.** Nothing is written when an attempt fails, but the attempt re-arms
`next_resync_time` by a whole interval, so the *next* successful record carries a
window that is an integer multiple of the setting. Here window 2 is 4.017d
against a 2d setting: exactly one miss, at ~2026-07-29 19:46Z, with the
`! NOSYNC x1` badge up for the two days until the 07-31 success. That matches
the operator's recollection of sync misses early in the run, and it is the only
place that event survives.

**No badge on the 2026-08-05 panel is consistent**: the last drift was 17 s,
under the 60 s threshold, and the miss had been cleared by two successes since.

##### What it does and doesn't say about the FireBeetle result

Three wake-rate/ppm pairs — 87→251, 182→400, 351→113 — are **not monotone**, so
the FireBeetle's clean r=−0.900 does not reproduce here. At n=3 that is an
anecdote rather than a refutation, and it is a different SoC and a different
part, so no shared slope was owed. It does mean the duty-cycle relation should
not be assumed general until the pinned-cadence run.

The open-air placement did **not** buy the better tempco test it should have.
Window-mean ambient spans only 23.2–24.7°C, *narrower* than the FireBeetle's
22.9–26.2°C, because these windows are 1–4 days long and averaging over 96 h
washes out exactly the volatility the placement was meant to add. A better clock
earns longer resync intervals, and longer intervals destroy the covariate needed
to explain it — worth knowing before designing the next run.

##### The header's build stamp is not the build that wrote the records

`history.py` prints `built 8712f72`, and that commit is **orphaned** — on no
branch, unreachable from master, with no equivalent message anywhere in the repo.
The reflog explains it: the sensor-identity work of 2026-07-26 evening was
developed as small commits (`57d33e4` → `5bf8129` → `8712f72`, 19:29–19:32 CEST)
and then squashed into `92da552` at 20:34, amended four times, landing as
`431b7b0` at 21:18. The device was flashed from that intermediate state, its
first boot formatted the store and stamped `8712f72` into the header sector —
which is written once and never rewritten (see the known cosmetic issue in
[history-store-validation.md](history-store-validation.md)). The base snapshot at
17:55:34Z is 23 min after that commit, which closes the timing.

**Confirmed on the device, not just inferred**: with the archive reading
`built 8712f72`, the panel was showing `431b7b0` at the same moment (operator
check, 2026-08-05, matching the `DSC_6110` footer). The two fields disagree
because they mean different things.

So: **the header stamp records the build that formatted the store, not the build
that wrote any given record.** Attribute data by the panel hash and the flash
log instead. Here every drift record postdates the `431b7b0` flash. The failure
mode this creates is worth naming — a header can point at a commit that `git
show` cannot resolve after a squash, which reads as a corrupt archive when it is
an accurate record of a build that no longer exists.

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

- **Is the rate stable?** **Answered 2026-08-05, yes** — ±4.5% over ten
  consecutive daily samples on the FireBeetle. Enough to compensate at the 1-day
  floor, not enough to reach the 28d cap. [Harvest](#harvest-2026-08-05-the-runs-ten-samples).
- **Temperature coefficient.** **Half answered 2026-08-05.** A tempco in
  temperature *level* is ruled out: r=+0.457 (p=0.22) against each window's mean
  ambient, collapsing to +0.275 once wakes/day is controlled for. A response to
  temperature *movement* is not ruled out — it is indistinguishable from wake
  count here (below). Caveat either way: this run spanned only 22.9–26.2°C of
  *window mean*, against the 21–32°C instantaneous swing that motivated the
  question, so anything outside that band is untested.
- **What does the rate track?** **Open, and now sharply posed.** ppm correlates
  with wakes/day at r=−0.900 (p=0.001, −0.881 controlling for ambient), but wakes
  are delta-triggered and correlate with the window's temperature volatility at
  +0.93…+0.98 — so the duty-cycle model of
  [Why the clock is slow](#why-the-clock-is-slow-mechanism) and a
  movement-sensitive thermal effect predict the same thing and cannot be told
  apart observationally. **Deciding it needs a run with the wake cadence pinned**
  so it stops tracking the room. Until then, no correction should assume which.
- **The loop can't converge at this rate.** +5066ppm needs a ~3.4h interval to
  keep drift under a minute, but `RESYNC_INTERVAL_MIN` is 1 day. So the device
  resyncs daily and still shows up to ~7.3min of error just before each sync,
  at the cost of a daily WiFi wake. Unchanged, and the reason compensation is
  now worth building.
- **Why did 2 of 3 resyncs fail?** (2026-07-25) Open, but **it did not recur**:
  10 of 10 attempts succeeded across the 2026-07-25 run, every window one
  interval long. So it is episodic rather than a standing property of this AP or
  this firmware, and the `! NOSYNC xN` badge is what will catch the next one.
  The serial log still distinguishes the causes (`WiFi failed` vs `sync
  failed`).

## Compensation: analysis and decision (2026-07-25)

Decision: **no compensation code**, and no extra RTC diagnostic fields, until
several daily samples exist. Recorded here so the reasoning isn't re-derived.

> **The precondition is now met** (2026-08-05): ten samples, ±4.5%, and a
> covariate identified. Everything below was written against a single datapoint
> and one of its inputs has changed — the ±10% futility threshold is cleared, so
> "compensation buys nothing at the 1-day floor" no longer holds. The decision
> itself has not been revisited; see the
> [harvest](#harvest-2026-08-05-the-runs-ten-samples) for what it would buy now.

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

## Phase 2: the pinned-cadence run (firmware landed 2026-08-05)

The harvest above cannot separate duty cycle from ambient movement, because
delta-triggered wakes make wakes/day a measurement of room volatility. Breaking
that coupling needs the cadence pinned, which the firmware could not do — the
delta thresholds and `DISPLAY_TEMP_DELTA` were plain `#define`s. They are now
`#ifndef`-guarded, and `REFRESH_EVERY_N_WAKES` adds a repaint term that keys off
the wake counter instead of the temperature.

The constraint that shaped the arms: **`update_hourly_history()` runs only on an
HP wake**, so hourly min/max/avg are built from wakes. Pinning a rig to the
hourly safety net alone would put one sample in each hour, collapse
`min == max == avg`, and destroy the intra-hour-spread covariate — the volatility
measure correlating most strongly (+0.981) with wake count. The primary endpoint
would have had nothing to test against, and it would have looked like a clean
null. At 1440 wakes/day there are 60 samples an hour and the covariates survive.
So the arms hold **wakes constant at 1440/day and vary only the refresh
cadence**, which is also the term the slope arithmetic points at: read as an
awake/asleep mixture, the fitted slope implies a per-event duration of 21.7 s
against a measured ~21 s Z90 refresh window and a 710 ms bare wake.

Two things make an arm self-identifying, because a bench rig that reads as a
field rig poisons every later observation:

- **`! EXP <id> <n>s` on the panel**, superseding `! DEBUG` rather than stacking
  with it. Ranked with the lab-build badge, so overflow cannot drop it.
- **an `arm` column in `dump --drift`**, from `EXPERIMENT_ARM` written into the
  drift record's one spare byte. Per-record rather than per-archive: a reflash
  between arms wipes RTC but not the journal, so one image spans several. No
  `HS_FORMAT` bump — a bump would leave every deployed archive inert until it
  was backed up and erased.

Also fixed here, because it misread the harvest above: `history.py` printed
`built <hash>` for a stamp written once at `store_format()` and never rewritten.
It now prints `formatted by`, flags a hash git cannot vouch for (the C6 hat's
resolved to an orphaned pre-squash commit while its panel showed `431b7b0`), and
reports `last snapshot written by <hash>` from a new field in the base snapshot.
That field is appended to `HistoryDriftState`, which is elastic — but only
forwards: older firmware refuses a longer stored payload and rebuilds from the
journal, which presents as `base (none — journal only)`, normally the signature
of a boot loop.

### Running arms (from 2026-08-05)

| Rig | Arm | Hash | Cadence | Ends |
|---|---|---|---|---|
| FireBeetle 2 E + BMP390L + GDEH0154Z90 | **1** | `1ea3cd7` | pinned: 1440 wakes/day, repaint every 60th (24/day) | harvest → arm 2, repaint every 5th (288/day) |
| XIAO C6 + Seeed hat (GDEW029I6FD) | **3** | `2fa3750` | vanilla, establishing a baseline correlation it never had | harvest → arm 4, pinned |
| XIAO C6 + DESPI-C02 + GDEH0576T81 | **5** | `f5e1749` | vanilla control, unchanged throughout | — |

**Crossed over 2026-08-23**, day 18 rather than the scheduled day 15. Now running:

| Rig | Arm | Hash | Cadence |
|---|---|---|---|
| FireBeetle 2 E | **2** | `ef27bd0` | pinned 1440 wakes/day, repaint every 5th (288/day) |
| XIAO C6 + Seeed hat | **4** | `cfcc35f` | pinned 1440 wakes/day, repaint every 60th (24/day) |
| XIAO C6 + DESPI-C02 + T81 | **5** | `f5e1749` | unchanged — harvested and RST'd, not reflashed |

Both crossover builds are on HEAD rather than their arms' original trees, so ~18
days of firmware change rides along with the cadence change. Named as a confound
in each arm's harvest section above.

#### Day-1 gates for arms 2 and 4

Off the panel, no reset.

| | arm 2 | arm 4 |
|---|---|---|
| status line | `! EXP 2 60s/RESYNC/REFRESH` | `! EXP 4 60s/RESYNC/REFRESH` |
| `#N` ÷ uptime-days | ≈1440 (expect 1449–1464: the E's own fast clock) | ≈1440 |
| `#N` ÷ `rN` | **≈5.0** (1440 ÷ 289) | **≈58** |
| `lpN` vs `#N` | `lp0`, structural on the FSM board | **≈1:1** |

**Arm 4's `lp ≈ #` is the one that matters.** It is the only field evidence that
the LP wake pin reached the binary, and the first flash of this arm silently did
not — see `.claude/rules/ulp.md`. Anything near 11:1 is the vanilla cadence.
Not readable until the first cadence repaint, ~1h after boot.

**The harvest and crossover are one session, scheduled 2026-08-20** — day 15 from
the flash, not the day 14 this section was drafted around. Harvesting costs a
reset and the in-progress window either way, so the two arms that change cadence
do it in the same session that reads them out. "Day 14" below means that session.

All three pinned to a 12 h resync (`RESYNC_INTERVAL_MIN=43200`) for ~2 samples/day.
The three hashes are docs-only apart; the firmware is identical (see
[history-store-validation.md](history-store-validation.md)).

**Discard the first record of every arm.** `drift_state_load()` restores
`resync_interval_s` from the archive and the clamp leaves a pre-flash 86400 s
untouched, so `next_resync_time = last_sync_time + resync_interval_s`
(`src/Thermometer.cpp`) schedules the first attempt off the *old* cadence. That
record's window therefore runs back to the last pre-flash sync and straddles the
regime change — while carrying the *new* arm byte. It is the one case where the
tag cannot separate the arms. Same at the day-14 crossover.

### Day-2 gates — check these before trusting fourteen days of it

Any one failing voids the phase; far cheaper to catch now than at harvest.

```
python3 tools/history.py dump <img> --drift    # gates 1 and 2
python3 tools/history.py dump <img> --csv      # gate 3
```

1. **`d_boot` ≈ 720 per 12 h window** on the FireBeetle, and **uncorrelated with
   that window's volatility**. If it still tracks the room, `ULP_ALWAYS_WAKE`
   did not take and the wake cadence is not pinned.
2. **`d_refresh` ≈ 12 per window** (arm 1; 144 in arm 2). If it tracks the room,
   `DISPLAY_TEMP_DELTA` did not take and the *manipulated variable* is still
   room-driven — the failure that would quietly invalidate the whole design.
3. **Hourly rows show `min_c` ≠ `max_c`.** This proves the 60-samples/hour
   density is real, and with it the intra-hour-spread covariate. An earlier
   draft of this experiment pinned the rig to 24 wakes/day, which would have put
   one sample in each hour, collapsed `min == max == avg`, and left the primary
   endpoint with no covariate to test against — presenting as a clean null.
   Note this follows *mechanically* from gate 1: 1440 wakes/day is 60 per hour,
   so if the footer ratio checks out this cannot be wrong. It is worth a look at
   the first real harvest, not worth a reset of its own.
4. **`arm` column reads 1 / 3 / 5**, not 0. Zero means the build ran without
   `EXPERIMENT_ARM` and the record cannot be attributed.

#### Gates 1, 2 and 4 are readable off the panel — no reset needed

The footer carries `#<boots> r<refreshes>` and the uptime, and the badge carries
the arm, so the expensive checks are the cheap ones:

| From | Arm 1 expects | Fails if |
|---|---|---|
| footer `#N` ÷ uptime-days | **≈1440/day** | much lower → `ULP_ALWAYS_WAKE` did not take |
| footer `rN` ÷ uptime-days | **≈24/day** (+1/day for the daily clear) | much higher → `DISPLAY_TEMP_DELTA` did not take |
| **`#N` ÷ `rN`** | **≈58** (1440 ÷ 25, the daily clear included) | anything else — this is the tell, and needs no arithmetic on elapsed time |
| status line | `! EXP 1 60s` | absent → the build carried no `EXPERIMENT_ARM`, so gate 4 fails too |

The ratio is the one to read: it is dimensionless, valid at any uptime, and both
overrides have to be working to produce it. A photograph of the panel a day in
settles the run's validity, and a harvest can then wait for day 14. Harvesting
costs a reset and the in-progress window, so fold any real read into a moment
you were going to disturb the rigs anyway, and expect to lose that sample.

On the two vanilla arms (3 and 5) there is nothing to check — their counters are
*supposed* to track the room. Their footer ratio is the baseline being measured:
the FireBeetle's own pre-experiment run sat near 0.7 refreshes per wake, against
the pinned 1-in-60 here.

#### Panel gate check, 2026-08-09 (day 4, not day 2)

Source: operator transcription of the three panels, no harvest, no reset. Uptime
is read to the hour, so every rate below is a range over the hour the footer
does not resolve — `4d3h` means uptime ∈ [4.125, 4.167) d.

| | Arm 1 (`1ea3cd7`) | Arm 3 (`2fa3750`) | Arm 5 (`f5e1749`) |
|---|---|---|---|
| footer | `#6039 r104 lp0 4d3h w:ULP mx4.2V` | `#563 r550 lp6092 4d4h w:ULP` | `#718 r708 lp6100 4d3h w:ULP` |
| wakes/day | **1449–1464** (target 1440) | 134–135 | 172–174 |
| mean wake interval | **59.0–59.6 s** (target 60) | 10.7 min | 8.3 min |
| refreshes/day | **25.0–25.2** (target 24+1) | 131–132 | 170–172 |
| `#` ÷ `r` | **58.07** (target 57.6) | 1.02 | 1.01 |
| LP samples/day | — (FSM, see below) | 1448–1462 | 1464–1479 |

**Arm 1 passes gates 1 and 2.** Both overrides took: the wake cadence is pinned
to the timer and no longer tracks the room, and the repaint count is one per 60
wakes plus the daily clear, which is what only `DISPLAY_TEMP_DELTA=999.0f` can
produce. The ratio lands at 58.07 against the 57.6 the two overrides imply — the
match is close enough that no third mechanism is needed to explain it.

The ~1.5% wake surplus over 1440/day is the E's own fast clock, not extra wakes:
its sleep timer is derived from the +5066 ppm oscillator measured in phase 1, so
a 60 s programmed sleep elapses in 59.7 s of real time, and the resync keeps
`now` — hence uptime — on real time. Predicted 59.7 s against 59.0–59.6 s read.

**`lp0` on arm 1 is structural, not a fault.** `lp_wake_count` is populated only
under `SOC_LP_CORE_SUPPORTED` (`src/Thermometer.cpp`), so the ULP FSM boards read
zero forever. The FireBeetle's sampling liveness has to come from `#N` instead.

**No `e<n>` or `u<n>` tokens on any of the three**, so zero LP errors across the
6092 + 6100 LP wakes the two C6 rigs logged, and no ULP reload.

**The vanilla controls refresh on ~98% of their wakes**, not the ~70% the
FireBeetle's pre-experiment run showed. That is the baseline arm 3 exists to
establish, so it is data rather than a fault, but it does put arm 5 at ~171
repaints/day. Multiplying that by the 45 mC/refresh measured 2026-07-03 gives
~7.7 C/day from repaints alone — *derived from two measurements, not measured
here*, and at the top of the single-digit band `docs/notes.md` records.

**The 200x200 footer cannot show the date or the sync age.** Confirmed against
`tools/mock_200x200_exp.png`: Org_01 advances 6 px/char, the zone leaves ~198 px,
so the line clips just past `mx4.2V` and `render_status_indicators()` re-emits the
hash as a badge (`src/DisplayRenderer.cpp`). So `1ea3cd7` on arm 1 was read off
the *status* line, and arm 1's resync health is not panel-readable at all on that
rig — only the `! NOSYNC` badge is. Worth knowing before the day-14 read: the
gate table above sends the reader to a footer that, on this panel, ends early.

**Gate 4 passes on all three.** Status lines read `! EXP 1 60s`, `! EXP 3 60s`,
`! EXP 5 60s`, so every record from here is attributable.

**Arm 3's `s4` is `s4h`, and its resync is healthy.** The unit is off the edge of
the 296x128 panel and cannot be read, but the arm carries **no `! NOSYNC`**, so
`resync_fail_count == 0`. `s4d` would require the flash-time sync to be the last
success, which means the attempt scheduled ~2026-08-06 01:00Z failed and the
counter would be non-zero. The absence of a `! DRIFT` badge says the same thing
independently: the badge fires at 60 s, and at this rig's +305 ppm a 4 d window
would have accrued ~105 s and lit it, where a 12 h window accrues ~13 s.

##### Arm 1's drift badge already answers the primary question

`! DRIFT +222s/12h +5119ppm n6 ±1%`. The `/12h` is the first on-panel proof the
`RESYNC_INTERVAL_MIN=43200` override took. `n6` is `DRIFT_PPM_HIST_SIZE`, so the
ring is saturated and covers the last ~3 days — the contaminated first record has
already aged out of it. Take `+5119` rather than back-computing from `+222s/12h`:
the badge span is hour-resolution, which alone spans 4744–5139 ppm, while the
aggregate is computed on-device from exact seconds. This file already established
the badge is exact to the digit on this rig.

**The duty-cycle reading of phase 1 does not survive.** Phase 1 fitted
`ppm ≈ 5339 − 1.342 × wakes/day` over 84–332 wakes/day. Arm 1 now runs pinned at
~1456 wakes/day, so that model predicts **+3385 ppm**. The rig reads **+5119 ppm**
— a 1734 ppm miss, ~34x the badge's own ±1% spread, and the rate has instead
barely moved from phase 1's +5066 ppm (+1.0%). Wake count went up 4.4x against
the busiest phase-1 day and 17x against the quietest, and the rate did not
follow. The extrapolation is far outside the fitted range and would not be worth
much on its own, but no linear-ish model through phase 1's points survives a miss
this size: this is what arm 1 was built to test, and at day 4 it reads negative.

**One thing cuts the other way, and should not be tidied away.** The spread
collapsed from ±4.5% (n=10, 1 d windows) to ±1% (n=6, 12 h windows). That is not
a window-length artefact — shorter windows are the *noisier* estimator, so this
should have widened. Under the duty-cycle reading, a pinned duty cycle giving a
pinned rate is exactly the expected tightening. So the level says duty cycle is
not the driver while the variance says it is. The reading that holds both: the
phase-1 slope was fitting *estimator* noise that tracked wake count, not a
physical dependence on it, and pinning the cadence removed the noise without
touching the level.

**The prediction that follows, recorded before the data exists.** If that reading
is right, arm 1's residual ±1% (~±51 ppm) should correlate with the window's
volatility covariate now that wakes/day is flat — testable at the day-14 harvest,
which is what supplies per-window ambient and intra-hour spread. If the residual
correlates with nothing, neither mechanism survives and it is oscillator noise.
Arm 2 then asks the same question of refresh count with wakes still pinned.
