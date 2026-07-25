---
paths:
  - "src/HistoryStore.cpp"
  - "include/HistoryStore.h"
  - "include/RtcHistory.h"
  - "include/TempHistory.h"
  - "tools/history.py"
  - "tools/hstest/**"
---

# Flash archive rules (`history` partition)

The design rationale lives in the header comment of `include/HistoryStore.h` —
read it first. These are the invariants that hold the archive together.

## The gate

**After any `HistoryStore.cpp` or on-flash-format change, run
`make -C tools/hstest sample`.** It compiles the real store against a simulated
NOR flash (writes clear bits, like the hardware) and covers the ring wrap, which
is many years out on a real device and would otherwise ship untested. The `sample`
target decodes a C-written image with `tools/history.py`, which is what keeps the
two implementations on one format — so it must *assert*, not merely print.

`make -C tools/hstest` alone is the fast host check; `sample` is the format gate.

## The archive outlives the firmware

- **A format-version mismatch must never reformat.** Erasing on an unrecognised
  version turns an ordinary firmware update into silent destruction of years of
  data. Migrate, or bail and run journal-only.
- **Only hourly entries are journaled.** That is what buys the archive its
  multi-year capacity — the current figure and its derivation are in the
  `include/HistoryStore.h` header. Don't add a per-refresh record type;
  short-lived data crowds out the permanent archive.
- **The RPO is one hour**, delivered by the journal, not by the base snapshot's
  cadence. The base cadence is emergent — a successful NTP resync, or a
  journal-volume backstop — so it varies with how bad the board's clock is. Say
  "one hour" when documenting the guarantee.

## Everything read back from flash is untrusted input

It has survived reflashes, panics and possibly a different firmware version.
Validate before it reaches RTC state that the rest of the code indexes off:

- Clamp `temp_count`, `hourly_count` and `hourly_idx` on restore.
- Clamp `resync_interval_s` into `[RESYNC_INTERVAL_MIN, RESYNC_INTERVAL_MAX]` and
  drop drift samples with a zero window — a zero interval puts WiFi on every wake.
- `history.py restore` must bound the image from **both** ends. Undersized is
  obvious; oversized writes past the partition at 0x10000 and into the `factory`
  app slot.

## Ring code is exercised at the wrap, not in the middle

- A multi-slot record must never straddle the wrap. Pad the trailing slot;
  otherwise it stays 0xFF forever and the scan mistakes the orphan for the cursor.
- Sector reclaim erases the sector **ahead** of the base cursor, never the
  cursor's own — that one holds records the newest snapshot has not absorbed.
- Any host-side reader that walks to the journal cursor must detect a wrapped
  ring first, or it silently omits everything from the cursor to the end.

## Host tooling round-trips or it doesn't ship

Every record type needs a **writer, a reader and a merge output**. When you add
one, extend `tools/hstest` so `sample` proves the C writer and the Python reader
still agree.

## Timing

Anything that walks the whole partition runs on a device under the task watchdog
(`CONFIG_ESP_TASK_WDT_TIMEOUT_S` in the generated sdkconfig). Measure it with
`ms_now()` on hardware and yield to IDLE0 — the cost is not reliably derivable
from record counts and sector arithmetic.
