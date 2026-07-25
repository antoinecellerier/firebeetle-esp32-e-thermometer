#pragma once

// The temperature history block held in RTC slow memory.
//
// Lives in its own header because two translation units need the layout:
// Thermometer.cpp owns the instance, and HistoryStore.cpp serializes it to the
// `history` flash partition.
//
// RTC memory survives deep sleep but NOT power-on reset (firmware upload,
// battery swap, reset button). More precisely: the bootloader reloads
// .rtc.data and startup zeroes .rtc.bss on ANY reset that isn't a deep-sleep
// wake (esp_image_format.c / cpu_start.c) — so RTC_DATA_ATTR state, including
// boot_count and all history, does not survive a panic/WDT/brownout reset
// either. .rtc_noinit is exempt from both, which is what CrashLog relies on;
// it dies only with the RTC power domain (battery swap, or the FireBeetle's
// reset button, whose circuit power-cycles RTC). HistoryStore is what makes
// the history itself outlive all of those.
//
// History is grouped in a struct with a version tag and self_addr field.
// The self_addr detects if the linker moved the struct (e.g. due to
// adding/removing other RTC variables). On power-on reset, .rtc.data is
// zeroed, version won't match, and history is reinitialized cleanly.
//
// Bump RTC_HISTORY_VERSION when changing anything inside RtcHistory
// (struct fields, buffer sizes, semantics). A bump alone does not discard the
// flash archive: HistoryStore stores the buffer geometry and accepts a stored
// payload shorter than the running struct, so appending a field stays
// non-destructive.

#include <stdint.h>
#include <time.h>

#include "Display.h"  // TempReading, HourlyEntry, *_HISTORY_SIZE

#define RTC_HISTORY_VERSION 0xDA050003

// History data — new fields must be added at the END (and bump
// RTC_HISTORY_VERSION). The self_addr field detects if the linker moved
// the struct between firmware versions.
struct RtcHistory {
  uint32_t version;
  uint32_t self_addr;  // &historical_data at init time; detects address shifts

  // 24h sparkline (linear, oldest first — see TempHistory.h)
  TempReading temp[TEMP_HISTORY_SIZE];
  uint16_t temp_count;

  // 30-day hourly chart (circular buffer, one entry per clock hour)
  HourlyEntry hourly[HOURLY_HISTORY_SIZE];
  uint16_t hourly_count;
  uint16_t hourly_idx;
  time_t hourly_latest_time;

  // In-progress hour accumulator (finalized on hour boundary)
  time_t current_hour_start;
  int32_t  current_hour_sum_x10;
  uint16_t current_hour_sample_count;
  int16_t  current_hour_min_x10;
  int16_t  current_hour_max_x10;
};

// Wall-clock values below this are treated as "clock not set" — the RTC timer
// starts at the epoch and NTP may never have landed. 2024-01-01T00:00:00Z.
// Deliberately NOT the `ntp_synced` flag: that is false after a reflash even
// though the RTC timer kept correct time across it.
#define TIME_PLAUSIBLE_EPOCH ((time_t)1704067200)
static inline bool time_is_plausible(time_t t) { return t >= TIME_PLAUSIBLE_EPOCH; }
