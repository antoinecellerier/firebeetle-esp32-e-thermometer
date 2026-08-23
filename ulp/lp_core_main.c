// LP core program for ESP32-C6
//
// __riscv guard: PlatformIO's espidf builder feeds every file in ulp/ to the
// active ULP toolchain. On the ESP32-E that is the FSM assembler (HULP builds
// its program at runtime instead — see src/UlpProgram*.cpp), so this file must
// preprocess to nothing there.
#ifdef __riscv
// Sensor implementations are in separate headers, selected at compile time.
// The LP core build does NOT inherit the main project's build_flags, but a
// relative #include reaches the generated rig selector, so the mode derives
// from the same USE_* the HP build uses — they can't disagree. The rig header
// rather than device-config.h: the sensor is all this needs, and it keeps the
// WiFi credentials out of the LP translation unit.
//
// Modes:
//   LP_CORE_IDLE     — power measurement: no I2C, wakes main CPU every N loops
//   LP_CORE_BMP390L  — BMP390L temperature polling via LP I2C
//   LP_CORE_BMP58X   — BMP58x (BMP581/BMP585) temperature polling via LP I2C
//
// Uncomment to override the sensor selection for power measurements:
//#define LP_CORE_IDLE

#include "../include/generated/rig_config.h"
#ifndef LP_CORE_IDLE
#if defined(USE_BMP58x)
#define LP_CORE_BMP58X
#elif defined(USE_BMP390L)
#define LP_CORE_BMP390L
#else
#define LP_CORE_IDLE // no ULP-capable sensor selected; binary embedded but never loaded
#endif
#endif

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
volatile uint32_t lp_error_count = 0;  // cumulative I2C / sensor failures
volatile int32_t  last_lp_error = 0;   // most recent esp_err_t from a failed LP op
// Identifies which step of the LP routine failed (0 = none yet):
//   1 = trigger / command write   2 = data read
volatile uint32_t last_lp_op    = 0;

// The three sensor programs live inline below rather than in ulp/lp_core_*.h.
// They are not headers in any useful sense — each is one int main() with a
// single includer — and as headers they were invisible to the build: the LP
// sub-build's object is keyed on this file's content, so editing one of them
// rebuilt nothing and the previously built ulp_main.bin was embedded again.
// Measured 2026-08-23, after an experiment arm was flashed with the wrong wake
// cadence while the panel badge, the ULP word count and the baked git hash all
// reported success. Keeping them here means a sensor edit changes this file.
//
// They also all reach into the shared state defined above, so splitting them
// into real .c files would need a header of extern declarations — which would
// be stale-able in precisely the same way. See .claude/rules/ulp.md.

#if defined(LP_CORE_IDLE)

// LP core idle mode: no I2C, wakes main CPU every N loops.
// Used for power measurement testing without sensor hardware.

#define WAKE_EVERY 6

int main(void)
{
    sample_count++;
    lp_wake_count++;

    // Simulate sensor read time (~7ms like BMP390L)
    ulp_lp_core_delay_us(7000);

    // Wake main CPU every N loops
    if ((sample_count % WAKE_EVERY) == 0) {
        // Alternate fake temperature to trigger delta detection
        temp_raw_1 = (sample_count / WAKE_EVERY) & 1 ? 0x80 : 0x60;
        wake_reason = 1;
        ulp_lp_core_wakeup_main_processor();
    }

    return 0;
}

#elif defined(LP_CORE_BMP390L)

// LP core BMP390L temperature polling via hardware LP I2C.
// Raw temperature bytes require compensation on the main CPU.

#include "ulp_lp_core_i2c.h"

#define BMP390L_I2C_ADDR     0x77
#define BMP390L_REG_PWR_CTRL 0x1B
#define BMP390L_REG_TEMP_0   0x07
#define BMP390L_FORCED_MODE  0x13

#define LP_I2C_TIMEOUT_CYCLES  5000
#define TEMP_DELTA_THRESHOLD   20   // ~0.1°C (each DATA_1 count ≈ 0.005°C)

int main(void)
{
    esp_err_t ret;
    lp_wake_count++;

    // 1. Trigger forced-mode measurement
    uint8_t pwr_ctrl_cmd[2] = {BMP390L_REG_PWR_CTRL, BMP390L_FORCED_MODE};
    ret = lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP390L_I2C_ADDR,
                                              pwr_ctrl_cmd, 2, LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
        last_lp_error = ret;
        last_lp_op = 1;  // trigger write
        lp_error_count++;
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 2. Wait ~7ms for conversion
    ulp_lp_core_delay_us(7000);

    // 3. Read 3 raw temperature bytes (DATA_0, DATA_1, DATA_2 are contiguous)
    uint8_t reg_addr = BMP390L_REG_TEMP_0;
    uint8_t data[3];
    ret = lp_core_i2c_master_write_read_device(LP_I2C_NUM_0, BMP390L_I2C_ADDR,
                                                &reg_addr, 1, data, 3,
                                                LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
        last_lp_error = ret;
        last_lp_op = 2;  // data read
        lp_error_count++;
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 4. Store raw temperature
    temp_raw_0 = data[0];
    temp_raw_1 = data[1];
    temp_raw_2 = data[2];
    sample_count++;

    // 5. Delta comparison on DATA_1 byte (~0.005°C resolution per count).
    // TODO: byte-wise compare wraps at ~1.28°C intervals. BMP390L raw needs
    // compensation before comparing in °C (unlike BMP58x). Fix once BMP390L
    // is re-enabled on C6.
    uint32_t current_msb = data[1];
    int32_t delta = (int32_t)current_msb - (int32_t)prev_temp_msb;
    if (delta < 0) delta = -delta;

    if (delta >= TEMP_DELTA_THRESHOLD) {
        prev_temp_msb = current_msb;
        wake_reason = 1;
        ulp_lp_core_wakeup_main_processor();
    }

    return 0;
}

#elif defined(LP_CORE_BMP58X)

// LP core BMP58x (BMP581/BMP585) temperature polling via hardware LP I2C.
// BMP58x output is already compensated — no NVM calibration needed.
// OSR_CONFIG is written once by the main CPU in Initialize(); this loop only
// triggers forced-mode measurements.

#include "ulp_lp_core_i2c.h"

#define BMP58X_I2C_ADDR       0x47
#define BMP58X_REG_ODR_CONFIG 0x37
#define BMP58X_REG_TEMP_XLSB  0x1D

#define LP_I2C_TIMEOUT_CYCLES  5000
// Wake HP when temperature has moved this far from the last reference.
// Overridable so a bench build can decouple the wake cadence from the room: 0
// wakes on every poll (the LP-core counterpart of ULP_ALWAYS_WAKE), a large
// value never wakes on delta and leaves the safety net as the only wake source.
#ifndef TEMP_DELTA_THRESHOLD_C
#define TEMP_DELTA_THRESHOLD_C 0.1f
#endif

int main(void)
{
    esp_err_t ret;

    // Counter reflects every wake attempt, so it increments even when an I2C
    // failure later short-circuits to wake_reason = 2.
    lp_wake_count++;

    // 1. Trigger forced-mode measurement (pwr_mode = BMP5_POWERMODE_FORCED)
    uint8_t odr_cmd[2] = {BMP58X_REG_ODR_CONFIG, 0x02};
    ret = lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP58X_I2C_ADDR,
                                              odr_cmd, 2, LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
        last_lp_error = ret;
        last_lp_op = 1;  // trigger write
        lp_error_count++;
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 2. Wait ~2ms for conversion (1x OSR, ~1.6ms typical)
    ulp_lp_core_delay_us(3000);

    // 3. Read 3 temperature bytes (XLSB, LSB, MSB are contiguous from 0x1D)
    uint8_t reg_addr = BMP58X_REG_TEMP_XLSB;
    uint8_t data[3];
    ret = lp_core_i2c_master_write_read_device(LP_I2C_NUM_0, BMP58X_I2C_ADDR,
                                                &reg_addr, 1, data, 3,
                                                LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
        last_lp_error = ret;
        last_lp_op = 2;  // data read
        lp_error_count++;
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 4. Store raw temperature
    temp_raw_0 = data[0];
    temp_raw_1 = data[1];
    temp_raw_2 = data[2];
    sample_count++;

    // 5. Delta comparison in °C. BMP58x output is already compensated:
    // 24-bit signed, 1/65536 °C per LSB. Avoid byte-wise compare (wraps at
    // every whole-degree boundary and spuriously wakes HP).
    int32_t raw = ((int32_t)data[2] << 16) | ((int32_t)data[1] << 8) | data[0];
    if (raw & 0x800000) raw |= 0xFF000000;  // sign-extend 24→32
    float current_c = (float)raw / 65536.0f;

    float delta = current_c - prev_temp_c;
    if (delta < 0.0f) delta = -delta;

    if (delta >= TEMP_DELTA_THRESHOLD_C) {
        prev_temp_c = current_c;
        wake_reason = 1;
        ulp_lp_core_wakeup_main_processor();
    }

    return 0;
}

#else

#error "No LP core mode selected — define LP_CORE_IDLE, LP_CORE_BMP390L, or LP_CORE_BMP58X"

#endif

#endif // __riscv
