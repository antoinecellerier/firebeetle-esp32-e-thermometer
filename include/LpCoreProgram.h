#pragma once

// LP core loader for ESP32-C6.
//
// Since pioarduino's pre-compiled Arduino libraries don't include the ULP
// component (CONFIG_ULP_COPROC_ENABLED is not set), we reimplement the
// essential loader functions using the available LL inline functions and
// HAL APIs.

#include "common.h"
#include "soc/soc_caps.h"

#if defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && !defined(NO_ULP)

#include <stdint.h>
#include <stddef.h>

// LP SRAM reservation — must match ulp/sdkconfig.h
#define LP_CORE_RESERVE_MEM  8192
#define LP_CORE_SHARED_MEM   16

// Initialize LP I2C peripheral from the main CPU.
// Must be called before loading/starting the LP core.
void lp_core_i2c_setup();

// Load LP core binary into LP SRAM.
void lp_core_load_binary(const uint8_t *bin, size_t size);

// Configure and start the LP core with LP timer wakeup.
// LP core main() returns after each iteration; LP timer re-arms automatically.
void lp_core_start(uint64_t wakeup_period_us);

// Stop the LP core.
void lp_core_stop();

#endif
