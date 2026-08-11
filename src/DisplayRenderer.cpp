#include "device-config.h"
// With DISABLE_DISPLAY the whole renderer (and its Adafruit_GFX dependency)
// drops out of the build — required for pure-IDF targets without the display
// component stack.
#ifndef DISABLE_DISPLAY

#include "DisplayRenderer.h"
#include "HistoryStore.h"   // HistoryStoreFault, for the "! NOARCH" badge
#include "app_common.h"
#include "Sensor.hpp"   // TEMP_NO_PREVIOUS, the "no reading" sentinel
#include "displays.h"  // DISPLAY_HAS_RED (panel tri-color capability)

#include "git_hash.h"

#include <math.h>
#include <stdarg.h>
#include "Adafruit_GFX.h"
// Temperature font: generated at build time based on display resolution.
// The TEMP_FONT macro is defined in generated/font_config.h.
#include "generated/font_config.h"
// Fallback fonts from Adafruit GFX library (used for secondary elements
// and on displays where the optimal size matches a library font)
#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/Org_01.h>
#include <Fonts/TomThumb.h>

// min/max/constrain come from Arduino.h — the arduino_shim version on device,
// the tools/sim stub on host (both define ARDUINO).

#ifndef EPD_BLACK
#define EPD_BLACK 0x0000
#endif
#ifndef EPD_WHITE
#define EPD_WHITE 0xFFFF
#endif
// RGB565 red — the exact value GxEPD2_3C routes to its red plane (== GxEPD_RED).
// Gated by DISPLAY_HAS_RED (see displays.h): on bi-color panels it collapses to
// EPD_BLACK, so every red draw below is a no-op there without a runtime flag.
// This is the single definition of the color; Display.cpp uses GxEPD_* directly
// for its driver calls, so the duplicate that previously drifted (and silently
// disabled red) is gone.
#if DISPLAY_HAS_RED
#define EPD_RED 0xF800
#else
#define EPD_RED EPD_BLACK
#endif

// Temperature at/above this renders red on tri-color panels (no-op on B&W).
#define TEMP_HOT_THRESHOLD_C 30.0f

// --- Drawing helpers ---

static void draw_hline(Adafruit_GFX &gfx, int16_t x, int16_t y, int16_t w,
                        uint16_t color)
{
  gfx.drawLine(x, y, x + w - 1, y, color);
}

static void draw_dotted_hline(Adafruit_GFX &gfx, int16_t x, int16_t y,
                               int16_t w, int16_t spacing, uint16_t color)
{
  for (int16_t px = x; px < x + w; px += spacing)
    gfx.drawPixel(px, y, color);
}

static void draw_battery_icon(Adafruit_GFX &gfx, int16_t x, int16_t y,
                               int16_t w, int16_t h,
                               uint32_t mv, uint16_t color)
{
  int16_t nub_w = max((int16_t)2, (int16_t)(w / 8));
  int16_t nub_h = h / 3;
  gfx.drawRect(x, y, w, h, color);
  gfx.fillRect(x + w, y + (h - nub_h) / 2, nub_w, nub_h, color);
  // Cast to signed to avoid unsigned underflow when mv < 3000
  float fill = constrain((float)((int32_t)mv - 3000) / (4200.0f - 3000.0f), 0.0f, 1.0f);
  int16_t fill_w = (int16_t)((w - 4) * fill);
  if (fill_w > 0)
    gfx.fillRect(x + 2, y + 2, fill_w, h - 4, color);
}

// Evaluate a Catmull-Rom spline at parameter t ∈ [0,1] between p1 and p2,
// using p0 and p3 as outer control points.
static inline float catmull_rom(float p0, float p1, float p2, float p3, float t)
{
  float t2 = t * t, t3 = t2 * t;
  return 0.5f * (2*p1 + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t2 + (-p0+3*p1-3*p2+p3)*t3);
}

static const char *month_abbr[] = {
  "Jan","Feb","Mar","Apr","May","Jun",
  "Jul","Aug","Sep","Oct","Nov","Dec"
};

// Proportional padding with minimum 1°C span, used by all chart Y-range computations.
static void pad_y_range(float &y_min, float &y_max)
{
  float pad = max(0.3f, (y_max - y_min) * 0.15f);
  y_min -= pad;
  y_max += pad;
  if (y_max - y_min < 1.0f)
  {
    float mid = (y_max + y_min) / 2;
    y_min = mid - 0.5f;
    y_max = mid + 0.5f;
  }
}

// --- Layout computation ---

Layout compute_layout(int16_t w, int16_t h)
{
  Layout L = {};
  L.dw = w;
  L.dh = h;
  // Threshold 1.5: 296x128 (2.31) and 212x104 (2.04) are landscape,
  // 920x680 (1.35) and 200x200 (1.0) use stacked portrait.
  L.landscape = (w > h * 15 / 10);
  // Temperature font: computed at build time by scripts/generate_font.py
  // based on display resolution. get_temp_font() is defined in
  // generated/font_config.h and returns the optimal font for any display size.
  L.big_font = get_temp_font(w, h);

  if (L.landscape)
  {
    // Side-by-side: temp on left, charts on right (296x128, 212x104)
    int16_t footer_h = 10;
    int16_t content_h = h - footer_h;
    int16_t chart_w = w * 55 / 100;  // charts get 55% (need room for Y labels)
    int16_t temp_w = w - chart_w;

    // Skip monthly bars if too short to be useful
    int16_t spark_h, month_h;
    if (content_h < 110)
    {
      spark_h = content_h;
      month_h = 0;
    }
    else
    {
      spark_h = content_h * 62 / 100;
      month_h = content_h - spark_h;
    }

    L.temp  = {0, 0, temp_w, content_h};
    L.spark = {temp_w, 0, chart_w, spark_h};
    L.month = {temp_w, spark_h, chart_w, month_h};
    L.info  = {0, 0, 0, 0};  // info embedded in temp zone bottom
    L.foot  = {0, content_h, w, footer_h};

    // No font downgrade needed — the build-time font generator already
    // computed the optimal size for this display's resolution.
  }
  else
  {
    // Stacked: temp, sparkline, monthly, info, footer (200x200, 920x680)
    bool large_display = (h >= 400);
    int16_t footer_h = large_display ? 30 : 12;
    int16_t info_h = large_display ? 30 : 22;
    int16_t remaining = h - footer_h - info_h;

    int16_t temp_h, spark_h, month_h;
    if (remaining >= 400)
    {
      // Large display: compact temp (just the number), generous charts
      temp_h = remaining * 25 / 100;
      spark_h = remaining * 42 / 100;
      month_h = remaining - temp_h - spark_h;
    }
    else
    {
      // Small display: balanced
      temp_h = remaining * 38 / 100;
      spark_h = remaining * 38 / 100;
      month_h = remaining - temp_h - spark_h;
    }

    int16_t y = 0;
    L.temp  = {0, y, w, temp_h};  y += temp_h;
    L.spark = {0, y, w, spark_h}; y += spark_h;
    L.month = {0, y, w, month_h}; y += month_h;
    L.info  = {0, y, w, info_h};  y += info_h;
    L.foot  = {0, y, w, footer_h};
  }

  return L;
}

// --- Zone renderers ---

void render_temperature(Adafruit_GFX &gfx, const Layout &L,
                         float temp, const DisplayStats &stats)
{
  Rect z = L.temp;

  char temp_str[16];
  // No reading is not a temperature. Printing a plausible-looking number for a
  // rejected read is the failure this exists to prevent, so show a gap instead.
  if (temp == TEMP_NO_PREVIOUS)
    snprintf(temp_str, sizeof(temp_str), "--.-");
  else
    snprintf(temp_str, sizeof(temp_str), "%.1f", temp);

  gfx.setFont(L.big_font);
  gfx.setTextSize(1);
  // Hot temperatures render red on tri-color panels; EPD_RED == EPD_BLACK on
  // bi-color panels, so this is automatically a no-op there.
  gfx.setTextColor(temp >= TEMP_HOT_THRESHOLD_C ? EPD_RED : EPD_BLACK);
  gfx.setTextWrap(false);

  int16_t tbx, tby;
  uint16_t tbw, tbh;
  gfx.getTextBounds(temp_str, 0, 0, &tbx, &tby, &tbw, &tbh);

  int16_t cx, cy; uint16_t cw, ch;
  gfx.getTextBounds("C", 0, 0, &cx, &cy, &cw, &ch);

  // Thin gap between number and "C" (~40% of "C" glyph width)
  int16_t gap = (int16_t)cw * 4 / 10;
  int16_t total_w = (int16_t)tbw + gap + (int16_t)cw;

  // Combined vertical extent of number + "C" (C may be taller than digits)
  int16_t top = min(tby, cy);              // highest point above baseline
  int16_t bot = max(tby + (int16_t)tbh, cy + (int16_t)ch); // lowest point below baseline
  int16_t full_h = bot - top;

  int16_t text_x = z.x + (z.w - total_w) / 2 - tbx;
  int16_t baseline_y = z.y + (z.h - full_h) / 2 - top;

  gfx.setCursor(text_x, baseline_y);
  gfx.print(temp_str);
  gfx.setCursor(text_x - tbx + (int16_t)tbw + gap - cx, baseline_y);
  gfx.print("C");
  gfx.setTextWrap(true);
}

// --- Shared Y-axis gridlines + labels ---

static void draw_y_grid(Adafruit_GFX &gfx, int16_t zone_x, int16_t label_w,
                          int16_t chart_x, int16_t chart_y,
                          int16_t chart_w, int16_t chart_h,
                          bool large, float y_min, float y_range)
{
  const GFXfont *label_font = large ? &FreeSans12pt7b : &TomThumb;
  gfx.setFont(label_font);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  int grid_spacing = large ? 8 : 5;
  int deg_min = (int)roundf(y_min);
  int deg_max = (int)roundf(y_min + y_range);
  int deg_range = deg_max - deg_min;

  // Gridline step: draw dotted lines at every grid_step degrees
  int grid_step;
  if (chart_h >= 100) grid_step = (deg_range > 8) ? 2 : 1;
  else if (chart_h >= 40) grid_step = (deg_range > 4) ? 2 : 1;
  else grid_step = max(2, deg_range / 2);

  // Label step: adaptive density based on chart height and font size.
  // Must be a multiple of grid_step so labels land on visited gridlines.
  // Pick the smallest multiple that keeps labels readable (at least
  // min_label_spacing pixels apart), preferring "nice" degree intervals.
  int16_t min_label_spacing = large ? 30 : 10;
  int16_t label_bottom_margin = large ? 8 : 4;
  int usable_h = max(1, (int)chart_h - label_bottom_margin);
  int max_labels = max(2, usable_h / min_label_spacing);  // always ≥2 for scale
  // Find smallest multiple of grid_step that fits within max_labels
  int label_step = grid_step;
  while (deg_range / label_step > max_labels)
    label_step += grid_step;
  // Align grid and label starts to multiples of their respective steps,
  // so label degrees always land on visited gridlines.
  int grid_start = (int)ceilf((float)deg_min / grid_step) * grid_step;
  int label_start = (int)ceilf((float)deg_min / label_step) * label_step;

  for (int deg = grid_start; deg <= deg_max; deg += grid_step)
  {
    int16_t gy = chart_y + chart_h - 1 - (int16_t)(((float)deg - y_min) / y_range * (chart_h - 1));
    if (gy <= chart_y || gy >= chart_y + chart_h - 1) continue;
    draw_dotted_hline(gfx, chart_x, gy, chart_w, grid_spacing, EPD_BLACK);

    // Label only at multiples of label_step, away from X-axis labels
    bool is_label_deg = (deg >= label_start && (deg - label_start) % label_step == 0);
    bool in_bottom_margin = (gy > chart_y + chart_h - label_bottom_margin);
    if (is_label_deg && !in_bottom_margin)
    {
      char label[8];
      int16_t lx, ly; uint16_t lw, lh;
      snprintf(label, sizeof(label), "%d", deg);
      gfx.getTextBounds(label, 0, 0, &lx, &ly, &lw, &lh);
      int16_t label_gap = large ? 12 : 3;
      gfx.setCursor(zone_x + label_w - lw - label_gap - lx, gy + lh / 2);
      gfx.print(label);
    }
  }
}

void render_sparkline(Adafruit_GFX &gfx, const Rect &zone,
                       const DisplayStats &stats, time_t now)
{
  if (stats.history_count == 0) return;

  draw_hline(gfx, zone.x, zone.y, zone.w, EPD_BLACK);

  // Size-aware rendering parameters
  bool large = (zone.h >= 100);
  bool medium = (zone.h >= 40);

  int16_t label_w = large ? 40 : (medium ? 20 : 16);
  int16_t pad_top = large ? 12 : 4;
  int16_t pad_bot = large ? 22 : (medium ? 10 : 3); // room for X-axis labels
  int16_t pad_right = large ? 8 : 3;
  int16_t chart_x = zone.x + label_w;
  int16_t chart_y = zone.y + pad_top;
  int16_t chart_w = zone.w - label_w - pad_right;
  int16_t chart_h = zone.h - pad_top - pad_bot;

  if (chart_w < 10 || chart_h < 10) return;

  time_t window_start = now - 86400;

  // Carry-in: value of the last reading before the window opens. Delta encoding
  // records no point until temperature next changes, so when the window starts
  // mid-stable-period the first in-window point sits well right of the left
  // edge, leaving the initial flat region unplotted. Anchoring that value at
  // window_start draws the flat region back to the left edge.
  bool has_carry_in = false;
  int16_t carry_in_x10 = 0;
  time_t first_in_window = 0;
  bool have_first = false;

  // Find temperature range within the 24h window
  float t_min = 999.0f, t_max = -999.0f;
  int valid_count = 0;
  for (int i = 0; i < stats.history_count; i++)
  {
    const TempReading &r = stats.temp_history[i];
    if (r.timestamp < window_start)
    {
      carry_in_x10 = r.temp_x10;
      has_carry_in = true;
    }
    else
    {
      if (!have_first) { first_in_window = r.timestamp; have_first = true; }
      float t = r.temp_x10 / 10.0f;
      if (t < t_min) t_min = t;
      if (t > t_max) t_max = t;
      valid_count++;
    }
  }
  if (valid_count == 0) return;

  bool prepend_anchor = has_carry_in && have_first && first_in_window > window_start;
  if (prepend_anchor)
  {
    float t = carry_in_x10 / 10.0f;
    if (t < t_min) t_min = t;
    if (t > t_max) t_max = t;
  }

  pad_y_range(t_min, t_max);
  float t_range = t_max - t_min;
  float time_range = (float)(now - window_start);

  // Dotted gridlines + Y-axis labels — adaptive step based on chart height
  draw_y_grid(gfx, zone.x, label_w, chart_x, chart_y, chart_w, chart_h,
              large, t_min, t_range);

  // Collect data points within the 24h window
  int16_t px_arr[TEMP_HISTORY_SIZE];
  int16_t py_arr[TEMP_HISTORY_SIZE];
  int num_pts = 0;

  // Synthetic anchor at the left edge for a mid-stable-period window start
  if (prepend_anchor)
  {
    float t = carry_in_x10 / 10.0f;
    int16_t py = chart_y + chart_h - 1 - (int16_t)((t - t_min) / t_range * (chart_h - 1));
    px_arr[num_pts] = chart_x;
    py_arr[num_pts] = constrain(py, chart_y, (int16_t)(chart_y + chart_h - 1));
    num_pts++;
  }

  for (int i = 0; i < stats.history_count; i++)
  {
    const TempReading &r = stats.temp_history[i];
    if (r.timestamp < window_start) continue;

    float t = r.temp_x10 / 10.0f;
    int16_t px = chart_x + (int16_t)((float)(r.timestamp - window_start) / time_range * chart_w);
    int16_t py = chart_y + chart_h - 1 - (int16_t)((t - t_min) / t_range * (chart_h - 1));
    px = constrain(px, chart_x, (int16_t)(chart_x + chart_w - 1));
    py = constrain(py, chart_y, (int16_t)(chart_y + chart_h - 1));

    px_arr[num_pts] = px;
    py_arr[num_pts] = py;
    num_pts++;
  }

  // Draw Catmull-Rom spline through the data points.
  // X advances linearly (it's time — always monotonic); only Y is
  // spline-interpolated. This avoids parametric x-overshoot that
  // caused the chart line to zigzag back and forth in time.
  int16_t steps_per_seg = large ? 16 : (medium ? 8 : 4);

  for (int i = 0; i < num_pts - 1; i++)
  {
    // Y control points for Catmull-Rom (clamp at boundaries)
    float y0 = py_arr[max(0, i - 1)];
    float y1 = py_arr[i];
    float y2 = py_arr[i + 1];
    float y3 = py_arr[min(num_pts-1, i+2)];

    int16_t prev_sx = px_arr[i], prev_sy = (int16_t)y1;

    for (int s = 1; s <= steps_per_seg; s++)
    {
      float t = (float)s / steps_per_seg;

      int16_t cur_sx = px_arr[i] + (int16_t)(t * (px_arr[i + 1] - px_arr[i]));
      float sy = catmull_rom(y0, y1, y2, y3, t);

      cur_sx = constrain(cur_sx, chart_x, (int16_t)(chart_x + chart_w - 1));
      int16_t cur_sy = constrain((int16_t)sy, chart_y, (int16_t)(chart_y + chart_h - 1));

      gfx.drawLine(prev_sx, prev_sy, cur_sx, cur_sy, EPD_BLACK);
      if (large) // thicker line on large displays
        gfx.drawLine(prev_sx, prev_sy + 1, cur_sx, cur_sy + 1, EPD_BLACK);

      prev_sx = cur_sx;
      prev_sy = cur_sy;
    }
  }

  // Current reading: filled dot at the rightmost point
  if (num_pts > 0)
    gfx.fillCircle(px_arr[num_pts-1], py_arr[num_pts-1], large ? 4 : 2, EPD_BLACK);

  // X-axis labels at round wall-clock hours: 0h, 6h, 12h, 18h
  if (chart_h > 30)
  {
    gfx.setFont(large ? &FreeSans9pt7b : &TomThumb);
    gfx.setTextSize(1);
    gfx.setTextColor(EPD_BLACK);

    // Find the first round 6h mark at or after window_start
    struct tm ws_tm;
    localtime_r(&window_start, &ws_tm);
    ws_tm.tm_min = 0;
    ws_tm.tm_sec = 0;
    ws_tm.tm_hour = ((ws_tm.tm_hour / 6) + 1) * 6; // next multiple of 6
    time_t mark_time = mktime(&ws_tm);

    while (mark_time < now)
    {
      int16_t mark_x = chart_x + (int16_t)((float)(mark_time - window_start) / time_range * chart_w);
      if (mark_x >= chart_x + 5 && mark_x <= chart_x + chart_w - 10)
      {
        gfx.drawLine(mark_x, chart_y + chart_h - 2, mark_x, chart_y + chart_h + 1, EPD_BLACK);

        struct tm mark_tm;
        localtime_r(&mark_time, &mark_tm);
        char hlabel[4];
        snprintf(hlabel, sizeof(hlabel), "%dh", mark_tm.tm_hour);
        int16_t hlx, hly; uint16_t hlw, hlh;
        gfx.getTextBounds(hlabel, 0, 0, &hlx, &hly, &hlw, &hlh);
        gfx.setCursor(mark_x - hlw / 2 - hlx, chart_y + chart_h + 3 + hlh);
        gfx.print(hlabel);
      }
      mark_time += 6 * 3600;
    }
  }
}

// Draw a Catmull-Rom spline as individual dots at regular arc-length intervals.
// dot_spacing is the distance in pixels between consecutive dots along the curve.
static void draw_spline_dotted(Adafruit_GFX &gfx,
                                 const int16_t *py, int n,
                                 int16_t x0, int16_t chart_w,
                                 int16_t y_clamp_min, int16_t y_clamp_max,
                                 float dot_spacing, uint16_t color)
{
  if (n < 2 || dot_spacing <= 0) return;
  // Fine evaluation: enough steps so each covers well under 1px of arc length,
  // even on steep curve sections where Y changes rapidly between data points.
  int steps = max(32, chart_w / max(1, n - 1));

  // Track position in float to avoid int16_t truncation errors in distance calc.
  // With sub-pixel step sizes (~0.15px/step), integer rounding would lose most
  // of the X movement and make spacing appear Y-only.
  float prev_fx = (float)x0;
  float prev_fy = constrain((float)py[0], (float)y_clamp_min, (float)y_clamp_max);
  gfx.drawPixel((int16_t)prev_fx, (int16_t)prev_fy, color);
  float accum = 0;

  for (int i = 0; i < n - 1; i++)
  {
    float p0 = py[max(0, i - 1)];
    float p1 = py[i];
    float p2 = py[i + 1];
    float p3 = py[min(n - 1, i + 2)];

    for (int s = 1; s <= steps; s++)
    {
      float t = (float)s / steps;

      float frac = (i + t) / (n - 1);
      float cur_fx = x0 + frac * chart_w;
      float cur_fy = catmull_rom(p0, p1, p2, p3, t);
      cur_fy = constrain(cur_fy, (float)y_clamp_min, (float)y_clamp_max);

      float dx = cur_fx - prev_fx;
      float dy = cur_fy - prev_fy;
      accum += sqrtf(dx * dx + dy * dy);

      if (accum >= dot_spacing)
      {
        gfx.drawPixel((int16_t)cur_fx, (int16_t)cur_fy, color);
        accum = 0;
      }

      prev_fx = cur_fx;
      prev_fy = cur_fy;
    }
  }
}

// Draw a solid Catmull-Rom spline through an array of Y values evenly spaced on X.
static void draw_spline(Adafruit_GFX &gfx,
                         const int16_t *py, int n,
                         int16_t x0, int16_t chart_w,
                         int16_t y_clamp_min, int16_t y_clamp_max,
                         bool thick, uint16_t color)
{
  if (n < 2) return;
  int steps = max(2, chart_w / max(1, n - 1));

  for (int i = 0; i < n - 1; i++)
  {
    float p0 = py[max(0, i - 1)];
    float p1 = py[i];
    float p2 = py[i + 1];
    float p3 = py[min(n - 1, i + 2)];

    int16_t prev_sx = x0 + (int16_t)((float)i / (n - 1) * chart_w);
    int16_t prev_sy = constrain((int16_t)p1, y_clamp_min, y_clamp_max);

    for (int s = 1; s <= steps; s++)
    {
      float t = (float)s / steps;

      float frac = (i + t) / (n - 1);
      int16_t cur_sx = x0 + (int16_t)(frac * chart_w);

      float sy = catmull_rom(p0, p1, p2, p3, t);
      int16_t cur_sy = constrain((int16_t)sy, y_clamp_min, y_clamp_max);

      gfx.drawLine(prev_sx, prev_sy, cur_sx, cur_sy, color);
      if (thick)
        gfx.drawLine(prev_sx, prev_sy + 1, cur_sx, cur_sy + 1, color);

      prev_sx = cur_sx;
      prev_sy = cur_sy;
    }
  }
}

// Access hourly entry i from the circular buffer, including the in-progress
// current_hour_entry as the last element when has_current_hour is true.
static HourlyEntry get_hourly_entry(const DisplayStats &stats, int i)
{
  if (i < (int)stats.hourly_count)
  {
    int idx = (stats.hourly_start + i) % HOURLY_HISTORY_SIZE;
    return stats.hourly_history[idx];
  }
  return stats.current_hour_entry;
}

// --- Monthly chart: X-axis date labels at midnight boundaries ---

static void draw_monthly_xlabels(Adafruit_GFX &gfx,
                                   int16_t chart_x, int16_t chart_y,
                                   int16_t chart_w, int16_t chart_h,
                                   bool large, time_t oldest_time,
                                   float total_seconds)
{
  if (chart_h <= 20) return;

  gfx.setFont(large ? &FreeSans9pt7b : &TomThumb);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  // Find the first midnight at or after oldest_time
  struct tm mt;
  localtime_r(&oldest_time, &mt);
  mt.tm_hour = 0;
  mt.tm_min = 0;
  mt.tm_sec = 0;
  time_t midnight = mktime(&mt);
  if (midnight <= oldest_time)
    midnight += 86400;

  // Adaptive stride: keep weekly cadence when the span yields >=2 weekly
  // labels; otherwise step down so cold-start charts still have scale refs.
  float span_days = total_seconds / 86400.0f;
  int stride_days;
  if (span_days >= 14.0f)      stride_days = 7;
  else if (span_days >= 6.0f)  stride_days = 3;
  else if (span_days >= 3.0f)  stride_days = 2;
  else                         stride_days = 1;
  time_t stride_sec = (time_t)stride_days * 86400;

  time_t end_time = oldest_time + (time_t)total_seconds;
  while (midnight < end_time)
  {
    int16_t mark_x = chart_x + (int16_t)((float)(midnight - oldest_time) / total_seconds * chart_w);
    if (mark_x >= chart_x + 5 && mark_x <= chart_x + chart_w - 10)
    {
      gfx.drawLine(mark_x, chart_y + chart_h - 2, mark_x, chart_y + chart_h + 1, EPD_BLACK);

      struct tm label_tm;
      localtime_r(&midnight, &label_tm);
      const char *mon = month_abbr[label_tm.tm_mon];
      char dlabel[8];
      snprintf(dlabel, sizeof(dlabel), "%s %d", mon, label_tm.tm_mday);
      int16_t dlx, dly; uint16_t dlw, dlh;
      gfx.getTextBounds(dlabel, 0, 0, &dlx, &dly, &dlw, &dlh);
      gfx.setCursor(mark_x - dlw / 2 - dlx, chart_y + chart_h + 3 + dlh);
      gfx.print(dlabel);
    }
    midnight += stride_sec;
  }
}

// --- Monthly chart: hourly resolution for large displays ---
// Draws all hourly entries as three Catmull-Rom splines (max solid, avg dotted,
// min solid), showing daily temperature cycles and transient events over 30 days.

static void render_monthly_hourly(Adafruit_GFX &gfx, const Rect &zone,
                                    int16_t chart_x, int16_t chart_y,
                                    int16_t chart_w, int16_t chart_h,
                                    const DisplayStats &stats, time_t now)
{
  int total_pts = stats.hourly_count + (stats.has_current_hour ? 1 : 0);
  if (total_pts < 2) return;

  // Heap-allocate to avoid both stack overflow (720+ × 2B × 3 = ~4.3KB) and
  // permanent BSS usage that pushes past pioarduino's effective DRAM ceiling
  // on ESP32 boards without PSRAM (~48KB BSS limit).
  int16_t *py_avg = (int16_t *)malloc((HOURLY_HISTORY_SIZE + 1) * sizeof(int16_t));
  int16_t *py_min = (int16_t *)malloc((HOURLY_HISTORY_SIZE + 1) * sizeof(int16_t));
  int16_t *py_max = (int16_t *)malloc((HOURLY_HISTORY_SIZE + 1) * sizeof(int16_t));
  if (!py_avg || !py_min || !py_max) {
    free(py_avg); free(py_min); free(py_max);
    return;
  }

  // First pass: collect temp values, forward-fill sentinels, find Y range
  int16_t last_avg = 200, last_min = 200, last_max = 200; // 20°C default
  float y_min_f = 999.0f, y_max_f = -999.0f;

  for (int i = 0; i < total_pts; i++)
  {
    HourlyEntry e = get_hourly_entry(stats, i);

    // Forward-fill sentinel entries (cold start / gap) with last known value
    if (e.min_x10 == HOURLY_NO_DATA)
      e = { last_min, last_max, last_avg };
    else
    {
      last_avg = e.avg_x10;
      last_min = e.min_x10;
      last_max = e.max_x10;
    }

    // Store raw temp_x10 values (converted to pixel Y in second pass)
    py_avg[i] = e.avg_x10;
    py_min[i] = e.min_x10;
    py_max[i] = e.max_x10;

    float fmin = e.min_x10 / 10.0f;
    float fmax = e.max_x10 / 10.0f;
    if (fmin < y_min_f) y_min_f = fmin;
    if (fmax > y_max_f) y_max_f = fmax;
  }

  pad_y_range(y_min_f, y_max_f);
  float y_range = y_max_f - y_min_f;

  // Gridlines + Y-axis labels
  draw_y_grid(gfx, zone.x, 40, chart_x, chart_y, chart_w, chart_h,
              true, y_min_f, y_range);

  // Second pass: convert temp_x10 values to pixel Y coordinates in-place
  for (int i = 0; i < total_pts; i++)
  {
    py_avg[i] = chart_y + chart_h - 1 - (int16_t)((py_avg[i] / 10.0f - y_min_f) / y_range * (chart_h - 1));
    py_min[i] = chart_y + chart_h - 1 - (int16_t)((py_min[i] / 10.0f - y_min_f) / y_range * (chart_h - 1));
    py_max[i] = chart_y + chart_h - 1 - (int16_t)((py_max[i] / 10.0f - y_min_f) / y_range * (chart_h - 1));
  }

  // Three curves: avg (solid 2px), min/max envelope (dotted 1px, 2px spacing).
  int16_t y_clamp_max = (int16_t)(chart_y + chart_h - 1);
  draw_spline(gfx, py_avg, total_pts, chart_x, chart_w,
               chart_y, y_clamp_max, true, EPD_BLACK);
  draw_spline_dotted(gfx, py_max, total_pts, chart_x, chart_w,
                      chart_y, y_clamp_max, 2.0f, EPD_BLACK);
  draw_spline_dotted(gfx, py_min, total_pts, chart_x, chart_w,
                      chart_y, y_clamp_max, 2.0f, EPD_BLACK);

  // X-axis date labels every 7 days
  time_t oldest_time = stats.hourly_latest_time - (time_t)(stats.hourly_count - 1) * 3600;
  float total_seconds = (float)(total_pts - 1) * 3600;
  draw_monthly_xlabels(gfx, chart_x, chart_y, chart_w, chart_h,
                        true, oldest_time, total_seconds);

  free(py_avg); free(py_min); free(py_max);
}

// --- Monthly chart: daily-derived view for small displays ---
// Groups hourly entries into days and draws daily min/max/avg splines,
// matching the visual style of the original daily chart.

static void render_monthly_daily(Adafruit_GFX &gfx, const Rect &zone,
                                   int16_t chart_x, int16_t chart_y,
                                   int16_t chart_w, int16_t chart_h,
                                   int16_t label_w, bool large,
                                   const DisplayStats &stats)
{
  int total_hourly = stats.hourly_count + (stats.has_current_hour ? 1 : 0);
  if (total_hourly == 0) return;

  // Derive daily summaries by grouping hourly entries by calendar day.
  // Uses hour-of-day modular arithmetic to detect midnight crossings,
  // avoiding expensive localtime_r calls in the inner loop.
  // (Ignores DST transitions — off by ±1 hour on transition days, negligible.)
  struct DerivedDay { float min_f, max_f, avg_f; uint8_t day; uint8_t month; };
  DerivedDay days[32];
  int num_days = 0;

  // Get hour-of-day for the oldest entry (one localtime_r call)
  time_t oldest_time = stats.hourly_latest_time - (time_t)(stats.hourly_count - 1) * 3600;
  struct tm oldest_tm;
  localtime_r(&oldest_time, &oldest_tm);
  int h = oldest_tm.tm_hour;

  int16_t day_min = TEMP_INIT_MIN_X10, day_max = TEMP_INIT_MAX_X10;
  int32_t day_sum = 0;
  int day_count = 0;
  float y_min = 999.0f, y_max = -999.0f;

  for (int i = 0; i < total_hourly; i++)
  {
    HourlyEntry e = get_hourly_entry(stats, i);

    // Skip sentinel entries (cold start gaps)
    if (e.min_x10 == HOURLY_NO_DATA) { h = (h + 1) % 24; continue; }

    if (e.min_x10 < day_min) day_min = e.min_x10;
    if (e.max_x10 > day_max) day_max = e.max_x10;
    day_sum += e.avg_x10;
    day_count++;

    h = (h + 1) % 24;
    bool midnight = (h == 0);
    bool last = (i == total_hourly - 1);

    if ((midnight || last) && day_count > 0 && num_days < 32)
    {
      // Compute the calendar date for this day (one localtime_r per day)
      time_t day_time = oldest_time + (time_t)i * 3600;
      struct tm day_tm;
      localtime_r(&day_time, &day_tm);

      days[num_days].min_f = day_min / 10.0f;
      days[num_days].max_f = day_max / 10.0f;
      days[num_days].avg_f = (float)day_sum / day_count / 10.0f;
      days[num_days].day = day_tm.tm_mday;
      days[num_days].month = day_tm.tm_mon + 1;

      if (days[num_days].min_f < y_min) y_min = days[num_days].min_f;
      if (days[num_days].max_f > y_max) y_max = days[num_days].max_f;
      num_days++;

      day_min = TEMP_INIT_MIN_X10; day_max = TEMP_INIT_MAX_X10;
      day_sum = 0; day_count = 0;
    }
  }

  if (num_days < 2) return;

  pad_y_range(y_min, y_max);
  float y_range = y_max - y_min;

  // Gridlines + Y-axis labels
  draw_y_grid(gfx, zone.x, label_w, chart_x, chart_y, chart_w, chart_h,
              large, y_min, y_range);

  // Convert to pixel Y coordinates
  int16_t py_min_arr[32], py_max_arr[32], py_avg_arr[32];
  for (int i = 0; i < num_days; i++)
  {
    py_min_arr[i] = chart_y + chart_h - 1 - (int16_t)((days[i].min_f - y_min) / y_range * (chart_h - 1));
    py_max_arr[i] = chart_y + chart_h - 1 - (int16_t)((days[i].max_f - y_min) / y_range * (chart_h - 1));
    py_avg_arr[i] = chart_y + chart_h - 1 - (int16_t)((days[i].avg_f - y_min) / y_range * (chart_h - 1));
  }

  // Draw curves: avg solid, min/max dotted envelope.
  // On very short charts (< 20px), skip envelope — too cramped to be useful.
  int16_t y_clamp_max = (int16_t)(chart_y + chart_h - 1);
  draw_spline(gfx, py_avg_arr, num_days, chart_x, chart_w,
               chart_y, y_clamp_max, false, EPD_BLACK);
  if (chart_h >= 20)
  {
    draw_spline_dotted(gfx, py_max_arr, num_days, chart_x, chart_w,
                        chart_y, y_clamp_max, 2.0f, EPD_BLACK);
    draw_spline_dotted(gfx, py_min_arr, num_days, chart_x, chart_w,
                        chart_y, y_clamp_max, 2.0f, EPD_BLACK);
  }

  // X-axis date labels every 7 days
  if (chart_h > 20 && num_days > 7)
  {
    gfx.setFont(large ? &FreeSans9pt7b : &TomThumb);
    gfx.setTextSize(1);
    gfx.setTextColor(EPD_BLACK);

    for (int i = 0; i < num_days; i += 7)
    {
      int16_t mark_x = chart_x + (int16_t)((float)i / (num_days - 1) * chart_w);
      gfx.drawLine(mark_x, chart_y + chart_h - 2, mark_x, chart_y + chart_h + 1, EPD_BLACK);

      const char *mon = (days[i].month >= 1 && days[i].month <= 12)
        ? month_abbr[days[i].month - 1] : "?";
      char dlabel[8];
      snprintf(dlabel, sizeof(dlabel), "%s %d", mon, days[i].day);
      int16_t dlx, dly; uint16_t dlw, dlh;
      gfx.getTextBounds(dlabel, 0, 0, &dlx, &dly, &dlw, &dlh);
      gfx.setCursor(mark_x - dlw / 2 - dlx, chart_y + chart_h + 3 + dlh);
      gfx.print(dlabel);
    }
  }
}

// --- Monthly chart entry point ---
// Large displays (chart_w >= 400): hourly resolution showing daily cycles.
// Small displays: daily summaries derived from hourly data.

void render_monthly_chart(Adafruit_GFX &gfx, const Rect &zone,
                           const DisplayStats &stats, time_t now)
{
  if (zone.h < 20) return;

  int total = stats.hourly_count + (stats.has_current_hour ? 1 : 0);
  if (total == 0) return;

  draw_hline(gfx, zone.x, zone.y, zone.w, EPD_BLACK);

  // Chart area dimensions
  bool large = (zone.h >= 80);
  int16_t label_w = large ? 40 : 18;
  int16_t pad_top = large ? 8 : 3;
  int16_t pad_bot = large ? 22 : (zone.h > 30 ? 10 : 2);
  int16_t pad_right = large ? 6 : 3;
  int16_t chart_x = zone.x + label_w;
  int16_t chart_y = zone.y + pad_top;
  int16_t chart_w = zone.w - label_w - pad_right;
  int16_t chart_h = zone.h - pad_top - pad_bot;

  if (chart_w < 10 || chart_h < 10) return;

  // Large displays have enough pixels to show all 720 hourly entries
  // with daily temperature cycles visible. Small displays aggregate
  // into daily min/max/avg for a cleaner view.
  if (chart_w >= 400)
    render_monthly_hourly(gfx, zone, chart_x, chart_y, chart_w, chart_h,
                           stats, now);
  else
    render_monthly_daily(gfx, zone, chart_x, chart_y, chart_w, chart_h,
                          label_w, large, stats);
}

void render_info(Adafruit_GFX &gfx, int16_t x, int16_t y, int16_t w,
                  uint32_t battery_mv, bool low_battery,
                  const struct tm *nowtm)
{
  // Three tiers: compact (landscape embed), normal (200x200), large (920x680)
  bool compact = (w < 160);
  bool large = (w >= 600);
  uint16_t bat_color = low_battery ? EPD_RED : EPD_BLACK;

  int16_t bat_w = compact ? 12 : (large ? 28 : 18);
  int16_t bat_h = bat_w / 2;

  // Measure text to compute vertical centering within the info zone
  const GFXfont *info_font = compact ? &Org_01 : (large ? &FreeSans12pt7b : &FreeSans9pt7b);
  gfx.setFont(info_font);
  gfx.setTextSize(1);

  char bat_str[16];
  if (compact)
    snprintf(bat_str, sizeof(bat_str), "%.2fV", battery_mv / 1000.0f);
  else
    snprintf(bat_str, sizeof(bat_str), "%dmV", (int)battery_mv);

  int16_t tbx, tby; uint16_t tbw, tbh;
  gfx.getTextBounds(bat_str, 0, 0, &tbx, &tby, &tbw, &tbh);
  int16_t text_h = -tby; // ascent (tby is negative)

  // Center icon and text vertically in the info zone.
  // Zone heights: 30px (large portrait), 22px (small portrait), ~12px (landscape embed)
  int16_t zone_h = compact ? (bat_h + 4) : (large ? 30 : 22);
  int16_t mid_y = y + zone_h / 2;

  int16_t bat_x = x + 4;
  int16_t bat_y = mid_y - bat_h / 2;
  draw_battery_icon(gfx, bat_x, bat_y, bat_w, bat_h, battery_mv, bat_color);

  int16_t text_baseline = mid_y + text_h / 2;

  gfx.setTextColor(bat_color);
  gfx.setCursor(bat_x + bat_w + (large ? 12 : 6), text_baseline);
  gfx.print(bat_str);

  // Date + time, right-aligned, same baseline. Pick the longest variant that
  // fits in the space between the battery text and the right edge: full date
  // with year, then date without year, then time-only.
  gfx.setTextColor(EPD_BLACK);

  char t_only[8];
  char t_date[16];
  char t_full[24];
  strftime(t_only, sizeof(t_only), "%H:%M", nowtm);
  snprintf(t_date, sizeof(t_date), "%s %d  %s",
           month_abbr[nowtm->tm_mon], nowtm->tm_mday, t_only);
  snprintf(t_full, sizeof(t_full), "%s %d %d  %s",
           month_abbr[nowtm->tm_mon], nowtm->tm_mday,
           nowtm->tm_year + 1900, t_only);

  int16_t bat_text_end = bat_x + bat_w + (large ? 12 : 6) + (int16_t)tbw;
  int16_t min_gap = large ? 20 : 10;
  int16_t avail_w = (x + w - 6) - bat_text_end - min_gap;

  // Skip date if clock is pre-NTP (year looks bogus)
  bool year_ok = (nowtm->tm_year + 1900) >= 2024;
  const char *candidates[3];
  int nc = 0;
  if (year_ok)
  {
    candidates[nc++] = t_full;
    candidates[nc++] = t_date;
  }
  candidates[nc++] = t_only;

  const char *time_str = t_only;
  for (int i = 0; i < nc; i++)
  {
    gfx.getTextBounds(candidates[i], 0, 0, &tbx, &tby, &tbw, &tbh);
    if ((int16_t)tbw <= avail_w || i == nc - 1)
    {
      time_str = candidates[i];
      break;
    }
  }

  gfx.setCursor(x + w - tbw - 6 - tbx, text_baseline);
  gfx.print(time_str);
}

// Compact span: "45m" under an hour, "7h" under a day, "21d" beyond.
static void fmt_span(char *buf, size_t n, time_t secs)
{
  if (secs < 0) secs = 0;
  if (secs < 3600)
    snprintf(buf, n, "%dm", (int)(secs / 60));
  else if (secs < 86400)
    snprintf(buf, n, "%dh", (int)(secs / 3600));
  else
    snprintf(buf, n, "%dd", (int)(secs / 86400));
}

#define FOOTER_TEXT_LEN 128

// Append to a fixed buffer, saturating instead of running off the end.
// snprintf() returns the length it WOULD have written, so accumulating that
// return value directly walks `out + pos` past the buffer and makes the next
// call's `n - pos` underflow to a huge size_t — a stack smash on the render
// path, reachable whenever the RTC counters hold garbage (which is exactly the
// ULP-scribbles-on-RTC_DATA case the RTC headroom check exists for). Losing the
// tail of the footer is fine: the caller measures this string and drops what
// does not fit anyway.
static void footer_append(char *out, size_t n, size_t *pos, const char *fmt, ...)
{
  if (n == 0 || *pos >= n - 1) return;
  va_list ap;
  va_start(ap, fmt);
  int w = vsnprintf(out + *pos, n - *pos, fmt, ap);
  va_end(ap);
  if (w < 0) return;
  *pos = ((size_t)w >= n - *pos) ? n - 1 : *pos + (size_t)w;
}

// The footer as one string. Built separately from the drawing so the status
// indicators can measure it and only repeat the build hash when this line is
// too long for the panel to show it.
static void build_footer_text(char *out, size_t n, time_t now,
                               const DisplayStats &stats)
{
  time_t uptime = now - stats.first_boot_time;
  int up_days = (int)(uptime / 86400);
  int up_hours = (int)((uptime % 86400) / 3600);

  // Unknown-but-nonzero cause: show the raw bitmap so an unmapped wake source
  // (new IDF cause, LP core trap, ...) is identifiable from the screen.
  // BIT(0) is excluded — that's just IDF's "undefined" marker, set on every
  // boot that isn't a deep-sleep wake (power-on, flash, crash reset).
  char wake_unk[12] = "?";
  if (stats.wake_cause == 0 && (stats.wake_causes_raw & ~1u) != 0)
    snprintf(wake_unk, sizeof(wake_unk), "?%x", (unsigned)stats.wake_causes_raw);
  const char *wake_str = (stats.wake_cause == 1) ? "ULP" :
                          (stats.wake_cause == 2) ? "TMR" :
                          (stats.wake_cause == 3) ? "USB" : wake_unk;

  // Format first boot date if NTP-synced (epoch > 1 day means real time)
  char boot_date[12] = "";
  if (stats.ntp_synced)
  {
    struct tm bt;
    localtime_r(&stats.first_boot_time, &bt);
    snprintf(boot_date, sizeof(boot_date), "%s%d'%02d",
             month_abbr[bt.tm_mon], bt.tm_mday, bt.tm_year % 100);
  }

  // Age since last successful NTP sync — confirms resync is actually working
  // on long-running deployments (grows unbounded if resync silently fails).
  char sync_str[12] = "";
  if (stats.ntp_synced && stats.last_sync_time > 0)
  {
    char age[10];
    fmt_span(age, sizeof(age), now - stats.last_sync_time);
    snprintf(sync_str, sizeof(sync_str), " s%s", age);
  }

  // Compact uptime: skip "0h", show hours only when non-zero
  char uptime_str[12];
  if (up_hours > 0)
    snprintf(uptime_str, sizeof(uptime_str), "%dd%dh", up_days, up_hours);
  else
    snprintf(uptime_str, sizeof(uptime_str), "%dd", up_days);

  size_t pos = 0;
  footer_append(out, n, &pos, "#%d r%d lp%u",
                stats.boot_count, stats.display_refresh_count,
                (unsigned)stats.lp_wake_count);
  if (stats.lp_error_count > 0)
    footer_append(out, n, &pos, " e%u", (unsigned)stats.lp_error_count);
  if (stats.ulp_reinit_count > 1)
    footer_append(out, n, &pos, " u%u", (unsigned)stats.ulp_reinit_count);
  footer_append(out, n, &pos, " %s w:%s mx%.1fV",
                uptime_str, wake_str, stats.max_battery_mv / 1000.0f);
  if (stats.bad_pin27_count > 0)
    footer_append(out, n, &pos, " b27:%d", (int)stats.bad_pin27_count);
  footer_append(out, n, &pos, " %s", GIT_HASH);
  if (boot_date[0])
    footer_append(out, n, &pos, " %s", boot_date);
  if (sync_str[0])
    footer_append(out, n, &pos, "%s", sync_str);
}

void render_footer(Adafruit_GFX &gfx, const Rect &zone,
                    time_t now, const DisplayStats &stats)
{
  draw_hline(gfx, zone.x, zone.y, zone.w, EPD_BLACK);

  bool large = (zone.w >= 600);
  gfx.setFont(large ? &FreeSans12pt7b : &Org_01);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  // Center text vertically in the footer zone
  int16_t fx, fy; uint16_t fw, fh;
  gfx.getTextBounds("M", 0, 0, &fx, &fy, &fw, &fh);
  int16_t footer_text_y = zone.y + zone.h / 2 + (-fy) / 2;

  char text[FOOTER_TEXT_LEN];
  build_footer_text(text, sizeof(text), now, stats);
  gfx.setCursor(zone.x + (large ? 4 : 2), footer_text_y);
  gfx.print(text);
}

// --- Status indicators (top-left corner of temp zone) ---

// Must cover every token that can be emitted in one frame, because nothing
// bounds-checks ntok: overrunning tok[] is a stack overwrite, not a dropped
// badge. The worst case is 11 — lab flags, USB window, NOARCH, crash,
// WIFI-or-NTP, NOSYNC, SENSOR, DRIFT, its ppm summary, LP, and the git hash the
// footer could not fit — so this carries one spare slot. Count again before
// adding a badge.
#define IND_MAX_TOKENS 12
#define IND_TOKEN_LEN  80
#define IND_LINE_LEN   128

// Rendered width of a string in the current font, left bearing included.
static int16_t text_width(Adafruit_GFX &gfx, const char *s)
{
  int16_t bx, by; uint16_t bw, bh;
  gfx.getTextBounds(s, 0, 0, &bx, &by, &bw, &bh);
  return (int16_t)bw + bx;
}

// Longest prefix of s that fits in max_w, never less than one character
// (otherwise a too-narrow zone would loop forever).
static int fit_prefix(Adafruit_GFX &gfx, const char *s, int16_t max_w)
{
  char buf[IND_TOKEN_LEN + 1];
  int len = (int)strlen(s);
  if (len > IND_TOKEN_LEN) len = IND_TOKEN_LEN;
  int best = 1;
  for (int n = 1; n <= len; n++)
  {
    memcpy(buf, s, (size_t)n);
    buf[n] = '\0';
    if (text_width(gfx, buf) > max_w)
      break;
    best = n;
  }
  return best;
}

// Height one indicator line occupies in the font the zone will use.
static int16_t indicator_line_h(Adafruit_GFX &gfx, const Layout &L)
{
  bool large = (L.dh >= 400 || L.dw >= 600);
  gfx.setFont(large ? &FreeSans12pt7b : &Org_01);
  gfx.setTextSize(1);
  int16_t bx, by; uint16_t bw, bh;
  gfx.getTextBounds("Mg", 0, 0, &bx, &by, &bw, &bh);
  return (int16_t)bh + (large ? 6 : 3);
}

static void render_status_indicators(Adafruit_GFX &gfx, const Layout &L,
                                       const DisplayStats &stats, time_t now)
{
  // Only render when there's an issue — no clutter when things are normal
  bool significant_drift = abs(stats.clock_drift_ms) >= 60000;  // >= 1 minute
  bool debug_build = !stats.power_efficient;
  bool resync_failing = stats.resync_fail_count > 0;
  // LP errors are only alarm-worthy when they form a meaningful fraction of
  // wake attempts (>=10%). Ignore rare transients and early-boot noise.
  bool lp_errors_significant = stats.lp_wake_count > 0
                             && stats.lp_error_count >= 3
                             && stats.lp_error_count * 10 >= stats.lp_wake_count;
  if (stats.wifi_ok && stats.ntp_synced && stats.sensor_ok
      && !stats.dummy_sensor && !stats.mock_data && !significant_drift
      && !resync_failing && stats.archive_fault == 0
      && !debug_build && !lp_errors_significant && stats.crash_count == 0
      && !stats.usb_window && stats.experiment_arm == 0)
    return;

  // Badges, most severe first — the tail is what gets replaced by a "+" when
  // the panel runs out of room.
  char tok[IND_MAX_TOKENS][IND_TOKEN_LEN];
  int ntok = 0;

  // Lab-build flags lead, in a single token. They are not a failure, but they
  // are the only badge that changes how the BIG NUMBER should be read — a
  // DummySensor build shows a constant 12.3C as if it were a measurement — and
  // that warning cannot come from anywhere but the screen. Ranked last it was
  // droppable: on a 200x200 a crash badge plus a drift badge already fill the
  // three available lines, so a lab build that had also crashed hid the fact
  // its reading was synthetic. Everything below it is also on serial and in the
  // coredump. One token, not three, so it costs at most one line — and in a
  // field build it is absent entirely, so leading with it costs nothing there.
  {
    char lab[IND_TOKEN_LEN];
    int pos = 0;
    // An experiment arm supersedes the plain debug badge rather than stacking
    // with it: it already implies a lab build, it carries the same sleep
    // interval, and the 200x200 status line is the scarce resource — a drift
    // badge, its ppm summary and the repeated hash are usually there too.
    if (stats.experiment_arm)
      pos += snprintf(lab + pos, IND_TOKEN_LEN - pos, "! EXP %u %ds",
                      (unsigned)stats.experiment_arm, SLEEP_INTERVAL_S);
    else if (debug_build)
      pos += snprintf(lab + pos, IND_TOKEN_LEN - pos, "! DEBUG %ds", SLEEP_INTERVAL_S);
    if (stats.dummy_sensor)
      pos += snprintf(lab + pos, IND_TOKEN_LEN - pos, "%s", pos ? "/DUMMY" : "! DUMMY");
    if (stats.mock_data)
      pos += snprintf(lab + pos, IND_TOKEN_LEN - pos, "%s", pos ? "/MOCK" : "! MOCK");
    // Distinct from the generic DEBUG flag because it says something the others
    // do not: this build's own instrumentation is on the trace. A capture
    // harvested from it reads high, so a photo of the panel has to be able to
    // disqualify the number.
    if (stats.ppk2_instrumented)
      pos += snprintf(lab + pos, IND_TOKEN_LEN - pos, "%s", pos ? "/PPK2" : "! PPK2");
    if (pos)
      snprintf(tok[ntok++], IND_TOKEN_LEN, "%s", lab);
  }

  // Held awake to keep the USB port enumerated for a reflash. Ranked with the
  // lab flags and for the same reason: the board is drawing milliamps instead of
  // microamps, and its own CPU is warming the sensor beside it, so the number
  // above is biased upward while this is on the panel. It is also the only way to
  // tell a parked board from a sleeping one without instruments.
  if (stats.usb_window)
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! USB");

  // Nothing is being archived. Ranked ahead of the crash badge because it is
  // the only condition here that is still destroying data: every hour it goes
  // unnoticed is permanently lost, whereas a crash's payload is already saved
  // to the coredump partition and does not degrade. It also cannot be seen any
  // other way — DISABLE_SERIAL removes the log line from release builds — and
  // it persists until someone runs `history.py backup` and erases the
  // partition, so it must survive the "+" overflow marker.
  if (stats.archive_fault != 0)
  {
    switch (stats.archive_fault)
    {
      case HS_FAULT_FOREIGN_FORMAT:
        // Says which format is on flash: the archive is intact and readable by
        // tools/history.py, this build just does not speak that version.
        snprintf(tok[ntok++], IND_TOKEN_LEN, "! NOARCH fmt%u",
                 (unsigned)stats.archive_flash_format);
        break;
      case HS_FAULT_NO_PARTITION:
        snprintf(tok[ntok++], IND_TOKEN_LEN, "! NOARCH nopart");
        break;
      default:
        snprintf(tok[ntok++], IND_TOKEN_LEN, "! NOARCH io");
        break;
    }
  }

  if (stats.crash_count > 0)
  {
    // Crash forensics, e.g. "! PANIC x2 @#273/render 3h pc:42008a3c main".
    // The boot counter restarts after every crash (RTC_DATA is wiped), so
    // @#N is relative to the crashed boot's own power-on epoch. Ranked ahead of
    // the live-fault badges below: those describe a state you can still go and
    // read, this describes an event that is already over.
    static const char *stage_names[] = {
      "?", "boot", "ulp", "sensor", "ntp", "render", "lpinit", "sleep", "usb"};
    uint8_t st = (stats.crash_stage < sizeof(stage_names) / sizeof(stage_names[0]))
                 ? stats.crash_stage : 0;
    char *rst_str = tok[ntok++];
    int pos = snprintf(rst_str, IND_TOKEN_LEN, "! %s", stats.crash_reason);
    if (stats.crash_count > 1)
      pos += snprintf(rst_str + pos, IND_TOKEN_LEN - pos, " x%u",
                      (unsigned)stats.crash_count);
    pos += snprintf(rst_str + pos, IND_TOKEN_LEN - pos, " @#%d/%s",
                    (int)stats.crash_boot_count, stage_names[st]);
    if (stats.crash_time > 0 && now > (time_t)stats.crash_time)
    {
      char age[10];
      fmt_span(age, sizeof(age), now - (time_t)stats.crash_time);
      pos += snprintf(rst_str + pos, IND_TOKEN_LEN - pos, " %s", age);
    }
    if (stats.crash_pc != 0)
      snprintf(rst_str + pos, IND_TOKEN_LEN - pos, " pc:%x@%s %s",
               (unsigned)stats.crash_pc, stats.crash_elf_sha,
               stats.crash_task);
  }

  if (!stats.wifi_ok)
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! NO WIFI");
  else if (!stats.ntp_synced)  // WiFi connected but NTP failed — different root cause
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! NO NTP");

  // Resync attempts failing: both the WiFi and the SNTP path just defer, so
  // without this the only symptom is a clock quietly free-running for another
  // interval. "! NOSYNC x2 14d" = 2 failures in a row, clock last set 14d ago.
  if (resync_failing)
  {
    char age[10] = "?";
    if (stats.last_sync_time > 0)
      fmt_span(age, sizeof(age), now - stats.last_sync_time);
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! NOSYNC x%u %s",
             (unsigned)stats.resync_fail_count, age);
  }

  if (!stats.sensor_ok)
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! SENSOR");

  if (significant_drift)
  {
    // "! DRIFT -9559s/21d". The window is the measured span since the clock
    // was last set, not the resync interval — each failed attempt stretches it
    // by a full interval, and the rate only means something against the span
    // the drift actually accrued over.
    char *d = tok[ntok++];
    int pos = snprintf(d, IND_TOKEN_LEN, "! DRIFT %+ds",
                       (int)(stats.clock_drift_ms / 1000));
    if (stats.drift_window_s > 0)
    {
      char span[10];
      fmt_span(span, sizeof(span), stats.drift_window_s);
      snprintf(d + pos, IND_TOKEN_LEN - pos, "/%s", span);
    }

    // "-5250ppm n4 ±2%" — the summary that survives missing a resync: the
    // rate the retained samples agree on, how many there are, and how far the
    // worst one sits from that rate. Tight over several samples means the RC
    // error is a constant worth compensating for; wide means it moves, and no
    // single correction factor would hold.
    //
    // Its own token so it wraps onto its own line rather than splitting
    // mid-number on a narrow panel.
    if (stats.drift_ppm_count > 0)
    {
      // Window-weighted, i.e. total drift over total observed time. Windows
      // vary (adaptive interval, failed attempts stretching it), and a short
      // one is the noisier estimate — the ±1s quantisation of an NTP-set
      // clock is 12ppm over a day but 280ppm over an hour. An unweighted mean
      // would let the weakest sample pull hardest.
      int64_t wsum = 0, wtot = 0;
      for (uint8_t i = 0; i < stats.drift_ppm_count; i++)
      {
        wsum += (int64_t)stats.drift_ppm_hist[i] * stats.drift_win_min[i];
        wtot += stats.drift_win_min[i];
      }
      int32_t mean = wtot ? (int32_t)(wsum / wtot) : 0;
      char *r = tok[ntok++];
      pos = snprintf(r, IND_TOKEN_LEN, "%+dppm n%u",
                     (int)mean, (unsigned)stats.drift_ppm_count);
      if (stats.drift_ppm_count > 1 && mean != 0)
      {
        // Widest single deviation from that mean, as a share of it — so
        // "+-2%" reads the way it looks: every sample landed within 2% of the
        // rate. ASCII because Org_01 and FreeSans12pt7b stop at 0x7E.
        int32_t worst = 0;
        for (uint8_t i = 0; i < stats.drift_ppm_count; i++)
          worst = max(worst, (int32_t)abs(stats.drift_ppm_hist[i] - mean));
        int32_t pct = worst * 100 / abs(mean);
        snprintf(r + pos, IND_TOKEN_LEN - pos, " +-%d%%",
                 (int)min(pct, (int32_t)999));
      }
    }
  }

  if (lp_errors_significant)
  {
    // op 1 = trigger/command write, 2 = sensor data read. Error is the raw
    // esp_err_t — grep ESP-IDF esp_err.h (e.g. 0x107 = ESP_ERR_TIMEOUT).
    const char *op_str = (stats.last_lp_op == 1) ? "W"
                       : (stats.last_lp_op == 2) ? "R"
                       : "?";
    snprintf(tok[ntok++], IND_TOKEN_LEN, "! LP %s 0x%x",
             op_str, (unsigned)stats.last_lp_error);
  }

  // The build hash goes last, and only when the footer's own copy can't be
  // read. Nothing above is actionable without knowing which build produced it,
  // but leading with it would spend the widest line on a field the panel may
  // already be showing.
  //
  // Measure only up to the END OF THE HASH, not the whole footer: the hash is
  // not the last field — the boot date and sync age follow it — so a footer
  // that overflows on those still shows the hash, and testing the full width
  // put a redundant copy in the status line on exactly the panels that did not
  // need one.
  {
    bool footer_large = (L.foot.w >= 600);
    gfx.setFont(footer_large ? &FreeSans12pt7b : &Org_01);
    gfx.setTextSize(1);
    // Wrap MUST be off to measure: with it on, getTextBounds wraps at the
    // canvas edge and the width saturates there, which on a 200px panel is
    // always wider than foot.w and so reported "clipped" for any footer long
    // enough to wrap at all. That repeated the hash even when it was plainly
    // readable in the footer.
    gfx.setTextWrap(false);
    char footer_text[FOOTER_TEXT_LEN];
    build_footer_text(footer_text, sizeof(footer_text), now, stats);

    const char *h = strstr(footer_text, GIT_HASH);
    if (h)
      footer_text[(h - footer_text) + strlen(GIT_HASH)] = '\0';
    if (text_width(gfx, footer_text) > L.foot.w - (footer_large ? 8 : 4))
      snprintf(tok[ntok++], IND_TOKEN_LEN, "%s", GIT_HASH);
  }

  bool large = (L.dh >= 400 || L.dw >= 600);
  gfx.setFont(large ? &FreeSans12pt7b : &Org_01);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);
  // Wrapping is done here, not by Adafruit_GFX: its wrap breaks mid-glyph-run
  // at the canvas edge and keeps going down the screen, over the temperature.
  gfx.setTextWrap(false);

  int16_t line_h = indicator_line_h(gfx, L);
  int16_t x = L.temp.x + 4;
  int16_t y = L.temp.y + (large ? 20 : 6);
  int16_t max_w = L.temp.w - 8;
  int16_t plus_w = text_width(gfx, " +");
  int16_t min_char_w = text_width(gfx, "M");
  // Advance of a space: measured as a difference because a space has no ink of
  // its own for getTextBounds to report.
  int16_t space_w = text_width(gfx, "M M") - 2 * min_char_w;

  // This runs after the temperature, and each line paints its own white band
  // first, so overflowing onto a second or third line stays readable — it
  // covers part of the digits instead of interleaving with them. Bounded by
  // the temp zone so it can never reach the sparkline below.
  int16_t max_lines = (int16_t)((L.temp.h - (y - L.temp.y)) / line_h);
  max_lines = constrain(max_lines, (int16_t)1, (int16_t)3);

  // Greedy pack: badges stay whole where they fit, one too wide for a whole
  // line is split rather than dropped, and a trailing "+" marks what didn't
  // fit at all (readable on serial, so the screen only has to say it exists).
  // Widths are accumulated rather than re-measured on a candidate string —
  // glyph advances are additive, and it keeps one line buffer on the stack.
  char line[IND_LINE_LEN];
  int t = 0;                 // next badge to place
  const char *rest = NULL;   // unplaced tail of a split badge
  int16_t lines_drawn = 0;

  while (t < ntok && lines_drawn < max_lines)
  {
    bool last_line = (lines_drawn == max_lines - 1);
    int len = 0;
    int16_t line_w = 0;
    line[0] = '\0';

    while (t < ntok)
    {
      const char *s = rest ? rest : tok[t];
      int sl = (int)strlen(s);
      int sep = len ? 1 : 0;
      const int16_t room = max_w - line_w - (sep ? space_w : 0);

      // The "+" costs width only on the last line, and only when something will
      // actually be left over. Placing a badge WHOLE leaves something over only
      // if another badge follows; SPLITTING one always does — including when it
      // is the last badge. Deciding the reservation before the split was known
      // let that case draw plus_w past the temp zone, and the white band behind
      // it erased pixels outside the zone too.
      int16_t avail = room;
      if (last_line && (rest || t + 1 < ntok))
        avail -= plus_w;
      const int16_t avail_split = last_line ? (int16_t)(room - plus_w) : room;

      if (text_width(gfx, s) <= avail && len + sep + sl < IND_LINE_LEN)
      {
        if (sep) line[len++] = ' ';
        memcpy(line + len, s, (size_t)sl);
        len += sl;
        line[len] = '\0';
        line_w = text_width(gfx, line);
        t++;
        rest = NULL;
        continue;
      }
      if (len == 0 || text_width(gfx, s) > max_w)
      {
        // Badge can never fit a line of its own, so splitting it here beats
        // flushing a half-empty line and splitting it on the next one anyway.
        if (avail_split < min_char_w)
          break;  // not even one character fits — flush the line as it stands
        int n = fit_prefix(gfx, s, avail_split);
        if (len + sep + n >= IND_LINE_LEN)
          break;
        if (sep) line[len++] = ' ';
        memcpy(line + len, s, (size_t)n);
        len += n;
        line[len] = '\0';
        rest = s + n;
      }
      break;  // line is full; the rest goes on the next one
    }

    if (len == 0)
      break;  // zone too narrow for even one character — nothing left to draw

    if (last_line && (t < ntok || rest) && len + 3 < IND_LINE_LEN)
    {
      line[len++] = ' ';
      line[len++] = '+';
      line[len] = '\0';
    }

    int16_t ly = y + lines_drawn * line_h;
    int16_t bx, by; uint16_t bw, bh;
    gfx.getTextBounds(line, x, ly, &bx, &by, &bw, &bh);
    gfx.fillRect(bx - 1, by - 1, (int16_t)bw + 2, (int16_t)bh + 2, EPD_WHITE);
    gfx.setCursor(x, ly);
    gfx.print(line);
    lines_drawn++;
  }

  gfx.setTextWrap(true);
}

// --- Full dashboard render ---

void render_dashboard(Adafruit_GFX &gfx, int16_t w, int16_t h,
                       float temp, uint32_t battery_mv, bool low_battery,
                       time_t now, const struct tm *nowtm,
                       const DisplayStats &stats)
{
  Layout L = compute_layout(w, h);

  render_temperature(gfx, L, temp, stats);
  render_status_indicators(gfx, L, stats, now);
  render_sparkline(gfx, L.spark, stats, now);
  render_monthly_chart(gfx, L.month, stats, now);

  // Info bar: embedded in temp zone bottom (landscape) or separate zone (portrait)
  if (L.landscape)
  {
    render_info(gfx, L.temp.x, L.temp.y + L.temp.h - 22,
                L.temp.w, battery_mv, low_battery, nowtm);
  }
  else
  {
    draw_hline(gfx, L.info.x, L.info.y, L.info.w, EPD_BLACK);
    render_info(gfx, L.info.x, L.info.y, L.info.w,
                battery_mv, low_battery, nowtm);
  }

  render_footer(gfx, L.foot, now, stats);
}

void render_empty_battery(Adafruit_GFX &gfx, int16_t w, int16_t h,
                           uint32_t battery_mv, time_t now,
                           const DisplayStats &stats)
{
  Layout L = compute_layout(w, h);
  bool large = (min(w, h) >= 400);

  // Warning text — sized to fit the display
  gfx.setTextWrap(false);
  gfx.setTextColor(EPD_BLACK);

  // Compute available height above footer
  int16_t avail_h = L.foot.y;

  int16_t line_gap, y1;
  if (large)
  {
    // Big display: use the build-time generated alert font (no aliased scaling)
    gfx.setFont(get_alert_font(w, h));
    line_gap = 70;
    y1 = avail_h / 5;
  }
  else
  {
    // Small displays: compact layout
    bool use_small = (avail_h < 140 || w < 220);
    gfx.setFont(use_small ? &FreeSansBold18pt7b : &FreeSansBold24pt7b);

    int16_t tbx, tby; uint16_t tbw, tbh;
    gfx.getTextBounds("M", 0, 0, &tbx, &tby, &tbw, &tbh);
    int16_t ascent = -tby;
    line_gap = ascent + 5;

    int16_t warn_h = ascent + line_gap * 2;
    int16_t y_start = max((int16_t)2, (int16_t)((avail_h - warn_h) / 2));
    y1 = y_start + ascent;
  }

  gfx.setTextSize(1);
  const char *lines[] = {"EMPTY", "BATTERY", "RECHARGE!"};
  int16_t tbx, tby; uint16_t tbw, tbh;
  for (int i = 0; i < 3; i++)
  {
    gfx.getTextBounds(lines[i], 0, 0, &tbx, &tby, &tbw, &tbh);
    gfx.setCursor((w - tbw) / 2 - tbx, y1 + i * line_gap);
    gfx.print(lines[i]);
  }

  gfx.setTextWrap(true);

  // Battery info bar (reuse the standard render_info) above footer
  struct tm now_tm;
  localtime_r(&now, &now_tm);
  if (L.info.h > 0)
  {
    draw_hline(gfx, L.info.x, L.info.y, L.info.w, EPD_BLACK);
    render_info(gfx, L.info.x, L.info.y, L.info.w,
                battery_mv, true, &now_tm);
  }
  else
  {
    // Landscape: put info at bottom of available space, above footer
    int16_t info_y = L.foot.y - 22;
    render_info(gfx, 0, info_y, w, battery_mv, true, &now_tm);
  }

  render_footer(gfx, L.foot, now, stats);
}

#endif // DISABLE_DISPLAY
