// Display simulator — renders using the same DisplayRenderer.cpp code
// as the device, outputs PNG files via Pillow conversion.
//
// Usage (from project root):
//   ./tools/sim/render_display                  # all sizes
//   ./tools/sim/render_display 920x680          # specific size
//   ./tools/sim/render_display 296x128 200x200  # multiple

#include "Adafruit_GFX.h"
#include "DisplayRenderer.h"
#include "Sensor.hpp"   // TEMP_NO_PREVIOUS
#include "HistoryStore.h"   // HistoryStoreFault, for the "! NOARCH" scenario
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

    // Scenario 7: clock drift badge, as seen on the ESP32-E 2026-07-25 —
    // -9559s accrued over 21d because the day-7 and day-14 resyncs failed.
    canvas.fillScreen(0xFFFF);
    // One long post-boot window, then three at the 1-day interval floor.
    static const int16_t drift_ppm[] = {-5268, -5102, -5390, -5241};
    static const uint16_t drift_win[] = {21 * 1440, 1440, 1440, 1440};
    DisplayStats drift_stats = stats;
    drift_stats.dummy_sensor = false;
    drift_stats.mock_data = false;
    drift_stats.power_efficient = true;
    drift_stats.clock_drift_ms = -9559000;
    drift_stats.drift_window_s = 21 * 86400;
    drift_stats.last_sync_time = now - 60;
    drift_stats.drift_ppm_hist = drift_ppm;
    drift_stats.drift_win_min = drift_win;
    drift_stats.drift_ppm_count = 4;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, drift_stats);
    save_and_convert(cfg.name, "_drift", canvas);

    // Scenario 7b: a pinned-cadence bench arm. Worst case for the status line,
    // which is why it is built on the drift scenario rather than a clean one:
    // on the 200x200 the lab badge, the drift badge, its ppm summary and the
    // repeated hash all compete for three lines. The lab badge must survive —
    // it is the only thing saying the refresh cadence is not field behaviour.
    canvas.fillScreen(0xFFFF);
    DisplayStats exp_stats = drift_stats;
    exp_stats.experiment_arm = 2;
    exp_stats.power_efficient = false;   // a resync override always forces this
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, exp_stats);
    save_and_convert(cfg.name, "_exp", canvas);

    // Scenario 7c: a PPK2-instrumented build. Same worst-case status line as
    // 7b and for the same reason, but this badge answers a different question:
    // not "is the cadence field behaviour" but "is this build's own
    // instrumentation on the trace". It is, and it costs an ungated ~40ms
    // selftest per boot plus a 3x50ms preamble on archive flushes, so any
    // charge figure harvested from such a build reads high. A photo of the
    // panel has to be enough to disqualify the number.
    canvas.fillScreen(0xFFFF);
    DisplayStats ppk2_stats = drift_stats;
    ppk2_stats.ppk2_instrumented = true;
    ppk2_stats.power_efficient = false;   // PPK2_DEBUG always forces this
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, ppk2_stats);
    save_and_convert(cfg.name, "_ppk2", canvas);

    // Scenario 8: resync failing right now — two attempts lost in a row, so
    // the clock has been free-running since it was last set 14d ago.
    canvas.fillScreen(0xFFFF);
    DisplayStats nosync_stats = drift_stats;
    nosync_stats.clock_drift_ms = 0;
    nosync_stats.drift_window_s = 0;
    nosync_stats.resync_fail_count = 2;
    nosync_stats.last_sync_time = now - 14 * 86400;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, nosync_stats);
    save_and_convert(cfg.name, "_nosync", canvas);

    // Scenario 9: the archive stopped recording — what a device looks like
    // after being flashed with a firmware that speaks a different on-flash
    // format. Everything else works, so this badge is the only sign that
    // history is being lost; render it in an otherwise clean field build to
    // confirm it survives on the narrowest panel.
    canvas.fillScreen(0xFFFF);
    DisplayStats noarch_stats = stats;
    noarch_stats.dummy_sensor = false;
    noarch_stats.mock_data = false;
    noarch_stats.power_efficient = true;
    noarch_stats.archive_fault = HS_FAULT_FOREIGN_FORMAT;
    noarch_stats.archive_flash_format = 3;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 3842, false,
                      now, &nowtm, noarch_stats);
    save_and_convert(cfg.name, "_noarch", canvas);

    // Scenario 10: the sensor read was rejected as implausible — a loose ground
    // or an unpowered device. The point of the variant is that NO number is
    // drawn: a plausible-looking value for a rejected read is the failure the
    // gate exists to prevent, so confirm the gap plus "! SENSOR" reads as a
    // fault at every panel size rather than as a rendering glitch.
    canvas.fillScreen(0xFFFF);
    DisplayStats nosensor_stats = stats;
    nosensor_stats.dummy_sensor = false;
    nosensor_stats.mock_data = false;
    nosensor_stats.power_efficient = true;
    nosensor_stats.sensor_ok = false;
    render_dashboard(canvas, cfg.w, cfg.h,
                      TEMP_NO_PREVIOUS, 3842, false,
                      now, &nowtm, nosensor_stats);
    save_and_convert(cfg.name, "_nosensor", canvas);

    // Scenario 11: parked awake for a USB host, so the port stays enumerated
    // for a reflash. An otherwise clean field build, USB-powered: the badge is
    // the only thing saying the board is burning milliamps and that its own CPU
    // is warming the sensor, so check it survives on the narrowest panel — and
    // that the plug-in wake reads as "w:USB" in the footer.
    canvas.fillScreen(0xFFFF);
    DisplayStats usb_stats = stats;
    usb_stats.dummy_sensor = false;
    usb_stats.mock_data = false;
    usb_stats.power_efficient = true;
    usb_stats.usb_window = true;
    usb_stats.wake_cause = 3;
    render_dashboard(canvas, cfg.w, cfg.h,
                      22.3f, 4180, false,
                      now, &nowtm, usb_stats);
    save_and_convert(cfg.name, "_usb", canvas);
  }

  return 0;
}
