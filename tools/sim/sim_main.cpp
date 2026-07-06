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

// Save GFXcanvas16 buffer as PPM (P6 binary, RGB). A 16-bit color canvas lets
// the tri-color panels' red (EPD_RED == 0xF800) show up distinctly — matching
// the real hardware instead of collapsing to black like the old 1-bit canvas.
static void save_ppm(const char *path, GFXcanvas16 &canvas)
{
  int16_t w = canvas.width();
  int16_t h = canvas.height();
  uint16_t *buf = canvas.getBuffer();

  FILE *f = fopen(path, "wb");
  if (!f) { fprintf(stderr, "Cannot write %s\n", path); return; }
  fprintf(f, "P6\n%d %d\n255\n", w, h);

  for (int i = 0; i < w * h; i++)
  {
    uint16_t c = buf[i];
    uint8_t rgb[3];
    // The renderer only emits black/white/red; map those crisply and fall back
    // to a generic RGB565->RGB888 expansion for anything unexpected.
    if (c == 0x0000)      { rgb[0] = rgb[1] = rgb[2] = 0; }
    else if (c == 0xFFFF) { rgb[0] = rgb[1] = rgb[2] = 255; }
    else if (c == 0xF800) { rgb[0] = 255; rgb[1] = 0; rgb[2] = 0; }
    else {
      rgb[0] = ((c >> 11) & 0x1F) << 3;
      rgb[1] = ((c >> 5) & 0x3F) << 2;
      rgb[2] = (c & 0x1F) << 3;
    }
    fwrite(rgb, 1, 3, f);
  }
  fclose(f);
}

static void save_and_convert(const char *size_name, const char *suffix,
                              GFXcanvas16 &canvas)
{
  char ppm[256], png[256], cmd[1024];
  snprintf(ppm, sizeof(ppm), "tools/mock_%s%s.ppm", size_name, suffix);
  snprintf(png, sizeof(png), "tools/mock_%s%s.png", size_name, suffix);

  save_ppm(ppm, canvas);

  // ImageMagick reads PPM natively — simpler and more portable than depending
  // on a Python Pillow install (which may be shadowed by a non-system python3).
  snprintf(cmd, sizeof(cmd), "convert '%s' '%s' && rm -f '%s'", ppm, png, ppm);
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

  // Noisy variant: exercises smart eviction (TempHistory.h) with more
  // delta-triggered readings than the buffer holds
  TempReading noisy_history[TEMP_HISTORY_SIZE];
  DisplayStats noisy_stats = stats;
  mock_fill_sparkline_noisy(now, noisy_history, &noisy_stats.history_count);
  noisy_stats.temp_history = noisy_history;

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

    GFXcanvas16 canvas(cfg.w, cfg.h);
    canvas.fillScreen(0xFFFF); // white

    // Scenario 1: Normal dashboard
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, stats);
    save_and_convert(cfg.name, "", canvas);

    // Scenario 1b: Hot temperature (>=30C renders red on tri-color panels)
    canvas.fillScreen(0xFFFF);
    render_dashboard(canvas, cfg.w, cfg.h,
                      31.5f, 3842, false,
                      now, &nowtm, stats);
    save_and_convert(cfg.name, "_hot", canvas);

    // Scenario 1c: Noisy 24h history (smart eviction keeps full-width span)
    canvas.fillScreen(0xFFFF);
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, noisy_stats);
    save_and_convert(cfg.name, "_noisy", canvas);

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

    // Scenario 6: Crash forensics indicator + uN footer field
    canvas.fillScreen(0xFFFF);
    DisplayStats crash_stats = stats;
    crash_stats.ulp_reinit_count = 3;
    crash_stats.crash_count = 2;
    snprintf(crash_stats.crash_reason, sizeof(crash_stats.crash_reason), "PANIC");
    crash_stats.crash_stage = STAGE_RENDER;
    crash_stats.crash_boot_count = 273;
    crash_stats.crash_time = (uint32_t)(now - 3 * 3600);
    crash_stats.crash_pc = 0x42008a3c;
    snprintf(crash_stats.crash_task, sizeof(crash_stats.crash_task), "main");
    snprintf(crash_stats.crash_elf_sha, sizeof(crash_stats.crash_elf_sha), "ab12cd34");
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, crash_stats);
    save_and_convert(cfg.name, "_crash", canvas);
  }

  return 0;
}
