#include "DisplayRenderer.h"

#include <math.h>
#include "Adafruit_GFX.h"
#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSansBold18pt7b.h>
#include "FreeSansBold80pt7b.h"
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/Org_01.h>
#include <Fonts/TomThumb.h>

#ifndef ARDUINO
#include <algorithm>
using std::min;
using std::max;
#define constrain(amt,low,high) ((amt)<(low)?(low):((amt)>(high)?(high):(amt)))
#endif

#ifndef EPD_BLACK
#define EPD_BLACK 0x0000
#endif
#ifndef EPD_RED
#define EPD_RED EPD_BLACK
#endif

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

// --- Layout computation ---

Layout compute_layout(int16_t w, int16_t h)
{
  Layout L = {};
  L.dw = w;
  L.dh = h;
  // Threshold 1.5: 296x128 (2.31) and 212x104 (2.04) are landscape,
  // 920x680 (1.35) and 200x200 (1.0) use stacked portrait.
  L.landscape = (w > h * 15 / 10);
  // Font selection by display size:
  //   96pt (native ~140px digits) — large displays (920x680)
  //   24pt (native ~35px digits)  — medium displays (296x128, 200x200)
  //   18pt (native ~26px digits)  — small displays (212x104)
  // All rendered at setTextSize(1) — no scaling, no aliasing.
  if (min(w, h) >= 400)
    L.big_font = &FreeSansBold80pt7b;
  else
    L.big_font = &FreeSansBold24pt7b;

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

    if (content_h < 100)
      L.big_font = &FreeSansBold18pt7b;
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
  bool large = (L.dh >= 400 || L.dw >= 600);

  // --- Main temperature number ---
  char temp_str[16];
  snprintf(temp_str, sizeof(temp_str), "%.1f", temp);

  // Measure digits and "C" suffix (same font for consistent sizing)
  gfx.setFont(L.big_font);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  int16_t tbx, tby;
  uint16_t tbw, tbh;
  gfx.getTextBounds(temp_str, 0, 0, &tbx, &tby, &tbw, &tbh);

  int16_t cx, cy; uint16_t cw, ch;
  gfx.getTextBounds("C", 0, 0, &cx, &cy, &cw, &ch);
  int16_t suffix_w = 12 + cw; // gap + "C"

  // Center temperature + suffix horizontally and vertically in zone
  int16_t text_x = z.x + (z.w - (int16_t)(tbw + suffix_w)) / 2 - tbx;
  int16_t baseline_y = z.y + (z.h + tbh) / 2;

  gfx.setCursor(text_x, baseline_y);
  gfx.print(temp_str);

  int16_t after_x = gfx.getCursorX();
  gfx.setCursor(after_x + 12, baseline_y);
  gfx.print("C");
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

  // Find temperature range within the 24h window
  float t_min = 999.0f, t_max = -999.0f;
  int valid_count = 0;
  for (int i = 0; i < stats.history_count; i++)
  {
    int idx = (stats.history_start + i) % TEMP_HISTORY_SIZE;
    const TempReading &r = stats.temp_history[idx];
    if (r.timestamp >= window_start)
    {
      float t = r.temp_x10 / 10.0f;
      if (t < t_min) t_min = t;
      if (t > t_max) t_max = t;
      valid_count++;
    }
  }
  if (valid_count == 0) return;

  // Y range with proportional padding, minimum 1°C span
  float pad_t = max(0.3f, (t_max - t_min) * 0.15f);
  t_min -= pad_t;
  t_max += pad_t;
  if (t_max - t_min < 1.0f)
  {
    float mid = (t_max + t_min) / 2;
    t_min = mid - 0.5f;
    t_max = mid + 0.5f;
  }
  float t_range = t_max - t_min;
  float time_range = (float)(now - window_start);

  // Y-axis labels — FreeSans12pt on large displays for clean strokes
  const GFXfont *label_font = large ? &FreeSans12pt7b : &TomThumb;
  gfx.setFont(label_font);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  // Dotted gridlines + Y-axis labels — adaptive step based on chart height
  int grid_spacing = large ? 8 : 5;
  int deg_min = (int)roundf(t_min);
  int deg_max = (int)roundf(t_max);
  int deg_range = deg_max - deg_min;
  int grid_step;
  if (chart_h >= 100) grid_step = (deg_range > 8) ? 2 : 1;
  else if (chart_h >= 40) grid_step = (deg_range > 4) ? 2 : 1;
  else grid_step = max(2, deg_range / 2);
  int label_step = grid_step;

  for (int deg = deg_min; deg <= deg_max; deg += grid_step)
  {
    int16_t gy = chart_y + chart_h - 1 - (int16_t)(((float)deg - t_min) / t_range * (chart_h - 1));
    if (gy <= chart_y || gy >= chart_y + chart_h - 1) continue;
    draw_dotted_hline(gfx, chart_x, gy, chart_w, grid_spacing, EPD_BLACK);

    if ((deg % label_step) == 0)
    {
      char label[8];
      int16_t lx, ly; uint16_t lw, lh;
      snprintf(label, sizeof(label), "%d", deg);
      gfx.getTextBounds(label, 0, 0, &lx, &ly, &lw, &lh);
      int16_t label_gap = large ? 12 : 3;
      gfx.setCursor(zone.x + label_w - lw - label_gap - lx, gy + lh / 2);
      gfx.print(label);
    }
  }

  // Collect data points within the 24h window
  int16_t px_arr[TEMP_HISTORY_SIZE];
  int16_t py_arr[TEMP_HISTORY_SIZE];
  time_t  pt_arr[TEMP_HISTORY_SIZE];
  int num_pts = 0;

  for (int i = 0; i < stats.history_count; i++)
  {
    int idx = (stats.history_start + i) % TEMP_HISTORY_SIZE;
    const TempReading &r = stats.temp_history[idx];
    if (r.timestamp < window_start) continue;

    float t = r.temp_x10 / 10.0f;
    int16_t px = chart_x + (int16_t)((float)(r.timestamp - window_start) / time_range * chart_w);
    int16_t py = chart_y + chart_h - 1 - (int16_t)((t - t_min) / t_range * (chart_h - 1));
    px = constrain(px, chart_x, (int16_t)(chart_x + chart_w - 1));
    py = constrain(py, chart_y, (int16_t)(chart_y + chart_h - 1));

    px_arr[num_pts] = px;
    py_arr[num_pts] = py;
    pt_arr[num_pts] = r.timestamp;
    num_pts++;
  }

  // Draw Catmull-Rom spline through the data points.
  // This produces a smooth curve that passes through each point
  // without the angular joints of piecewise linear interpolation.
  int16_t steps_per_seg = large ? 16 : (medium ? 8 : 4);

  for (int i = 0; i < num_pts - 1; i++)
  {
    // Break the line at gaps > 4 hours (stable temperature, no readings)
    if (pt_arr[i + 1] - pt_arr[i] > 4 * 3600) continue;

    // Control points: clamp at boundaries by duplicating endpoints
    float x0 = px_arr[max(0, i - 1)], y0 = py_arr[max(0, i - 1)];
    float x1 = px_arr[i],             y1 = py_arr[i];
    float x2 = px_arr[i + 1],         y2 = py_arr[i + 1];
    float x3 = px_arr[min(num_pts-1, i+2)], y3 = py_arr[min(num_pts-1, i+2)];

    int16_t prev_sx = (int16_t)x1, prev_sy = (int16_t)y1;

    for (int s = 1; s <= steps_per_seg; s++)
    {
      float t = (float)s / steps_per_seg;
      float t2 = t * t, t3 = t2 * t;

      float sx = 0.5f * (2*x1 + (-x0+x2)*t + (2*x0-5*x1+4*x2-x3)*t2 + (-x0+3*x1-3*x2+x3)*t3);
      float sy = 0.5f * (2*y1 + (-y0+y2)*t + (2*y0-5*y1+4*y2-y3)*t2 + (-y0+3*y1-3*y2+y3)*t3);

      int16_t cur_sx = constrain((int16_t)sx, chart_x, (int16_t)(chart_x + chart_w - 1));
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

// Draw a Catmull-Rom spline through an array of Y values evenly spaced on X.
// If dotted > 0, draw every dotted-th pixel instead of a solid line.
static void draw_spline(Adafruit_GFX &gfx,
                         const int16_t *py, int n,
                         int16_t x0, int16_t chart_w,
                         int16_t y_clamp_min, int16_t y_clamp_max,
                         int dotted, bool thick, uint16_t color)
{
  if (n < 2) return;
  int steps = max(2, chart_w / max(1, n - 1));

  int pixel_count = 0;
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
      float t2 = t * t, t3 = t2 * t;

      float frac = (i + t) / (n - 1);
      int16_t cur_sx = x0 + (int16_t)(frac * chart_w);

      float sy = 0.5f * (2*p1 + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t2 + (-p0+3*p1-3*p2+p3)*t3);
      int16_t cur_sy = constrain((int16_t)sy, y_clamp_min, y_clamp_max);

      pixel_count++;
      if (dotted > 0 && (pixel_count % dotted) >= dotted / 2)
      {
        prev_sx = cur_sx;
        prev_sy = cur_sy;
        continue; // skip this segment for dotted effect
      }

      gfx.drawLine(prev_sx, prev_sy, cur_sx, cur_sy, color);
      if (thick)
        gfx.drawLine(prev_sx, prev_sy + 1, cur_sx, cur_sy + 1, color);

      prev_sx = cur_sx;
      prev_sy = cur_sy;
    }
  }
}

void render_monthly_bars(Adafruit_GFX &gfx, const Rect &zone,
                          const DisplayStats &stats)
{
  if (zone.h < 20) return;

  bool has_today = (stats.today_day != 0 &&
                    stats.today_min_x10 <= stats.today_max_x10 &&
                    stats.today_min_x10 < 9990);
  int total_pts = stats.daily_count + (has_today ? 1 : 0);
  if (total_pts == 0) return;

  draw_hline(gfx, zone.x, zone.y, zone.w, EPD_BLACK);

  // Collect min/max/avg data points
  float mins[DAILY_HISTORY_SIZE + 1];
  float maxs[DAILY_HISTORY_SIZE + 1];
  float avgs[DAILY_HISTORY_SIZE + 1];
  int16_t overall_min_x10 = 9990, overall_max_x10 = -9990;

  for (int i = 0; i < stats.daily_count; i++)
  {
    int idx = (stats.daily_start + i) % DAILY_HISTORY_SIZE;
    mins[i] = stats.daily_history[idx].min_x10 / 10.0f;
    maxs[i] = stats.daily_history[idx].max_x10 / 10.0f;
    avgs[i] = (mins[i] + maxs[i]) / 2.0f;
    if (stats.daily_history[idx].min_x10 < overall_min_x10)
      overall_min_x10 = stats.daily_history[idx].min_x10;
    if (stats.daily_history[idx].max_x10 > overall_max_x10)
      overall_max_x10 = stats.daily_history[idx].max_x10;
  }
  if (has_today)
  {
    int i = stats.daily_count;
    mins[i] = stats.today_min_x10 / 10.0f;
    maxs[i] = stats.today_max_x10 / 10.0f;
    avgs[i] = (mins[i] + maxs[i]) / 2.0f;
    if (stats.today_min_x10 < overall_min_x10) overall_min_x10 = stats.today_min_x10;
    if (stats.today_max_x10 > overall_max_x10) overall_max_x10 = stats.today_max_x10;
  }

  // Chart area
  bool large = (zone.h >= 80);
  int16_t label_w = large ? 40 : 18;
  int16_t pad_top = large ? 8 : 3;
  int16_t pad_bot = large ? 22 : (zone.h > 30 ? 10 : 2); // room for X-axis labels
  int16_t pad_right = large ? 6 : 3;
  int16_t chart_x = zone.x + label_w;
  int16_t chart_y = zone.y + pad_top;
  int16_t chart_w = zone.w - label_w - pad_right;
  int16_t chart_h = zone.h - pad_top - pad_bot;

  if (chart_w < 10 || chart_h < 10) return;

  // Y range
  float y_min = (overall_min_x10 - 5) / 10.0f;
  float y_max = (overall_max_x10 + 5) / 10.0f;
  if (y_max - y_min < 1.0f)
  {
    float mid = (y_max + y_min) / 2;
    y_min = mid - 0.5f;
    y_max = mid + 0.5f;
  }
  float y_range = y_max - y_min;

  // Dotted gridlines + Y-axis labels at whole degrees
  // Y-axis labels — FreeSans12pt on large displays for clean strokes
  const GFXfont *label_font = large ? &FreeSans12pt7b : &TomThumb;
  gfx.setFont(label_font);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  int grid_spacing = large ? 8 : 5;
  int deg_min = (int)roundf(y_min);
  int deg_max = (int)roundf(y_max);
  int deg_range = deg_max - deg_min;
  // Adapt grid step to chart height: aim for ~3-5 visible gridlines
  int grid_step;
  if (chart_h >= 100) grid_step = (deg_range > 8) ? 2 : 1;
  else if (chart_h >= 40) grid_step = (deg_range > 4) ? 2 : 1;
  else grid_step = max(2, deg_range / 2);
  int label_step = grid_step;
  // Bottom margin: skip Y labels near the bottom edge to avoid
  // overlapping with X-axis date labels
  int16_t label_bottom_margin = (chart_h > 50) ? 15 : 8;

  for (int deg = deg_min; deg <= deg_max; deg += grid_step)
  {
    int16_t gy = chart_y + chart_h - 1 - (int16_t)(((float)deg - y_min) / y_range * (chart_h - 1));
    if (gy <= chart_y || gy >= chart_y + chart_h - 1) continue;
    draw_dotted_hline(gfx, chart_x, gy, chart_w, grid_spacing, EPD_BLACK);

    // Draw label only if not in the X-axis label zone at the bottom
    bool in_label_zone = (gy > chart_y + chart_h - label_bottom_margin);
    if (!in_label_zone && (deg % label_step) == 0)
    {
      char label[8];
      int16_t lx, ly; uint16_t lw, lh;
      snprintf(label, sizeof(label), "%d", deg);
      gfx.getTextBounds(label, 0, 0, &lx, &ly, &lw, &lh);
      int16_t label_gap = large ? 12 : 3;
      gfx.setCursor(zone.x + label_w - lw - label_gap - lx, gy + lh / 2);
      gfx.print(label);
    }
  }

  // Convert temperature values to pixel Y coordinates
  int16_t py_min[DAILY_HISTORY_SIZE + 1];
  int16_t py_max[DAILY_HISTORY_SIZE + 1];
  int16_t py_avg[DAILY_HISTORY_SIZE + 1];

  for (int i = 0; i < total_pts; i++)
  {
    py_min[i] = chart_y + chart_h - 1 - (int16_t)((mins[i] - y_min) / y_range * (chart_h - 1));
    py_max[i] = chart_y + chart_h - 1 - (int16_t)((maxs[i] - y_min) / y_range * (chart_h - 1));
    py_avg[i] = chart_y + chart_h - 1 - (int16_t)((avgs[i] - y_min) / y_range * (chart_h - 1));
  }

  // On large zones: three curves (max, avg dotted, min).
  // On small zones (< 60px chart height): just the avg curve for clarity.
  bool thick = large;
  if (chart_h >= 60)
  {
    draw_spline(gfx, py_max, total_pts, chart_x, chart_w,
                 chart_y, (int16_t)(chart_y + chart_h - 1), 0, thick, EPD_BLACK);
    draw_spline(gfx, py_avg, total_pts, chart_x, chart_w,
                 chart_y, (int16_t)(chart_y + chart_h - 1), 6, false, EPD_BLACK);
    draw_spline(gfx, py_min, total_pts, chart_x, chart_w,
                 chart_y, (int16_t)(chart_y + chart_h - 1), 0, thick, EPD_BLACK);
  }
  else
  {
    draw_spline(gfx, py_avg, total_pts, chart_x, chart_w,
                 chart_y, (int16_t)(chart_y + chart_h - 1), 0, false, EPD_BLACK);
  }

  // X-axis day labels: every 7th day
  // X-axis date labels — skip on small charts where they'd be illegible
  if (chart_h > 20 && total_pts > 7)
  {
    gfx.setFont(large ? &FreeSans9pt7b : &TomThumb);
    gfx.setTextSize(1);
    gfx.setTextColor(EPD_BLACK);

    static const char *month_abbr[] = {
      "Jan","Feb","Mar","Apr","May","Jun",
      "Jul","Aug","Sep","Oct","Nov","Dec"
    };

    for (int i = 0; i < total_pts; i += 7)
    {
      int16_t mark_x = chart_x + (int16_t)((float)i / (total_pts - 1) * chart_w);

      gfx.drawLine(mark_x, chart_y + chart_h - 2, mark_x, chart_y + chart_h + 1, EPD_BLACK);

      // "Mar 24" format label
      int idx = (i < stats.daily_count)
        ? (stats.daily_start + i) % DAILY_HISTORY_SIZE
        : -1;
      int day_num = (idx >= 0) ? stats.daily_history[idx].day : stats.today_day;
      int month = (idx >= 0) ? stats.daily_history[idx].month : 0;
      // month is 1-12 in DailySummary; for today, derive from the last entry
      if (month == 0 && stats.daily_count > 0)
      {
        int last = (stats.daily_start + stats.daily_count - 1) % DAILY_HISTORY_SIZE;
        month = stats.daily_history[last].month;
      }
      const char *mon = (month >= 1 && month <= 12) ? month_abbr[month - 1] : "?";
      char dlabel[8];
      snprintf(dlabel, sizeof(dlabel), "%s %d", mon, day_num);
      int16_t dlx, dly; uint16_t dlw, dlh;
      gfx.getTextBounds(dlabel, 0, 0, &dlx, &dly, &dlw, &dlh);
      gfx.setCursor(mark_x - dlw / 2 - dlx, chart_y + chart_h + 3 + dlh);
      gfx.print(dlabel);
    }
  }
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

  // Time, right-aligned, same baseline
  gfx.setTextColor(EPD_BLACK);
  char time_str[8];
  strftime(time_str, sizeof(time_str), "%H:%M", nowtm);

  gfx.getTextBounds(time_str, 0, 0, &tbx, &tby, &tbw, &tbh);
  gfx.setCursor(x + w - tbw - 6 - tbx, text_baseline);
  gfx.print(time_str);
}

void render_footer(Adafruit_GFX &gfx, const Rect &zone,
                    time_t now, const DisplayStats &stats)
{
  draw_hline(gfx, zone.x, zone.y, zone.w, EPD_BLACK);

  bool large = (zone.w >= 600);
  gfx.setFont(large ? &FreeSans12pt7b : &Org_01);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  time_t uptime = now - stats.first_boot_time;
  int up_days = (int)(uptime / 86400);
  int up_hours = (int)((uptime % 86400) / 3600);

  const char *wake_str = (stats.wake_cause == 1) ? "ULP" :
                          (stats.wake_cause == 2) ? "TMR" : "?";

  // Format first boot date if NTP-synced (epoch > 1 day means real time)
  static const char *mon_names[] = {
    "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"
  };
  char boot_date[12] = "";
  if (stats.ntp_synced)
  {
    struct tm bt;
    localtime_r(&stats.first_boot_time, &bt);
    snprintf(boot_date, sizeof(boot_date), "%s%d'%02d",
             mon_names[bt.tm_mon], bt.tm_mday, bt.tm_year % 100);
  }

  // Center text vertically in the footer zone
  int16_t fx, fy; uint16_t fw, fh;
  gfx.getTextBounds("M", 0, 0, &fx, &fy, &fw, &fh);
  int16_t footer_text_y = zone.y + zone.h / 2 + (-fy) / 2;

  // Compact uptime: skip "0h", show hours only when non-zero
  char uptime_str[12];
  if (up_hours > 0)
    snprintf(uptime_str, sizeof(uptime_str), "%dd%dh", up_days, up_hours);
  else
    snprintf(uptime_str, sizeof(uptime_str), "%dd", up_days);

  gfx.setCursor(zone.x + (large ? 4 : 2), footer_text_y);

  gfx.printf("#%d r%d %s w:%s mx%.1fV",
              stats.boot_count, stats.display_refresh_count,
              uptime_str, wake_str,
              stats.max_battery_mv / 1000.0f);
  if (stats.bad_pin27_count > 0)
    gfx.printf(" b27:%d", (int)stats.bad_pin27_count);
  if (boot_date[0])
    gfx.printf(" %s", boot_date);
}

// --- Status indicators (top-left corner of temp zone) ---

static void render_status_indicators(Adafruit_GFX &gfx, const Layout &L,
                                       const DisplayStats &stats)
{
  // Only render when there's an issue — no clutter when things are normal
  if (stats.wifi_ok && stats.ntp_synced && stats.sensor_ok)
    return;

  bool large = (L.dh >= 400 || L.dw >= 600);
  gfx.setFont(large ? &FreeSans12pt7b : &Org_01);
  gfx.setTextSize(1);
  gfx.setTextColor(EPD_BLACK);

  int16_t x = L.temp.x + 4;
  int16_t y = L.temp.y + (large ? 16 : 8);
  int16_t line_h = large ? 18 : 9;

  if (!stats.wifi_ok)
  {
    gfx.setCursor(x, y);
    gfx.print("! NO WIFI");
    y += line_h;
  }
  else if (!stats.ntp_synced)
  {
    // WiFi connected but NTP failed — different root cause
    gfx.setCursor(x, y);
    gfx.print("! NO NTP");
    y += line_h;
  }

  if (!stats.sensor_ok)
  {
    gfx.setCursor(x, y);
    gfx.print("! SENSOR");
  }
}

// --- Full dashboard render ---

void render_dashboard(Adafruit_GFX &gfx, int16_t w, int16_t h,
                       float temp, uint32_t battery_mv, bool low_battery,
                       time_t now, const struct tm *nowtm,
                       const DisplayStats &stats)
{
  Layout L = compute_layout(w, h);

  render_temperature(gfx, L, temp, stats);
  render_status_indicators(gfx, L, stats);
  render_sparkline(gfx, L.spark, stats, now);
  render_monthly_bars(gfx, L.month, stats);

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

  if (large)
  {
    // Big display: use 24pt at 2x for maximum impact
    gfx.setFont(&FreeSansBold24pt7b);
    gfx.setTextSize(2);
    int16_t line_gap = 70;
    int16_t y1 = avail_h / 5;

    const char *lines[] = {"EMPTY", "BATTERY", "RECHARGE!"};
    int16_t tbx, tby; uint16_t tbw, tbh;
    for (int i = 0; i < 3; i++)
    {
      gfx.getTextBounds(lines[i], 0, 0, &tbx, &tby, &tbw, &tbh);
      gfx.setCursor((w - tbw) / 2 - tbx, y1 + i * line_gap);
      gfx.print(lines[i]);
    }

    gfx.setFont(&FreeSans9pt7b);
    gfx.setTextSize(1);
    char bat_str[24];
    snprintf(bat_str, sizeof(bat_str), "bat %dmV", (int)battery_mv);
    gfx.getTextBounds(bat_str, 0, 0, &tbx, &tby, &tbw, &tbh);
    gfx.setCursor((w - tbw) / 2 - tbx, y1 + 3 * line_gap);
    gfx.print(bat_str);
  }
  else
  {
    // Small displays: compact layout, single message + voltage
    bool use_small = (avail_h < 140 || w < 220);
    gfx.setFont(use_small ? &FreeSansBold18pt7b : &FreeSansBold24pt7b);
    gfx.setTextSize(1);

    int16_t tbx, tby; uint16_t tbw, tbh;
    gfx.getTextBounds("M", 0, 0, &tbx, &tby, &tbw, &tbh);
    int16_t ascent = -tby; // how far text extends above baseline
    int16_t line_h = ascent + 5;

    // Stack from top: center the 3-line warning block vertically
    int16_t warn_h = ascent + line_h * 2;
    int16_t total_h = warn_h;
    int16_t y_start = max((int16_t)2, (int16_t)((avail_h - total_h) / 2));
    int16_t y1 = y_start + ascent; // first baseline

    const char *lines[] = {"EMPTY", "BATTERY", "RECHARGE!"};
    for (int i = 0; i < 3; i++)
    {
      gfx.getTextBounds(lines[i], 0, 0, &tbx, &tby, &tbw, &tbh);
      gfx.setCursor((w - tbw) / 2 - tbx, y1 + i * line_h);
      gfx.print(lines[i]);
    }
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
