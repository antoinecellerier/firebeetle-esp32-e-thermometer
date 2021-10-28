// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

#include "time.h"

#ifndef DISBALE_WIFI
#include "WiFi.h"
#endif

#include "FastLED.h"

#include "Adafruit_ThinkInk.h"

#define EPD_DC    17 // D10
#define EPD_CS     2 // D9
#define EPD_BUSY  13 // D7
#define SRAM_CS   14 // D6
#define EPD_RESET 25 // D2

ThinkInk_154_Tricolor_Z90 display(EPD_DC, EPD_RESET, EPD_CS, -1/*SRAM_CS*/, EPD_BUSY);

#include "OneWire.h"
#include "DallasTemperature.h"

// Don't use pin 12 for one wire as it resets the board if high on boot
#define ONE_WIRE   4 // D12

OneWire oneWire(ONE_WIRE);
DallasTemperature sensors(&oneWire);

RTC_DATA_ATTR int boot_count = 0;
RTC_DATA_ATTR int display_refresh_count = 0;

RTC_DATA_ATTR time_t first_boot_time = 0;
RTC_DATA_ATTR time_t next_clear_time = 0;

RTC_DATA_ATTR float previous_temp = -1;
RTC_DATA_ATTR int previous_boot_count = -1;


void setup_serial()
{
  Serial.begin(115200);
  while (!Serial)
  {
    delay(10);
  }
}

void start_deep_sleep()
{
  // Go to sleep
  esp_sleep_enable_timer_wakeup(5*1000000);
  esp_sleep_enable_gpio_switch(true);
  Serial.println("Sleeping for 5 seconds");
  Serial.flush();
  esp_deep_sleep_start();
  Serial.println("oy!!");
}

void clear_display()
{
  display.begin(THINKINK_TRICOLOR);
  Serial.println("Clearing display");
  display.clearDisplay();
  display.powerDown();
  Serial.println("Done");
}

// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
uint32_t read_battery_level()
{
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  uint32_t battery_mv = analogReadMilliVolts(34) * 2;
  Serial.printf("Battery level: %d mV\n", battery_mv);
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
  Serial.println("Setting up sensors");
  sensors.begin();
  bool parasite = sensors.isParasitePowerMode();
  Serial.printf("Parasitic power is: %d\n", (int)parasite);
  while (!parasite)
  {
    // Looks like parasite power detection is unreliable. Waiting a bit and trying again seems to fix it.
    delay(10);
    Serial.printf("Attempting to reinitialize to fix parasite power mode detection\n");
    sensors.begin();
    parasite = sensors.isParasitePowerMode();
    Serial.printf("Parasitic power is: %d\n", (int)parasite);
  }
  sensors.setResolution(12);

  Serial.println("Done");
}

float read_temperature()
{
  Serial.println("Getting temperature");
  sensors.requestTemperatures();
  float temp = sensors.getTempCByIndex(0);
  Serial.printf("temp: %f °C\n", temp);
  return temp;
}

void initialize_display()
{
  Serial.println("Initializing display");
  display.begin(THINKINK_TRICOLOR);
  display.cp437(true);
  display.clearBuffer();
  Serial.println("Done");
}


void handle_permanent_shutdown(uint32_t battery_mv)
{
  uint16_t pin27 = touchRead(27);
  Serial.printf("Touch read 27: %d\n", pin27);
  if (pin27 == 0 || battery_mv < no_battery_mv)
  {
    // If button is pressed or battery is dead, powerdown
    if (battery_mv < no_battery_mv)
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
      display.printf("   bat %d mV", battery_mv);
      display.display();
    }
    else
    {
      clear_display();
    }
    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    Serial.println("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}


void update_display(uint32_t battery_mv, float temp, const struct tm *nowtm)
{
  display_refresh_count++; // Help get a sense of frequency of refreshes

  initialize_display();

  Serial.println("Display text");
  display.setTextSize(3);
  display.setCursor(0, 0);
  display.setTextColor(EPD_BLACK);
  display.printf("%.1f C\n", temp);

  char formatted_time[256];
  strftime(formatted_time, 256, "%F %T", nowtm);
  Serial.printf("now: %s\n", formatted_time);
  display.setTextSize(2);
  display.printf("%s\n", formatted_time);
  
  if (battery_mv < low_battery_mv)
    display.setTextColor(EPD_RED);
  display.printf("%s %d mV\n", battery_mv < low_battery_mv ? "LOW BAT" : "bat", battery_mv);

  display.setTextSize(1);
  display.setTextColor(EPD_BLACK);
  display.printf("seq %d (was %d). refresh %d\n", boot_count, previous_boot_count, display_refresh_count);
  // TODO: Maybe don't format this every time we render?
  struct tm tm;
  localtime_r(&first_boot_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("first boot %s\n", formatted_time);
  localtime_r(&next_clear_time, &tm);
  strftime(formatted_time, 256, "%F %T", &tm);
  display.printf("next clear %s\n", formatted_time);

  // Seems like partial display updates are broken.
  // See https://github.com/ZinggJM/GxEPD for possible alternative lib which doesn't seem to support 1.54" partial updates
  //if (boot_count > 1)
  //{
  //  // TODO: Figure out how to determine proper partial update region
  //  display.displayPartial(0, 0, 190, 190);
  //}
  //else
  {
    display.display();
  }
  display.powerDown();
  Serial.println("Done updating display and powering down");
}

void on_first_boot()
{
#ifdef DISABLE_WIFI
  Serial.printf("WiFi has been disabled at build time with DISABLE_WIFI. See local-secrets.h to fix.\n");
  set_status_led(CRGB::Yellow);
  delay(100);
#else
  if (my_wifi_ssid == NULL || *my_wifi_ssid == 0)
  {
    Serial.printf("Missing WiFi SSID. Will assume network connectivity isn't possible. See local-secrets.h to fix.\n");
    return;
  }

  // Connect to WiFi
  Serial.printf("Connecting to WiFi\n");
  set_status_led(CRGB::Blue);

  WiFi.begin(my_wifi_ssid, my_wifi_password);
  while (!WiFi.isConnected())
  {
    delay(100);
    Serial.printf("Waiting for WiFi\n");
  }
  Serial.printf("Connected to WiFi\n");

  // Synchronize time
  Serial.printf("Synchronizing time\n");
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
  const time_t one_day = 86400;

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

// TODO: trigger display clear once a day
void setup()
{
  setup_serial();

  boot_count++;
  Serial.printf("Boot count: %d\n", boot_count);
  Serial.printf("Wakeup caused by %d\n", (int)esp_sleep_get_wakeup_cause());

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

  setenv("TZ", my_tz, 1);
  tzset();
  time_t now;
  struct tm nowtm;
  time(&now);
  localtime_r(&now, &nowtm);

  Serial.printf("now: %d. next clear time: %d. first boot time: %d\n", now, next_clear_time, first_boot_time);
  if (!periodic_display_clear(now, nowtm) &&
      abs(temp - previous_temp) < 0.1) // TODO: check rounded up temp as that's what really matters for the display
  {
    Serial.printf("temperature hasn't changed significantly, no need to refresh display\n");
  }
  else
  {
    update_display(battery_mv, temp, &nowtm);

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
