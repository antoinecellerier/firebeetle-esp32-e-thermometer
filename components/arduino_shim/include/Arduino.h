#pragma once
// Minimal Arduino compatibility layer over ESP-IDF — just enough surface for
// the vendored GxEPD2 + Adafruit_GFX components (see components/gxepd2,
// components/adafruit_gfx). Grown from tools/sim/stubs/Arduino.h, which
// proved the Adafruit_GFX surface; this adds real GPIO/timing on IDF drivers.
//
// Application code must NOT include this — it uses IDF APIs directly
// (app_common.h helpers). Measured consumer surface (GxEPD2 base + panels):
// pinMode/digitalWrite/digitalRead, delay/delayMicroseconds/millis/micros,
// yield, Serial.print* (diagnostics, off by default), SPI byte transfers,
// PROGMEM/pgm_read_*.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <cmath>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"

#define ARDUINO 10812

// --- GPIO ---
#define LOW  0x0
#define HIGH 0x1
#define INPUT        0x01
#define OUTPUT       0x03
#define INPUT_PULLUP 0x05

void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t val);
int digitalRead(uint8_t pin);

// --- Timing ---
static inline unsigned long millis() { return (unsigned long)(esp_timer_get_time() / 1000); }
static inline unsigned long micros() { return (unsigned long)esp_timer_get_time(); }
static inline void delay(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }
static inline void delayMicroseconds(uint32_t us) { esp_rom_delay_us(us); }
// GxEPD2 busy-waits call yield(); give the idle task (and TWDT) a chance
static inline void yield() { vTaskDelay(1); }

// --- PROGMEM (flash is memory-mapped on ESP32 — direct access) ---
#define PROGMEM
#define pgm_read_byte(addr)    (*(const uint8_t *)(addr))
#define pgm_read_word(addr)    (*(const uint16_t *)(addr))
#define pgm_read_dword(addr)   (*(const uint32_t *)(addr))
// (no pgm_read_pointer here — Adafruit_GFX.cpp defines its own; a second
// definition is a redefinition error under IDF 6's warnings-as-errors)
#define PSTR(s) (s)

class __FlashStringHelper;
#define F(string_literal) (reinterpret_cast<const __FlashStringHelper *>(PSTR(string_literal)))

// --- Types & helper macros (match Arduino core macro behavior) ---
typedef bool boolean;
typedef uint8_t byte;

#ifndef min
#define min(a,b) ((a)<(b)?(a):(b))
#endif
#ifndef max
#define max(a,b) ((a)>(b)?(a):(b))
#endif
#ifndef abs
#define abs(x) ((x)>0?(x):-(x))
#endif
#ifndef constrain
#define constrain(amt,low,high) ((amt)<(low)?(low):((amt)>(high)?(high):(amt)))
#endif
#ifndef PI
#define PI 3.1415926535897932384626433832795
#endif
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define radians(deg) ((deg)*DEG_TO_RAD)
#define degrees(rad) ((rad)*RAD_TO_DEG)
#define sq(x) ((x)*(x))
#define DEC 10
#define HEX 16

#include "Print.h"

// String stub (referenced by Adafruit_GFX.h signatures, not used at runtime)
class String {
  const char *_s;
public:
  String() : _s("") {}
  String(const char *s) : _s(s ? s : "") {}
  const char *c_str() const { return _s; }
  size_t length() const { return strlen(_s); }
  char charAt(size_t i) const { return _s[i]; }
};

// --- Serial (stdout-backed; GxEPD2 uses it only for gated diagnostics) ---
class SerialShim : public Print {
public:
  void begin(unsigned long baud) { (void)baud; }
  void flush() { fflush(stdout); }
  explicit operator bool() const { return true; }
  size_t write(uint8_t c) override { putchar(c); return 1; }
  using Print::write;
};
extern SerialShim Serial;
