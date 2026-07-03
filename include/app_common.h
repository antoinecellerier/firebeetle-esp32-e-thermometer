#pragma once

// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

// ESP_PLATFORM is defined for device builds (both Arduino-ESP32 and pure
// ESP-IDF); the host simulator compiles this header without it.
#ifdef ESP_PLATFORM
#include <stdint.h>
#include <stdio.h>
#include "soc/soc_caps.h" // SOC_ULP_FSM_SUPPORTED / SOC_LP_CORE_SUPPORTED guards
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"

// Framework-agnostic time helpers (IDF APIs)
static inline uint32_t ms_now(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static inline void sleep_ms(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }

// Wakeup cause, collapsed to the single value this app branches on.
// IDF 6 deprecated the scalar API in favor of a bitmap; only ULP and TIMER
// wake sources are ever armed here, so priority-picking them is lossless.
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
  return ESP_SLEEP_WAKEUP_UNDEFINED;
#else
  return esp_sleep_get_wakeup_cause();
#endif
}

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

// PPK2 debug pins — wire to PPK2 digital channels for power trace correlation
// D10/GPIO17 → PPK2 D0: HIGH while main CPU is awake
// D11/GPIO16 → PPK2 D1: HIGH during display refresh
// D13/GPIO12 → PPK2 D2: HIGH while ULP is executing (RTC GPIO, toggled by ULP itself)
//   ⚠ PPK2_DEBUG_ULP_GPIO requires RTC peripherals to stay powered during deep sleep,
//     which increases sleep current. Enable separately only when needed.
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
