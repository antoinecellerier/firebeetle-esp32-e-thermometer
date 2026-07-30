#pragma once

// Shared mock data generation for display layout testing.
// Used by both the device (Thermometer.cpp with MOCK_DISPLAY_DATA)
// and the host simulator (sim_main.cpp).

#include "Display.h"
#include "TempHistory.h"
#include <math.h>
#include <time.h>

// Realistic indoor temperature profile: piecewise linear with 20 control
// points covering a full 24h cycle. Returns temperature in °C for a given
// hour-of-day (0.0–24.0).
inline float mock_temp_at_hour(float h)
{
  struct Point { float hour; float temp; };
  static const Point profile[] = {
    { 0.0f, 20.5f}, { 2.0f, 20.0f}, { 4.0f, 19.5f}, { 6.0f, 19.0f},
    { 6.5f, 19.5f}, { 7.0f, 20.2f}, { 7.5f, 20.8f}, { 8.0f, 21.3f},
    { 9.0f, 21.5f}, {12.0f, 21.8f}, {14.0f, 22.0f}, {16.0f, 21.8f},
    {17.0f, 22.0f}, {18.0f, 22.3f}, {19.0f, 22.5f}, {20.0f, 22.3f},
    {21.0f, 21.8f}, {22.0f, 21.3f}, {23.0f, 20.8f}, {24.0f, 20.5f},
  };
  static const int N = sizeof(profile) / sizeof(profile[0]);

  while (h >= 24.0f) h -= 24.0f;
  while (h < 0.0f) h += 24.0f;
  for (int j = 0; j < N - 1; j++)
    if (h >= profile[j].hour && h < profile[j+1].hour)
    {
      float frac = (h - profile[j].hour) / (profile[j+1].hour - profile[j].hour);
      return profile[j].temp + frac * (profile[j+1].temp - profile[j].temp);
    }
  return profile[N - 1].temp;
}

// Fill the 24h sparkline history buffer with mock readings.
// Readings are spaced irregularly: clustered during rapid temperature changes
// (morning warmup, evening cooldown) and sparse during stable periods — this
// mirrors the real delta-threshold-based wake behavior.
inline void mock_fill_sparkline(time_t now, TempReading *history,
                                 uint16_t *out_count)
{
  time_t start_time = now - 86400;
  uint16_t count = 0;

  // Stable initial period: when the 24h window opens mid–flat-night, the device
  // carries in its last pre-window reading and records nothing (delta encoding)
  // until the temperature next moves. Reproduce that here — one carry-in reading
  // just before the window, then no readings for the first STABLE_HOURS — so the
  // chart must anchor the flat region back to the left edge instead of leaving
  // it blank. Regression test for that rendering path.
  const float STABLE_HOURS = 6.0f;
  history[count++] = { (uint32_t)(start_time - 1800),
                       (int16_t)(mock_temp_at_hour(STABLE_HOURS) * 10) };
  time_t t = start_time + (time_t)(STABLE_HOURS * 3600);

  while (t < now && count < TEMP_HISTORY_SIZE)
  {
    float h = ((float)((t - start_time) % 86400)) / 3600.0f;
    float temp = mock_temp_at_hour(h);
    temp += ((count * 73 + 17) % 100 - 50) * 0.001f; // small deterministic noise

    history[count++] = { (uint32_t)t, (int16_t)(temp * 10) };

    // Variable gap: more readings during rapid temperature changes
    float rate = fabsf(mock_temp_at_hour(h + 0.1f) - mock_temp_at_hour(h));
    int gap;
    if (rate > 0.03f)       gap = 300 + (count * 37 % 600);    // 5-15 min
    else if (rate > 0.01f)  gap = 900 + (count * 53 % 1200);   // 15-35 min
    else                    gap = 2400 + (count * 71 % 3000);   // 40-90 min
    t += gap;
  }

  *out_count = count;
}

// Noisy 24h scenario: a heatwave day where a window opens mid-afternoon,
// producing sustained ±0.5°C oscillation. The delta trigger then fires on
// nearly every 60s poll, generating far more than TEMP_HISTORY_SIZE points —
// this drives readings through the real TempHistory.h append/evict path, so
// the sim exercises smart eviction end to end. Regression test: the rendered
// sparkline must still span the full 24h (a drop-oldest ring would truncate
// to the most recent few hours).
inline void mock_fill_sparkline_noisy(time_t now, TempReading *history,
                                       uint16_t *out_count)
{
  uint16_t count = 0;
  float last_recorded = -999.0f;

  // Start 26h back so the buffer holds a pre-window carry-in point
  for (time_t t = now - 26 * 3600; t <= now; t += 60)  // 60s = ULP poll cadence
  {
    float win_h = (float)(t - (now - 86400)) / 3600.0f;  // hours into 24h window
    float h = ((float)(t % 86400)) / 3600.0f;
    float temp = mock_temp_at_hour(h);

    // Heatwave: ramp +3°C over window hours 8-16, hold after
    if (win_h > 8.0f)
      temp += 3.0f * fminf((win_h - 8.0f) / 8.0f, 1.0f);

    // Open window: ±0.5°C triangle wave, ~10 min period, hours 10-16
    if (win_h >= 10.0f && win_h < 16.0f)
      temp += ((t / 300) % 2 == 0) ? 0.5f : -0.5f;

    // Recording gate — mirrors DISPLAY_TEMP_DELTA in Thermometer.cpp
    if (fabsf(temp - last_recorded) >= 0.1f)
    {
      temp_history_record(history, &count, t, (int16_t)(temp * 10));
      last_recorded = temp;
    }
  }

  *out_count = count;
}

// Fill the 30-day hourly history buffer with mock data.
// Generates 720 hourly entries (30 days × 24 hours) with:
// - Realistic daily temperature cycles via mock_temp_at_hour()
// - Gradual spring warming trend (+0.08°C/day)
// - Cold snap mid-month (days 12-16)
// - Slightly warmer weekends (people home all day)
// - Small min/max spread per hour, with occasional larger spikes
//   simulating transient events (window opens, sun/shadow)
inline void mock_fill_hourly(time_t now, HourlyEntry *history,
                              uint16_t *out_count, uint16_t *out_idx,
                              time_t *out_latest_time)
{
  // Compute the start-of-hour for the last complete hour before now
  struct tm now_tm;
  localtime_r(&now, &now_tm);
  now_tm.tm_min = 0;
  now_tm.tm_sec = 0;
  time_t latest = mktime(&now_tm) - 3600;

  // Compute hour-of-day and day-of-week for the oldest entry
  // to avoid calling localtime_r in the inner loop
  time_t first_time = latest - (time_t)(HOURLY_HISTORY_SIZE - 1) * 3600;
  struct tm first_tm;
  localtime_r(&first_time, &first_tm);
  int first_hour = first_tm.tm_hour;
  int first_wday = first_tm.tm_wday;

  uint16_t idx = 0;

  for (int i = 0; i < HOURLY_HISTORY_SIZE; i++)
  {
    // Approximate hour-of-day and day offset (ignores DST — fine for mock data)
    int h = (first_hour + i) % 24;
    int day_offset = (first_hour + i) / 24;
    int day_num = day_offset + 1;  // 1 = oldest day, ~30 = newest
    int wday = (first_wday + day_offset) % 7;

    // Day-to-day trend: gradual warming
    float base_offset = day_num * 0.08f;

    // Cold snap: days 12-16 drop 1-3°C
    if (day_num >= 12 && day_num <= 16)
    {
      float snap = (day_num == 14) ? 3.0f : (day_num == 13 || day_num == 15) ? 2.0f : 1.0f;
      base_offset -= snap;
    }

    // Weekend bump
    if (wday == 0 || wday == 6)
      base_offset += 0.3f;

    float temp = mock_temp_at_hour((float)h) + base_offset;

    // Deterministic noise
    int seed = i;
    temp += ((seed * 73 + 17) % 100 - 50) * 0.002f;

    int16_t avg = (int16_t)(temp * 10);

    // Min/max spread: larger during rapid temperature changes (morning/evening),
    // with occasional bigger spikes simulating door/window events
    float rate = fabsf(mock_temp_at_hour((float)h + 0.5f) - mock_temp_at_hour((float)h - 0.5f));
    int16_t spread = (int16_t)(rate * 10) + 1;  // at least 0.1°C
    if ((seed * 41 + 7) % 47 == 0)
      spread += 15;  // +1.5°C transient spike every ~2 days

    history[idx].avg_x10 = avg;
    history[idx].min_x10 = avg - spread;
    history[idx].max_x10 = avg + spread;
    idx = (idx + 1) % HOURLY_HISTORY_SIZE;
  }

  *out_count = HOURLY_HISTORY_SIZE;
  *out_idx = idx;
  *out_latest_time = latest;
}

// Populate a DisplayStats struct with a complete set of mock data.
// Used by the simulator; device code calls the fill functions directly.
inline DisplayStats mock_make_stats(time_t now,
                                     TempReading *history_buf,
                                     HourlyEntry *hourly_buf)
{
  uint16_t h_count;
  uint16_t hr_count, hr_idx;
  time_t hr_latest;
  mock_fill_sparkline(now, history_buf, &h_count);
  mock_fill_hourly(now, hourly_buf, &hr_count, &hr_idx, &hr_latest);

  DisplayStats stats = {};
  stats.boot_count = 847;
  stats.previous_boot_count = 846;
  stats.display_refresh_count = 203;
  stats.lp_wake_count = 50820;  // ~60 per boot, consistent with stable temp
  stats.lp_error_count = 0;
  stats.last_lp_error = 0;
  stats.last_lp_op = 0;
  stats.first_boot_time = now - 12 * 86400;
  stats.next_clear_time = now + 3600;
  stats.max_battery_mv = 4200;
  stats.bad_pin27_count = 0;
  stats.ulp_supported = true;
  stats.wake_cause = 1;  // mock: ULP wake
  stats.wifi_ok = true;
  stats.ntp_synced = true;
  stats.sensor_ok = true;
  stats.dummy_sensor = true;
  stats.mock_data = true;
  stats.power_efficient = false;
  stats.usb_window = false;
  stats.clock_drift_ms = 0;
  stats.drift_window_s = 0;
  stats.last_sync_time = now - 7200;  // 2h ago
  stats.resync_fail_count = 0;
  stats.drift_ppm_hist = NULL;
  stats.drift_win_min = NULL;
  stats.drift_ppm_count = 0;
  stats.ulp_reinit_count = 1;   // healthy: exactly one init since power-on
  stats.wake_causes_raw = 1u << 6;  // BIT(ESP_SLEEP_WAKEUP_ULP)
  stats.previous_temp = 22.1f;
  stats.min_temp = 18.5f;
  stats.max_temp = 22.8f;
  stats.temp_history = history_buf;
  stats.history_count = h_count;
  stats.hourly_history = hourly_buf;
  stats.hourly_count = hr_count;
  stats.hourly_start = (hr_count < HOURLY_HISTORY_SIZE) ? 0 : hr_idx;
  stats.hourly_latest_time = hr_latest;

  // Mock in-progress hour: 22.3°C average with small spread
  stats.current_hour_entry = { 219, 228, 223 };  // 21.9/22.8/22.3°C
  stats.has_current_hour = true;

  return stats;
}
