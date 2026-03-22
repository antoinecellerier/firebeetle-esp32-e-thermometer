#pragma once

// Shared mock data generation for display layout testing.
// Used by both the device (Thermometer.cpp with MOCK_DISPLAY_DATA)
// and the host simulator (sim_main.cpp).

#include "Display.h"
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
                                 uint8_t *out_count, uint8_t *out_idx)
{
  time_t start_time = now - 86400;
  time_t t = start_time;
  uint8_t count = 0;
  uint8_t idx = 0;

  while (t < now && count < TEMP_HISTORY_SIZE)
  {
    float h = ((float)((t - start_time) % 86400)) / 3600.0f;
    float temp = mock_temp_at_hour(h);
    temp += ((count * 73 + 17) % 100 - 50) * 0.001f; // small deterministic noise

    history[idx] = { t, (int16_t)(temp * 10) };
    idx = (idx + 1) % TEMP_HISTORY_SIZE;
    count++;

    // Variable gap: more readings during rapid temperature changes
    float rate = fabsf(mock_temp_at_hour(h + 0.1f) - mock_temp_at_hour(h));
    int gap;
    if (rate > 0.03f)       gap = 300 + (count * 37 % 600);    // 5-15 min
    else if (rate > 0.01f)  gap = 900 + (count * 53 % 1200);   // 15-35 min
    else                    gap = 2400 + (count * 71 % 3000);   // 40-90 min
    t += gap;
  }

  *out_count = count;
  *out_idx = idx;
}

// Fill the 30-day daily summary buffer with mock data.
// Shows a gradual spring warming trend with a cold snap mid-month
// and slightly warmer weekends (people home all day).
inline void mock_fill_daily(time_t now, DailySummary *daily,
                             uint8_t *out_count, uint8_t *out_idx)
{
  uint8_t count = 0;
  uint8_t idx = 0;

  for (int i = 29; i >= 0; i--)
  {
    time_t day_time = now - (time_t)i * 86400;
    struct tm day_tm;
    localtime_r(&day_time, &day_tm);

    int day_num = 30 - i; // 1 = oldest, 30 = today
    float base = 20.0f + day_num * 0.08f;

    // Cold snap: days 12-16 drop 1-3°C
    if (day_num >= 12 && day_num <= 16)
    {
      float snap = (day_num == 14) ? 3.0f : (day_num == 13 || day_num == 15) ? 2.0f : 1.0f;
      base -= snap;
    }

    // Weekend bump
    if (day_tm.tm_wday == 0 || day_tm.tm_wday == 6)
      base += 0.3f;

    float dmin = base - 1.5f - ((day_num * 41 + 7) % 100) * 0.005f;
    float dmax = base + 1.5f + ((day_num * 29 + 13) % 100) * 0.005f;

    daily[idx] = {
      (int16_t)(dmin * 10), (int16_t)(dmax * 10),
      (uint8_t)day_tm.tm_mday, (uint8_t)(day_tm.tm_mon + 1)
    };
    idx = (idx + 1) % DAILY_HISTORY_SIZE;
    count++;
  }

  *out_count = count;
  *out_idx = idx;
}

// Populate a DisplayStats struct with a complete set of mock data.
// Used by the simulator; device code calls the fill functions directly.
inline DisplayStats mock_make_stats(time_t now,
                                     TempReading *history_buf,
                                     DailySummary *daily_buf)
{
  uint8_t h_count, h_idx, d_count, d_idx;
  mock_fill_sparkline(now, history_buf, &h_count, &h_idx);
  mock_fill_daily(now, daily_buf, &d_count, &d_idx);

  struct tm today_tm;
  localtime_r(&now, &today_tm);

  DisplayStats stats = {};
  stats.boot_count = 847;
  stats.previous_boot_count = 846;
  stats.display_refresh_count = 203;
  stats.first_boot_time = now - 12 * 86400;
  stats.next_clear_time = now + 3600;
  stats.max_battery_mv = 4200;
  stats.bad_pin27_count = 0;
  stats.ulp_supported = true;
  stats.wake_cause = 1;  // mock: ULP wake
  stats.wifi_ok = true;
  stats.ntp_synced = true;
  stats.sensor_ok = true;
  stats.previous_temp = 22.1f;
  stats.min_temp = 18.5f;
  stats.max_temp = 22.8f;
  stats.temp_history = history_buf;
  stats.history_count = h_count;
  stats.history_start = (h_count < TEMP_HISTORY_SIZE) ? 0 : h_idx;
  stats.daily_history = daily_buf;
  stats.daily_count = d_count;
  stats.daily_start = (d_count < DAILY_HISTORY_SIZE) ? 0 : d_idx;
  stats.today_min_x10 = 195;
  stats.today_max_x10 = 223;
  stats.today_day = today_tm.tm_mday;
  return stats;
}
