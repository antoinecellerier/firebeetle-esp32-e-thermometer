#pragma once

// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

// TODO: Figure out how to get proper logging facilities working (probably after switching to platformio)
#ifndef DISABLE_SERIAL
#define LOGI(str, ...) Serial.printf(str "\n", ##__VA_ARGS__)
#else
#define LOGI(...)
#endif

// I2C pins — BMP390L must be wired to these
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
#define PPK2_CPU_ACTIVE_HIGH() digitalWrite(PPK2_PIN_CPU_ACTIVE, HIGH)
#define PPK2_CPU_ACTIVE_LOW()  digitalWrite(PPK2_PIN_CPU_ACTIVE, LOW)
#define PPK2_DISPLAY_HIGH()    digitalWrite(PPK2_PIN_DISPLAY, HIGH)
#define PPK2_DISPLAY_LOW()     digitalWrite(PPK2_PIN_DISPLAY, LOW)
#else
#define PPK2_CPU_ACTIVE_HIGH()
#define PPK2_CPU_ACTIVE_LOW()
#define PPK2_DISPLAY_HIGH()
#define PPK2_DISPLAY_LOW()
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
#define PPK2_PIN_ULP_ACTIVE 12
#endif
