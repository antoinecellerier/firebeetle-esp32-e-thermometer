// LP core program for ESP32-C6
//
// Sensor implementations are in separate headers, selected at compile time.
// The LP core build does NOT inherit the main project's build_flags or include
// paths, so sensor selection uses a #define in this file (not local-secrets.h).
//
// Available modes:
//   LP_CORE_IDLE     — power measurement: no I2C, wakes main CPU every N loops
//   LP_CORE_BMP390L  — BMP390L temperature polling via LP I2C
//   LP_CORE_BMP58X   — BMP58x (BMP581/BMP585) temperature polling via LP I2C
//
// Uncomment exactly one:
//#define LP_CORE_IDLE
//#define LP_CORE_BMP390L
#define LP_CORE_BMP58X

#include <stdint.h>
#include "ulp_lp_core_utils.h"

// Shared variables — accessible from main CPU via ulp_ prefixed symbols
volatile uint32_t temp_raw_0 = 0;
volatile uint32_t temp_raw_1 = 0;
volatile uint32_t temp_raw_2 = 0;
volatile uint32_t prev_temp_msb = 0;   // BMP390L path (single-byte reference; TODO: byte-wrap bug)
volatile float    prev_temp_c = 0.0f;  // BMP58x path (full °C, no byte-wrap issues)
volatile uint32_t wake_reason = 0;     // 0=none, 1=temp change, 2=I2C error
volatile uint32_t sample_count = 0;    // reset by HP each wake
volatile uint32_t lp_wake_count = 0;   // cumulative; HP reads for lp/hp ratio diagnostic

#if defined(LP_CORE_IDLE)
#include "lp_core_idle.h"
#elif defined(LP_CORE_BMP390L)
#include "lp_core_bmp390l.h"
#elif defined(LP_CORE_BMP58X)
#include "lp_core_bmp58x.h"
#else
#error "No LP core mode selected — define LP_CORE_IDLE, LP_CORE_BMP390L, or LP_CORE_BMP58X"
#endif
