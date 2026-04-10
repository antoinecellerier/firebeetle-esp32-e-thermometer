#include "Display.h"
#include "DisplayRenderer.h"
#include "common.h"

#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
// 3.3V GND SCK MOSI DC CS BUSY RESET pins are all on the same side of the Firebeetle board
#define EPD_DC     2 // D9
#define EPD_CS    14 // D6 (was D5/GPIO0, moved to free GPIO0 for RTC I2C SDA)
#define EPD_BUSY  26 // D3
#define EPD_RESET 25 // D2
#elif defined(ARDUINO_XIAO_ESP32C6)
// Same Dx labels as Firebeetle — see docs/wiring.md for C6 GPIO mapping
#define EPD_DC    20 // D9
#define EPD_CS    16 // D6
#define EPD_BUSY  21 // D3
#define EPD_RESET  2 // D2
#else
#error "EPD pin mapping not defined for this board"
#endif
#ifndef DISABLE_DISPLAY

#ifdef EPD_POWER_GATE
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#define EPD_POWER 13 // D7 — P-FET gate: LOW = on, HIGH = off
#elif defined(ARDUINO_XIAO_ESP32C6)
#define EPD_POWER 17 // D7
#else
#error "EPD_POWER pin not defined for this board"
#endif
static void epd_power_on()
{
  pinMode(EPD_POWER, OUTPUT);
  digitalWrite(EPD_POWER, LOW);
  delay(10); // let boost converter stabilize
}
static void epd_power_off()
{
  digitalWrite(EPD_POWER, HIGH);
}
#else
static void epd_power_on() {}
static void epd_power_off() {}
#endif

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
#elif defined(USE_290_I6FD)
  GxEPD2_BW<GxEPD2_290_I6FD, GxEPD2_290_I6FD::HEIGHT> display(GxEPD2_290_I6FD(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_BLACK
#elif defined(USE_154_GDEY)
  GxEPD2_BW<GxEPD2_154_GDEY0154D67, GxEPD2_154_GDEY0154D67::HEIGHT> display(GxEPD2_154_GDEY0154D67(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_BLACK
#elif defined(USE_576_T81)
  // Heap-allocate: the 78KB buffer won't fit in static BSS alongside other globals,
  // but there's plenty of heap. Paged rendering doesn't work (SSD2677 requires full-screen writes).
  static auto& display = *new GxEPD2_BW<GxEPD2_576_GDEH0576T81, GxEPD2_576_GDEH0576T81::HEIGHT>(GxEPD2_576_GDEH0576T81(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
  #define EPD_RED GxEPD_BLACK
#else
  #error Unknown screen type
#endif
#define EPD_BLACK GxEPD_BLACK
#define EPD_WHITE GxEPD_WHITE

static void epd_configure_pins()
{
  // Ensure EPD pins are in GPIO mode before GxEPD2 calls digitalWrite.
  // Required on C6 where GPIO16 (CS) defaults to non-GPIO function;
  // harmless on ESP32-E where these are already GPIO.
  pinMode(EPD_CS, OUTPUT);
  pinMode(EPD_DC, OUTPUT);
  pinMode(EPD_RESET, OUTPUT);
#if defined(ARDUINO_XIAO_ESP32C6)
  // GxEPD2 calls SPI.begin() with no args, which configures GPIO20 as MISO
  // and GPIO21 as SS — both conflict with EPD_DC and EPD_BUSY. Pre-init SPI
  // with only SCK/MOSI (e-paper is write-only, CS managed by GxEPD2).
  SPI.begin(SCK, -1, MOSI, -1);
  // Reconfigure DC and BUSY after SPI.begin() since it may have claimed them
  // as MISO/SS (GPIO20/21 are the default SPI MISO/SS on C6).
  pinMode(EPD_DC, OUTPUT);
  pinMode(EPD_BUSY, INPUT);
#else
  pinMode(EPD_BUSY, INPUT);
#endif
}

static void init_for_render(int boot_count)
{
  LOGI("Initializing display");
  epd_configure_pins();
  // Second arg: true on first boot triggers full hardware reset;
  // false on subsequent boots allows faster partial-update init.
  display.init(0 /* disable serial debug output */,
               boot_count == 1 /* full reset on first boot only */);
  #if defined(USE_213_M21) || defined(USE_290_I6FD)
  display.setRotation(1);
  #elif defined(USE_576_T81)
  display.setRotation(0);
  #else
  display.setRotation(2);
  #endif
  display.fillScreen(GxEPD_WHITE);
}

#endif // DISABLE_DISPLAY


void display_clear()
{
#ifndef DISABLE_DISPLAY
  epd_power_on();
  epd_configure_pins();
  display.init(0 /* disable serial debug output */);
  display.clearScreen();
  display.hibernate();
  epd_power_off();
  LOGI("Done");
#endif
}

void display_show_temperature(float temp, uint32_t battery_mv, bool low_battery,
                              time_t now, const struct tm *nowtm,
                              const DisplayStats &stats)
{
#ifndef DISABLE_DISPLAY
  epd_power_on();
  init_for_render(stats.boot_count);

  LOGI("Display dashboard (%dx%d)", display.width(), display.height());
  render_dashboard(display, display.width(), display.height(),
                    temp, battery_mv, low_battery, now, nowtm, stats);

  display.display();
  display.hibernate();
  epd_power_off();
#endif
}

void display_show_pin27_diagnostic(int boot_count)
{
#ifndef DISABLE_DISPLAY
  epd_power_on();
  init_for_render(boot_count);
  display.setFont(NULL);
  display.setTextSize(2);
  display.setTextColor(EPD_BLACK);
  display.setCursor(10, 30);
  display.print("Read pin27 == 0");
  display.display();
  display.hibernate();
  epd_power_off();
#endif
}

void display_show_empty_battery(uint32_t battery_mv, time_t now,
                                const DisplayStats &stats)
{
#ifndef DISABLE_DISPLAY
  epd_power_on();
  init_for_render(stats.boot_count);
  render_empty_battery(display, display.width(), display.height(),
                        battery_mv, now, stats);
  display.display();
  display.hibernate();
  epd_power_off();
#endif
}
