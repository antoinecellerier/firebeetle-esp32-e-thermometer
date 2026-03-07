#pragma once

// ULP coprocessor program for BMP390L temperature polling
//
// The ULP wakes periodically, triggers a forced-mode measurement on the BMP390L
// via bit-bang I2C (HULP), reads the raw temperature bytes, and compares the middle byte
// (DATA_1, ~0.4°C resolution) against the previous reading. If the delta exceeds
// the threshold, it wakes the main CPU to update the display.
//
// I2C pins: GPIO0=SDA, GPIO4=SCL (bit-bang via HULP; EPD_CS moved to GPIO14/D6)

#include <stdint.h>
#include <stddef.h>
#include "common.h"

// ULP wakeup period in microseconds
#define ULP_WAKEUP_PERIOD_US (SLEEP_INTERVAL_S * 1000000ULL)

// Temperature delta threshold on DATA_1 byte (~0.4°C per count)
// 1 = wake on ~0.4°C change, 2 = ~0.8°C, etc.
#define ULP_TEMP_DELTA_THRESHOLD 20  // ~0.1°C (each DATA_1 count ≈ 0.005°C)

// In test mode (ULP_TEST_NO_I2C), wake main CPU every N ULP cycles
#ifndef ULP_TEST_WAKE_EVERY
#define ULP_TEST_WAKE_EVERY 3
#endif

// Fixed base address for ULP data variables in RTC_SLOW_MEM.
// Using a fixed address avoids label resolution issues with large bit-bang I2C subroutines.
// Must be past the end of the largest ULP program (~110 instructions).
#define ULP_DATA_BASE 200

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

// Initialise RTC I2C, build/load ULP program, and configure wakeup period.
// Must be called once from the main CPU before starting the ULP.
void ulp_configure_i2c_bitbang();
size_t ulp_build_and_load_program();
void ulp_start(size_t data_offset);

// Read/write ULP variables in RTC slow memory.
uint16_t ulp_read_var(size_t data_offset, enum ulp_var_offset var);
void ulp_write_var(size_t data_offset, enum ulp_var_offset var, uint16_t value);
