#pragma once

#include <time.h>
#include <stdint.h>

// A single temperature reading with timestamp, for the 24h sparkline.
// uint32_t (not time_t) + packed = 6 bytes per entry, so 320 entries fit in
// the same RTC slow memory as 192 did at 10 bytes. Good until 2106.
struct __attribute__((packed)) TempReading {
  uint32_t timestamp;  // unix time
  int16_t temp_x10;    // temperature * 10, e.g. 223 = 22.3°C
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

#define TEMP_HISTORY_SIZE 320
#define HOURLY_HISTORY_SIZE 720  // 30 days × 24 hours/day

// Retained clock-drift rates (ppm, one per successful NTP resync) with the
// window each was measured over. Enough to tell a stable oscillator error from
// a wandering one without waiting for a month of resyncs; at the 1-day floor
// this is a week of history.
#define DRIFT_PPM_HIST_SIZE 6

// Shortest window worth keeping a rate from. The drift is derived from a
// whole-second clock, so a sample's noise floor is ~1s/window: 12ppm over a
// day, 280ppm over an hour — the latter is the same size as the spread we're
// trying to measure. In practice the resync interval floor (1 day) keeps
// windows well above this.
#define DRIFT_MIN_WINDOW_S (6 * 3600)

// Breadcrumb checkpoints for crash forensics. Thermometer.cpp stamps the
// current stage into RTC_NOINIT as the wake progresses; after an abnormal
// reset the surviving value says what the firmware was doing when it died.
// Order matters only for the renderer's name table.
enum CrashStage : uint8_t {
  STAGE_NONE = 0,
  STAGE_BOOT,      // early setup, first-boot init
  STAGE_ULP_READ,  // reading the ULP/LP core sample
  STAGE_SENSOR,    // digital sensor read
  STAGE_NTP,       // WiFi/NTP resync
  STAGE_RENDER,    // display clear/refresh (incl. busy-wait light sleep)
  STAGE_LP_INIT,   // (re)loading the ULP/LP program
  STAGE_SLEEP,     // entering deep sleep
  STAGE_USB_WINDOW,// parked awake for a USB host instead of sleeping
};

// Sentinel value for hours with no readings (e.g., gap after device restart).
// Check with: entry.min_x10 == HOURLY_NO_DATA
#define HOURLY_NO_DATA ((int16_t)0x8000)

// Initial min/max sentinel values for temperature accumulators (x10 scale).
// Any real reading will be below/above these, so the first reading always wins.
#define TEMP_INIT_MIN_X10  ((int16_t) 9990)   //  999.0 C
#define TEMP_INIT_MAX_X10  ((int16_t)-9990)   // -999.0 C

// Data needed by the display — passed by value/pointer to avoid
// coupling the display module to Thermometer's RTC globals.
struct DisplayStats {
  int boot_count;
  int previous_boot_count;
  int display_refresh_count;
  uint32_t lp_wake_count;   // cumulative LP core wakes (0 if no ULP support)
  uint32_t lp_error_count;  // cumulative LP I2C failures
  int32_t  last_lp_error;   // esp_err_t of most recent LP failure
  uint32_t last_lp_op;      // 0=none, 1=write/trigger, 2=data read
  time_t first_boot_time;
  time_t next_clear_time;
  uint32_t max_battery_mv;
  uint32_t bad_pin27_count;
  bool ulp_supported;
  int wake_cause;      // 0=unknown, 1=ULP, 2=timer (for footer debug)
  bool wifi_ok;        // true if WiFi connected on first boot
  bool ntp_synced;     // true if NTP time sync succeeded
  bool sensor_ok;      // false if last sensor read had an error/fallback
  bool dummy_sensor;   // true if USE_DUMMY_SENSOR is defined
  bool mock_data;      // true if MOCK_DISPLAY_DATA is defined
  bool power_efficient; // true if build has no debug power drains (serial off, long sleep, no PPK2)
  uint8_t experiment_arm; // EXPERIMENT_ARM: nonzero means this device is running a
                          // pinned-cadence bench arm, not field behaviour. Same value
                          // is journaled per drift record, so screen and archive agree.
  bool usb_window;     // true while held awake for a USB host: the port is
                       // enumerated and the reading carries CPU self-heating
  int32_t clock_drift_ms;    // drift at last NTP resync (positive = clock ahead), 0 = no resync yet
  int32_t drift_window_s;    // measured span the drift accumulated over (since the clock was last set)
  time_t  last_sync_time;    // wall-clock of last successful NTP sync (0 = never)
  uint16_t resync_fail_count; // resync attempts failed since the last success (0 = healthy)
  uint8_t  archive_fault;     // HistoryStoreFault; nonzero = nothing is being archived
  uint16_t archive_flash_format;  // on-flash format, when archive_fault says it is foreign
  const int16_t *drift_ppm_hist;  // rate of each retained resync, newest last
  const uint16_t *drift_win_min;  // window each rate was measured over, minutes
  uint8_t drift_ppm_count;        // valid entries (0..DRIFT_PPM_HIST_SIZE)

  // Temperature context
  float previous_temp;
  float min_temp;
  float max_temp;

  // 24h sparkline history (linear, oldest first)
  const TempReading *temp_history;
  uint16_t history_count;  // number of valid entries (0..TEMP_HISTORY_SIZE)

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

  // ULP re-init tracking. Healthy is exactly 1 (first boot); the footer shows
  // "uN" when > 1, meaning LP/ULP counters are being wiped in the field.
  uint32_t ulp_reinit_count;
  // Raw wakeup-cause bitmap at boot (IDF 6) — rendered as "w:?<hex>" when it
  // contains only causes app_wakeup_cause() doesn't map.
  uint32_t wake_causes_raw;

  // Crash forensics, from the RTC_NOINIT CrashLog (survives panic/WDT/
  // brownout resets — unlike RTC_DATA, which the bootloader reinitializes
  // on any reset that isn't a deep-sleep wake). All zero when healthy.
  uint8_t  crash_count;        // abnormal resets since power-on
  uint8_t  crash_stage;        // CrashStage reached before the latest death
  char     crash_reason[8];    // short reset-reason name ("PANIC", "TWDT", ...)
  int32_t  crash_boot_count;   // boot_count of the boot that died
  uint32_t crash_time;         // epoch stamped shortly before death (0 = unknown)
  uint32_t crash_pc;           // coredump exception PC (0 = no dump harvested)
  char     crash_task[16];     // coredump crashed task name
  char     crash_elf_sha[9];   // first 8 hex chars of the crashing build's
                               // ELF SHA256 — pairs the PC with the right ELF
};

// Panel health, inferred from the BUSY line during the last refresh.
//
// This is the one fault the status line cannot report, because the panel is what
// broke — so it goes to the LED and the console instead. BUSY is also the only
// evidence available: the DESPI-C02 wiring carries no MISO, so nothing about the
// panel can be read back. It proves the controller is alive and clocking, NOT
// that pixels changed — a damaged panel that still drives BUSY reads as healthy.
enum DisplayFault : uint8_t {
  DISPLAY_FAULT_NONE = 0,
  DISPLAY_FAULT_BUSY_IDLE,   // BUSY never asserted: nothing is answering
  DISPLAY_FAULT_BUSY_STUCK,  // BUSY never released: panel absent, or its rail is off
};

// Verdict on the refresh just performed. Meaningful only after one of the
// display_* calls below has run; DISPLAY_FAULT_NONE before that.
uint8_t display_fault();

#ifdef EPD_PROBE
// Bench probe (EPD_PROBE builds only): dump whatever the panel drives back on the
// data line. Call only with the panel powered and initialised.
void display_probe_readback(const char *when);
#endif

// Poll the panel's BUSY line with plain delays instead of light sleep. Light
// sleep gates the USB PHY clock, and the port may not re-enumerate afterwards
// without replugging the cable — so a refresh that happens while a USB host is
// being served must not use it. Costs the light-sleep saving for those refreshes,
// which only ever run on USB power.
void display_set_busy_wait_plain(bool plain);

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
