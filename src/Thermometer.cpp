#include "common.h"

// needed for setenv and tzset :-/
#undef __STRICT_ANSI__
#include "time.h"
#include "stdlib.h"

#ifndef DISABLE_WIFI
#include "WiFi.h"
#endif

#include "FastLED.h"

#ifdef USE_BMP390L
#include "UlpProgram.h"
#include "BMP390LCompensation.h"
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
#include "driver/rtc_io.h"
#endif

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

#endif

#if defined(USE_DS18B20_PAR)
  #include "sensors/DS18B20Sensor.hpp"
  DS18B20Sensor sensor;
#elif defined(USE_BMP390L)
  #include "sensors/BMP390LSensor.hpp"
  BMP390LSensor sensor;
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

#ifdef USE_BMP390L
// ULP state persisted across deep sleep
RTC_DATA_ATTR bool ulp_running = false;
RTC_DATA_ATTR struct BMP390LCalib bmp390l_calib = {};
#endif

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
#ifdef USE_BMP390L
  if (ulp_running)
  {
    // ULP is polling the sensor — it will wake us when temperature changes
    esp_sleep_enable_ulp_wakeup();
    // Timer safety net for periodic housekeeping (display clear, battery check)
    esp_sleep_enable_timer_wakeup(ULP_SAFETY_NET_US);
    LOGI("Sleeping with ULP wakeup (timer safety net: %d min)", (int)(ULP_SAFETY_NET_US / 60000000ULL));
  }
  else
#endif
  {
    esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_INTERVAL_S * 1000000ULL);
    LOGI("Sleeping for %d seconds", SLEEP_INTERVAL_S);
  }
  Serial.flush();
  PPK2_CPU_ACTIVE_LOW();
  esp_deep_sleep_start();
}

void clear_display()
{
#ifndef DISABLE_DISPLAY
  display.init(0 /* disable serial debug output */);
  display.clearScreen();
  display.hibernate();
  LOGI("Done");
#endif
}

void get_time(time_t *now, struct tm *nowtm)
{
  setenv("TZ", MY_TZ, 1);
  tzset();
  time(now);
  localtime_r(now, nowtm);
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

void initialize_display()
{
#ifndef DISABLE_DISPLAY
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
  LOGI("Done");
#else
  LOGI("Display has been disabled at build time with DISABLE_DISPLAY. See local-secrets.h to fix.");
#endif
}

#ifndef DISABLE_DISPLAY
void display_stats(time_t now, const struct tm *nowtm)
{
  char formatted_time[256];

  display.setTextSize(1);
  display.setTextColor(EPD_RED);
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
  display.printf("up ~%d days (%d s)\n", uptime/one_day, uptime);
  display.printf("max bat %d mV. bad27 %d\n", max_battery_mv, bad_pin27_count);

#ifdef USE_BMP390L
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  const char *cause_str = cause == ESP_SLEEP_WAKEUP_ULP ? "ULP" :
                          cause == ESP_SLEEP_WAKEUP_TIMER ? "TMR" : "?";
  display.printf("wake:%s ulp:%s", cause_str, ulp_running ? "ON" : "OFF");
#endif
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

      clear_display();

      // ... and add somethign on screen for diagnostics purposes in case the delay isn't sufficient
      // TODO remove this later
      initialize_display();
      display.setCursor(0, 0);
      display.setTextColor(EPD_BLACK);
      display.setTextSize(1);
      display.printf("Read pin27 == 0");
      display.display();
      display.hibernate();
    }
    else //  battery_mv < no_battery_mv
    {
      initialize_display();
      #ifndef DISABLE_DISPLAY
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

      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);
      display_stats(now, &nowtm);

      display.display();

      display.hibernate();
      #endif
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

  PPK2_DISPLAY_HIGH();
  initialize_display();
#ifndef DISABLE_DISPLAY
  LOGI("Display text");
  display.setTextSize(3);
  display.setCursor(10, 10);
  display.setTextColor(EPD_BLACK);
  display.printf("%.1f C\n", temp);

  display.setTextSize(2);
  if (battery_mv < low_battery_mv)
    display.setTextColor(EPD_RED);
  display.printf("%s %d mV\n", battery_mv < low_battery_mv ? "LOW BAT" : "bat", battery_mv);
  if (max_battery_mv < battery_mv)
    max_battery_mv = battery_mv;

  display_stats(now, nowtm);

  // TODO: There might be an opportunity to light sleep while the display updates
  display.display();
  display.hibernate();
  PPK2_DISPLAY_LOW();
  LOGI("Done updating display and powering down");
#endif
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

#ifdef USE_BMP390L
void initialize_ulp()
{
#ifdef ULP_TEST_NO_I2C
  LOGI("Initialising ULP coprocessor (TEST MODE: counter only, no I2C)");
#else
  LOGI("Initialising ULP coprocessor for BMP390L polling");

  // Only read calibration on first boot — it's stored in RTC memory and survives deep sleep
  if (bmp390l_calib.parT1 == 0.0f)
  {
    if (!bmp390l_read_calibration(sensor.GetWire(), &bmp390l_calib))
    {
      LOGI("ERROR: Failed to read BMP390L calibration data. ULP will not start.");
      return;
    }
    LOGI("BMP390L calibration: parT1=%.2f parT2=%.10f parT3=%.15f",
         bmp390l_calib.parT1, bmp390l_calib.parT2, bmp390l_calib.parT3);
  }
  else
  {
    LOGI("BMP390L calibration loaded from RTC memory");
  }

  // Release digital I2C before switching pins to ULP bit-bang
  sensor.GetWire().end();
  delay(10);

  // I2C bus recovery: 9 SCL clocks + STOP condition.
  // Wire.end() may leave a slave holding SDA low.
  pinMode(I2C_SCL_PIN, OUTPUT);
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  for (int i = 0; i < 9; i++)
  {
    digitalWrite(I2C_SCL_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(5);
    if (digitalRead(I2C_SDA_PIN))
      break;
  }
  // Generate STOP condition (SDA low→high while SCL high)
  pinMode(I2C_SDA_PIN, OUTPUT);
  digitalWrite(I2C_SDA_PIN, LOW);
  delayMicroseconds(5);
  digitalWrite(I2C_SCL_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(I2C_SDA_PIN, HIGH);
  delayMicroseconds(5);

  // Configure GPIO pins for HULP bit-bang I2C (bypasses hardware RTC I2C peripheral)
  ulp_configure_i2c_bitbang();
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
  // Configure D13/GPIO12 as RTC GPIO output so the ULP can toggle it
  rtc_gpio_init(GPIO_NUM_12);
  rtc_gpio_set_direction(GPIO_NUM_12, RTC_GPIO_MODE_OUTPUT_ONLY);
  rtc_gpio_set_level(GPIO_NUM_12, 0);
  // RTC peripherals must stay powered during deep sleep for ULP GPIO access
  esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);
#endif

  // Build and load ULP program into RTC slow memory, then start
  ulp_build_and_load_program();
  ulp_start();
  ulp_running = true;
  LOGI("ULP started with %d µs wakeup period", (int)ULP_WAKEUP_PERIOD_US);
}
#endif

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

#ifdef USE_BMP390L
  // --- ULP wakeup path ---
  if (wakeup_cause == ESP_SLEEP_WAKEUP_ULP && ulp_running)
  {
    uint16_t wake_reason = ulp_read_var(ULP_DATA_BASE, ULP_VAR_WAKE_REASON);
    uint16_t samples = ulp_read_var(ULP_DATA_BASE, ULP_VAR_SAMPLE_COUNT);
    ulp_write_var(ULP_DATA_BASE, ULP_VAR_WAKE_REASON, 0);
    ulp_write_var(ULP_DATA_BASE, ULP_VAR_SAMPLE_COUNT, 0);

    uint16_t raw_0 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_0);
    uint16_t raw_1 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_1);
    uint16_t raw_2 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_2);

    LOGI("ULP wake (reason=%d): raw temp=%02x %02x %02x, samples=%d",
         wake_reason, raw_2, raw_1, raw_0, samples);

    if (wake_reason == 2)
    {
      LOGI("ULP I2C error, falling back to normal boot path");
    }
    else
    {
      float temp = bmp390l_compensate_temperature(&bmp390l_calib,
                                                   (uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
      LOGI("ULP compensated temp: %.2f °C", temp);

      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);

      LOGI("now: %d. next clear time: %d. first boot time: %d", now, next_clear_time, first_boot_time);
      periodic_display_clear(now, nowtm);

      update_display(battery_mv, temp, now, &nowtm);
      previous_temp = temp;
      previous_boot_count = boot_count;

      // Reinitialize ULP with fresh program before sleeping
      initialize_ulp();

      start_deep_sleep();
      return; // never reached
    }
  }
#endif

  // --- Normal boot path (first boot or timer wakeup) ---

  // TODO: rather than run this only once, run daily/weekly
  if (boot_count == 1)
  {
    initialize_status_led();
    on_first_boot();
    clear_status_led(); // TODO: double check that this stops drawing power
  }

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

#ifdef USE_BMP390L
  // (Re)initialize ULP every normal boot to ensure latest program is loaded
  // This handles both first boot and post-reflash scenarios
  initialize_ulp();
#endif

  start_deep_sleep();
}

void loop()
{
  // Never gets invoked as we deep sleep at the end of setup()
}
