#pragma once

// Flash-backed temperature archive.
//
// `pio run -t upload` rewrites only the bootloader, the partition table and the
// app, so a data partition survives reflashing; only `esptool erase_flash` wipes
// it. That is the whole trick: RTC memory cannot survive a flash (esptool
// asserts EN before writing anything, and the bootloader reloads .rtc.data on
// any non-deep-sleep-wake reset), but flash can.
//
// Layout inside the `history` partition:
//
//   0x0000  base slot A   8KB   full RtcHistory + drift state, CRC32
//   0x2000  base slot B   8KB   ping-pong; highest valid seq wins
//   0x4000  journal       rest  16-byte append records, wraps as a ring
//
// The journal is both the crash-recovery log and the long-term archive: it is
// never erased wholesale, only one sector at a time as the cursor reaches it.
//
// **Only hourly entries are journaled.** They are the archive: the base
// snapshot holds just the last HOURLY_HISTORY_SIZE hours, so once an hour falls
// out of that ring the journal record is the only copy. At 24 records/day that
// is 140KB/year, so a 1904KB journal holds ~13.7 years.
//
// The 24h sparkline is deliberately NOT journaled. It is restored from the base
// snapshot, which already contains it (it lives inside RtcHistory), so it costs
// nothing extra and comes back up to one base-interval stale — which is fine
// for a window that rolls over daily anyway. Journaling it instead would have
// let short-lived data crowd out the permanent archive: at the observed refresh
// rate it was two thirds of the volume, and it made the archive's lifetime
// depend on how twitchy the display was.
//
// Energy: appending to erased NOR needs no erase, which is what makes this
// affordable — a 16-byte program costs a fraction of a mC against a 45-112mC
// display refresh.
//
// The base snapshot dominates, and it is PPK2-MEASURED on an ESP32-E rather
// than estimated (docs/notes.md): **170ms at 41.94mA = 7.14mC** (23.6mJ at
// 3.3V). Of that, ~13mA over baseline is the flash itself (2.2mC) and the rest
// is the awake time the write forces (4.9mC) — unavoidable, since programming
// runs with the CPU up and the cache disabled.
//
// **The archive's recovery-point objective is one hour**, and the journal alone
// provides it: an hourly entry reaches flash as its hour finalizes, so the most
// any failure costs is the hour in progress. The base snapshot does not improve
// that and is not what the RPO rests on.
//
// The snapshot earns its keep elsewhere — it holds the only copy of the 24h
// sparkline, it is the anchor restore cannot proceed without, and it bounds
// journal replay. One per 24 records plus one per successful NTP resync is
// 7mC/day, **0.1%** of this rig's ~7.1C/day. Hourly would be 171mC/day (2.4%),
// every wake 514mC/day (7.2%).

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#include "Display.h"      // HourlyEntry, DRIFT_PPM_HIST_SIZE
#include "RtcHistory.h"

// NTP/drift state persisted alongside the history. Fixed-width throughout: this
// is an on-flash layout, and the host decoder in tools/history.py mirrors it.
// docs/clock-drift.md notes these die on every flash today — this is what fixes
// that, and what lets the drift collection run survive a reflash.
struct __attribute__((packed)) HistoryDriftState {
  int32_t  resync_interval_s;
  int32_t  last_drift_ms;
  int32_t  last_drift_window_s;
  int64_t  last_sync_time;
  uint16_t resync_fail_count;
  uint8_t  drift_ppm_count;
  uint8_t  rsvd;
  int16_t  drift_ppm_hist[DRIFT_PPM_HIST_SIZE];
  uint16_t drift_win_min[DRIFT_PPM_HIST_SIZE];
  // Build that wrote the most recent snapshot. The store header's git_hash is
  // stamped once at store_format() and never rewritten, so on a device that has
  // since been reflashed it names a build that may no longer exist on any
  // branch — it says how the partition was created, not what produced the data.
  // This rides in the drift block because that is the one part of the snapshot
  // with a size descriptor and zero-fill on short reads, so appending here does
  // not bump HS_FORMAT. Empty on snapshots written before this field existed.
  char     git_hash[16];
};

// One clock-drift observation, journaled per successful resync (<=1/day).
// Counters are stored ABSOLUTE so the host computes day-over-day deltas — the
// duty-cycle and self-heating correlates docs/clock-drift.md wants — without
// any new RTC variable.
struct HistoryDriftSample {
  time_t   sync_time;
  int32_t  drift_ms;
  int32_t  window_s;
  int16_t  ppm;
  int16_t  ambient_mean_x10;
  uint16_t ambient_hours;   // hours actually averaged; < window/3600 means clipped
  uint32_t boot_count;
  uint32_t refresh_count;
};

// Why the archive is not recording, for the status line. A disabled archive is
// silent by nature — the device keeps measuring and displaying perfectly well
// while permanently losing every hour it should have kept — and the only other
// signal is a serial log line that DISABLE_SERIAL removes from release builds.
// So it has to reach the panel.
enum HistoryStoreFault : uint8_t {
  HS_FAULT_NONE = 0,
  HS_FAULT_NO_PARTITION,    // old partition table, no `history` entry
  HS_FAULT_FOREIGN_FORMAT,  // on-flash format this firmware cannot read
  HS_FAULT_IO,              // erase or write failed
};

// Zero once the store is up. Meaningful only after history_store_available().
uint8_t history_store_fault(void);
uint16_t history_store_flash_format(void);  // on-flash format for FOREIGN_FORMAT

// True when the store is usable (partition present and initialized).
// Board family, e.g. "thermometer_c6". Lives here because the archive header
// stamps it (and bounds it to 24 bytes), but it is board identity rather than
// archive state — the DHCP hostname uses it too, so the router's device list
// and a harvested image can never name the same board differently.
const char *history_store_board_name(void);

bool history_store_available(void);

// Rebuild `out` (and `drift`, if non-null) from the newest base snapshot plus
// the journal records written after it. Returns false if there is nothing
// valid to restore, leaving both untouched.
//
// Pass out=nullptr to load only the drift block — it skips the 6.3KB read and
// the journal replay, so the caller needs no RtcHistory-sized buffer.
//
// Deliberately independent of the wall clock: the snapshot is internally
// self-consistent, and a first-boot NTP failure is permanent today
// (on_first_boot() runs only at boot_count==1 and maybe_ntp_resync() returns
// early while !ntp_synced), so gating the restore on a plausible clock would
// mean it often never fires at all.
bool history_store_restore(RtcHistory *out, HistoryDriftState *drift);

// Append one record. Cheap (single page program, no erase); safe to call on
// every wake that produces data. min/max ride along with avg at no cost — the
// record is 16 bytes either way — and the display needs them for the min/max
// envelope and the derived daily extremes.
void history_store_append_hourly(time_t hour_start, const HourlyEntry *entry);
void history_store_append_drift(const HistoryDriftSample *s);

// Request a base snapshot at the next flush. Called after a successful NTP
// resync so the drift state is persisted promptly. It is not what bounds the
// data at risk — the store's own 24-record rule does that, because the resync
// interval is adaptive and an accurate clock stretches it to 28 days.
void history_store_mark_base_dirty(void);

// Perform any deferred flash work. Call once, from start_deep_sleep(), so all
// of it lands at a single point that is easy to isolate on the PPK2.
void history_store_flush(const RtcHistory *hist, const HistoryDriftState *drift,
                        time_t now);
