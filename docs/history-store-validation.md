# Flash history archive — hardware validation log

What has actually been exercised on hardware for `src/HistoryStore.cpp`, and
how. Append a row per experiment; don't rewrite old ones. Host-only checks live
in `tools/hstest` and are not repeated here.

Rig unless stated otherwise: **FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90**,
`dfrobot_firebeetle2_esp32e_debug`, `/dev/ttyUSB0`, USB-powered.

`local-secrets.h` must match the wired hardware (`USE_154_Z90` + `USE_BMP390L`
here). Flashing a mismatched panel/sensor config panic-loops at ~600ms and
looks like a huge sleep floor on the PPK2 — a stale frame on the e-paper (old
GIT_HASH/time) is the tell.

## Plan

Device-side steps from the implementation plan. Host-side equivalents already
pass in `make -C tools/hstest`.

| # | Experiment | Why it needs hardware |
|---|---|---|
| 1 | First boot on the new partition table | one-time format over the old app image; ~475 sector erases |
| 2 | Archive accumulates | real ULP wakes, real refresh cadence |
| 3 | `history.py backup` + `dump --csv` | real esptool over the CP2102/CH340 bridge |
| 4 | **Reflash test** | the whole point: history survives `pio run -t upload` |
| 5 | Power-cycle test | RTC gone, restore + `HOURLY_NO_DATA` gap |
| 6 | Cold-clock test | unsynced device records nothing, NOSYNC badge, bounded retries |
| 7 | Transport test | baud actually decisive on this board |
| 8 | `erase_flash` | clean start, no boot loop |
| 9 | PPK2 | append/base/erase costs vs the ~0.04/4.5/2 mC estimates |

## Measured flash cost (2026-07-25, ESP32-E, `-DHISTORY_BASE_EVERY_WAKE`)

Timed on-device around the flash calls, n=4 per variant, tight spread. Only the
**durations** are measured here; the current is assumed and is what a PPK2 pass
would pin down.

| Phase | Time | Note |
|---|---|---|
| erase 2 sectors (8KB) | **107 ms** | ~53 ms/sector — set by the flash part, not by CPU speed |
| program 6.4KB payload | **25 ms** | one page-aligned write |
| read back + CRC32 | **7 ms** | |
| **total per base snapshot** | **140 ms** | ~5.6 mC at an assumed 40 mA |

Writing the payload as three calls (header, RtcHistory, drift block) instead of
one cost **66 ms** rather than 25: the middle write started mid-page, so nearly
every 256-byte page took an extra program cycle. Batching into one page-aligned
write took 21% off the whole snapshot and is simpler code. Estimate before
measuring was 13 ms for this phase — off by 5x.

Extrapolations from the erase rate: the one-time format is 480 sectors ≈ 26 s
(the log's "~24s" guess holds). At the current ~daily base cadence the store
costs ~6 mC/day; one base per hour instead would be ~134 mC/day, ~1.9% of the
~7.1 C/day budget.

## Before starting the real drift collection

**The board currently holds synthetic data** (720 injected hourly entries, a
ramp sparkline, and a fabricated drift sample). Wipe it first, or the fake
sample joins the retained ring and the first real measurement is computed
against an invented `last_sync_time`:

```bash
~/.platformio/penv/bin/esptool --port /dev/ttyUSB0 erase_flash   # or erase_region 0x10000 0x1E0000
pio run -e dfrobot_firebeetle2_esp32e_debug -t upload
```

Also note `include/local-secrets.h` was switched to this rig (`USE_154_Z90` +
`USE_BMP390L`) from the C6 config; switch it back before building for the C6.

## Known cosmetic issue

`store created` in the header is stamped during `store_format()`, which runs in
`setup()` before the first NTP sync, so on a fresh device it is an epoch-zero
value. The header sector is written once and never rewritten, so there is
nowhere to backfill it. `history.py` prints "(before first NTP sync)" rather
than a 1970 date; not worth a format change.

## Observations

| # | Date | Result | Notes |
|---|------|--------|-------|
| 1 | 2026-07-25 | **PASS** | Device was on the old table (`factory` 0x10000/3968K, no `history`), confirmed by `esptool read_flash 0x8000`. Upload wrote the app to its new home at 0x1f0000 and the screen came up on `b10cd29` (was `95c7b04-dirty`), so the relocation is real and the panel refreshed normally. First boot then formatted the region and wrote `base snapshot seq 1 (0 hourly, 1 sparkline, cursor 0x000010)`. The format log itself was missed — serial capture started mid-boot — so the ~475-erase timing is still unmeasured. |
| 3 | 2026-07-25 | **PASS** | `history.py backup` over the CH340 bridge at 921600. Read the right identity off the device: `firebeetle2_esp32e c4:5b:be:8c:4d:b8 (GDEH0154Z90/BMP390L)`, build `b10cd29`. Incremental read did its job — **24576 bytes, not 1920KB**. |
| 2 | 2026-07-25 | **PARTIAL** | Sparkline records accumulate: 1 → 3 → 6 → 8 over ~7 min of consecutive backups. That is the refresh path (one record per display refresh, on \|Δtemp\| ≥ 0.1°C), not the hourly one — ambient was genuinely ~28.5°C with the sensor 15cm off-board, so this is real noise driving real refreshes, not a tethered-board artifact. `0 hourly` throughout, correctly: the first hourly entry needs a clock-hour boundary. **Hourly accumulation still unverified.** |
| 4 | 2026-07-25 | **PASS** | The one that matters. Made airtight rather than inferred: `esptool ... --after no_reset write_flash 0x1000/0x8000/0x1f0000`, then the reset pulsed by hand while already capturing, so the log starts at byte zero of the new image's first boot. Result: `RTC history version mismatch — resetting history` / `History restored: 0 hourly, 8 sparkline (base seq 1, +0/7 replayed)`. An earlier capture of a plain `pio run -t upload` had missed the line by starting mid-boot — the restore had worked then too. |
| 5 | 2026-07-25 | **PARTIAL** | A DTR/RTS reset presents as `rst:0x1 (POWERON_RESET)` and wipes RTC (boot_count back to 1), and restore repopulated 6 sparkline points spanning two flashes. So restore-after-RTC-loss is proven. The `HOURLY_NO_DATA` gap fill is **not** yet exercised — it needs hourly entries to exist first. |
| 7 | 2026-07-25 | **PARTIAL** | 921600 works on this bridge (CH340, `1a86:` by-id, not the CP2102 the docs assume) for both `read_flash` and `write_flash`. The 115200-vs-921600 timing claim is unmeasured, and the incremental read makes it mostly moot here. |
| 2 | 2026-07-25 | **PASS** | Hourly path confirmed once the clock crossed 15:00Z: `1 hourly` covering `2026-07-25 14:00:00Z` at 29.0/29.2/29.1 °C — min, max and avg all distinct, so the accumulator works, not just the append. |
| — | 2026-07-25 | **PASS** | Format 2 (hourly-only journaling) re-formats on first boot as intended, and restores with the sparkline sourced wholly from the base: `History restored: 0 hourly (+0 replayed), 9 sparkline, base seq 13`. |
| — | 2026-07-25 | **PASS** | **Synthetic archive injection.** `hstest --inject <size> <mac> <now> <file>` builds a full 1920KB image with the *real* store code — so it cannot disagree with what the firmware writes — filled from `MockData.h` and stamped with this board's MAC. `history.py restore` accepted it (MAC matched), and the device came up with `History restored: 720 hourly (+0 replayed), 62 sparkline, base seq 1` and refreshed. Reading it back gives 720 rows spanning 2026-06-25 15:00Z .. 2026-07-25 14:00Z with sane values. This is how to get a populated 30-day chart without waiting 30 days. |
| — | 2026-07-25 | **PASS** | **30-day chart confirmed against the injected series.** On-screen dip reported at "around July 8"; the coldest day in the injected data is 2026-07-08 at 19.3°C daily avg. Daily aggregates (what the 200x200 panel plots) run 16.8-26.1°C, consistent with the observed 24°C gridline. |
| — | 2026-07-25 | **PASS** | **24h sparkline confirmed via a ramp.** `--inject ... ramp` replaces the sparkline with a 10.0→30.0°C diagonal at fixed 30min spacing — a shape neither the room nor `MockData.h` produces. Restored as 48 points (100→300 x10, 1800s apart) and observed as a clean diagonal on the panel. Settles that the 24h chart is fed from flash, not from anything compiled in. |
| — | 2026-07-25 | note | Two earlier observations on the mock sparkline were **not** faults: the flat stretch "up to 0h" is `MockData.h`'s deliberate 6h flat carry-in (a spline regression case; 21:41Z = 23:41 CEST, hence 0h on screen), and >1 point/hour is correct — the 24h chart records per display refresh, only the 30-day chart is hourly. |
| — | 2026-07-25 | **BUG FOUND** | Injection exposed that `drift_state_load()` trusted flash: an injected `resync_interval_s = 0` puts `next_resync_time` on `now`, so **every wake would bring up WiFi** (1.5-4.5C per failed attempt). Now clamped, and drift samples with a zero measurement window are dropped rather than inflating the on-screen `nN`. Badge went `+0ppm n1` → `-5265ppm n1`. |
