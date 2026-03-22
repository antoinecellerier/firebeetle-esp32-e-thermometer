#pragma once

#include "Display.h"
#include "Adafruit_GFX.h"

struct Rect {
  int16_t x, y, w, h;
};

struct Layout {
  int16_t dw, dh;
  bool landscape;
  const GFXfont *big_font; // temperature font
  Rect temp;               // temperature zone
  Rect spark;              // 24h sparkline zone
  Rect month;              // 30-day bar chart zone
  Rect info;               // battery + time zone (portrait only; zero in landscape)
  Rect foot;               // debug footer zone
};

Layout compute_layout(int16_t w, int16_t h);

// Full dashboard render — the single entry point used by both the device
// and the simulator. Draws all zones onto the given Adafruit_GFX surface.
void render_dashboard(Adafruit_GFX &gfx, int16_t w, int16_t h,
                       float temp, uint32_t battery_mv, bool low_battery,
                       time_t now, const struct tm *nowtm,
                       const DisplayStats &stats);

// Individual zone renderers (called by render_dashboard, exposed for testing).
void render_temperature(Adafruit_GFX &gfx, const Layout &L,
                         float temp, const DisplayStats &stats);

void render_sparkline(Adafruit_GFX &gfx, const Rect &zone,
                       const DisplayStats &stats, time_t now);

void render_monthly_bars(Adafruit_GFX &gfx, const Rect &zone,
                          const DisplayStats &stats);

void render_info(Adafruit_GFX &gfx, int16_t x, int16_t y, int16_t w,
                  uint32_t battery_mv, bool low_battery,
                  const struct tm *nowtm);

void render_footer(Adafruit_GFX &gfx, const Rect &zone,
                    time_t now, const DisplayStats &stats);

// Full-screen empty battery warning (for permanent shutdown screen).
void render_empty_battery(Adafruit_GFX &gfx, int16_t w, int16_t h,
                           uint32_t battery_mv, time_t now,
                           const DisplayStats &stats);
