#pragma once
// Minimal Arduino stubs for compiling Adafruit_GFX on the host.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <cmath>
#include <algorithm>

// Arduino version — needed by Adafruit_GFX.h
#define ARDUINO 200

// Print class — base for Adafruit_GFX text rendering
class Print {
public:
  virtual ~Print() {}
  virtual size_t write(uint8_t c) = 0;
  virtual size_t write(const uint8_t *buffer, size_t size) {
    size_t n = 0;
    while (size--) n += write(*buffer++);
    return n;
  }
  size_t write(const char *str) {
    return write((const uint8_t *)str, strlen(str));
  }
  size_t print(const char *s) { return write((const uint8_t *)s, strlen(s)); }
  size_t print(char c) { return write((uint8_t)c); }
  size_t print(int n, int base = 10) {
    char buf[34]; snprintf(buf, sizeof(buf), base == 16 ? "%x" : "%d", n);
    return print(buf);
  }
  size_t print(unsigned int n, int base = 10) {
    char buf[34]; snprintf(buf, sizeof(buf), base == 16 ? "%x" : "%u", n);
    return print(buf);
  }
  size_t print(long n, int base = 10) {
    char buf[34]; snprintf(buf, sizeof(buf), base == 16 ? "%lx" : "%ld", n);
    return print(buf);
  }
  size_t print(unsigned long n, int base = 10) {
    char buf[34]; snprintf(buf, sizeof(buf), base == 16 ? "%lx" : "%lu", n);
    return print(buf);
  }
  size_t print(double n, int digits = 2) {
    char buf[64]; snprintf(buf, sizeof(buf), "%.*f", digits, n);
    return print(buf);
  }
  size_t println() { return print("\r\n"); }
  size_t println(const char *s) { return print(s) + println(); }
  int printf(const char *fmt, ...) __attribute__((format(printf, 2, 3))) {
    va_list args; va_start(args, fmt);
    char buf[512]; int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (len > 0) write((const uint8_t *)buf, len);
    return len;
  }
};

// PROGMEM stubs
#define PROGMEM
#define pgm_read_byte(addr)    (*(const uint8_t *)(addr))
#define pgm_read_word(addr)    (*(const uint16_t *)(addr))
#define pgm_read_dword(addr)   (*(const uint32_t *)(addr))
#define pgm_read_pointer(addr) (*(const void *const *)(addr))
#define PSTR(s) (s)

// __FlashStringHelper stub
class __FlashStringHelper;
#define F(string_literal) (reinterpret_cast<const __FlashStringHelper *>(PSTR(string_literal)))

// Types
typedef bool boolean;
typedef uint8_t byte;

// Arduino macros
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
#define DEC 10
#define HEX 16

// String class stub (not actually used but Adafruit_GFX.h references it)
class String {
  const char *_s;
public:
  String() : _s("") {}
  String(const char *s) : _s(s ? s : "") {}
  const char *c_str() const { return _s; }
  size_t length() const { return strlen(_s); }
  char charAt(size_t i) const { return _s[i]; }
};
