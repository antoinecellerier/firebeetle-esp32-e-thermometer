// Display simulator — renders using the same DisplayRenderer.cpp code
// as the device, outputs PNG files via Pillow conversion.
//
// Usage (from project root):
//   ./tools/sim/render_display                  # all sizes
//   ./tools/sim/render_display 920x680          # specific size
//   ./tools/sim/render_display 296x128 200x200  # multiple

#include "Adafruit_GFX.h"
#include "DisplayRenderer.h"
#include "MockData.h"
#include <cstdio>
#include <cstring>
#include <ctime>

// Display configurations matching the supported hardware
static const struct { const char *name; int16_t w, h; } displays[] = {
  {"296x128", 296, 128},   // 2.9" landscape (USE_290_I6FD)
  {"212x104", 212, 104},   // 2.13" landscape (USE_213_M21)
  {"200x200", 200, 200},   // 1.54" square (USE_154_*)
  {"920x680", 920, 680},   // 5.76" (USE_576_T81, rotation 0)
};

// Save GFXcanvas1 buffer as PBM (P4 binary).
// GFXcanvas1 with fillScreen(0xFFFF): bit 1 = white, bit 0 = black (drawn).
// PBM P4: bit 1 = black, bit 0 = white. So we invert.
static void save_pbm(const char *path, GFXcanvas1 &canvas)
{
  int16_t w = canvas.width();
  int16_t h = canvas.height();
  uint8_t *buf = canvas.getBuffer();
  int bytes_per_row = (w + 7) / 8;

  FILE *f = fopen(path, "wb");
  if (!f) { fprintf(stderr, "Cannot write %s\n", path); return; }
  fprintf(f, "P4\n%d %d\n", w, h);

  for (int y = 0; y < h; y++)
    for (int x = 0; x < bytes_per_row; x++)
    {
      uint8_t b = ~buf[y * bytes_per_row + x]; // invert for PBM
      fwrite(&b, 1, 1, f);
    }
  fclose(f);
}

static void save_and_convert(const char *size_name, const char *suffix,
                              GFXcanvas1 &canvas)
{
  char pbm[256], png[256], cmd[512];
  snprintf(pbm, sizeof(pbm), "tools/mock_%s%s.pbm", size_name, suffix);
  snprintf(png, sizeof(png), "tools/mock_%s%s.png", size_name, suffix);

  save_pbm(pbm, canvas);

  snprintf(cmd, sizeof(cmd),
    "python3 -c \"from PIL import Image; Image.open('%s').save('%s')\" && rm -f '%s'",
    pbm, png, pbm);
  system(cmd);

  printf("  %s\n", png);
}

int main(int argc, char **argv)
{
  time_t now = time(NULL);
  bool filter = (argc > 1);

  // Shared mock data buffers
  TempReading mock_history[TEMP_HISTORY_SIZE];
  static HourlyEntry mock_hourly[HOURLY_HISTORY_SIZE]; // static: 4320 bytes, avoid stack overflow
  DisplayStats stats = mock_make_stats(now, mock_history, mock_hourly);

  struct tm nowtm;
  localtime_r(&now, &nowtm);

  int num_displays = sizeof(displays) / sizeof(displays[0]);
  for (int d = 0; d < num_displays; d++)
  {
    auto &cfg = displays[d];

    if (filter)
    {
      bool found = false;
      for (int i = 1; i < argc; i++)
        if (strcmp(argv[i], cfg.name) == 0) { found = true; break; }
      if (!found) continue;
    }

    GFXcanvas1 canvas(cfg.w, cfg.h);
    canvas.fillScreen(0xFFFF); // white

    // Scenario 1: Normal dashboard
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, stats);
    save_and_convert(cfg.name, "", canvas);

    // Scenario 2: Low battery warning (red icon)
    canvas.fillScreen(0xFFFF);
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3150, true,
                      now, &nowtm, stats);
    save_and_convert(cfg.name, "_lowbat", canvas);

    // Scenario 3: WiFi failure + sensor error
    canvas.fillScreen(0xFFFF);
    DisplayStats err_stats = stats;
    err_stats.wifi_ok = false;
    err_stats.ntp_synced = false;
    err_stats.sensor_ok = false;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, err_stats);
    save_and_convert(cfg.name, "_nowifi", canvas);

    // Scenario 4: WiFi connected but NTP failed
    canvas.fillScreen(0xFFFF);
    err_stats.wifi_ok = true;
    err_stats.ntp_synced = false;
    err_stats.sensor_ok = true;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, err_stats);
    save_and_convert(cfg.name, "_nontp", canvas);

    // Scenario 5: Empty battery shutdown screen
    canvas.fillScreen(0xFFFF);
    render_empty_battery(canvas, cfg.w, cfg.h,
                          2950, now, stats);
    save_and_convert(cfg.name, "_empty", canvas);
  }

  return 0;
}
