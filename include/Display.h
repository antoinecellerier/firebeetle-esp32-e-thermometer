#pragma once

#include <time.h>
#include <stdint.h>

// Data needed by the stats overlay — passed by value to avoid
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
};

// Clear the e-paper to white and hibernate.
void display_clear();

// Show temperature, battery level, and stats overlay.
void display_show_temperature(float temp, uint32_t battery_mv, bool low_battery,
                              time_t now, const struct tm *nowtm,
                              const DisplayStats &stats);

// Show "Read pin27 == 0" diagnostic before permanent shutdown.
void display_show_pin27_diagnostic(int boot_count);

// Show empty battery warning with stats before permanent shutdown.
void display_show_empty_battery(uint32_t battery_mv, time_t now,
                                const struct tm *nowtm,
                                const DisplayStats &stats);
