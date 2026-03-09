#include "Display.h"
#include "common.h"

// 3.3V GND SCK MOSI DC CS BUSY RESET pins are all on the same side of the Firebeetle board to simplify wiring
#define EPD_DC     2 // D9
#define EPD_CS    14 // D6 (was D5/GPIO0, moved to free GPIO0 for RTC I2C SDA)
#define EPD_BUSY  26 // D3
#define EPD_RESET 25 // D2

#ifndef DISABLE_DISPLAY

#include "GxEPD2_BW.h"
#if defined(USE_154_Z90)
  #include "GxEPD2_3C.h"
  GxEPD2_3C<GxEPD2_154_Z90c, GxEPD2_154_Z90c::HEIGHT> display(GxEPD2_154_Z90c(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_RED
#elif defined(USE_154_M09)
  GxEPD2_BW<GxEPD2_154_M09, GxEPD2_154_M09::HEIGHT> display(GxEPD2_154_M09(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_BLACK
#elif defined(USE_213_M21)
  GxEPD2_BW<GxEPD2_213_M21, GxEPD2_213_M21::HEIGHT> display(GxEPD2_213_M21(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_BLACK
#else
  #error Unknown screen type
#endif
#define EPD_BLACK GxEPD_BLACK
#define EPD_WHITE GxEPD_WHITE

static const time_t one_day = 86400;

static void init_for_render(int boot_count)
{
  LOGI("Initializing display");
  display.init(0 /* disable serial debug output */,
               boot_count == 1 /* allow partial updates directly after power-up for non first runs */);
  display.cp437(true);
  #ifdef USE_213_M21
  display.setRotation(1);
  #else
  display.setRotation(2);
  #endif
  display.fillScreen(GxEPD_WHITE);
}

static void render_stats(time_t now, const struct tm *nowtm, const DisplayStats &stats)
{
  char formatted_time[256];

  display.setTextSize(1);
  display.setTextColor(EPD_RED);
  display.printf("seq %d (was %d). refresh %d\n", stats.boot_count, stats.previous_boot_count, stats.display_refresh_count);
  // TODO: Maybe don't format this every time we render?
  struct tm tm;
  localtime_r(&stats.first_boot_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("first boot %s\n", formatted_time);
  strftime(formatted_time, 256, "%F %T", nowtm);
  display.printf("last refresh %s\n", formatted_time);
  localtime_r(&stats.next_clear_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("next clear %s\n", formatted_time);

  time_t uptime = now - stats.first_boot_time;
  display.printf("up ~%d days (%d s)\n", uptime/one_day, uptime);
  display.printf("max bat %d mV. bad27 %d\n", stats.max_battery_mv, stats.bad_pin27_count);

  if (stats.ulp_supported)
  {
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    const char *cause_str = cause == ESP_SLEEP_WAKEUP_ULP ? "ULP" :
                            cause == ESP_SLEEP_WAKEUP_TIMER ? "TMR" : "?";
    display.printf("wake:%s ulp:ON", cause_str);
  }
}

#endif // DISABLE_DISPLAY


void display_clear()
{
#ifndef DISABLE_DISPLAY
  display.init(0 /* disable serial debug output */);
  display.clearScreen();
  display.hibernate();
  LOGI("Done");
#endif
}

void display_show_temperature(float temp, uint32_t battery_mv, bool low_battery,
                              time_t now, const struct tm *nowtm,
                              const DisplayStats &stats)
{
#ifndef DISABLE_DISPLAY
  init_for_render(stats.boot_count);

  LOGI("Display text");
  display.setTextSize(3);
  display.setCursor(10, 10);
  display.setTextColor(EPD_BLACK);
  display.printf("%.1f C\n", temp);

  display.setTextSize(2);
  if (low_battery)
    display.setTextColor(EPD_RED);
  display.printf("%s %d mV\n", low_battery ? "LOW BAT" : "bat", battery_mv);

  render_stats(now, nowtm, stats);

  // TODO: There might be an opportunity to light sleep while the display updates
  display.display();
  display.hibernate();
  LOGI("Done updating display and powering down");
#endif
}

void display_show_pin27_diagnostic(int boot_count)
{
#ifndef DISABLE_DISPLAY
  init_for_render(boot_count);
  display.setCursor(0, 0);
  display.setTextColor(EPD_BLACK);
  display.setTextSize(1);
  display.printf("Read pin27 == 0");
  display.display();
  display.hibernate();
#endif
}

void display_show_empty_battery(uint32_t battery_mv, time_t now,
                                const struct tm *nowtm,
                                const DisplayStats &stats)
{
#ifndef DISABLE_DISPLAY
  init_for_render(stats.boot_count);
  display.setCursor(0, 0);
  display.setTextColor(EPD_RED);
  if (display.height() < 200)
  {
    display.setTextSize(2);
    display.printf("  EMPTY BATTERY\n"
                   "    RECHARGE!\n");
  }
  else
  {
    display.setTextSize(3);
    display.printf("\n\n"
                  "   EMPTY\n"
                  "  BATTERY\n"
                  " RECHARGE!\n"
                  "\n");
  }
  display.setTextSize(2);
  display.setTextColor(EPD_BLACK);
  display.printf("   bat %d mV\n", battery_mv);

  render_stats(now, nowtm, stats);

  display.display();
  display.hibernate();
#endif
}
