// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

// TODO: Figure out how to get proper logging facilities working (probably after switching to platformio)
#ifndef DISABLE_SERIAL
#define LOGI(...) { Serial.printf(__VA_ARGS__); Serial.print("\n"); }
#else
#define LOGI(...)
#endif

#include "time.h"

#ifndef DISBALE_WIFI
#include "WiFi.h"
#endif

#include "FastLED.h"

#define EPD_DC    17 // D10
#define EPD_CS     2 // D9
#define EPD_BUSY  13 // D7
#define SRAM_CS   14 // D6
#define EPD_RESET 25 // D2

#define USE_GXEPD
#ifdef USE_GXEPD
#include "GxEPD2_3C.h"
GxEPD2_3C<GxEPD2_154_Z90c, GxEPD2_154_Z90c::HEIGHT> display(GxEPD2_154_Z90c(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#define EPD_BLACK GxEPD_BLACK
#define EPD_RED GxEPD_RED
#define EPD_WHITE GxEPD_WHITE
#else
#include "Adafruit_ThinkInk.h"
ThinkInk_154_Tricolor_Z90 display(EPD_DC, EPD_RESET, EPD_CS, SRAM_CS, EPD_BUSY);
#endif

#include "OneWire.h"
#include "DallasTemperature.h"

// Don't use pin 12 / D13 for one wire as it resets the board if high on boot
#define ONE_WIRE   4 // D12

OneWire oneWire(ONE_WIRE);
DallasTemperature sensors(&oneWire);

RTC_DATA_ATTR int boot_count = 0;
RTC_DATA_ATTR int display_refresh_count = 0;

RTC_DATA_ATTR time_t first_boot_time = 0;
RTC_DATA_ATTR time_t next_clear_time = 0;
const time_t one_day = 86400;

RTC_DATA_ATTR float previous_temp = -1;
RTC_DATA_ATTR int previous_boot_count = -1;

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
  // Go to sleep
  esp_sleep_enable_timer_wakeup(5*1000000);
  esp_sleep_enable_gpio_switch(true);
  LOGI("Sleeping for 5 seconds");
  Serial.flush();
  esp_deep_sleep_start();
}

void clear_display()
{
#ifdef USE_GXEPD
  display.init(0 /* disable serial debug output */);
  display.clearScreen();
  display.hibernate();
#else
  display.begin(THINKINK_TRICOLOR);
  LOGI("Clearing display");
  display.clearDisplay();
  display.powerDown();
#endif
  LOGI("Done");
}

// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
uint32_t read_battery_level()
{
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  uint32_t battery_mv = analogReadMilliVolts(34) * 2;
  LOGI("Battery level: %d mV", battery_mv);
  return battery_mv;
}

#define NUM_LEDS 1
CRGB leds[NUM_LEDS];

void initialize_status_led()
{
  FastLED.addLeds<NEOPIXEL, 5/*data pin*/>(leds, NUM_LEDS);
  FastLED.setBrightness(128);
}

void set_status_led(CRGB color)
{
  // Looks like Red is a greenish tint
  // Green and Blue both show up correct
  leds[0] = color;
  FastLED.show();
}

void clear_status_led()
{
  FastLED.clear(true);
}

void initialize_sensors()
{
  LOGI("Setting up sensors");
  sensors.begin();
  bool parasite = sensors.isParasitePowerMode();
  LOGI("Parasitic power is: %d", (int)parasite);
  while (!parasite)
  {
    // Looks like parasite power detection is unreliable. Waiting a bit and trying again seems to fix it.
    delay(10);
    LOGI("Attempting to reinitialize to fix parasite power mode detection");
    sensors.begin();
    parasite = sensors.isParasitePowerMode();
    LOGI("Parasitic power is: %d", (int)parasite);
  }
  sensors.setResolution(12);
  // Set to non blocking to allow going to light sleep while we wait for temperature conversion in order to save power
  sensors.setWaitForConversion(false);

  LOGI("Done");
}

float read_temperature()
{
  LOGI("Getting temperature");
  sensors.requestTemperatures();
  esp_sleep_enable_timer_wakeup(sensors.millisToWaitForConversion(sensors.getResolution()) * 1000);
  LOGI("going to light sleep");
  esp_light_sleep_start();
  LOGI("back from light sleep");
  float temp = sensors.getTempCByIndex(0);
  LOGI("temp: %f °C", temp);
  return temp;
}

void initialize_display()
{
  LOGI("Initializing display");
#ifdef USE_GXEPD
  display.init(0 /* disable serial debug output */,
               boot_count == 1 /* allow partial updates directly after power-up for non first runs */);
  display.cp437(true);
  display.setRotation(2);
  display.fillScreen(GxEPD_WHITE);
#else
  display.begin(THINKINK_TRICOLOR);
  display.cp437(true);
  display.clearBuffer();
#endif
  LOGI("Done");
}

void display_stats(time_t now, const struct tm *nowtm)
{
  char formatted_time[256];

  display.setTextSize(1);
  display.setTextColor(EPD_BLACK);
  display.printf("seq %d (was %d). refresh %d\n", boot_count, previous_boot_count, display_refresh_count);
  // TODO: Maybe don't format this every time we render?
  struct tm tm;
  localtime_r(&first_boot_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("first boot %s\n", formatted_time);
  strftime(formatted_time, 256, "%F %T", nowtm);
  display.printf("last refresh %s\n", formatted_time);
  localtime_r(&next_clear_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("next clear %s\n", formatted_time);

  time_t uptime = now-first_boot_time;
  display.printf("up ~%d days (%d s)", uptime/one_day, uptime);
}

void handle_permanent_shutdown(uint32_t battery_mv)
{
  uint16_t pin27 = touchRead(27);
  LOGI("Touch read 27: %d", pin27);
  if (pin27 == 0 || battery_mv < no_battery_mv)
  {
    // If button is pressed or battery is dead, powerdown
    if (pin27 == 0)
    {
      clear_display();
    }
    else //  battery_mv < no_battery_mv
    {
      initialize_display();
      display.setTextSize(3);
      display.setCursor(0, 0);
      display.setTextColor(EPD_RED);
      display.printf("\n\n"
                     "   EMPTY\n"
                     "  BATTERY\n"
                     " RECHARGE!\n"
                     "\n");
      display.setTextSize(2);
      display.setTextColor(EPD_BLACK);
      display.printf("   bat %d mV\n", battery_mv);

      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);
      display_stats(now, &nowtm);

      display.display();
    }

    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    LOGI("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}


void update_display(uint32_t battery_mv, float temp, time_t now, const struct tm *nowtm)
{
  display_refresh_count++; // Help get a sense of frequency of refreshes

  initialize_display();

  LOGI("Display text");
  display.setTextSize(3);
  display.setCursor(0, 0);
  display.setTextColor(EPD_BLACK);
  display.printf("%.1f C\n", temp);

  display.setTextSize(2);
  if (battery_mv < low_battery_mv)
    display.setTextColor(EPD_RED);
  display.printf("%s %d mV\n", battery_mv < low_battery_mv ? "LOW BAT" : "bat", battery_mv);

  display_stats(now, nowtm);

#if 0
#ifdef USE_GXEPD
  if (boot_count > 1)
  {
    // TODO Partial display works ... figure out if they're worth using
    // TODO: Figure out how to determine proper partial update region
    display.displayWindow(50, 50, 150, 150);
  }
  else
#endif
#endif
  {
    // TODO: There might be an opportunity to light sleep while the display updates
    display.display();
  }
#ifdef USE_GXEPD
  display.hibernate();
#else
  display.powerDown();
#endif
  LOGI("Done updating display and powering down");
}

void on_first_boot()
{
#ifdef DISABLE_WIFI
  LOGI("WiFi has been disabled at build time with DISABLE_WIFI. See local-secrets.h to fix.");
  set_status_led(CRGB::Yellow);
  delay(100);
#else
  if (my_wifi_ssid == NULL || *my_wifi_ssid == 0)
  {
    LOGI("Missing WiFi SSID. Will assume network connectivity isn't possible. See local-secrets.h to fix.");
    return;
  }

  // Connect to WiFi
  LOGI("Connecting to WiFi");
  set_status_led(CRGB::Blue);

  WiFi.begin(my_wifi_ssid, my_wifi_password);
  while (!WiFi.isConnected())
  {
    delay(100);
    LOGI("Waiting for WiFi");
  }
  LOGI("Connected to WiFi");

  // Synchronize time
  LOGI("Synchronizing time");
  set_status_led(CRGB::Green);
  // Example TZ formats are available at https://github.com/esp8266/Arduino/blob/master/cores/esp8266/TZ.h
  configTzTime(my_tz, "pool.ntp.org");
  struct tm t;
  getLocalTime(&t, 30000U /* max wait time in ms */); // Wait for time to have synced
  first_boot_time = mktime(&t);

  // TODO: double check that this effectively completely shuts off all wireless current consumption
  WiFi.disconnect(true, true);
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

  clear_display();
  next_clear_time += one_day; // Schedule next clear in a day
  return true;
}

void get_time(time_t *now, struct tm *nowtm)
{
  setenv("TZ", my_tz, 1);
  tzset();
  time(now);
  localtime_r(now, nowtm);
}

// TODO: trigger display clear once a day
void setup()
{
  setup_serial();

  boot_count++;
  LOGI("Boot count: %d", boot_count);
  LOGI("Wakeup caused by %d", (int)esp_sleep_get_wakeup_cause());

  uint32_t battery_mv = read_battery_level();

  handle_permanent_shutdown(battery_mv);

  // TODO: rather than run this only once, run daily/weekly
  if (boot_count == 1)
  {
    initialize_status_led();
    on_first_boot();
    clear_status_led(); // TODO: double check that this stops drawing power
  }

  initialize_sensors();

  float temp = read_temperature();

  time_t now;
  struct tm nowtm;
  get_time(&now, &nowtm);

  LOGI("now: %d. next clear time: %d. first boot time: %d", now, next_clear_time, first_boot_time);
  if (!periodic_display_clear(now, nowtm) &&
      abs(temp - previous_temp) < 0.1) // TODO: check rounded up temp as that's what really matters for the display
  {
    LOGI("temperature hasn't changed significantly, no need to refresh display");
  }
  else
  {
    update_display(battery_mv, temp, now, &nowtm);

    // Persist state change
    previous_temp = temp;
    previous_boot_count = boot_count;
  }

  start_deep_sleep();
}

void loop()
{
  // Never gets invoked as we deep sleep at the end of setup()
}
