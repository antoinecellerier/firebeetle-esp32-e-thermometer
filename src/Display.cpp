#include "Display.h"
#include "app_common.h"
#include "displays.h"               // DISPLAY_HAS_RED / DISPLAY_ROTATION

#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
// 3.3V GND SCK MOSI DC CS BUSY RESET pins are all on the same side of the Firebeetle board
#define EPD_DC     2 // D9
#define EPD_CS    14 // D6 (was D5/GPIO0, moved to free GPIO0 for RTC I2C SDA)
#define EPD_BUSY  26 // D3
#define EPD_RESET 25 // D2
#elif defined(ARDUINO_XIAO_ESP32C6)
#if defined(SEEED_XIAO_EPD_BOARD)
// Seeed ePaper Driver Board for XIAO — the shield hardwires these
// (SCK=D8/MOSI=D10 match the DESPI wiring; see docs/wiring.md)
#define EPD_DC    21 // D3
#define EPD_CS     1 // D1
#define EPD_BUSY   2 // D2
#define EPD_RESET  0 // D0
// The shield has no panel power gate (3V3 hardwired to booster/FPC), so
// override an EPD_POWER_GATE left enabled in local-secrets.h.
#undef EPD_POWER_GATE
#elif defined(THERMOMETER_C6_BOARD)
// Custom thermometer-c6 board (hardware/thermometer-c6): EPD deliberately on
// the SDIO strap group — boot-time toggles drive an unpowered (gated) panel.
#define EPD_DC    21
#define EPD_CS    20
#define EPD_BUSY  23
#define EPD_RESET 22 // 10k pull-up to gated EPD_VCC (not 3V3)
#ifndef EPD_POWER_GATE
#error "THERMOMETER_C6_BOARD requires EPD_POWER_GATE in local-secrets.h (the panel rail is hardware-gated)"
#endif
#else
// DESPI-C02, same Dx labels as Firebeetle — see docs/wiring.md for C6 GPIO mapping
#define EPD_DC    20 // D9
#define EPD_CS    16 // D6
#define EPD_BUSY  21 // D3
#define EPD_RESET  2 // D2
#endif
#else
#error "EPD pin mapping not defined for this board"
#endif
#ifndef DISABLE_DISPLAY

#include "DisplayRenderer.h" // pulls in Adafruit_GFX — display builds only
#include "generated/font_config.h"  // FONT_CONFIG_W/H for the stale-font guard

#ifdef EPD_POWER_GATE
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#define EPD_POWER 13 // D7 — P-FET gate: LOW = on, HIGH = off
#elif defined(THERMOMETER_C6_BOARD)
#define EPD_POWER 14 // EPD_PWR_EN → Q2 P-FET via R24 soft-start; 10k pull-up = off at reset/sleep
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
#if defined(THERMOMETER_C6_BOARD)
  // With the rail gated off, a high EPD output back-powers the panel through
  // its input protection diodes (CS and RST both idle high). Float the
  // plain-GPIO control pins — epd_configure_pins() re-arms them on next use.
  // MOSI/SCK stay bound to the SPI peripheral (idle low, harmless).
  const int pins[] = {EPD_CS, EPD_DC, EPD_RESET};
  for (size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); i++)
  {
    gpio_set_direction((gpio_num_t)pins[i], GPIO_MODE_INPUT);
    gpio_pullup_dis((gpio_num_t)pins[i]);
    gpio_pulldown_dis((gpio_num_t)pins[i]);
  }
#endif
}
#else
static void epd_power_on() {}
static void epd_power_off() {}
#endif

// This file drives GxEPD2 directly, so it uses the library's GxEPD_* color
// constants. The renderer (DisplayRenderer.cpp) owns the EPD_* abstraction and
// its panel-keyed EPD_RED — keeping the color in one place avoids the duplicate
// that once drifted and silently disabled the tri-color red.
#include "GxEPD2_BW.h"
#if defined(USE_154_Z90)
  #include "GxEPD2_3C.h"
  using PanelT = GxEPD2_154_Z90c;
  GxEPD2_3C<PanelT, PanelT::HEIGHT> display(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#elif defined(USE_154_M09)
  using PanelT = GxEPD2_154_M09;
  GxEPD2_BW<PanelT, PanelT::HEIGHT> display(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#elif defined(USE_213_M21)
  using PanelT = GxEPD2_213_M21;
  GxEPD2_BW<PanelT, PanelT::HEIGHT> display(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#elif defined(USE_290_I6FD)
  using PanelT = GxEPD2_290_I6FD;
  GxEPD2_BW<PanelT, PanelT::HEIGHT> display(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#elif defined(USE_154_GDEY)
  using PanelT = GxEPD2_154_GDEY0154D67;
  GxEPD2_BW<PanelT, PanelT::HEIGHT> display(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#elif defined(USE_576_T81)
  using PanelT = GxEPD2_576_GDEH0576T81;
  // Heap-allocate: the 78KB buffer won't fit in static BSS alongside other globals,
  // but there's plenty of heap. Paged rendering doesn't work (SSD2677 requires full-screen writes).
  static auto& display = *new GxEPD2_BW<PanelT, PanelT::HEIGHT>(PanelT(EPD_CS, EPD_DC, EPD_RESET, EPD_BUSY));
#else
  #error Unknown screen type
#endif

// The GxEPD2 panel is the authority. Cross-check the two things that must agree
// with it: displays.h's tri-color flag, and the generated font's dimensions
// (relied on by the GxEPD2-free renderer/sim and the Python font generator).
// GxEPD2's WIDTH/HEIGHT are pre-rotation, so compare the font as an unordered pair.
#ifndef DISABLE_DISPLAY
static_assert(PanelT::hasColor == (bool)DISPLAY_HAS_RED,
              "DISPLAY_HAS_RED (displays.h) disagrees with the GxEPD2 panel's hasColor");
#if defined(FONT_CONFIG_W)
static_assert((FONT_CONFIG_W == PanelT::WIDTH && FONT_CONFIG_H == PanelT::HEIGHT) ||
              (FONT_CONFIG_W == PanelT::HEIGHT && FONT_CONFIG_H == PanelT::WIDTH),
              "font_config.h built for different dimensions than the panel — "
              "stale include/generated/font_config.h; rebuild");
#endif
#endif

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
  SPI.begin(19 /* SCK, D8 */, -1, 18 /* MOSI, D10 */, -1);
  // Reconfigure DC and BUSY after SPI.begin() since it may have claimed them
  // as MISO/SS (GPIO20/21 are the default SPI MISO/SS on C6).
  pinMode(EPD_DC, OUTPUT);
  pinMode(EPD_BUSY, INPUT);
#else
  pinMode(EPD_BUSY, INPUT);
#endif
}

// Light-sleep instead of spin-waiting while the panel refreshes — otherwise
// the CPU idles at run current for the whole busy window (measured ~25mC of
// the ~95mC per-refresh charge on the XIAO C6 + GDEH0576T81 920x680; absolute
// numbers vary per panel/board, see docs/notes.md).
// GxEPD2 calls this repeatedly from _waitWhileBusy until BUSY deasserts.
// Level-agnostic: whatever level BUSY has now is the "busy" level GxEPD2 is
// waiting on, so arm the GPIO wake for the opposite level; a 500ms timer
// backstop bounds each slice. Console output pauses during the sleep slices
// (it is flushed before each entry).
#include "esp_sleep.h"

// SPI pins as wired (match components/arduino_shim/spi_shim.cpp defaults)
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#define EPD_SCK  18
#define EPD_MOSI 23
#elif defined(ARDUINO_XIAO_ESP32C6)
#define EPD_SCK  19
#define EPD_MOSI 18
#endif

// In light sleep, GPIOs switch to their per-pin sleep configuration — the EPD
// control and SPI lines must stay actively driven or the panel sees RST/CS
// glitches mid-refresh and aborts the waveform (symptom: faint noise, no image).
static void epd_pin_sleep_hold()
{
  const int pins[] = {EPD_CS, EPD_DC, EPD_RESET, EPD_SCK, EPD_MOSI,
#ifdef EPD_POWER_GATE
                      EPD_POWER, // FET gate must stay LOW (panel powered) through slices
#endif
  };
  for (size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); i++)
    gpio_sleep_sel_dis((gpio_num_t)pins[i]);
}

static bool s_busy_wait_plain = false;

static void epd_busy_light_sleep(const void *)
{
  if (s_busy_wait_plain)
  {
    // GxEPD2 re-reads BUSY between callbacks, so a short slice just paces the
    // polling; the wait still ends as soon as the panel releases the line.
    sleep_ms(5);
    return;
  }
  int busy_level = gpio_get_level((gpio_num_t)EPD_BUSY);
  gpio_wakeup_enable((gpio_num_t)EPD_BUSY,
                     busy_level ? GPIO_INTR_LOW_LEVEL : GPIO_INTR_HIGH_LEVEL);
  esp_sleep_enable_gpio_wakeup();
  esp_sleep_enable_timer_wakeup(500000); // backstop only — the GPIO level wake ends each wait instantly
#if SOC_PM_SUPPORT_TOP_PD
  // Keep the HP peripheral domain powered: GPSPI register state must survive
  // the slice (C6; deep sleep is unaffected — restored to AUTO below)
  esp_sleep_pd_config(ESP_PD_DOMAIN_TOP, ESP_PD_OPTION_ON);
#endif
  esp_light_sleep_start();
  // Fully disarm: neither source may leak into the later deep sleep — the
  // permanent-shutdown path arms nothing and must stay asleep, and the 100ms
  // timer would otherwise pre-empt it.
#if SOC_PM_SUPPORT_TOP_PD
  esp_sleep_pd_config(ESP_PD_DOMAIN_TOP, ESP_PD_OPTION_AUTO);
#endif
  gpio_wakeup_disable((gpio_num_t)EPD_BUSY);
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_TIMER);
}

static void init_for_render(int boot_count)
{
  LOGI("Initializing display");
  epd_configure_pins();
  epd_pin_sleep_hold();
  display.epd2.setBusyCallback(&epd_busy_light_sleep);
  // Second arg: true on first boot triggers full hardware reset;
  // false on subsequent boots allows faster partial-update init.
  display.init(0 /* disable serial debug output */,
               boot_count == 1 /* full reset on first boot only */);
  display.setRotation(DISPLAY_ROTATION);
  display.fillScreen(GxEPD_WHITE);
}

#endif // DISABLE_DISPLAY


void display_set_busy_wait_plain(bool plain)
{
#ifndef DISABLE_DISPLAY
  s_busy_wait_plain = plain;
#else
  (void)plain;
#endif
}

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
#if defined(FONT_CONFIG_W)
  if (display.width() != FONT_CONFIG_W || display.height() != FONT_CONFIG_H) {
    LOGI("*** FONT CONFIG MISMATCH: fonts built for %dx%d but display is %dx%d "
         "— temperature text will be wrong size. Stale include/generated/"
         "font_config.h; rebuild. ***",
         FONT_CONFIG_W, FONT_CONFIG_H, display.width(), display.height());
  }
#endif
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
  display.setTextColor(GxEPD_BLACK);
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
