#pragma once

#include <time.h>
#include <stdint.h>

// A single temperature reading with timestamp, for the 24h sparkline.
struct TempReading {
  time_t timestamp;
  int16_t temp_x10;  // temperature * 10, e.g. 223 = 22.3°C
};

// Finalized hourly temperature entry for the 30-day chart.
// Each entry summarizes all temperature readings within one clock hour.
// Min/max capture transient events (window opens, sun/shadow, wind) while
// avg tracks the underlying trend. On large displays this enables a continuous
// temperature curve with a volatility envelope showing daily cycles over 30 days.
// On small displays, daily min/max/avg are derived from these entries at render time.
struct HourlyEntry {
  int16_t min_x10;  // minimum temperature × 10 during this hour
  int16_t max_x10;  // maximum temperature × 10 during this hour
  int16_t avg_x10;  // average temperature × 10 (from accumulated readings)
};

#define TEMP_HISTORY_SIZE 96
#define HOURLY_HISTORY_SIZE 720  // 30 days × 24 hours/day

// Sentinel value for hours with no readings (e.g., gap after device restart).
// Check with: entry.min_x10 == HOURLY_NO_DATA
#define HOURLY_NO_DATA ((int16_t)0x8000)

// Data needed by the display — passed by value/pointer to avoid
// coupling the display module to Thermometer's RTC globals.
struct DisplayStats {
  int boot_count;
  int previous_boot_count;
  int display_refresh_count;
  time_t first_boot_time;
  time_t next_clear_time;
  uint32_t max_battery_mv;
  uint32_t bad_pin27_count;
  bool ulp_supported;
  int wake_cause;      // 0=unknown, 1=ULP, 2=timer (for footer debug)
  bool wifi_ok;        // true if WiFi connected on first boot
  bool ntp_synced;     // true if NTP time sync succeeded
  bool sensor_ok;      // false if last sensor read had an error/fallback

  // Temperature context
  float previous_temp;
  float min_temp;
  float max_temp;

  // 24h sparkline history (circular buffer)
  const TempReading *temp_history;
  uint8_t history_count;  // number of valid entries (0..TEMP_HISTORY_SIZE)
  uint8_t history_start;  // index of oldest entry in circular buffer

  // 30-day hourly history (circular buffer, one entry per clock hour).
  // Each entry's wall-clock time is derived from hourly_latest_time:
  // entry at position i (0=oldest, hourly_count-1=newest) corresponds to
  // hourly_latest_time - (hourly_count - 1 - i) * 3600.
  // Sentinel entries (min_x10 == HOURLY_NO_DATA) mark hours without readings.
  const HourlyEntry *hourly_history;
  uint16_t hourly_count;       // valid entries (0..HOURLY_HISTORY_SIZE)
  uint16_t hourly_start;       // index of oldest entry in circular buffer
  time_t hourly_latest_time;   // wall-clock start-of-hour of the newest finalized entry

  // In-progress current hour (not yet finalized into hourly_history).
  // Displayed as the rightmost data point on the monthly chart.
  HourlyEntry current_hour_entry;
  bool has_current_hour;       // true if accumulator has at least one reading
};

// Clear the e-paper to white and hibernate.
void display_clear();

// Show temperature, battery level, charts, and stats overlay.
void display_show_temperature(float temp, uint32_t battery_mv, bool low_battery,
                              time_t now, const struct tm *nowtm,
                              const DisplayStats &stats);

// Show "Read pin27 == 0" diagnostic before permanent shutdown.
void display_show_pin27_diagnostic(int boot_count);

// Show empty battery warning with stats before permanent shutdown.
void display_show_empty_battery(uint32_t battery_mv, time_t now,
                                const DisplayStats &stats);
