#include "time.h"

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

void handle_permanent_shutdown()
{
  uint16_t pin27 = touchRead(27);
  Serial.printf("Touch read 27: %d\n", pin27);
  if (pin27 == 0)
  {
    // If button is pressed, powerdown
    display.begin(THINKINK_TRICOLOR);
    Serial.println("Clearing display");
    display.clearDisplay();
    display.powerDown();
    Serial.println("Done");
    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    Serial.println("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}

uint32_t read_battery_level()
{
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  uint32_t battery_mv = analogReadMilliVolts(34) * 2;
  Serial.printf("Battery level: %d mV\n", battery_mv);
  return battery_mv;
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
  //display.begin(THINKINK_MONO);
  display.begin(THINKINK_TRICOLOR);
  display.cp437(true);
  Serial.println("Done");
}

void update_display(uint32_t battery_mv, float temp, const struct tm *timeinfo)
{
  display_refresh_count++; // Help get a sense of frequency of refreshes

  initialize_display();

  Serial.println("Display text");
  display.clearBuffer();

  display.setTextSize(3);
  display.setCursor(0, 0);
  display.setTextColor(EPD_BLACK);
  display.printf("%.1f C\n", temp);

  char formatted_time[256];
  strftime(formatted_time, 256, "%F %T", timeinfo);
  Serial.printf("now: %s\n", formatted_time);
  display.setTextSize(2);
  display.printf("%s\n", formatted_time);
  
  display.setTextColor(EPD_RED);
  display.printf("bat %d mV\n", battery_mv);



  display.setTextSize(1);
  display.setTextColor(EPD_BLACK);
  display.printf("seq %d (was %d). refresh %d\n", boot_count, previous_boot_count, display_refresh_count);

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

// TODO: trigger display clear once a day
void setup()
{
  setup_serial();

  boot_count++;
  Serial.printf("Boot count: %d\n", boot_count);
  Serial.printf("Wakeup caused by %d\n", (int)esp_sleep_get_wakeup_cause());

  handle_permanent_shutdown();

  uint32_t battery_mv = read_battery_level();

  initialize_sensors();

  float temp = read_temperature();

  if (abs(temp - previous_temp) < 0.1) // TODO: check rounded up temp as that's what really matters for the display
  {
    Serial.printf("temperature hasn't changed significantly, no need to refresh display\n");
  }
  else
  {
    time_t now;
    struct tm timeinfo;
    time(&now);
    gmtime_r(&now, &timeinfo);

    update_display(battery_mv, temp, &timeinfo);

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
