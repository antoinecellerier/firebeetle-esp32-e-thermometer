---
paths:
  - "include/RtcHistory.h"
  - "src/Thermometer.cpp"
---

# RTC memory rules

## What survives what

| Reset | `RTC_DATA_ATTR` (`.rtc.data`) | `.rtc_noinit` | `history` partition |
|---|---|---|---|
| deep-sleep wake | survives | survives | survives |
| panic / WDT / brownout | **wiped** (bootloader reloads it) | survives | survives |
| power-on, battery swap | wiped | wiped | survives |
| `pio run -t upload` | wiped (esptool asserts EN) | wiped | survives |
| `esptool erase_flash` | wiped | wiped | **gone** |

A crash therefore looks exactly like a fresh flash — boot count 1, history empty.
That is why the crash log lives in `.rtc_noinit` and why history is mirrored to
flash. Anything that must outlive a panic goes in one of those two, never in
plain `RTC_DATA_ATTR`.

Any esptool operation (including `history.py backup`) enters download mode and
presents as `rst:0x1 POWERON_RESET`, so it wipes RTC as a side effect. Harvest at
the end of a run, not during one.

## Version bumps

- Bump `RTC_HISTORY_VERSION` when changing the `RtcHistory` struct
  (`include/RtcHistory.h`).
- Bump `RTC_STATE_VERSION` for other RTC variable changes.
- A `RTC_HISTORY_VERSION` bump is **not** destructive to the flash archive: the
  snapshot stores the buffer geometry and zero-fills a shorter stored payload, so
  appending a field stays non-destructive. Keep it that way.
- The `self_addr` field in `historical_data` auto-detects linker address shifts.

## Adding a variable is not free

Each new `RTC_DATA_ATTR` variable shifts `historical_data` and eats
`ULP_DATA_BASE` headroom — **60 bytes spare on ESP32-E**
(`.claude/rules/ulp.md`). `HistoryStore` deliberately derives its state from
flash rather than adding any. Prefer that.

## Clock sanity

- **Nothing is recorded without a plausible clock** (`time_is_plausible()`,
  `include/RtcHistory.h`). Entries are filed by clock hour, so a 1970 timestamp
  files them ~54 years before everything stored.
- A backward clock step must **clamp**, not rebase by a fixed delta. Drift
  accumulates gradually, so a single offset applied to the whole series corrupts
  the 30-day chart.
- A restored `hourly_latest_time` is authoritative — the first post-restore
  reading must not overwrite it, or the whole ring is re-dated to the reboot hour
  and the `HOURLY_NO_DATA` outage gap is never written.
- A failed NTP sync is not the same as having no time: read the clock anyway, in
  case the RTC timer survived with good time.
