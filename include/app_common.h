#pragma once

// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

// ESP_PLATFORM is defined for device builds (both Arduino-ESP32 and pure
// ESP-IDF); the host simulator compiles this header without it.
#ifdef ESP_PLATFORM
#include <stdint.h>
#include <stdio.h>
#include "soc/soc_caps.h" // SOC_ULP_FSM_SUPPORTED / SOC_LP_CORE_SUPPORTED guards
#include "sdkconfig.h"    // CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED

// SoC has a ULP FSM (ESP32-E) or LP core (C6) and NO_ULP isn't set. Defined
// here — not in per-sensor headers — so every TU sees the same value
// regardless of include order.
#if (!defined(NO_ULP)) && (defined(SOC_ULP_FSM_SUPPORTED) || (defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED))
#define HAS_ULP_SUPPORT 1
#endif

// USB flash-service window: hold the CPU awake while a USB host is attached so
// the USB-Serial-JTAG port stays enumerated and esptool can reset the chip into
// download mode without the BOOT button. Requires a way to detect USB presence
// *before* the port comes up, which only the custom board has (VBUS divider on
// VBUS_SENSE_GPIO). The XIAO has no VBUS-visible pin and the SoC capability
// macro is deliberately NOT the gate: keying on it is what once shipped this
// behaviour to boards that cannot detect the host, where it stranded them.
#if defined(THERMOMETER_C6_BOARD) && defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED) && !defined(DISABLE_USB_WINDOW)
#define HAS_USB_SERVICE_WINDOW 1
#endif
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

// Framework-agnostic time helpers (IDF APIs)
static inline uint32_t ms_now(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static inline void sleep_ms(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }

// Wakeup cause, collapsed to the single value this app branches on.
// IDF 6 deprecated the scalar API in favor of a bitmap; ULP, TIMER and (with
// HAS_USB_SERVICE_WINDOW) the VBUS GPIO are the only wake sources ever armed
// here, so priority-picking them is lossless. A cause left unmapped reads as
// UNDEFINED, which the app treats as a cold boot and answers by reloading the
// ULP — so every armed source must appear below.
#include "esp_sleep.h"
#include "esp_idf_version.h"
static inline esp_sleep_wakeup_cause_t app_wakeup_cause(void)
{
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
  uint32_t causes = esp_sleep_get_wakeup_causes();
  if (causes & BIT(ESP_SLEEP_WAKEUP_ULP))
    return ESP_SLEEP_WAKEUP_ULP;
  if (causes & BIT(ESP_SLEEP_WAKEUP_TIMER))
    return ESP_SLEEP_WAKEUP_TIMER;
  if (causes & BIT(ESP_SLEEP_WAKEUP_GPIO))
    return ESP_SLEEP_WAKEUP_GPIO;
  return ESP_SLEEP_WAKEUP_UNDEFINED;
#else
  return esp_sleep_get_wakeup_cause();
#endif
}

// Raw wakeup-cause value for diagnostics: the full IDF 6 bitmap (bit index =
// esp_sleep_wakeup_cause_t), or the scalar cause on older IDF. Lets the
// footer show causes app_wakeup_cause() doesn't map (rendered "w:?<hex>").
static inline uint32_t app_wakeup_causes_raw(void)
{
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
  return esp_sleep_get_wakeup_causes();
#else
  return (uint32_t)esp_sleep_get_wakeup_cause();
#endif
}

#ifdef HAS_USB_SERVICE_WINDOW
// Deep-sleep wake when a pad goes high. IDF 6 renamed both the call and its mode
// enum; the fork belongs here rather than at the call site.
// Relies on CONFIG_ESP_SLEEP_GPIO_ENABLE_INTERNAL_RESISTORS=n
// (sdkconfig.defaults.thermometer_c6): the internal pulldown IDF would otherwise
// add for a high trigger loads the VBUS divider below VIH.
static inline esp_err_t app_enable_gpio_high_wakeup(int pin)
{
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
  return esp_sleep_enable_gpio_wakeup_on_hp_periph_powerdown(1ULL << pin,
                                                             ESP_GPIO_WAKEUP_GPIO_HIGH);
#else
  return esp_deep_sleep_enable_gpio_wakeup(1ULL << pin, ESP_GPIO_WAKEUP_GPIO_HIGH);
#endif
}
#endif

static inline void gpio_out_init(int pin)
{
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << pin;
  cfg.mode = GPIO_MODE_OUTPUT;
  gpio_config(&cfg);
}
#endif // ESP_PLATFORM

#ifndef DISABLE_SERIAL
#define LOGI(str, ...) printf(str "\n", ##__VA_ARGS__)
#else
// Dead-branch form: keeps a statement body (-Werror=empty-body), references
// the arguments (no unused-variable warnings), still checks format strings,
// and folds to nothing at any optimization level.
#define LOGI(str, ...) do { if (0) printf(str "\n", ##__VA_ARGS__); } while (0)
#endif

// I2C pins — BMP390L or BMP58x must be wired to these
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
// RTC I2C pins for ULP bit-bang I2C (HULP)
#define I2C_SDA_PIN 0  // GPIO0 (D5) — RTC I2C SDA
#define I2C_SCL_PIN 4  // GPIO4 (D12) — RTC I2C SCL
#elif defined(ARDUINO_XIAO_ESP32C6)
// LP I2C pins (hardware LP I2C peripheral, fixed by silicon)
#define I2C_SDA_PIN 6  // GPIO6 — LP I2C SDA
#define I2C_SCL_PIN 7  // GPIO7 — LP I2C SCL
#else
#error "Unknown board type — define I2C pins"
#endif
// ULP polling interval and non-ULP sleep interval.
// Keep low (5s) for development/testing, increase to 60s for production.
#ifndef SLEEP_INTERVAL_S
#define SLEEP_INTERVAL_S 60
#endif

// Timer safety net when ULP is running: main CPU wakes periodically for
// housekeeping (daily display clear, battery check) even if temperature is stable.
#define ULP_SAFETY_NET_US (3600ULL * 1000000ULL)  // 1 hour

#if defined(THERMOMETER_C6_BOARD)
// R22/R23 100k/100k divider from VBUS. Reads ~2.5V with USB attached, a hard 0V
// (R23 to GND, zero drain) without — so it is also usable as a deep-sleep wake
// source, GPIO4 being inside the C6's LP-IO range.
#define VBUS_SENSE_GPIO 4
#endif

#ifdef HAS_USB_SERVICE_WINDOW
// All four are estimates, not measured: the window only runs on USB power, so
// none of them affects a battery figure.
#define USB_WINDOW_POLL_MS 100          // VBUS/host re-check cadence while parked
#define USB_WINDOW_ENUM_GRACE_MS 3000   // wait for host traffic before calling it a charger
#define USB_WINDOW_VBUS_DEBOUNCE_N 3    // consecutive low reads before believing an unplug
#define USB_WINDOW_HOST_IDLE_S 60       // host traffic gone this long (VBUS still up) closes the window
// Sleeps to skip the host probe after one found only a charger. The probe costs
// USB_WINDOW_ENUM_GRACE_MS of CPU-active time, and a docked board wakes every
// interval, so probing each time would be a recurring burst against a bus with
// nothing on it. Any wake that sees VBUS absent resets it, so plugging into a
// host is still noticed immediately.
#define USB_WINDOW_PROBE_SKIP_WAKES 10

// Sleeps a host would have held open that are spent on real deep sleep instead,
// so deep-sleep paths can be exercised without unplugging the cable. A reflash
// wipes RTC and so re-arms the count: every flash gets N real cycles, then the
// port comes back by itself.
#ifndef USB_WINDOW_OBSERVE_CYCLES
#define USB_WINDOW_OBSERVE_CYCLES 0
#endif
#endif

// PPK2 debug pins — wire to PPK2 digital channels for power trace correlation
// D10/GPIO17 → PPK2 D0: HIGH while main CPU is awake
// D11/GPIO16 → PPK2 D1: HIGH during display refresh
// D13/GPIO12 → PPK2 D2: HIGH while ULP is executing (RTC GPIO, toggled by ULP itself)
//   ⚠ PPK2_DEBUG_ULP_GPIO requires RTC peripherals to stay powered during deep sleep,
//     which increases sleep current. Enable separately only when needed.
// On THERMOMETER_C6_BOARD the same numbers work but land differently:
// GPIO17/16 are UART0 RX/TX = J5 pins 5/4 (probe there; mutually exclusive
// with a wired UART console — the primary console is USB-Serial-JTAG), and
// GPIO12 is USB D−, usable only with USB detached (true for any floor
// measurement anyway).
#ifdef PPK2_DEBUG
#define PPK2_PIN_CPU_ACTIVE 17
#define PPK2_PIN_DISPLAY    16
#define PPK2_CPU_ACTIVE_HIGH() gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 1)
#define PPK2_CPU_ACTIVE_LOW()  gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 0)
#define PPK2_DISPLAY_HIGH()    gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 1)
#define PPK2_DISPLAY_LOW()     gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 0)
#else
#define PPK2_CPU_ACTIVE_HIGH()
#define PPK2_CPU_ACTIVE_LOW()
#define PPK2_DISPLAY_HIGH()
#define PPK2_DISPLAY_LOW()
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
#define PPK2_PIN_ULP_ACTIVE 12
#endif
