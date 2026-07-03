#pragma once
// Print base class for Adafruit_GFX / GxEPD2 diagnostics (same shape as the
// host-sim stub in tools/sim/stubs/Arduino.h).

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdarg>

class __FlashStringHelper;

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
  size_t print(const __FlashStringHelper *s) { return print((const char *)s); }
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
  size_t println(const __FlashStringHelper *s) { return println((const char *)s); }
  size_t println(int n, int base = 10) { return print(n, base) + println(); }
  size_t println(unsigned int n, int base = 10) { return print(n, base) + println(); }
  size_t println(long n, int base = 10) { return print(n, base) + println(); }
  size_t println(unsigned long n, int base = 10) { return print(n, base) + println(); }
  size_t println(double n, int digits = 2) { return print(n, digits) + println(); }
  int printf(const char *fmt, ...) __attribute__((format(printf, 2, 3))) {
    va_list args; va_start(args, fmt);
    char buf[512]; int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (len > 0) write((const uint8_t *)buf, len);
    return len;
  }
};
