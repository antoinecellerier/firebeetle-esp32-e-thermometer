#include "app_common.h"

// needed for setenv and tzset :-/
#undef __STRICT_ANSI__
#include "time.h"
#include "stdlib.h"

#include "esp_sleep.h"
#include "esp_log.h"
#include "esp_system.h"  // esp_reset_reason
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include <math.h>
#include <string.h>
#ifdef CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH
#include "esp_core_dump.h"
#endif
#ifndef DISABLE_WIFI
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "freertos/event_groups.h"
#endif

#include "Display.h"
#include "TempHistory.h"

// Used for JTAG. Avoid for other purposes if possible
// Firebeetle Pin | JTAG PIN
//            12  |  TDI
//            13  |  TCK
//            14  |  TMS
//            15  |  TDO
// JTAG init and deep sleep don't seem to play well together
// openocd errors when trying to init JTAG during deep sleep:
//   Error: JTAG scan chain interrogation failed: all ones
//   Error: Check JTAG interface, timings, target power, etc.
//   Error: Trying to use configured scan chain anyway...
//   Error: esp32.cpu0: IR capture error; saw 0x1f not 0x01
// when that error is hit you might need to kill the openocd process even if debugging is stopped in VS code
// Repro cmd
// ~/.platformio/packages/tool-openocd-esp32/bin/openocd -s ~/.platformio/packages/tool-openocd-esp32 -c "gdb_port pipe; tcl_port disabled; telnet_port disabled" -s ~/.platformio/packages/tool-openocd-esp32/share/openocd/scripts -f interface/ftdi/esp32_devkitj_v1.cfg -f board/esp-wroom-32.cfg -c "adapter_khz 5000"

#if defined(USE_DS18B20_PAR)
  #include "sensors/DS18B20Sensor.hpp"
  DS18B20Sensor sensor;
#elif defined(USE_BMP390L)
  #include "sensors/BMP390LSensor.hpp"
  BMP390LSensor sensor;
#elif defined(USE_BMP58x)
  #include "sensors/BMP58xSensor.hpp"
  BMP58xSensor sensor;
#elif defined(USE_DUMMY_SENSOR)
  #include "sensors/DummySensor.hpp"
  DummySensor sensor;
#else
  #error "Unknown sensor type"
#endif

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
void ulp_check_data_overlap();
#endif

#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
#include "ulp_main.h"  // exposes ulp_lp_wake_count and other LP-core globals
#endif

// --- RTC memory layout ---
// RTC memory survives deep sleep but NOT power-on reset (firmware upload,
// battery swap, reset button). More precisely: the bootloader reloads
// .rtc.data and startup zeroes .rtc.bss on ANY reset that isn't a deep-sleep
// wake (esp_image_format.c / cpu_start.c) — so RTC_DATA_ATTR state, including
// boot_count and all history, does not survive a panic/WDT/brownout reset
// either. .rtc_noinit is exempt from both, which is what CrashLog (below)
// relies on; it dies only with the RTC power domain (battery swap, or the
// FireBeetle's reset button, whose circuit power-cycles RTC).
//
// History is grouped in a struct with a version tag and self_addr field.
// The self_addr detects if the linker moved the struct (e.g. due to
// adding/removing other RTC variables). On power-on reset, .rtc.data is
// zeroed, version won't match, and history is reinitialized cleanly.
//
// Bump RTC_HISTORY_VERSION when changing anything inside RtcHistory
// (struct fields, buffer sizes, semantics).
// Bump RTC_STATE_VERSION when changing operational state variables below.
#define RTC_HISTORY_VERSION 0xDA050003
#define RTC_STATE_VERSION   0xDA050003

// Initial min/max temperature sentinels (float).
// Any real reading will replace these on first comparison.
#define TEMP_INIT_MIN  999.0f
#define TEMP_INIT_MAX (-999.0f)

// Minimum temperature change (C) to trigger a display refresh
#define DISPLAY_TEMP_DELTA 0.1f

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
RTC_DATA_ATTR RtcHistory historical_data;

// Operational state — changes here are caught by self_addr if the linker
// shifts historical_data, and by RTC_STATE_VERSION for format changes.
RTC_DATA_ATTR uint32_t rtc_state_version = 0;

RTC_DATA_ATTR int boot_count = 0;
RTC_DATA_ATTR int display_refresh_count = 0;

// InitializeUlp() calls this power cycle. Healthy value is exactly 1 (first
// boot); anything higher means ULP/LP state (wake counters, delta reference)
// is being wiped in the field — rendered as "uN" in the footer when > 1.
RTC_DATA_ATTR uint32_t ulp_reinit_count = 0;

// Wakeup cause, cached before anything can light-sleep: esp_sleep reports the
// cause of the MOST RECENT sleep, and the EPD busy-wait light sleep
// (epd_busy_light_sleep) replaces the deep-sleep cause with its GPIO wake.
// Querying live after a display refresh misread every refresh boot as a fresh
// boot and reloaded the LP core each time (wiping its counters and delta
// reference). Always use these, never app_wakeup_cause(), past setup() entry.
static esp_sleep_wakeup_cause_t s_wake_cause = ESP_SLEEP_WAKEUP_UNDEFINED;
static uint32_t s_wake_causes_raw = 0;

// --- Crash forensics -------------------------------------------------------
// Lives in .rtc_noinit: the only RTC storage that survives panic/WDT/brownout
// resets (see RTC memory layout comment above). Breadcrumbs (stage,
// cur_boot_count, cur_time) are stamped while running; the first boot after
// an abnormal reset copies them into the last_* fields and, when a flash
// coredump is present, harvests the exception PC + task name. Garbage after a
// true power-on — guarded by the magic word. Rendered by the "! <reason>"
// status indicator until the next RTC power cycle.
#define CRASH_LOG_MAGIC 0xC0DEB008  // bump when CrashLog layout changes
struct CrashLog {
  uint32_t magic;
  // Live breadcrumbs, stamped as the current wake progresses
  uint8_t  stage;            // CrashStage checkpoint (Display.h)
  uint8_t  unused0;
  uint16_t unused1;
  int32_t  cur_boot_count;
  uint32_t cur_time;         // epoch, stamped once wall clock is known
  // Harvested on the first boot after an abnormal reset
  uint8_t  crash_count;      // abnormal resets since RTC power-on
  uint8_t  last_reason;      // esp_reset_reason_t
  uint8_t  last_stage;
  uint8_t  unused2;
  int32_t  last_boot_count;
  uint32_t last_time;
  uint32_t pc;               // coredump exception PC (0 = none)
  char     task[16];         // coredump crashed task name
  char     elf_sha[9];       // first 8 hex chars of the crashing app's ELF
                             // SHA256 — identifies which build to addr2line
};
RTC_NOINIT_ATTR static CrashLog crash_log;

static const char *reset_reason_str(uint8_t r)
{
  switch (r)
  {
    case ESP_RST_SW:         return "SW";
    case ESP_RST_PANIC:      return "PANIC";
    case ESP_RST_INT_WDT:    return "IWDT";
    case ESP_RST_TASK_WDT:   return "TWDT";
    case ESP_RST_WDT:        return "WDT";
    case ESP_RST_BROWNOUT:   return "BROWN";
    case ESP_RST_EFUSE:      return "EFUSE";
    case ESP_RST_PWR_GLITCH: return "GLITCH";
    case ESP_RST_CPU_LOCKUP: return "LOCKUP";
    default:                 return "RST";
  }
}

// Copy PC + task name out of a flash coredump into crash_log, then erase the
// dump so a stale one is never re-harvested after a later dump-less reset
// (e.g. RTC WDT, where the panic handler never ran).
static void harvest_coredump_summary()
{
  crash_log.pc = 0;
  crash_log.task[0] = '\0';
  crash_log.elf_sha[0] = '\0';
#ifdef CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH
  esp_core_dump_summary_t *sum =
      (esp_core_dump_summary_t *)calloc(1, sizeof(*sum));
  if (sum == NULL)
    return;
  if (esp_core_dump_get_summary(sum) == ESP_OK)
  {
    crash_log.pc = sum->exc_pc;
    memcpy(crash_log.task, sum->exc_task, sizeof(crash_log.task));
    crash_log.task[sizeof(crash_log.task) - 1] = '\0';
    // Already a hex string in the summary; keep the first 8 chars
    size_t sha_n = strnlen((const char *)sum->app_elf_sha256,
                           sizeof(crash_log.elf_sha) - 1);
    memcpy(crash_log.elf_sha, sum->app_elf_sha256, sha_n);
    crash_log.elf_sha[sha_n] = '\0';
    esp_core_dump_image_erase();
  }
  free(sum);
#endif
}

// Detect and record an abnormal reset. Must run before RTC state is used in
// anger, but after setup_serial() so the LOGI is visible.
static void crash_forensics_on_boot()
{
  esp_reset_reason_t rr = esp_reset_reason();
  if (crash_log.magic != CRASH_LOG_MAGIC)
  {
    // True power-on (or first firmware with CrashLog): noinit RAM is garbage
    memset(&crash_log, 0, sizeof(crash_log));
    crash_log.magic = CRASH_LOG_MAGIC;
  }
  else if (rr != ESP_RST_DEEPSLEEP && rr != ESP_RST_POWERON &&
           rr != ESP_RST_USB && rr != ESP_RST_JTAG && rr != ESP_RST_SDIO)
  {
    // USB/JTAG/SDIO excluded: flash-tool resets, not field crashes
    if (crash_log.crash_count < 255)
      crash_log.crash_count++;
    crash_log.last_reason     = (uint8_t)rr;
    crash_log.last_stage      = crash_log.stage;
    crash_log.last_boot_count = crash_log.cur_boot_count;
    crash_log.last_time       = crash_log.cur_time;
    harvest_coredump_summary();
    LOGI("Abnormal reset #%u: %s at boot %d stage %d pc 0x%x %s",
         (unsigned)crash_log.crash_count, reset_reason_str(crash_log.last_reason),
         (int)crash_log.last_boot_count, (int)crash_log.last_stage,
         (unsigned)crash_log.pc, crash_log.task);
  }
  crash_log.stage = STAGE_BOOT;
}

RTC_DATA_ATTR time_t first_boot_time = 0;
RTC_DATA_ATTR time_t next_clear_time = 0;
const time_t one_day = 86400;

RTC_DATA_ATTR float previous_temp = TEMP_NO_PREVIOUS;
RTC_DATA_ATTR int previous_boot_count = -1;

RTC_DATA_ATTR uint32_t max_battery_mv = 0;

RTC_DATA_ATTR uint32_t bad_pin27_count = 0;

// Min/max temperature since boot
RTC_DATA_ATTR float min_temp_since_boot = TEMP_INIT_MIN;
RTC_DATA_ATTR float max_temp_since_boot = TEMP_INIT_MAX;

// Periodic NTP resync state
RTC_DATA_ATTR time_t next_resync_time = 0;           // when to next attempt NTP resync
RTC_DATA_ATTR int32_t resync_interval_s = 7 * 86400; // current interval (starts at 1 week)
RTC_DATA_ATTR int32_t last_drift_ms = 0;             // drift measured at last resync (positive = clock ahead)
RTC_DATA_ATTR int32_t last_drift_window_s = 0;       // measured span the drift accumulated over (NOT the interval setting: failed attempts stretch it)
RTC_DATA_ATTR time_t last_sync_time = 0;             // wall-clock of last successful NTP sync (0 = never)
RTC_DATA_ATTR uint16_t resync_fail_count = 0;        // failed resync attempts since the last success
// Rate history, newest last. One measurement says how far the clock ran off;
// several say whether the RC oscillator's error is a stable constant (which is
// what drift compensation would need) or wanders with temperature.
RTC_DATA_ATTR int16_t drift_ppm_hist[DRIFT_PPM_HIST_SIZE] = {};
RTC_DATA_ATTR uint16_t drift_win_min[DRIFT_PPM_HIST_SIZE] = {};  // window per rate, for weighting
RTC_DATA_ATTR uint8_t drift_ppm_count = 0;

// Status flags for display error indicators
RTC_DATA_ATTR bool wifi_ok = false;
RTC_DATA_ATTR bool ntp_synced = false;
RTC_DATA_ATTR bool last_sensor_ok = true;

// Update the hourly history buffer with a new temperature reading.
// Called on every main CPU wake (both delta-triggered and safety-net timer).
// When the clock hour changes, the accumulated entry is finalized and appended
// to the circular buffer. Any skipped hours (shouldn't happen normally since
// the safety net wakes every hour) are filled with sentinel entries.
static void update_hourly_history(time_t now, const struct tm *nowtm, float temp)
{
  int16_t temp_x10 = (int16_t)(temp * 10);

  // Compute wall-clock start-of-hour for current local time
  struct tm hour_tm = *nowtm;
  hour_tm.tm_min = 0;
  hour_tm.tm_sec = 0;
  time_t hour_start = mktime(&hour_tm);

  if (historical_data.current_hour_start != 0 && hour_start != historical_data.current_hour_start)
  {
    // Clock hour changed — finalize the completed hour's entry
    HourlyEntry entry;
    entry.min_x10 = historical_data.current_hour_min_x10;
    entry.max_x10 = historical_data.current_hour_max_x10;
    entry.avg_x10 = (historical_data.current_hour_sample_count > 0)
      ? (int16_t)(historical_data.current_hour_sum_x10 / historical_data.current_hour_sample_count)
      : historical_data.current_hour_min_x10;

    historical_data.hourly[historical_data.hourly_idx] = entry;
    historical_data.hourly_idx = (historical_data.hourly_idx + 1) % HOURLY_HISTORY_SIZE;
    if (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
      historical_data.hourly_count++;

    // Fill any skipped hours with the finalized entry's values.
    // Skipped hours mean the ULP safety-net woke but no delta was detected,
    // so temperature was stable — the last known value is the best estimate.
    // Uses time_t difference (UTC-based) so DST transitions are handled
    // correctly — a "spring forward" skip produces one fill, a "fall back"
    // repeat produces hours_elapsed=0 (no fill needed).
    int hours_elapsed = (int)((hour_start - historical_data.current_hour_start) / 3600);
    if (hours_elapsed > HOURLY_HISTORY_SIZE)
      hours_elapsed = HOURLY_HISTORY_SIZE;
    for (int i = 1; i < hours_elapsed; i++)
    {
      historical_data.hourly[historical_data.hourly_idx] = entry;  // repeat last known value
      historical_data.hourly_idx = (historical_data.hourly_idx + 1) % HOURLY_HISTORY_SIZE;
      if (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
        historical_data.hourly_count++;
    }

    // Update reference time: the last written entry's start-of-hour
    historical_data.hourly_latest_time = hour_start - 3600;

    // Reset accumulator for the new hour
    historical_data.current_hour_sum_x10 = 0;
    historical_data.current_hour_sample_count = 0;
    historical_data.current_hour_min_x10 = TEMP_INIT_MIN_X10;
    historical_data.current_hour_max_x10 = TEMP_INIT_MAX_X10;
  }

  // First reading after boot — initialize reference time
  if (historical_data.current_hour_start == 0)
    historical_data.hourly_latest_time = hour_start;

  historical_data.current_hour_start = hour_start;

  // Accumulate reading into current hour's stats
  historical_data.current_hour_sample_count++;
  historical_data.current_hour_sum_x10 += temp_x10;
  if (temp_x10 < historical_data.current_hour_min_x10)
    historical_data.current_hour_min_x10 = temp_x10;
  if (temp_x10 > historical_data.current_hour_max_x10)
    historical_data.current_hour_max_x10 = temp_x10;
}

static void update_temp_extremes(float temp)
{
  if (temp < min_temp_since_boot)
    min_temp_since_boot = temp;
  if (temp > max_temp_since_boot)
    max_temp_since_boot = temp;
}

#ifdef MOCK_DISPLAY_DATA
#include "MockData.h"

static void fill_mock_data(time_t now)
{
  mock_fill_sparkline(now, historical_data.temp, &historical_data.temp_count);
  mock_fill_hourly(now, historical_data.hourly, &historical_data.hourly_count, &historical_data.hourly_idx,
                   &historical_data.hourly_latest_time);

  min_temp_since_boot = 18.5f;
  max_temp_since_boot = 22.8f;
  previous_temp = 22.1f;

  // Set up in-progress hour accumulator with mock values
  struct tm now_tm;
  localtime_r(&now, &now_tm);
  now_tm.tm_min = 0;
  now_tm.tm_sec = 0;
  historical_data.current_hour_start = mktime(&now_tm);
  historical_data.current_hour_sample_count = 3;
  historical_data.current_hour_sum_x10 = 223 * 3;  // 22.3°C × 3 readings
  historical_data.current_hour_min_x10 = 219;      // 21.9°C
  historical_data.current_hour_max_x10 = 228;      // 22.8°C
}
#endif

DisplayStats make_display_stats()
{
  // Compute circular buffer start index (oldest entry)
  uint16_t hourly_start = (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
    ? 0
    : historical_data.hourly_idx;

  // Map ESP-IDF wake cause to a portable int for display
  int wake = (s_wake_cause == ESP_SLEEP_WAKEUP_ULP) ? 1 :
             (s_wake_cause == ESP_SLEEP_WAKEUP_TIMER) ? 2 : 0;

  // Compute in-progress hour entry from accumulator
  bool has_current = (historical_data.current_hour_sample_count > 0);
  HourlyEntry current_entry = {};
  if (has_current)
  {
    current_entry.min_x10 = historical_data.current_hour_min_x10;
    current_entry.max_x10 = historical_data.current_hour_max_x10;
    current_entry.avg_x10 = (int16_t)(historical_data.current_hour_sum_x10 / historical_data.current_hour_sample_count);
  }

  uint32_t lp_wakes = 0;
  uint32_t lp_errors = 0;
  int32_t  lp_last_err = 0;
  uint32_t lp_last_op = 0;
#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
  // These counters live in the LP core's .bss, which is zeroed only by
  // InitializeUlp() (ulp_lp_core_load_binary() doesn't touch .bss). On a cold
  // boot that runs *after* this render, so the symbols still hold uninitialised
  // SRAM — leave the stats at 0 until an LP/timer wake proves the LP core has
  // run this power cycle. Avoids a phantom "! LP" indicator on the first frame.
  if (wake != 0)
  {
    lp_wakes    = ulp_lp_wake_count;
    lp_errors   = ulp_lp_error_count;
    lp_last_err = (int32_t)ulp_last_lp_error;
    lp_last_op  = ulp_last_lp_op;
  }
#endif

  DisplayStats s = {
    boot_count, previous_boot_count, display_refresh_count,
    lp_wakes, lp_errors, lp_last_err, lp_last_op,
    first_boot_time, next_clear_time, max_battery_mv, bad_pin27_count,
    sensor.SupportsUlp(), wake, wifi_ok, ntp_synced, last_sensor_ok,
#ifdef USE_DUMMY_SENSOR
    true,
#else
    false,
#endif
#ifdef MOCK_DISPLAY_DATA
    true,
#else
    false,
#endif
    // power_efficient: true only when serial is off, sleep interval is
    // production-length, and no debug instrumentation
#if defined(DISABLE_SERIAL) && SLEEP_INTERVAL_S >= 60 && !defined(PPK2_DEBUG)
    true,
#else
    false,
#endif
    last_drift_ms, last_drift_window_s, last_sync_time, resync_fail_count,
    drift_ppm_hist, drift_win_min, drift_ppm_count,
    previous_temp, min_temp_since_boot, max_temp_since_boot,
    historical_data.temp, historical_data.temp_count,
    historical_data.hourly, historical_data.hourly_count, hourly_start,
    historical_data.hourly_latest_time, current_entry, has_current,
    ulp_reinit_count, s_wake_causes_raw,
    0, 0, "", 0, 0, 0, "", ""  // crash fields, assigned below
  };
  s.crash_count = crash_log.crash_count;
  s.crash_stage = crash_log.last_stage;
  snprintf(s.crash_reason, sizeof(s.crash_reason), "%s",
           reset_reason_str(crash_log.last_reason));
  s.crash_boot_count = crash_log.last_boot_count;
  s.crash_time = crash_log.last_time;
  s.crash_pc = crash_log.pc;
  memcpy(s.crash_task, crash_log.task, sizeof(s.crash_task));
  memcpy(s.crash_elf_sha, crash_log.elf_sha, sizeof(s.crash_elf_sha));
  return s;
}

void setup_serial()
{
#ifndef DISABLE_SERIAL
  // The IDF console (UART on the FireBeetle, USB-Serial-JTAG on the C6, per
  // sdkconfig) is ready before app_main — nothing to set up.
  LOGI("Logging to log facilities - info");
#else
  // TODO: update our own logging levels when using JTAG debugging
  esp_log_level_set("*", ESP_LOG_ERROR);
#endif
}

void start_deep_sleep()
{
  if (sensor.SupportsUlp())
  {
    // ULP is polling the sensor — it will wake us when temperature changes
    esp_sleep_enable_ulp_wakeup();
    // Timer safety net for periodic housekeeping (display clear, battery check)
    esp_sleep_enable_timer_wakeup(ULP_SAFETY_NET_US);
    LOGI("Sleeping with ULP wakeup (timer safety net: %d min)", (int)(ULP_SAFETY_NET_US / 60000000ULL));
  }
  else
  {
    esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_INTERVAL_S * 1000000ULL);
    LOGI("Sleeping for %d seconds", SLEEP_INTERVAL_S);
  }
  fflush(stdout);
  PPK2_CPU_ACTIVE_LOW();
  crash_log.stage = STAGE_SLEEP;
  esp_deep_sleep_start();
}

void get_time(time_t *now, struct tm *nowtm)
{
  setenv("TZ", MY_TZ, 1);
  tzset();
  time(now);
  localtime_r(now, nowtm);
}

#ifndef DISABLE_WIFI
// Connect to WiFi with timeout. Returns true on success.
static const uint32_t WIFI_TIMEOUT_MS = 15000;

static EventGroupHandle_t s_wifi_events;
static esp_event_handler_instance_t s_wifi_handler, s_ip_handler;
static volatile bool s_wifi_stopping = false;
#define WIFI_CONNECTED_BIT BIT0

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START)
    esp_wifi_connect();
  else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED)
  {
    // Keep retrying until the timeout in wifi_connect() expires
    if (!s_wifi_stopping)
      esp_wifi_connect();
  }
  else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP)
    xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
}

// Radio fully off before deep sleep (matches former WiFi.disconnect(true, true)).
// Handlers unregister before deinit and the stopping flag stays set throughout,
// so a late STA_DISCONNECTED can't call esp_wifi_connect() on a dead driver.
static void wifi_disconnect()
{
  s_wifi_stopping = true;
  esp_wifi_stop();
  if (s_wifi_handler)
  {
    esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, s_wifi_handler);
    s_wifi_handler = nullptr;
  }
  if (s_ip_handler)
  {
    esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, s_ip_handler);
    s_ip_handler = nullptr;
  }
  esp_wifi_deinit();
  s_wifi_stopping = false;
}

static bool wifi_connect()
{
  esp_err_t err = nvs_flash_init(); // esp_wifi_init() requires NVS
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
  {
    nvs_flash_erase();
    err = nvs_flash_init();
  }
  if (err != ESP_OK)
  {
    LOGI("NVS init failed: 0x%x", err);
    return false;
  }

  // Degrade to "NO WIFI" on any init failure (the Arduino path never aborted);
  // a panic here would boot-loop a battery device instead of rendering a frame.
#define WIFI_TRY(x)                                        \
  do {                                                     \
    esp_err_t _e = (x);                                    \
    if (_e != ESP_OK)                                      \
    {                                                      \
      LOGI("WiFi setup failed (%s): " #x, esp_err_to_name(_e)); \
      wifi_disconnect();                                   \
      return false;                                        \
    }                                                      \
  } while (0)

  WIFI_TRY(esp_netif_init());
  err = esp_event_loop_create_default();
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) // INVALID_STATE = already created
  {
    LOGI("Event loop creation failed: 0x%x", err);
    return false;
  }
  static esp_netif_t *sta_netif = nullptr;
  if (!sta_netif)
    sta_netif = esp_netif_create_default_wifi_sta();
  if (!sta_netif)
  {
    LOGI("WiFi setup failed: no STA netif");
    return false;
  }

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  WIFI_TRY(esp_wifi_init(&cfg));

  if (!s_wifi_events)
    s_wifi_events = xEventGroupCreate();
  xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
  WIFI_TRY(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                               &wifi_event_handler, nullptr, &s_wifi_handler));
  WIFI_TRY(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                               &wifi_event_handler, nullptr, &s_ip_handler));

  wifi_config_t wcfg = {};
  strncpy((char *)wcfg.sta.ssid, MY_WIFI_SSID, sizeof(wcfg.sta.ssid) - 1);
  strncpy((char *)wcfg.sta.password, MY_WIFI_PASSWORD, sizeof(wcfg.sta.password) - 1);
  WIFI_TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM)); // reconfigured every boot; skip NVS writes
  WIFI_TRY(esp_wifi_set_mode(WIFI_MODE_STA));
  WIFI_TRY(esp_wifi_set_config(WIFI_IF_STA, &wcfg));
  WIFI_TRY(esp_wifi_start());
#undef WIFI_TRY

  LOGI("Waiting for WiFi");
  EventBits_t bits = xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT,
                                         pdFALSE, pdFALSE, pdMS_TO_TICKS(WIFI_TIMEOUT_MS));
  if (!(bits & WIFI_CONNECTED_BIT))
  {
    LOGI("WiFi connection timed out after %u ms", (unsigned)WIFI_TIMEOUT_MS);
    wifi_disconnect();
    return false;
  }
  return true;
}

// One-shot SNTP sync: fresh instance, wait for a genuinely new time response.
static bool sntp_sync_once(uint32_t timeout_ms)
{
  esp_sntp_config_t scfg = {};
  scfg.start = true;
  scfg.wait_for_sync = true;
  scfg.num_of_servers = 1;
  scfg.servers[0] = "pool.ntp.org";
#if CONFIG_LWIP_SNTP_MAX_SERVERS >= 2
  scfg.num_of_servers = 2;
  scfg.servers[1] = "time.google.com";
#endif
  if (esp_netif_sntp_init(&scfg) != ESP_OK)
    return false;
  bool ok = (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(timeout_ms)) == ESP_OK);
  esp_netif_sntp_deinit();
  return ok;
}

// Minimum resync interval (1 day) — floor to avoid hammering WiFi
#define RESYNC_INTERVAL_MIN  (86400)
// Maximum resync interval (4 weeks)
#define RESYNC_INTERVAL_MAX  (28 * 86400)

// Attempt NTP resync if due. Measures clock drift and adjusts next interval.
static void maybe_ntp_resync(time_t now)
{
  if (!ntp_synced)
    return;  // never synced — nothing to resync against
  if (next_resync_time == 0)
  {
    // First call after boot — schedule initial resync
    next_resync_time = now + resync_interval_s;
    return;
  }
  if (now < next_resync_time)
    return;

  LOGI("NTP resync: connecting to WiFi");
  if (!wifi_connect())
  {
    resync_fail_count++;
    LOGI("NTP resync: WiFi failed (%u in a row), deferring to next scheduled resync",
         (unsigned)resync_fail_count);
    next_resync_time = now + resync_interval_s;
    return;
  }

  // Capture pre-sync time for drift measurement
  time_t before_sync;
  time(&before_sync);

  // Fresh SNTP instance waits for a genuinely new time response. The clock is
  // already set (just drifted), so anything that returns early on a valid-
  // looking clock would measure ~0 drift and never actually correct it.
  if (!sntp_sync_once(30000U))
  {
    resync_fail_count++;
    LOGI("NTP resync: sync failed (%u in a row), deferring to next scheduled resync",
         (unsigned)resync_fail_count);
    wifi_disconnect();
    next_resync_time = now + resync_interval_s;
    return;
  }

  time_t after_sync;
  time(&after_sync);

  // Window the drift accumulated over: since the clock was last *set* (boot
  // sync or a previous successful resync), not since the last attempt. Failed
  // attempts re-arm at +resync_interval_s, so the interval setting understates
  // the span by a whole multiple after every failure.
  time_t last_set = (last_sync_time > 0) ? last_sync_time : first_boot_time;
  last_drift_window_s = (int32_t)(before_sync - last_set);
  last_sync_time = after_sync;

  // Drift = what the clock said before sync minus what NTP says now.
  // Positive = clock was ahead, negative = clock was behind.
  // after_sync is the corrected time; before_sync was the drifted time.
  last_drift_ms = (int32_t)(before_sync - after_sync) * 1000;
  // Rate in ppm, kept with its window as a short history so the screen can
  // show whether the oscillator error is a stable constant. Short windows are
  // dropped rather than averaged in — see DRIFT_MIN_WINDOW_S.
  if (last_drift_window_s >= DRIFT_MIN_WINDOW_S)
  {
    int32_t ppm = (int32_t)((last_drift_ms * 1000LL) / last_drift_window_s);
    ppm = (ppm > 32767) ? 32767 : (ppm < -32768 ? -32768 : ppm);
    int32_t win_min = last_drift_window_s / 60;
    if (win_min > 65535) win_min = 65535;  // saturates at 45 days
    if (drift_ppm_count == DRIFT_PPM_HIST_SIZE)
    {
      memmove(drift_ppm_hist, drift_ppm_hist + 1,
              sizeof(drift_ppm_hist) - sizeof(drift_ppm_hist[0]));
      memmove(drift_win_min, drift_win_min + 1,
              sizeof(drift_win_min) - sizeof(drift_win_min[0]));
      drift_ppm_count--;
    }
    drift_win_min[drift_ppm_count] = (uint16_t)win_min;
    drift_ppm_hist[drift_ppm_count++] = (int16_t)ppm;
    LOGI("NTP resync: rate %d ppm over %d min (%u samples retained)",
         (int)ppm, (int)win_min, (unsigned)drift_ppm_count);
  }

  LOGI("NTP resync: drift was %d ms over %d s (%u attempts failed since last sync)",
       (int)last_drift_ms, (int)last_drift_window_s, (unsigned)resync_fail_count);
  resync_fail_count = 0;

  // Only shorten the interval if drift is significant (>= 1 minute).
  // For a low-fidelity EPD thermometer display, sub-minute drift is invisible.
  int32_t abs_drift = abs(last_drift_ms);
  if (abs_drift >= 60000)
  {
    // Aim for <60s drift at next resync. The rate is drift over the measured
    // window, not over the interval setting — using the setting after a run of
    // failed attempts overstates the rate and shortens the interval too far.
    int32_t target = (int32_t)((60LL * last_drift_window_s * 1000) / abs_drift);
    if (target < RESYNC_INTERVAL_MIN)
      target = RESYNC_INTERVAL_MIN;
    if (target > RESYNC_INTERVAL_MAX)
      target = RESYNC_INTERVAL_MAX;
    resync_interval_s = target;
    LOGI("NTP resync: significant drift, interval adjusted to %d s (%d h)",
         (int)resync_interval_s, (int)(resync_interval_s / 3600));
  }
  else
  {
    // Drift < 1 minute — double the interval (capped)
    if (resync_interval_s < RESYNC_INTERVAL_MAX / 2)
      resync_interval_s *= 2;
    else
      resync_interval_s = RESYNC_INTERVAL_MAX;
    LOGI("NTP resync: drift negligible, extending interval to %d s (%d h)",
         (int)resync_interval_s, (int)(resync_interval_s / 3600));
  }

  wifi_disconnect();
  next_resync_time = after_sync + resync_interval_s;
}
#endif // DISABLE_WIFI

// Battery thresholds (mV).
#if defined(ARDUINO_XIAO_ESP32C6)
// The XIAO's 3V3 rail is a pure buck (SGM6029C): at VBAT ≤3.6V it enters a
// bootstrap-starvation sag band (rail sags ~VTH below VIN; wakes collapse it
// into 0.5-0.9A brownout-restart storms; 30Hz sawtooth at 3.3V). Fine sweep
// 2026-07-05 (docs/notes.md): 3.7V is the lowest verified-healthy point,
// 3.6V is already inside the sag band — so shut down at the electrical
// cliff, not the battery's own limit (~12-15% SoC abandoned per OCV curve).
// The custom thermometer-c6 board (RT9080 LDO, not a buck) keeps the same
// numbers: worst-case LDO dropout at the refresh peak sits right at this
// cutoff, and SCHEMATIC-VERIFICATION.md says keep shutdown ≥3.6V pending
// the first-article dropout measurement.
const uint32_t low_battery_mv = 3800;
const uint32_t no_battery_mv = 3700;
#else
// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
#endif

uint32_t read_battery_level()
{
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  // GPIO34 (A2) = ADC1 channel 6
  // On ADC failure return a value in the low-battery band: visible on the
  // display as a warning, but above no_battery_mv so a transient ADC error
  // can never trigger the permanent shutdown in handle_permanent_shutdown().
  const uint32_t adc_fail_mv = 3100;

  adc_oneshot_unit_handle_t unit;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &unit) != ESP_OK)
  {
    LOGI("ERROR: ADC unit init failed");
    return adc_fail_mv;
  }
  adc_oneshot_chan_cfg_t ccfg = {};
  ccfg.atten = ADC_ATTEN_DB_12;
  ccfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_oneshot_config_channel(unit, ADC_CHANNEL_6, &ccfg);

  adc_cali_handle_t cali = nullptr;
  adc_cali_line_fitting_config_t lcfg = {};
  lcfg.unit_id = ADC_UNIT_1;
  lcfg.atten = ADC_ATTEN_DB_12;
  lcfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_cali_create_scheme_line_fitting(&lcfg, &cali);

  int raw = 0, mv = 0;
  bool read_ok = (adc_oneshot_read(unit, ADC_CHANNEL_6, &raw) == ESP_OK);
  if (cali)
  {
    adc_cali_raw_to_voltage(cali, raw, &mv);
    adc_cali_delete_scheme_line_fitting(cali);
  }
  else
  {
    mv = raw * 3100 / 4095; // uncalibrated fallback, 12dB full scale ~3.1V
  }
  adc_oneshot_del_unit(unit);

  if (!read_ok)
  {
    LOGI("ERROR: ADC read failed");
    return adc_fail_mv;
  }

  uint32_t battery_mv = (uint32_t)mv * 2;
  LOGI("Battery level: %d mV", (int)battery_mv);
  return battery_mv;
#elif defined(THERMOMETER_C6_BOARD)
  // Custom thermometer-c6 board: high-side switched 100k/100k divider
  // (R20/R21). VDIV_EN (GPIO3) high → Q5 NFET → Q4 P-FET connects VBAT;
  // the external 100k pull-down keeps it hard-off in deep sleep. C29 10nF
  // reservoir on the ADC node charges through 100k — give it a few ms.
  // VBAT_ADC = GPIO2 = ADC1_CH2. While VBUS is present this node reads the
  // charger CV output, not battery SoC — see vbus_present().
  // ADC-failure fallback sits between no_battery_mv and low_battery_mv:
  // visible as a warning, can never trigger permanent shutdown.
  const uint32_t adc_fail_mv = 3750;

  gpio_out_init(3 /* VDIV_EN */);
  gpio_set_level(GPIO_NUM_3, 1);
  sleep_ms(5);

  adc_oneshot_unit_handle_t unit;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &unit) != ESP_OK)
  {
    gpio_set_level(GPIO_NUM_3, 0);
    LOGI("ERROR: ADC unit init failed");
    return adc_fail_mv;
  }
  adc_oneshot_chan_cfg_t ccfg = {};
  ccfg.atten = ADC_ATTEN_DB_12;
  ccfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_oneshot_config_channel(unit, ADC_CHANNEL_2, &ccfg);

  adc_cali_handle_t cali = nullptr;
  adc_cali_curve_fitting_config_t cfcfg = {};
  cfcfg.unit_id = ADC_UNIT_1;
  cfcfg.chan = ADC_CHANNEL_2;
  cfcfg.atten = ADC_ATTEN_DB_12;
  cfcfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_cali_create_scheme_curve_fitting(&cfcfg, &cali);

  int raw = 0, mv = 0;
  bool read_ok = (adc_oneshot_read(unit, ADC_CHANNEL_2, &raw) == ESP_OK);
  if (cali)
  {
    adc_cali_raw_to_voltage(cali, raw, &mv);
    adc_cali_delete_scheme_curve_fitting(cali);
  }
  else
  {
    mv = raw * 3300 / 4095; // uncalibrated fallback, 12dB full scale ~3.3V
  }
  adc_oneshot_del_unit(unit);
  gpio_set_level(GPIO_NUM_3, 0); // divider off; external pull-down holds it in sleep

  if (!read_ok)
  {
    LOGI("ERROR: ADC read failed");
    return adc_fail_mv;
  }

  uint32_t battery_mv = (uint32_t)mv * 2;
  LOGI("Battery level: %d mV", (int)battery_mv);
  return battery_mv;
#elif defined(ARDUINO_XIAO_ESP32C6)
  // https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/#reading-battery-voltage
  // Requires wiring A0/GPIO0 to VBAT see https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/#check-the-battery-voltage
  return 4321; // TODO: remove this once proper circuit has been soldered
#else
  #error "Unknown board type"
#endif
}

// USB presence. With VBUS attached, VBAT_ADC reads the charger CV node, so
// SoC-based decisions (especially permanent shutdown) must be suppressed.
bool vbus_present()
{
#if defined(THERMOMETER_C6_BOARD)
  // R22/R23 100k/100k from VBUS → ~2.5V at GPIO4 with USB attached; the
  // divider is dead (0V, zero drain) with USB unplugged.
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << 4;
  cfg.mode = GPIO_MODE_INPUT;
  cfg.pull_up_en = GPIO_PULLUP_DISABLE;
  cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
  gpio_config(&cfg);
  return gpio_get_level(GPIO_NUM_4) != 0;
#else
  return false;
#endif
}

#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  #include "Adafruit_NeoPixel.h"
  Adafruit_NeoPixel status_led(1, 5 /*data pin*/, NEO_GRB + NEO_KHZ800);
#elif defined(ARDUINO_XIAO_ESP32C6)
  #define STATUS_LED_PIN 15 // GPIO 15 (LED_BUILTIN), yellow, active-high
#else
  #error "Unknown board type"
#endif
#endif

static uint32_t rgb(uint8_t r, uint8_t g, uint8_t b)
{
  return ((uint32_t)r << 16) | ((uint32_t)g << 8) | b;
}

void initialize_status_led()
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  status_led.begin();
  status_led.setBrightness(128);
#elif defined(ARDUINO_XIAO_ESP32C6)
  gpio_out_init(STATUS_LED_PIN);
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0);
#else
  #error "Unknown board type"
#endif
#endif
}

void set_status_led(uint32_t color)
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // Looks like Red is a greenish tint
  // Green and Blue both show up correct
  status_led.setPixelColor(0, color);
  status_led.show();
#elif defined(ARDUINO_XIAO_ESP32C6)
  // Single-color yellow LED
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, color != 0 ? 1 : 0);
#else
  #error "Unknown board type"
#endif
#endif
}

void clear_status_led()
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  status_led.clear();
  status_led.show();
#elif defined(ARDUINO_XIAO_ESP32C6)
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0);
#else
  #error "Unknown board type"
#endif
#endif
}

float read_temperature()
{
  LOGI("Getting temperature");
  float temp = sensor.GetTemperatureC();
  LOGI("temp: %f °C", temp);
  return temp;
}

uint16_t buttonRead(uint8_t pin)
{
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << pin;
  cfg.mode = GPIO_MODE_INPUT;
  cfg.pull_up_en = GPIO_PULLUP_ENABLE;
  gpio_config(&cfg);
  return gpio_get_level((gpio_num_t)pin); // return 0 when pressed
}

#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#define SHUTDOWN_BUTTON_PIN 27
#elif defined(ARDUINO_XIAO_ESP32C6)
#define SHUTDOWN_BUTTON_PIN 9
#else
  #error "Unknown board type"
#endif

void handle_permanent_shutdown(uint32_t battery_mv)
{
  uint16_t pin27 = buttonRead(SHUTDOWN_BUTTON_PIN);
  LOGI("Button read %d: %d", SHUTDOWN_BUTTON_PIN, pin27);
  // On USB power the measured voltage is the charger CV node, not battery
  // SoC — never let it trigger the permanent shutdown while charging.
  if (pin27 == 0 || (battery_mv < no_battery_mv && !vbus_present()))
  {
    // If button is pressed or battery is dead, powerdown
    if (pin27 == 0)
    {
      // Looks like we might be getting extremely rare spurious reads of 0
      // Double check after a delay ...
      sleep_ms(1000);
      pin27 = buttonRead(SHUTDOWN_BUTTON_PIN);
      LOGI("Button read %d confirmation: %d", SHUTDOWN_BUTTON_PIN, pin27);
      if (pin27 != 0)
      {
        bad_pin27_count++;
        return;
      }

      display_clear();

      // ... and add somethign on screen for diagnostics purposes in case the delay isn't sufficient
      // TODO remove this later
      display_show_pin27_diagnostic(boot_count);
    }
    else //  battery_mv < no_battery_mv
    {
      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);
      display_show_empty_battery(battery_mv, now, make_display_stats());
    }

    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    LOGI("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}

void on_first_boot()
{
#ifdef DISABLE_WIFI
  LOGI("WiFi has been disabled at build time with DISABLE_WIFI. See local-secrets.h to fix.");
  // Not an error — suppress "! NO WIFI" indicator on display
  wifi_ok = true;
  set_status_led(rgb(255, 255, 0));
  sleep_ms(100);
#else
  #if !(defined(MY_WIFI_SSID) && defined(MY_WIFI_PASSWORD))
    #error "MY_WIFI_SSID and/or MY_WIFI_PASSWORD are not defined. See local-secrets.h to fix."
  #endif
  if (*MY_WIFI_SSID == 0)
  {
    LOGI("Missing WiFi SSID. Will assume network connectivity isn't possible. See local-secrets.h to fix.");
    return;
  }

  // Connect to WiFi with timeout (avoids hanging forever if network is down)
  LOGI("Connecting to WiFi");
  set_status_led(rgb(0, 0, 255));

  if (!wifi_connect())
  {
    // wifi_ok stays false, ntp_synced stays false
    return;
  }
  LOGI("Connected to WiFi");
  wifi_ok = true;

  // Synchronize time via NTP
  LOGI("Synchronizing time");
  set_status_led(rgb(0, 255, 0));
  if (!sntp_sync_once(30000U /* max wait time in ms */))
    LOGI("NTP sync failed — time is unreliable");
  time(&first_boot_time);

  // Verify sync succeeded (time should be well past epoch)
  ntp_synced = (first_boot_time > 86400 * 365);
  if (ntp_synced)
    last_sync_time = first_boot_time;

  wifi_disconnect();
  LOGI("WiFi disconnected");
#endif
}


bool periodic_display_clear(const time_t now, struct tm nowtm)
{
  // Trigger screen clear daily
  if (next_clear_time == 0)
  {
    if (now < one_day)
    {
      // We don't seem to have a synchronized clock, clear screen periodically from first boot
      next_clear_time = now + one_day;
    }
    else
    {
      // We have a synchronzied clock, clear screen periodically when it's likely to be least disruptive
      // Let's pick the next time it's 04h00
      time_t offset = 0;
      if (4 <= nowtm.tm_hour)
      {
        offset = one_day;
      }
      nowtm.tm_hour = 4;
      nowtm.tm_min = 0;
      nowtm.tm_sec = 0;
      next_clear_time = mktime(&nowtm) + offset;
    }
  }

  if (now < next_clear_time)
  {
    return false;
  }

  display_clear();
  next_clear_time += one_day; // Schedule next clear in a day
  return true;
}

void refresh_and_sleep(uint32_t battery_mv, float temp)
{
  time_t now;
  struct tm nowtm;
  get_time(&now, &nowtm);

#ifndef DISABLE_WIFI
  crash_log.stage = STAGE_NTP;
  maybe_ntp_resync(now);
  // Re-read time after potential resync correction
  get_time(&now, &nowtm);
#endif
  crash_log.cur_time = (uint32_t)now;

  update_temp_extremes(temp);
  update_hourly_history(now, &nowtm, temp);

  LOGI("now: %ld. next clear time: %ld. first boot time: %ld. prev_temp: %.1f",
       (long)now, (long)next_clear_time, (long)first_boot_time, previous_temp);
#ifdef MOCK_DISPLAY_DATA
  // Override sensor reading to match mock data range so it doesn't
  // distort the chart Y-axis (DummySensor returns a constant 12.3°C)
  temp = 22.3f;
#endif
  // RENDER covers both the periodic clear and the refresh below — either can
  // die mid-EPD-write (SPI, busy-wait light sleep, panel power)
  crash_log.stage = STAGE_RENDER;

#ifdef CRASH_TEST_BOOT
  // Deliberate crash to exercise the forensics path on hardware — flash with
  //   PLATFORMIO_BUILD_FLAGS="-DCRASH_TEST_BOOT=3" pio run -e <env> -t upload
  // (add -DCRASH_TEST_HANG to test the task-WDT→panic path instead of a null
  // deref). Fires on the first wake at/after that boot count, once per RTC
  // power cycle: the crash_count guard stops a crash loop, and also means a
  // second test needs a power cycle (which clears the CrashLog) first.
  if (boot_count >= CRASH_TEST_BOOT && crash_log.crash_count == 0)
  {
    LOGI("CRASH_TEST_BOOT: deliberately crashing at boot %d", boot_count);
    fflush(stdout);
#ifdef CRASH_TEST_HANG
    while (true) {}                    // starve idle task → TWDT → panic
#else
    *(volatile uint32_t *)0 = 0xdead;  // store to NULL → panic + coredump
#endif
  }
#endif
  bool should_refresh = periodic_display_clear(now, nowtm) ||
                         fabsf(temp - previous_temp) >= DISPLAY_TEMP_DELTA;
  if (!should_refresh)
  {
    LOGI("temperature hasn't changed significantly, no need to refresh display");
  }
  else
  {
    display_refresh_count++;
    if (max_battery_mv < battery_mv)
      max_battery_mv = battery_mv;

    temp_history_record(historical_data.temp, &historical_data.temp_count,
                        now, (int16_t)(temp * 10));

    PPK2_DISPLAY_HIGH();
    display_show_temperature(temp, battery_mv, battery_mv < low_battery_mv,
                             now, &nowtm, make_display_stats());
    PPK2_DISPLAY_LOW();

    previous_temp = temp;
    previous_boot_count = boot_count;
  }

  // Only (re)load the LP/ULP program on a fresh boot. On deep-sleep wakes
  // the LP core is still running with its existing configuration — reloading
  // the binary would wipe its counters and is not needed. Must test the
  // CACHED cause: by this point the EPD light sleeps have overwritten the
  // live one, and querying it here re-inited the LP core on every refresh.
  if (sensor.SupportsUlp()
      && s_wake_cause == ESP_SLEEP_WAKEUP_UNDEFINED)
  {
    crash_log.stage = STAGE_LP_INIT;
    ulp_reinit_count++;
    sensor.InitializeUlp();
  }

  start_deep_sleep();
}


// Reset history buffers (sparkline + hourly).
// Called when the history data format changes (struct layout, buffer sizes).
static void reset_rtc_history()
{
  memset(&historical_data, 0, sizeof(historical_data));
  historical_data.current_hour_min_x10 = TEMP_INIT_MIN_X10;
  historical_data.current_hour_max_x10 = TEMP_INIT_MAX_X10;
  historical_data.version = RTC_HISTORY_VERSION;
  historical_data.self_addr = (uint32_t)&historical_data;
}

// Reset operational state (counters, flags, thresholds).
// Called when non-history RTC variables change. Preserves history.
static void reset_rtc_state()
{
  boot_count = 0;
  display_refresh_count = 0;
  ulp_reinit_count = 0;
  first_boot_time = 0;
  next_clear_time = 0;
  previous_temp = TEMP_NO_PREVIOUS;
  previous_boot_count = -1;
  max_battery_mv = 0;
  bad_pin27_count = 0;
  min_temp_since_boot = TEMP_INIT_MIN;
  max_temp_since_boot = TEMP_INIT_MAX;
  next_resync_time = 0;
  resync_interval_s = 7 * 86400;
  last_drift_ms = 0;
  last_drift_window_s = 0;
  last_sync_time = 0;
  resync_fail_count = 0;
  memset(drift_ppm_hist, 0, sizeof(drift_ppm_hist));
  memset(drift_win_min, 0, sizeof(drift_win_min));
  drift_ppm_count = 0;
  wifi_ok = false;
  ntp_synced = false;
  last_sensor_ok = true;
  rtc_state_version = RTC_STATE_VERSION;
}

void setup()
{
  // Must run before anything that can light-sleep (see s_wake_cause).
  s_wake_causes_raw = app_wakeup_causes_raw();
  s_wake_cause = app_wakeup_cause();

  setup_serial();
  crash_forensics_on_boot();

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
  ulp_check_data_overlap();  // abort immediately if ULP data overlaps RTC variables
#endif

#ifdef PPK2_DEBUG
  gpio_out_init(PPK2_PIN_CPU_ACTIVE);
  gpio_out_init(PPK2_PIN_DISPLAY);
#endif
  PPK2_CPU_ACTIVE_HIGH();

  // Detect stale RTC memory from a different firmware version.
  // Three checks: version tag mismatch (format changed), address shift
  // (linker moved the struct due to other RTC variable changes), and
  // state version mismatch (non-history RTC variables changed).
  if (historical_data.version != RTC_HISTORY_VERSION ||
      historical_data.self_addr != (uint32_t)&historical_data)
  {
    if (historical_data.version != RTC_HISTORY_VERSION)
      LOGI("RTC history version mismatch — resetting history");
    else
      LOGI("RTC history address shifted (was 0x%08x, now 0x%08x) — resetting history",
           (unsigned)historical_data.self_addr, (unsigned)(uint32_t)&historical_data);
    reset_rtc_history();
    reset_rtc_state();
  }
  else if (rtc_state_version != RTC_STATE_VERSION)
  {
    LOGI("RTC state version mismatch — resetting state (history preserved)");
    reset_rtc_state();
  }

  boot_count++;
  crash_log.cur_boot_count = boot_count;
  // CPU frequency is fixed at 80 MHz at build time (CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ)
  // — replaces the Arduino-era setCpuFrequencyMhz(80) on non-first boots.

  LOGI("Boot count: %d [%s] sizeof(TempReading)=%d sizeof(time_t)=%d",
       boot_count, GIT_HASH, (int)sizeof(TempReading), (int)sizeof(time_t));

  // Diagnostic: dump sparkline buffer to detect packed struct corruption
  if (historical_data.temp_count > 0)
  {
    LOGI("Sparkline: count=%d", historical_data.temp_count);
    for (int i = 0; i < historical_data.temp_count; i++)
    {
      LOGI("  [%d] ts=%lld temp_x10=%d",
           i,
           (long long)historical_data.temp[i].timestamp,
           (int)historical_data.temp[i].temp_x10);
    }
  }

  esp_sleep_wakeup_cause_t wakeup_cause = s_wake_cause;
  LOGI("Wakeup caused by %d (raw 0x%x)", (int)wakeup_cause, (unsigned)s_wake_causes_raw);

  uint32_t battery_mv = read_battery_level();

  handle_permanent_shutdown(battery_mv);

  if ((wakeup_cause == ESP_SLEEP_WAKEUP_ULP || wakeup_cause == ESP_SLEEP_WAKEUP_TIMER)
      && sensor.SupportsUlp())
  {
    float temp;
    crash_log.stage = STAGE_ULP_READ;
    if (sensor.ReadUlpTemperature(&temp, previous_temp))
    {
      last_sensor_ok = true;
      refresh_and_sleep(battery_mv, temp);
      return; // never reached
    }
    // ULP I2C error — fall through to normal sensor read
    last_sensor_ok = false;
  }

  if (boot_count == 1)
  {
    initialize_status_led();
    on_first_boot();
    clear_status_led(); // TODO: double check that this stops drawing power
  }

#ifdef MOCK_DISPLAY_DATA
  // Fill mock data if history is empty (handles both first boot and stale RTC
  // memory after firmware upload without power-cycle)
  if (historical_data.temp_count == 0)
  {
    time_t mock_now;
    struct tm mock_nowtm;
    get_time(&mock_now, &mock_nowtm);
    fill_mock_data(mock_now);
    // Force display refresh by invalidating previous_temp
    previous_temp = TEMP_NO_PREVIOUS;
  }
#endif

  crash_log.stage = STAGE_SENSOR;
  float temp = read_temperature();
  refresh_and_sleep(battery_mv, temp);
}

extern "C" void app_main(void)
{
  setup(); // deep-sleeps at the end; never returns
}
