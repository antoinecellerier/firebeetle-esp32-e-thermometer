#pragma once
// AVR pgmspace compat (GxEPD2 includes <avr/pgmspace.h> directly, as does the
// real Arduino-ESP32 core via its own compat header). Flash is memory-mapped
// on ESP32 — all PROGMEM accessors collapse to direct reads (see Arduino.h).
#include "Arduino.h"

#ifndef pgm_read_float
#define pgm_read_float(addr) (*(const float *)(addr))
#endif
#ifndef memcpy_P
#define memcpy_P memcpy
#endif
#ifndef strcpy_P
#define strcpy_P strcpy
#endif
#ifndef strlen_P
#define strlen_P strlen
#endif
