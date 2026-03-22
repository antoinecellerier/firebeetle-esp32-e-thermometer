#pragma once

#include <time.h>
#include <stdint.h>

// A single temperature reading with timestamp, for the 24h sparkline.
struct TempReading {
  time_t timestamp;
  int16_t temp_x10;  // temperature * 10, e.g. 223 = 22.3°C
};

// Min/max temperature summary for a single day, for the 30-day range chart.
struct DailySummary {
  int16_t min_x10;
  int16_t max_x10;
  uint8_t day;    // day of month (1-31)
  uint8_t month;  // month (1-12)
};

#define TEMP_HISTORY_SIZE 96
#define DAILY_HISTORY_SIZE 31

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
  int wake_cause;  // 0=unknown, 1=ULP, 2=timer, 3=other (for footer debug)

  // Temperature context
  float previous_temp;
  float min_temp;
  float max_temp;

  // 24h sparkline history (circular buffer)
  const TempReading *temp_history;
  uint8_t history_count;  // number of valid entries (0..TEMP_HISTORY_SIZE)
  uint8_t history_start;  // index of oldest entry in circular buffer

  // 30-day daily summary (circular buffer)
  const DailySummary *daily_history;
  uint8_t daily_count;    // number of valid entries (0..DAILY_HISTORY_SIZE)
  uint8_t daily_start;    // index of oldest entry in circular buffer
  int16_t today_min_x10;  // in-progress current day min
  int16_t today_max_x10;  // in-progress current day max
  uint8_t today_day;      // current day of month
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
                                const struct tm *nowtm,
                                const DisplayStats &stats);
