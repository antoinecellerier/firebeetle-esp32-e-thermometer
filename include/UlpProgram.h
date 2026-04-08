#pragma once

// ULP coprocessor program for BMP390L / BMP58x temperature polling
//
// The ULP wakes periodically, triggers a forced-mode measurement on the sensor
// via bit-bang I2C (HULP), reads the raw temperature bytes, and compares the middle byte
// (DATA_1) against the previous reading. If the delta exceeds the threshold, it wakes
// the main CPU to update the display.
//
// Sensor selection: USE_BMP390L or USE_BMP58x (compile-time, from local-secrets.h)
// I2C pins: GPIO0=SDA, GPIO4=SCL (bit-bang via HULP; EPD_CS moved to GPIO14/D6)

#include "common.h"
#include "soc/soc_caps.h"

#if !defined(NO_ULP) && defined(SOC_ULP_FSM_SUPPORTED)
#include <stdint.h>
#include <stddef.h>

// ULP wakeup period in microseconds
#define ULP_WAKEUP_PERIOD_US (SLEEP_INTERVAL_S * 1000000ULL)

// Temperature delta threshold on DATA_1 byte (~0.4°C per count)
// 1 = wake on ~0.4°C change, 2 = ~0.8°C, etc.
#define ULP_TEMP_DELTA_THRESHOLD 20  // ~0.1°C (each DATA_1 count ≈ 0.005°C)

// In test mode (ULP_TEST_NO_I2C), wake main CPU every N ULP cycles
#ifndef ULP_TEST_WAKE_EVERY
#define ULP_TEST_WAKE_EVERY 3
#endif

// Fixed base address for ULP data variables in RTC_SLOW_MEM (32-bit word offset).
// Using a fixed address avoids label resolution issues with large bit-bang I2C subroutines.
// Must be past BOTH the ULP program (~110 words) AND the .rtc.data section
// (RTC_DATA_ATTR variables), which share the same 8KB physical memory.
// Current .rtc.data ends at word ~1628 (check firmware.map after layout changes).
#define ULP_DATA_BASE 1800

// RTC slow memory offsets for shared variables (in 32-bit words from ULP_DATA_BASE)
// These are written by the ULP and read by the main CPU after wakeup.
enum ulp_var_offset {
  ULP_VAR_TEMP_0 = 0,       // raw temp byte 0 (bits [7:0])
  ULP_VAR_TEMP_1,           // raw temp byte 1 (bits [15:8])
  ULP_VAR_TEMP_2,           // raw temp byte 2 (bits [23:16])
  ULP_VAR_PREV_TEMP_MSB,    // previous DATA_1 for delta comparison
  ULP_VAR_WAKE_REASON,      // 0=none, 1=temp change, 2=I2C error
  ULP_VAR_SAMPLE_COUNT,     // number of ULP measurement cycles
  ULP_VAR_COUNT             // total number of variables
};

// Verify ULP data area doesn't overlap RTC slow memory variables (they share
// the same 8KB). Uses the linker symbol _rtc_force_slow_end. Aborts on overlap.
void ulp_check_data_overlap();

// Initialise I2C, build/load ULP program, and start ULP with configured wakeup period.
// Must be called once from the main CPU before entering deep sleep.
void ulp_configure_i2c_bitbang();
void ulp_build_and_load_program();
void ulp_start();

// Read/write ULP variables in RTC slow memory.
uint16_t ulp_read_var(size_t data_offset, enum ulp_var_offset var);
void ulp_write_var(size_t data_offset, enum ulp_var_offset var, uint16_t value);

#endif
