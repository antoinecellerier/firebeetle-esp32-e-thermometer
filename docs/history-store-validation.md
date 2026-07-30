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
| 9 | PPK2 | append/base/erase costs vs the estimates — **DONE**, see below |

## Measured flash cost — PPK2 confirmed (2026-07-25, ESP32-E)

Full numbers and setup in [`docs/notes.md`](notes.md). Headline: **170.2 ms at 41.94 mA =
7.14 mC** per base snapshot (3300 mV), which is **0.1%** of this rig's
~7.1 C/day at the one-per-day snapshot cadence. Hourly would be 2.4%.

### What the RPO actually is

**One hour, for the hourly archive, and the journal alone delivers it.** An
hourly entry is programmed to flash as its hour finalizes — `journal_append()`
writes immediately, it is not deferred to the flush — so a reflash, panic or
battery pull costs at most the hour in progress. The snapshot cadence does not
enter into it.

The base snapshot covers what the journal does not, and that is a shorter list
than it first appears:

| Data | RPO | Journal-backed? |
|---|---|---|
| Hourly archive | **~1 h** | yes, directly |
| Drift samples | ~1 day (one per resync) | yes, `REC_DRIFT` |
| `resync_interval_s`, `resync_fail_count` | 24 h | no — but both re-derive after one sync |
| 24 h sparkline | 24 h | **no — base only** |
| Restore anchor | 24 h | **no — `history_store_restore()` bails without a valid base** |

So the snapshot is worth keeping for the anchor and the sparkline, not for the
archive. `HS_BASE_MAX_RECORDS = 24` keeps it at about a day. Note the sparkline
gains little from 24 specifically: it is a 24 h window, so a day-old snapshot
restores a chart whose every point has just aged out. Going finer would fix
that and cost proportionally more — not taken, since the sparkline refills
within a day of running.

The cadence used to be an accident: the only non-NTP trigger was a full journal
sector (256 records, 10.7 days), so it was whatever the adaptive resync interval
happened to be — 1 day on this rig only because its −5265 ppm drift pins the
interval at its floor, and up to the 28-day cap on a crystal-equipped board.
That made the board with the *better* clock the one that could not restore.
Cost of owning it there goes from ~0.7 to 7.1 mC/day — still 0.1%.

On-device timing of the flash calls alone, which is what the cadence work was
based on before the PPK2 pass:

| Phase | Time | Note |
|---|---|---|
| erase 2 sectors (8KB) | **104-125 ms** | ~53 ms/sector — set by the flash part, not by CPU speed |
| program 6.4KB payload | **25 ms** | one page-aligned write |
| read back + CRC32 | **7-8 ms** | |
| (marker also brackets) | ~13 ms | CRC32 over the payload + malloc/memcpy |

Writing the payload as three calls (header, RtcHistory, drift block) instead of
one cost **66 ms** rather than 25: the middle write started mid-page, so nearly
every 256-byte page took an extra program cycle. Batching into one page-aligned
write took 21% off the whole snapshot and is simpler code. Estimate before
measuring was 13 ms for this phase — off by 5x.

The estimate that preceded the PPK2 pass was 5.6 mC; actual is 7.14 mC, 27%
low. The assumed **current** was nearly right (40 vs 41.94 mA) — the error was
duration, because the on-device timing covered only the flash calls and not
everything the marker brackets.

Extrapolation from the erase rate: the one-time format is 480 sectors ≈ 26 s
(the log's "~24s" guess holds).

## Clean state (2026-07-25 16:55Z) — ready for the drift collection

Synthetic test data wiped and a plain build installed. Verified:

- `esptool erase_flash`, then `pio run -e dfrobot_firebeetle2_esp32e_debug -t upload`
- running `99390e1`, **no `-dirty`** (tree fully committed), **no PPK2_DEBUG**
  (no selftest line in the boot log), no `HISTORY_BASE_EVERY_WAKE`
- archive: `0 hourly, 1 sparkline, 0 drift`, base seq 1 at cursor 0x000000
- drift block at defaults: `resync_interval_s 86400`, `ppm_hist` all zero,
  `drift_ppm_count 0`, `last_sync_time` from a real NTP sync on this boot

Repeat that recipe if the board ever needs resetting again — anything injected
by `hstest --inject` must be erased before a real measurement run, or the
fabricated drift sample joins the retained ring and the first genuine
measurement is computed against an invented `last_sync_time`.

Note `include/local-secrets.h` is switched to this rig (`USE_154_Z90` +
`USE_BMP390L`); switch it back before building for the C6, and remember a
mismatched panel/sensor config panic-loops rather than erroring cleanly.

## When the archive stops recording

The store degrades rather than panicking a battery device, so nothing else on
screen changes — the device keeps measuring, charting and refreshing perfectly
while every hour it should have kept is lost for good. The `! NOARCH` badge is
the only signal that reaches the panel; `DISABLE_SERIAL` removes the log line
from release builds.

| Badge | Meaning | What to do |
|---|---|---|
| `! NOARCH fmt<N>` | on-flash format N, this firmware speaks another | `history.py backup --full`, then `esptool erase_flash` and reflash |
| `! NOARCH nopart` | no `history` partition — device is on an old table | reflash; the upload rewrites the partition table |
| `! NOARCH io` | an erase or write failed | suspect the flash part; back up if it still reads |

Rendered by `tools/sim` as `mock_*_noarch.png`. It is ranked ahead of the crash
badge deliberately: a crash's payload is already saved to the coredump
partition and does not decay, whereas this condition is still destroying data
every hour it goes unnoticed.

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
| — | 2026-07-25 | **PASS** | **Restore keeps its anchor and marks the outage it spans** (`1f6552d`). `hstest --inject 1966080 <mac> $(date +%s)-259200` built a 30-day archive whose newest hour is 2026-07-22 17:00Z; `history.py restore` took it and the board booted `f050bfc` with `History restored: 720 hourly (+0 replayed), 62 sparkline, base seq 1`, NTP-syncing at 2026-07-25 18:55:51Z. Read back: 792 hourly rows — the 720 injected ones **still dated 2026-06-22 18:00Z .. 2026-07-22 17:00Z**, unmoved — followed by exactly **72 contiguous `HOURLY_NO_DATA` rows covering the outage**, ending adjacent to the in-progress hour. The decisive part is decoding the base snapshot ring *on its own*, since that is what `Display.h` dates every entry from: the anchor moved 2026-07-22 17:00Z → 2026-07-25 17:00Z while the newest real entry stayed at 2026-07-22 17:00Z / 24.7-24.9-24.8 °C and the ring rolled 72h. The old code made the same anchor move with no fills, re-dating all 720 readings 3 days forward. |
| — | 2026-07-25 | **PASS** | **A format bump no longer erases the archive** (`19dde9f`). `HS_FORMAT` 2→3, nothing else changed, uploaded, reset pulsed while already capturing: `HistoryStore: on-flash format 2, firmware speaks 3 — archive left intact and DISABLED. Back it up (tools/history.py backup), then erase_flash to start a new one.` No `formatting`, no `restored`, no base write — on that boot or the two after. The partition is **byte-identical** across the exercise: sha256 `bd49a1a6…c774b2`, 1966080 bytes, `cmp` clean. The "before" image was read with `esptool --after no_reset` deliberately — a normal backup's trailing reset lets the working firmware cold-boot and append a legitimate record, which would have confounded the hash. `history.py backup --full` still decoded the disabled archive off the device (792 hourly), so the recovery path the log points at works. |
| — | 2026-07-25 | **BUG FOUND** | **The journal rebuild boot-looped the device.** Scanning slot by slot meant ~119k `esp_partition_read` calls per pass, which blew the 5s task watchdog: `task_wdt: IDLE0 (CPU 0)` → panic → reboot → repeat, on every cold boot with no base (i.e. every boot after `erase_flash`). Symptom on the bench was subtle: the panel kept a stale frame and `history.py backup` showed `base (none — journal only)`, which reads like "hasn't slept yet" rather than "looping". Fixed by reading 512-byte chunks, skipping all-0xFF chunks outright (an erased journal now costs one read per chunk and no CRC), and yielding to IDLE0 every 256 chunks so the margin does not depend on an estimate. `tools/hstest` now bounds flash *calls*, not bytes — it fails at `2051 flash reads over 2048 slots` if the per-slot scan returns. |
| — | 2026-07-25 | **PASS** | **Real rebuild measured.** Injected a 720-hour archive, clobbered both base slots, restored: `no base — rebuilt 720 hours from 720 journal records in 2444ms`, then `sparkline backfilled with 24 hourly points`, then a normal boot — no watchdog. 2444ms is ~3x the estimate that replaced a 10x-wrong one, which is why it is logged at runtime now. Dominated by per-call read overhead (~320µs per 512-byte read), so a full journal adds CRC for ~122k slots per pass on top; the yield is what keeps that safe rather than the arithmetic. |
| — | 2026-07-25 | note | `! NOARCH fmt2` was **not** visually confirmed on the panel — no camera on the bench. The plumbing is verified (serial line correct; `s_flash_format` carries the *on-flash* value, so it reads `fmt2` not `fmt3`) and `tools/sim` renders the badge at all four sizes, but the physical frame is inference. |
| — | 2026-07-25 | **BUG FOUND** | Injection exposed that `drift_state_load()` trusted flash: an injected `resync_interval_s = 0` puts `next_resync_time` on `now`, so **every wake would bring up WiFi** (1.5-4.5C per failed attempt). Now clamped, and drift samples with a zero measurement window are dropped rather than inflating the on-screen `nN`. Badge went `+0ppm n1` → `-5265ppm n1`. |
| — | 2026-07-26 | flash | **Different rig: XIAO ESP32-C6 + BMP581 + Seeed ePaper driver board (GDEW029I6FD), `/dev/ttyACM0` (USB-Serial-JTAG, MAC 58:E6:C5:16:1F:08), PPK2-powered at 4.2V via the shield JST.** Env `seeed_xiao_esp32c6_epaper_release`, `PLATFORMIO_BUILD_FLAGS="-DPPK2_DEBUG"`, hash `4c0bbef`. `local-secrets.h` moved from `USE_154_Z90`+`USE_BMP390L` (the FireBeetle rig) to `USE_290_I6FD`+`USE_BMP58x`; original backed up for restore. Previous firmware was `1ed89a3` (2026-07-06) on the **old** table — `factory` at 0x10000, no `history` — after a 19d23h basement run, so this upload is the relocation to `factory` 0x1f0000 and the archive's first appearance on this board. Written with `--before no_reset --after no_reset` so the chip stayed halted in download mode and boot #1 lands on a PPK2 capture rather than on the USB session. No `erase_flash`: the old app's bytes are simply inside the new `history` region, the same starting state as observation #1 on the E. Boot #1 result pending. |
| — | 2026-07-26 | note | **Probe the XIAO's soldered BAT connector, not the hat's JST2.** JST2 is not the battery input: energising it gives a 0.2ms ~14mA inrush into its own input capacitance and then nothing, which reads exactly like a dead board. Measured on the BAT pads the supply bypasses the shield's ETA9740 path, so the ~330-500µA that path idles at is absent and a sleep-floor figure *is* valid from this wiring — compare against the 22µA @ 4.2V battery-direct datapoint in [`docs/notes.md`](notes.md). |
| — | 2026-07-26 | flash | Re-armed the first-boot measurement on the C6 ePaper rig: `erase_flash` then reflash of the same `4c0bbef` / `seeed_xiao_esp32c6_epaper_release` / `-DPPK2_DEBUG`, both with `--before no_reset --after no_reset` so one BOOT+RESET covered both operations. Needed because an unpowered PPK2 lead (hat JST2, see note below) meant the board first booted on USB, consuming the one-time format. **Full-chip erase of 4MB took 1.7s**, which argues the archive format is erase-block bound (30 aligned 64KB blocks) rather than the 480 sector erases the ~26s projection assumes — expect single-digit seconds. Unmeasured either way until the trace comes back. |
| — | 2026-07-26 | flash | C6 ePaper rig to `f07d2c9` (`seeed_xiao_esp32c6_epaper_release`, `-DPPK2_DEBUG`), `--before default_reset --after no_reset`, **no** `erase_flash` — so the archive formatted on the previous boot survives and the one-time format will not recur. Two operational lessons: **nrfconnect holds serial ports exclusively and resets whatever it opens**, which knocked the chip out of download mode mid-session; and **the ttyACM number is not stable** — when the ESP32 dropped off the bus the PPK2 inherited `ttyACM0`, so a hardcoded node sent esptool sync bytes to the PPK2 (harmless, connect failed). Resolve via `find /dev/serial/by-id -name '*Espressif*'`. A poll-and-retry loop on that path flashed successfully with `default_reset` alone the moment the device enumerated, so the BOOT hold is not always needed. |
| — | 2026-07-26 | flash | C6 ePaper rig to `91f08eb`, `seeed_xiao_esp32c6_epaper_release`, **no `PLATFORMIO_BUILD_FLAGS`** — a true production build: no `PPK2_DEBUG`, so no D0/D1 markers, no `ppk2_selftest()`, GPIO16/17 never touched, and `power_efficient` true so no `! DEBUG` badge. Flashed to test whether the sleep-floor hump seen on `f07d2c9` exists in shipping firmware or is confined to the debug build's pad handling. Analysis must be current-only; the marker-driven paths in `tools/ppk2.py` have nothing to key off. |
| — | 2026-07-26 | flash | C6 ePaper rig to `e8fb31e`, `seeed_xiao_esp32c6_epaper_release`, `PLATFORMIO_BUILD_FLAGS="-DPPK2_DEBUG"` (1000402 B; the same env without the flag is 1000114 B, which is how to tell the two apart — the selftest's `LOGI` string is eliminated under `DISABLE_SERIAL`, so its absence proves nothing). Verification flash for the code-review fixes: the marker fingerprint is now 80 ms and emitted every wake rather than 400 ms on the first boot only, the unbounded USB flash-hold is gone, and `tools/ppk2.py` reports floor/mean/excess per sleep region with a non-homogeneity warning. Analyse marker captures with `--decimate 1`; the short fingerprint does not survive decimation. |
| — | 2026-07-26 | flash | **Clean state.** `esptool erase_flash` (full chip, 1.5 s) then `2d90340`, `seeed_xiao_esp32c6_epaper_release`, **no `PLATFORMIO_BUILD_FLAGS`** (1000114 B — the same env with `-DPPK2_DEBUG` is 1000402 B, which is how to tell them apart). Erased deliberately: a sensor ground came loose and a spurious **127.5 °C** reading had been recorded, and with no temperature plausibility gate in the firmware it reached the hourly ring, the sparkline, the boot min/max and `previous_temp` — and through the base snapshot, flash. Archive starts empty; the 30-day chart rebuilds from here. Write verified by esptool exit status, not by pipeline exit status — a watcher loop of the form `esptool ... \| tail && echo OK` reports success unconditionally, because it tests `tail`. |
| — | 2026-07-26 | **PASS** | **Temperature plausibility gate and unattended sensor recovery.** C6 ePaper rig, `seeed_xiao_esp32c6_epaper_release`, no `PLATFORMIO_BUILD_FLAGS`. Flashed from an uncommitted working tree, so the panel hash was `-dirty` and resolves to no commit — an early version of the gate, before the identity check and the recovery rework. Sensor ground pulled with the device running: panel showed `--.-` with `! SENSOR`, status line `#5 r2 lp1 u4 0d w:ULP mx4.3V`. **Two refreshes across five wakes** — one into the fault, one on recovery, the three intervening wakes silent. `u4` climbing once per wake identifies the failure as a NACKing sensor rather than one returning zeros: both LP-core I2C error paths call `ulp_lp_core_wakeup_main_processor()` unconditionally, so a dead bus costs one CPU wake and one LP program reload per `SLEEP_INTERVAL_S` (60 s on a release build). Left unbounded by decision — rare, and either self-clearing or terminal. |
| — | 2026-07-26 | **BUG FOUND** | **`lp1` after nine reloads: LP counters cannot survive a reload on their own.** Measured on the C6 ePaper rig during a sustained sensor fault (`u9`, `lp1`). `ulp_lp_core_load_binary()` memsets the whole `CONFIG_ULP_COPROC_RESERVE_MEM` region before copying the program — that is how it initialises `.bss` — so two comments claiming the loader leaves `.bss` alone were wrong, and confining the driver's own zeroing to cold boots changed nothing. The counters are now saved and written back around the load; `prev_temp_c` deliberately is not, because a zero reference is what guarantees the next sample wakes the CPU. |
| — | 2026-07-26 | **BUG FOUND** | **A preserved LP delta reference stranded a repaired sensor.** Carrying `prev_temp_c` across a reload left it holding a value the LP core had latched from a floating bus during the fault, within `TEMP_DELTA_THRESHOLD_C` of the real room. Ground reconnected, sensor reading correctly, no delta produced, CPU never woken, panel blanked — until warming the sensor by hand supplied a change large enough to wake it. Recovery would otherwise have waited on the hourly safety net. Wakes are delta-triggered, not periodic, which is also why nothing that counts consecutive wakes can be used to confirm recovery. |

| — | 2026-07-26 | note | **A 0.0 °C reading entered the archive on a pre-gate build**, and is still there. 0.0 °C is a plausible room temperature, so a raw `0x000000` from the disconnected sensor ground reached the hourly ring, the sparkline and, through the base snapshot, flash. The archive dates from the `2d90340` clean-state erase earlier the same day, so discarding it costs about a day: `esptool erase_flash` then reflash if the 30-day chart's daily minimum matters more than that day of history. Left in place otherwise — one point, and bounded. || — | 2026-07-26 | **CONSTRAINT** | **On the C6 the CPU cannot use the sensor bus once the LP core owns it.** The sensor is wired to one pair of pins (GPIO6/7) that both cores drive; `lp_core_i2c_master_init()` calls `rtc_gpio_init()` on them, setting their `LP_AON_GPIO_MUX_SEL` bit and routing the pads out of the digital GPIO domain, where `i2c_new_master_bus()` cannot reach them. There is no `lp_core_i2c_master_deinit()`, but **`rtc_gpio_deinit()` on both pins clears that bit and hands them back** — the same call the ESP32-E path already makes. Verified against ESP-IDF v6.0.1 source and the C6 API reference; the recipe itself is inferred from the two call sites, not documented by Espressif as a named procedure, and is untested on this board. Caveat: on C6 `rtc_gpio_deinit()` also force-disables the shared LP IO clock gate under an open IDF TODO (IDF-14951), which may disturb other LP peripherals. A second option, also inferred: have the HP side open its bus on the **LP_I2C port** (`i2c_new_master_bus()` with port >= `SOC_HP_I2C_NUM`) rather than HP I2C0, which drives the same hardware block and needs no pin hand-back at all. Measured: with the ground reseated the LP core read the sensor on **28 of 30 cycles (`lp30 e2`)** while every CPU-side read failed and the panel stayed `--.-`. `ulp_lp_core_stop()` does not help: it halts the RISC-V core and touches no GPIO, RTCIO or LP_I2C register. The only successful CPU reads all session were on cold boots, before the LP core existed. Consequences: recovery from a sensor fault must run through the coprocessor, and `verify_ulp_temp()`'s direct re-read — whose comment claims "C6 LP I2C uses dedicated pins, no RTC GPIO deinit needed" — has almost certainly never worked on this board. The ESP32-E is unaffected: it bit-bangs over RTC GPIOs and `release_i2c_pins_to_hp()` hands them back. |
| — | 2026-07-26 | **PASS** | **Temperature plausibility, fault rendering and diagnosis, on `seeed_xiao_esp32c6_epaper_debug`.** With the sensor ground unplugged: the driver refuses to read a part that did not answer with its chip ID, so the reading is the sentinel and the 127.5 C an undriven bus produces is never formed (the earlier build reported `temp: 127.498032` from the same wiring and relied on it landing outside the range). First boot renders `--.-` with `! SENSOR` — the original defect was rendering nothing at all. Fault state stays quiet: **`r2` across 31 wakes**, one frame at boot and one at the `FAULT_REPAINT_WAKES` heartbeat, which is what makes a wedged device distinguishable from a healthy quiet one. **`lp30 e30 u30` at that heartbeat**: the LP wake counter survived 30 reloads where it previously read `lp1`, since `ulp_lp_core_load_binary()` memsets the whole reserve region and the counters must be carried across by hand. That let `! LP W 0x108` appear for the first time — LP core, trigger write, `ESP_ERR_INVALID_RESPONSE`, i.e. the sensor did not ACK. |
| — | 2026-07-26 | note | **Serial cannot be captured on wakes on this rig.** USB-Serial-JTAG re-enumerates on every deep-sleep wake, so wake-time `printf` is gone before the host attaches; only the boot after `pio run -t upload -t monitor` is catchable. Worse, the CDC control lines drive the chip — esptool resets it "via RTS pin" — and pyserial asserts DTR on open, which on this board is **GPIO9: both the BOOT strapping pin and the firmware's shutdown button**. Opening the console can therefore strap the chip into the bootloader or press its shutdown button. Treat attaching a monitor as intrusive, and read the panel counters instead. |
| — | 2026-07-26 | **PASS** | **Unattended fault/recovery cycle, twice, no power cycle.** C6 ePaper rig, `seeed_xiao_esp32c6_epaper_debug`. Sequence: boot with the sensor ground disconnected → `--.- C`; ground reseated → real temperature; ground pulled again → `--.- C`; reseated → real temperature. Recovery runs through the coprocessor, which is the only path that can reach the sensor once LP I2C owns the pins (see the CONSTRAINT row above). The rule that briefly refused a coprocessor reading while the panel showed a fault — intended to force an identity-checked CPU read on the recovery transition — is what broke this, and was reverted: on the C6 it made recovery impossible rather than merely unverified. |
| — | 2026-07-26 | flash | C6 ePaper rig to `431b7b0`, `seeed_xiao_esp32c6_epaper_release`, **no `PLATFORMIO_BUILD_FLAGS`** (1008016 B). Production build carrying the sensor-identity work. Archive harvested first and found **empty** — `0 hourly, 0 sparkline, 0 drift`, one base snapshot from 17:55:34Z written before the first NTP sync. That is a vacuous pass on "no garbage reached flash": nothing bogus was written, but nothing was written at all, because every reflash during the session wiped RTC and reset `current_hour_start`, so no uninterrupted run spanned a wall-clock hour boundary with a valid clock. The recording path — real hourly entries, and `HOURLY_NO_DATA` for an hour whose readings were all rejected — is still unverified at the storage layer and wants an undisturbed run. |
| — | 2026-07-29 | flash | **New rig: custom thermometer-c6 rev A, board 1** (MAC 98:88:E0:75:47:9C, USB-Serial-JTAG), USB-powered, no battery, no panel. Env `thermometer_c6_debug`, no `PLATFORMIO_BUILD_FLAGS`, hash `3b42d3a` (clean tree). `local-secrets.h`: `USE_BMP58x` + `DISABLE_DISPLAY` + LEDs enabled (previous config `USE_290_I6FD` backed up in session scratchpad). First boot on factory-blank flash, all clean: **no 32k-XTAL fallback warning** (FC-135 is the RTC slow clock), BMP581 chip ID 0x50 / 29.79°C on LP I2C, battery 4196mV (charger float-held VBAT — no pack attached), base snapshot seq 1 (erase 4ms / program 12ms / verify 4ms), LP core started at 5s poll, deep sleep entered, STATUS LED observed on wake. LP-counter survival and vbus_present() unverified — deferred to the panel-attach step (wake serial is uncapturable on USB-Serial-JTAG; panel footer will carry the counters). |
| — | 2026-07-29 | flash | **thermometer-c6 board 1 to `91bd4d8`** (`thermometer_c6_debug`, no `PLATFORMIO_BUILD_FLAGS`), `local-secrets.h` now `USE_BMP58x` + `USE_154_GDEY` + LEDs enabled, GDEM0154I61 seated in J4 (unpowered attach). Two flash attempts failed/silent first — lesson relearned on this board: **attaching serial can strap GPIO9/BOOT** (DTR on open), leaving the chip silently parked in the bootloader; resolution was a human RST press with no host process on the port. **First render PASS**: 33.9°C / 16:01 CEST / `4204mV` (float-held node, no pack) / `! DEBUG 5s` / footer `#3 r3 lp2 0d w:ULP mx4.2V 91bd4d8` — `w:ULP` proves an LP-core delta wake drove the frame (LP survives deep sleep), `#3 r3` proves archive continuity across the reflash, and the refresh itself functionally verifies the whole DESPI-clone boost chain on the as-shipped 0.47Ω/10µH jumpers. 33.9°C vs 29.8°C an hour earlier = USB self-heat + bench sun, unquantified (Phase 3 item). |
| — | 2026-07-29 | flash | **thermometer-c6 board 1 to `cbda104`, `thermometer_c6_release`, no `PLATFORMIO_BUILD_FLAGS`** — true production build (`DISABLE_SERIAL`, 60s interval, no `! DEBUG` badge), `local-secrets.h` unchanged (`USE_BMP58x` + `USE_154_GDEY` + LEDs enabled — LED wake blinks are the only observability concession). Flashed with the chip parked in download mode by a manual BOOT+RST (the poll-for-a-wake-window loop was moot — the port was up the whole time). Purpose: sleep-floor measurement on PPK2 source at J1 (4.0V), EPD_VCC post-hibernate decay at 60s spacing, vbus_present()-false behavior, and the first drift-ppm datapoint on the FC-135. |
| — | 2026-07-30 | flash | **thermometer-c6 board 1 to `73d4f8a`, `thermometer_c6_debug`** — four uploads: three with no `PLATFORMIO_BUILD_FLAGS`, one with `-DUSB_WINDOW_OBSERVE_CYCLES=2`. `local-secrets.h` unchanged (`USE_BMP58x` + `USE_154_GDEY` + `EPD_POWER_GATE`, LEDs enabled), battery attached (3770mV read), panel seated. **USB flash-service window PASS**: `! USB` badge on panel, port continuously enumerated (45s/45s vs ~1s-on/4s-off when sleeping), **two back-to-back hands-free reflashes at ~18s each with nothing touched**, board returning to the running app rather than parked. `-DUSB_WINDOW_OBSERVE_CYCLES=2` gave exactly two real deep sleeps then the window, and logged `USB host attached, but this sleep is an observe cycle`. `Sleeping with ULP wakeup (timer safety net: 5 s)` confirms the docked safety net replaces the 1h one. **Continuous serial across cycles now works** (six consecutive cycles on one attached port, no re-enumeration) — the XIAO's long-standing capture problem is a consequence of sleeping, not of USJ. Four findings: (a) the manual BOOT+RST park leaves the chip in ROM download mode after `pio upload` (`rst:0x15 (USB_UART_HPSYS),boot:0x10 (USB_BOOT)`, `wait usb download`) and needs a physical RST — flashing *through the window* does not; esptool's `--after watchdog_reset` is not supported on the C6 (falls back to RTS). (b) Attaching any monitor resets the chip — cdc-acm raises DTR/RTS at open — so serial is not usable to diagnose a boot problem here. (c) The host probe is timing-marginal against Linux USB autosuspend (`power/control=auto`, 2000ms): the first probe after a slow boot found no SOF, logged `charger, not a bus`, and the window only opened ~50s later on the re-probe (`! USB` first seen at r14). (d) First frame after any reflash renders `--.-` with `! SENSOR`: cold boot has no coprocessor sample, and the direct read fails with `failed to read BMP58x chip ID` because the LP-IO mux still routes the I2C pins to the LP domain across a chip reset. Sensor read 33.7°C flat while charging — self-heat datapoint, not an equilibrium delta. |
| — | 2026-07-30 | flash | **thermometer-c6 board 1 to `aec755b` then `ac2647e`, `thermometer_c6_debug`**, no `PLATFORMIO_BUILD_FLAGS`, `local-secrets.h` unchanged, battery attached. Second half of the session, after the fixes the first half's findings prompted. **VBUS GPIO4 wake PASS**: unplugged, `! USB` cleared within one refresh (~300ms debounce plus the forced repaint); replugged, `! USB` back in ~2s. Decisive because VBUS-absent sleep arms the 1h safety net, so anything under a minute can only be the GPIO wake. Window reopened and held the port 25/25s afterwards. **LP-IO pad reclaim PASS, and the failure is intermittent — not the 100% it appeared to be**: five resets taken while the LP core owned the bus (each via a monitor attach), 3 hit `Chip ID read failed — reclaiming I2C pads from the LP domain and retrying` followed by `BMP581 detected (chip ID 0x50)`, 2 read the chip on the first attempt with no reclaim needed. `failed to read BMP58x chip ID` — the string that produced `--.-` — did not occur once, and both post-flash first frames carried a real temperature. Note `rtc_gpio_deinit()` therefore ran on 3 of these boots and the window still opened afterwards, so IDF-14951's shared LP-IO clock gate did not break the wake path in that direction. **IDF-14951 clock gate CLEARED**: the board was then left asleep on battery (≥9min by the presence log; the unplug itself was not timed) and replugged at 20:15:12 — port enumerated at 20:15:13, **~1s**, and the window reopened and held it. That sleep was entered on a boot where `rtc_gpio_deinit()` had run, so the shared LP-IO clock-gate side effect does not break the GPIO4 wake armed in the same domain. Reasoned before, measured now. **Still open**: the sleep floor with the GPIO4 wake armed against the 18.7µA baseline — the one measurement that gates deployment. Thermal: ~33.5°C while parked in the window with the charger running, falling on battery once both stopped, with `w:ULP` delta wakes every cycle during the descent. Absolute numbers not yet captured, so still no equilibrium delta. |
| — | 2026-07-30 | flash | **thermometer-c6 board 1 to `1d567b6`, `thermometer_c6_debug`, `PLATFORMIO_BUILD_FLAGS="-DBATTERY_SHUTDOWN_DISABLED -DDISABLE_WIFI"`** — bench sweep build for the battery-floor runs (notes.md power logbook, same date). `local-secrets.h` unchanged, battery and USB out, PPK2 sourcing at J1. ~20 power cycles across the sweeps; `DISABLE_WIFI` means no plausible clock, so nothing reached the archive by design (RTC state wiped every step regardless). **The device still carries this build: the 3700 mV shutdown latch is OFF and WiFi/NTP is dead — reflash `thermometer_c6_release` with no `PLATFORMIO_BUILD_FLAGS` before any deployment or soak.** |
