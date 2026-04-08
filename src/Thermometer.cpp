#include "common.h"

// needed for setenv and tzset :-/
#undef __STRICT_ANSI__
#include "time.h"
#include "stdlib.h"

#include "Arduino.h"
#include "esp_sleep.h"
#include <math.h>
#ifndef DISABLE_WIFI
#include "WiFi.h"
#endif

#include "Display.h"

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

// --- RTC memory layout ---
// RTC memory survives deep sleep but NOT power-on reset (firmware upload,
// battery swap, reset button). RTC_NOINIT_ATTR doesn't help — the FireBeetle
// board's reset circuit causes a full RTC power cycle on every reset.
//
// History is grouped in a struct with a version tag and self_addr field.
// The self_addr detects if the linker moved the struct (e.g. due to
// adding/removing other RTC variables). On power-on reset, .rtc.data is
// zeroed, version won't match, and history is reinitialized cleanly.
//
// Bump RTC_HISTORY_VERSION when changing anything inside RtcHistory
// (struct fields, buffer sizes, semantics).
// Bump RTC_STATE_VERSION when changing operational state variables below.
#define RTC_HISTORY_VERSION 0xDA050002
#define RTC_STATE_VERSION   0xDA050001

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

  // 24h sparkline
  TempReading temp[TEMP_HISTORY_SIZE];
  uint8_t temp_count;
  uint8_t temp_idx;

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
RTC_DATA_ATTR int32_t last_resync_interval_s = 0;    // interval at time of last drift measurement

// Status flags for display error indicators
RTC_DATA_ATTR bool wifi_ok = false;
RTC_DATA_ATTR bool ntp_synced = false;
RTC_DATA_ATTR bool last_sensor_ok = true;

static void append_temp_history(time_t now, float temp)
{
  // Backfill: if there's a long gap since the last entry (stable temperature,
  // no display refreshes), insert a point just before the new reading at the
  // previous temperature. This anchors the flat region so the sparkline
  // renderer draws a continuous line instead of a gap.
  if (historical_data.temp_count > 0)
  {
    int prev_idx = (historical_data.temp_idx + TEMP_HISTORY_SIZE - 1) % TEMP_HISTORY_SIZE;
    time_t prev_time = historical_data.temp[prev_idx].timestamp;
    if (now - prev_time > 3600)  // arbitrary; harmless even if lowered
    {
      historical_data.temp[historical_data.temp_idx] = { now - 1, historical_data.temp[prev_idx].temp_x10 };
      historical_data.temp_idx = (historical_data.temp_idx + 1) % TEMP_HISTORY_SIZE;
      if (historical_data.temp_count < TEMP_HISTORY_SIZE)
        historical_data.temp_count++;
    }
  }

  historical_data.temp[historical_data.temp_idx] = { now, (int16_t)(temp * 10) };
  historical_data.temp_idx = (historical_data.temp_idx + 1) % TEMP_HISTORY_SIZE;
  if (historical_data.temp_count < TEMP_HISTORY_SIZE)
    historical_data.temp_count++;
}

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
  mock_fill_sparkline(now, historical_data.temp, &historical_data.temp_count, &historical_data.temp_idx);
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
  // Compute circular buffer start indices (oldest entry)
  uint8_t history_start = (historical_data.temp_count < TEMP_HISTORY_SIZE)
    ? 0
    : historical_data.temp_idx;
  uint16_t hourly_start = (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
    ? 0
    : historical_data.hourly_idx;

  // Map ESP-IDF wake cause to a portable int for display
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  int wake = (cause == ESP_SLEEP_WAKEUP_ULP) ? 1 :
             (cause == ESP_SLEEP_WAKEUP_TIMER) ? 2 : 0;

  // Compute in-progress hour entry from accumulator
  bool has_current = (historical_data.current_hour_sample_count > 0);
  HourlyEntry current_entry = {};
  if (has_current)
  {
    current_entry.min_x10 = historical_data.current_hour_min_x10;
    current_entry.max_x10 = historical_data.current_hour_max_x10;
    current_entry.avg_x10 = (int16_t)(historical_data.current_hour_sum_x10 / historical_data.current_hour_sample_count);
  }

  return {
    boot_count, previous_boot_count, display_refresh_count,
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
    last_drift_ms, last_resync_interval_s,
    previous_temp, min_temp_since_boot, max_temp_since_boot,
    historical_data.temp, historical_data.temp_count, history_start,
    historical_data.hourly, historical_data.hourly_count, hourly_start,
    historical_data.hourly_latest_time, current_entry, has_current
  };
}

void setup_serial()
{
#ifndef DISABLE_SERIAL
  Serial.begin(115200);
  while (!Serial)
  {
    delay(10);
  }
  Serial.printf("Logging to serial\n");
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
  Serial.flush();
  PPK2_CPU_ACTIVE_LOW();
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
static const unsigned long WIFI_TIMEOUT_MS = 15000;

static bool wifi_connect()
{
  WiFi.begin(MY_WIFI_SSID, MY_WIFI_PASSWORD);
  unsigned long start = millis();
  while (!WiFi.isConnected())
  {
    if (millis() - start > WIFI_TIMEOUT_MS)
    {
      LOGI("WiFi connection timed out after %lu ms", WIFI_TIMEOUT_MS);
      WiFi.disconnect(true, true);
      return false;
    }
    delay(100);
    LOGI("Waiting for WiFi");
  }
  return true;
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
    LOGI("NTP resync: WiFi failed, deferring to next scheduled resync");
    next_resync_time = now + resync_interval_s;
    return;
  }

  // Capture pre-sync time for drift measurement
  time_t before_sync;
  time(&before_sync);

  configTzTime(MY_TZ, "pool.ntp.org");
  struct tm t;
  if (!getLocalTime(&t, 30000U))
  {
    LOGI("NTP resync: sync failed, deferring to next scheduled resync");
    WiFi.disconnect(true, true);
    next_resync_time = now + resync_interval_s;
    return;
  }

  time_t after_sync;
  time(&after_sync);

  // Drift = what the clock said before sync minus what NTP says now.
  // Positive = clock was ahead, negative = clock was behind.
  // after_sync is the corrected time; before_sync was the drifted time.
  last_drift_ms = (int32_t)(before_sync - after_sync) * 1000;
  last_resync_interval_s = resync_interval_s;
  LOGI("NTP resync: drift was %d ms (interval was %d s)",
       (int)last_drift_ms, (int)resync_interval_s);

  // Only shorten the interval if drift is significant (>= 1 minute).
  // For a low-fidelity EPD thermometer display, sub-minute drift is invisible.
  int32_t abs_drift = abs(last_drift_ms);
  if (abs_drift >= 60000)
  {
    // Aim for <60s drift at next resync.
    // target = 60 * interval_s * 1000 / abs_drift_ms
    int32_t target = (int32_t)((60LL * resync_interval_s * 1000) / abs_drift);
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

  WiFi.disconnect(true, true);
  next_resync_time = after_sync + resync_interval_s;
}
#endif // DISABLE_WIFI

// Battery thresholds (mV).
// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V

uint32_t read_battery_level()
{
  #if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  #define VOLTAGE_PIN 34
  // 34 = A2
  #elif defined(ARDUINO_XIAO_ESP32C6)
  // https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/#reading-battery-voltage
  // Requires wiring A0 to VBAT see https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/#check-the-battery-voltage
  #define VOLTAGE_PIN A0
  return 4321; // TODO: remove this once proper circuit has been soldered
  #else
  #error "Unknown board type"
  #endif
  uint32_t battery_mv = analogReadMilliVolts(VOLTAGE_PIN) * 2;
  LOGI("Battery level: %d mV", battery_mv);
  return battery_mv;
}

#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  #include "Adafruit_NeoPixel.h"
  Adafruit_NeoPixel status_led(1, 5 /*data pin*/, NEO_GRB + NEO_KHZ800);
#elif defined(ARDUINO_XIAO_ESP32C6)
  #define STATUS_LED_PIN LED_BUILTIN // GPIO 15, yellow, active-high
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
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);
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
  digitalWrite(STATUS_LED_PIN, color != 0 ? HIGH : LOW);
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
  digitalWrite(STATUS_LED_PIN, LOW);
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
  pinMode(pin, INPUT_PULLUP);
  return digitalRead(pin); // return 0 when pressed
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
  if (pin27 == 0 || battery_mv < no_battery_mv)
  {
    // If button is pressed or battery is dead, powerdown
    if (pin27 == 0)
    {
      // Looks like we might be getting extremely rare spurious reads of 0
      // Double check after a delay ...
      delay(1000);
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
  delay(100);
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
  configTzTime(MY_TZ, "pool.ntp.org");
  struct tm t;
  getLocalTime(&t, 30000U /* max wait time in ms */);
  first_boot_time = mktime(&t);

  // Verify sync succeeded (time should be well past epoch)
  ntp_synced = (first_boot_time > 86400 * 365);
  if (!ntp_synced)
    LOGI("NTP sync failed — time is unreliable");

  WiFi.disconnect(true, true);
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
  maybe_ntp_resync(now);
  // Re-read time after potential resync correction
  get_time(&now, &nowtm);
#endif

  update_temp_extremes(temp);
  update_hourly_history(now, &nowtm, temp);

  LOGI("now: %ld. next clear time: %ld. first boot time: %ld. prev_temp: %.1f",
       (long)now, (long)next_clear_time, (long)first_boot_time, previous_temp);
#ifdef MOCK_DISPLAY_DATA
  // Override sensor reading to match mock data range so it doesn't
  // distort the chart Y-axis (DummySensor returns a constant 12.3°C)
  temp = 22.3f;
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

    append_temp_history(now, temp);

    PPK2_DISPLAY_HIGH();
    display_show_temperature(temp, battery_mv, battery_mv < low_battery_mv,
                             now, &nowtm, make_display_stats());
    PPK2_DISPLAY_LOW();

    previous_temp = temp;
    previous_boot_count = boot_count;
  }

  if (sensor.SupportsUlp())
    sensor.InitializeUlp();

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
  last_resync_interval_s = 0;
  wifi_ok = false;
  ntp_synced = false;
  last_sensor_ok = true;
  rtc_state_version = RTC_STATE_VERSION;
}

void setup()
{
  setup_serial();

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
  ulp_check_data_overlap();  // abort immediately if ULP data overlaps RTC variables
#endif

#ifdef PPK2_DEBUG
  pinMode(PPK2_PIN_CPU_ACTIVE, OUTPUT);
  pinMode(PPK2_PIN_DISPLAY, OUTPUT);
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
  if (boot_count != 1)
  {
    // Reducing CPU frequency to 80 MHz to save power (as none of this CPU bound)
    setCpuFrequencyMhz(80);
  }
  LOGI("CPU frequency: %d", getCpuFrequencyMhz());
  LOGI("Xtal frequency: %d", getXtalFrequencyMhz());

  LOGI("Boot count: %d [%s] sizeof(TempReading)=%d sizeof(time_t)=%d",
       boot_count, GIT_HASH, (int)sizeof(TempReading), (int)sizeof(time_t));

  // Diagnostic: dump sparkline buffer to detect packed struct corruption
  if (historical_data.temp_count > 0)
  {
    LOGI("Sparkline: count=%d idx=%d", historical_data.temp_count, historical_data.temp_idx);
    int start = (historical_data.temp_count < TEMP_HISTORY_SIZE)
      ? 0 : historical_data.temp_idx;
    for (int i = 0; i < historical_data.temp_count; i++)
    {
      int idx = (start + i) % TEMP_HISTORY_SIZE;
      LOGI("  [%d] idx=%d ts=%lld temp_x10=%d",
           i, idx,
           (long long)historical_data.temp[idx].timestamp,
           (int)historical_data.temp[idx].temp_x10);
    }
  }

  esp_sleep_wakeup_cause_t wakeup_cause = esp_sleep_get_wakeup_cause();
  LOGI("Wakeup caused by %d", (int)wakeup_cause);

  uint32_t battery_mv = read_battery_level();

  handle_permanent_shutdown(battery_mv);

  if ((wakeup_cause == ESP_SLEEP_WAKEUP_ULP || wakeup_cause == ESP_SLEEP_WAKEUP_TIMER)
      && sensor.SupportsUlp())
  {
    float temp;
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

  float temp = read_temperature();
  refresh_and_sleep(battery_mv, temp);
}

void loop()
{
  // Never gets invoked as we deep sleep at the end of setup()
}
