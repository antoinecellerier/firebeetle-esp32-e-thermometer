#include "common.h"

// needed for setenv and tzset :-/
#undef __STRICT_ANSI__
#include "time.h"
#include "stdlib.h"

#ifndef DISABLE_WIFI
#include "WiFi.h"
#endif

#include "FastLED.h"
#include "Display.h"

// Used for JTAG. Avoid for other purposes if possible
// Firebeetle Pin | JTAG PIN
//            12  |  TDI
//            13  |  TCK
//            14  |  TMS
//            15  |  TDO
// JTAG init and deep sleep don't seem to play well together
// openocd errors when trying to init JTAG during deep sleep:
//   Error: JTAG scan chain interrogation failed: all ones
//   Error: Check JTAG interface, timings, target power, etc.
//   Error: Trying to use configured scan chain anyway...
//   Error: esp32.cpu0: IR capture error; saw 0x1f not 0x01
// when that error is hit you might need to kill the openocd process even if debugging is stopped in VS code
// Repro cmd
// ~/.platformio/packages/tool-openocd-esp32/bin/openocd -s ~/.platformio/packages/tool-openocd-esp32 -c "gdb_port pipe; tcl_port disabled; telnet_port disabled" -s ~/.platformio/packages/tool-openocd-esp32/share/openocd/scripts -f interface/ftdi/esp32_devkitj_v1.cfg -f board/esp-wroom-32.cfg -c "adapter_khz 5000"

#if defined(USE_DS18B20_PAR)
  #include "sensors/DS18B20Sensor.hpp"
  DS18B20Sensor sensor;
#elif defined(USE_BMP390L)
  #include "sensors/BMP390LSensor.hpp"
  BMP390LSensor sensor;
#elif defined(USE_DUMMY_SENSOR)
  #include "sensors/DummySensor.hpp"
  DummySensor sensor;
#else
# error Unknown sensor type
#endif

RTC_DATA_ATTR int boot_count = 0;
RTC_DATA_ATTR int display_refresh_count = 0;

RTC_DATA_ATTR time_t first_boot_time = 0;
RTC_DATA_ATTR time_t next_clear_time = 0;
const time_t one_day = 86400;

RTC_DATA_ATTR float previous_temp = -1;
RTC_DATA_ATTR int previous_boot_count = -1;

RTC_DATA_ATTR uint32_t max_battery_mv = 0;

RTC_DATA_ATTR uint32_t bad_pin27_count = 0;

DisplayStats make_display_stats()
{
  return {
    boot_count, previous_boot_count, display_refresh_count,
    first_boot_time, next_clear_time, max_battery_mv, bad_pin27_count,
    sensor.SupportsUlp()
  };
}

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
  if (sensor.SupportsUlp())
  {
    // ULP is polling the sensor — it will wake us when temperature changes
    esp_sleep_enable_ulp_wakeup();
    // Timer safety net for periodic housekeeping (display clear, battery check)
    esp_sleep_enable_timer_wakeup(ULP_SAFETY_NET_US);
    LOGI("Sleeping with ULP wakeup (timer safety net: %d min)", (int)(ULP_SAFETY_NET_US / 60000000ULL));
  }
  else
  {
    esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_INTERVAL_S * 1000000ULL);
    LOGI("Sleeping for %d seconds", SLEEP_INTERVAL_S);
  }
  Serial.flush();
  PPK2_CPU_ACTIVE_LOW();
  esp_deep_sleep_start();
}

void get_time(time_t *now, struct tm *nowtm)
{
  setenv("TZ", MY_TZ, 1);
  tzset();
  time(now);
  localtime_r(now, nowtm);
}

#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
#elif defined(ARDUINO_XIAO_ESP32C6)
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
#else
  #error "Unknown board type"
#endif

uint32_t read_battery_level()
{
  #if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  #define VOLTAGE_PIN 34
  // 34 = A2
  #elif defined(ARDUINO_XIAO_ESP32C6)
  // https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/#reading-battery-voltage
  // Requires wiring A0 to VBAT see https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/#check-the-battery-voltage
  #define VOLTAGE_PIN A0
  return 4321; // TODO: remove this once proper circuit has been soldered
  #else
  #error "Unknown board type"
  #endif
  uint32_t battery_mv = analogReadMilliVolts(VOLTAGE_PIN) * 2;
  LOGI("Battery level: %d mV", battery_mv);
  return battery_mv;
}

#ifndef DISABLE_LEDS
#define NUM_LEDS 1
CRGB leds[NUM_LEDS];
#endif

void initialize_status_led()
{
#ifndef DISABLE_LEDS
  FastLED.addLeds<NEOPIXEL, 5/*data pin*/>(leds, NUM_LEDS);
  FastLED.setBrightness(128);
#endif
}

void set_status_led(CRGB color)
{
#ifndef DISABLE_LEDS
  // Looks like Red is a greenish tint
  // Green and Blue both show up correct
  leds[0] = color;
  FastLED.show();
#endif
}

void clear_status_led()
{
#ifndef DISABLE_LEDS
  FastLED.clear(true);
#endif
}

float read_temperature()
{
  LOGI("Getting temperature");
  float temp = sensor.GetTemperatureC();
  LOGI("temp: %f °C", temp);
  return temp;
}

#ifndef SOC_TOUCH_SENSOR_SUPPORTED
uint16_t touchRead(uint8_t /*pin*/)
{
  // FIXME: We should have an alternate shutdown method
  return 1; // Touch isn't supported, so always return non-zero
}
#endif

void handle_permanent_shutdown(uint32_t battery_mv)
{
  uint16_t pin27 = touchRead(27);
  LOGI("Touch read 27: %d", pin27);
  if (pin27 == 0 || battery_mv < no_battery_mv)
  {
    // If button is pressed or battery is dead, powerdown
    if (pin27 == 0)
    {
      // Looks like we might be getting extremely rare spurious reads of 0
      // Double check after a delay ...
      delay(1000);
      pin27 = touchRead(27);
      LOGI("Touch read 27 confirmation: %d", pin27);
      if (pin27 != 0)
      {
        bad_pin27_count++;
        return;
      }

      display_clear();

      // ... and add somethign on screen for diagnostics purposes in case the delay isn't sufficient
      // TODO remove this later
      display_show_pin27_diagnostic(boot_count);
    }
    else //  battery_mv < no_battery_mv
    {
      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);
      display_show_empty_battery(battery_mv, now, &nowtm, make_display_stats());
    }

    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    LOGI("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}

void on_first_boot()
{
#ifdef DISABLE_WIFI
  LOGI("WiFi has been disabled at build time with DISABLE_WIFI. See local-secrets.h to fix.");
  set_status_led(CRGB::Yellow);
  delay(100);
#else
  #if !(defined(MY_WIFI_SSID) && defined(MY_WIFI_PASSWORD))
    #error "MY_WIFI_SSID and/or MY_WIFI_PASSWORD are not defined. See local-secrets.h to fix."
  #endif
  if (*MY_WIFI_SSID == 0)
  {
    LOGI("Missing WiFi SSID. Will assume network connectivity isn't possible. See local-secrets.h to fix.");
    return;
  }

  // Connect to WiFi
  LOGI("Connecting to WiFi");
  set_status_led(CRGB::Blue);

  WiFi.begin(MY_WIFI_SSID, MY_WIFI_PASSWORD);
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
  configTzTime(MY_TZ, "pool.ntp.org");
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

  display_clear();
  next_clear_time += one_day; // Schedule next clear in a day
  return true;
}

void refresh_and_sleep(uint32_t battery_mv, float temp)
{
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
    display_refresh_count++;
    if (max_battery_mv < battery_mv)
      max_battery_mv = battery_mv;

    PPK2_DISPLAY_HIGH();
    display_show_temperature(temp, battery_mv, battery_mv < low_battery_mv,
                             now, &nowtm, make_display_stats());
    PPK2_DISPLAY_LOW();

    previous_temp = temp;
    previous_boot_count = boot_count;
  }

  if (sensor.SupportsUlp())
    sensor.InitializeUlp();

  start_deep_sleep();
}


void setup()
{

  setup_serial();

#ifdef PPK2_DEBUG
  pinMode(PPK2_PIN_CPU_ACTIVE, OUTPUT);
  pinMode(PPK2_PIN_DISPLAY, OUTPUT);
#endif
  PPK2_CPU_ACTIVE_HIGH();

  boot_count++;
  if (boot_count != 1)
  {
    // Reducing CPU frequency to 80 MHz to save power (as none of this CPU bound)
    setCpuFrequencyMhz(80);
  }
  LOGI("CPU frequency: %d", getCpuFrequencyMhz());
  LOGI("Xtal frequency: %d", getXtalFrequencyMhz());

  LOGI("Boot count: %d", boot_count);
  esp_sleep_wakeup_cause_t wakeup_cause = esp_sleep_get_wakeup_cause();
  LOGI("Wakeup caused by %d", (int)wakeup_cause);

  uint32_t battery_mv = read_battery_level();

  handle_permanent_shutdown(battery_mv);

  if (wakeup_cause == ESP_SLEEP_WAKEUP_ULP && sensor.SupportsUlp())
  {
    float temp;
    if (sensor.ReadUlpTemperature(&temp))
    {
      refresh_and_sleep(battery_mv, temp);
      return; // never reached
    }
    // ULP I2C error — fall through to normal sensor read
  }

  // TODO: rather than run this only once, run daily/weekly
  if (boot_count == 1)
  {
    initialize_status_led();
    on_first_boot();
    clear_status_led(); // TODO: double check that this stops drawing power
  }

  float temp = read_temperature();
  refresh_and_sleep(battery_mv, temp);
}

void loop()
{
  // Never gets invoked as we deep sleep at the end of setup()
}
