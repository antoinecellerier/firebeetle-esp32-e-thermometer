// LP core program for ESP32-C6
//
// Two modes selected at compile time:
//   LP_CORE_IDLE — power measurement: no I2C, wakes main CPU every N loops
//   Default      — BMP390L temperature polling via LP I2C
//
// LP core main() returns after each iteration. The LP core startup code
// re-arms the LP timer and halts. This matches the official ESP-IDF
// lp_adc example pattern (ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER).

// Guard: this file is for LP core targets only (C6, C5, P4).
// The lib-recompile path (espidf.py) tries to compile ulp/ files for all
// targets — skip everything on non-LP-core MCUs like ESP32.
#include "soc/soc_caps.h"
#if SOC_LP_CORE_SUPPORTED

// Toggle for testing without BMP390L hardware
#define LP_CORE_IDLE

#include <stdint.h>
#include "ulp_lp_core_utils.h"

// Shared variables — accessible from main CPU via ulp_ prefixed symbols
volatile uint32_t temp_raw_0 = 0;
volatile uint32_t temp_raw_1 = 0;
volatile uint32_t temp_raw_2 = 0;
volatile uint32_t prev_temp_msb = 0;
volatile uint32_t wake_reason = 0;    // 0=none, 1=temp change, 2=I2C error
volatile uint32_t sample_count = 0;

#ifdef LP_CORE_IDLE

// ---- Idle mode: simulate BMP390L pattern without hardware ----

#define WAKE_EVERY 6

int main(void)
{
    sample_count++;

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

#else

// ---- BMP390L mode: real I2C temperature polling ----

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

    // 1. Trigger forced-mode measurement
    uint8_t pwr_ctrl_cmd[2] = {BMP390L_REG_PWR_CTRL, BMP390L_FORCED_MODE};
    ret = lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP390L_I2C_ADDR,
                                              pwr_ctrl_cmd, 2, LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
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
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 4. Store raw temperature
    temp_raw_0 = data[0];
    temp_raw_1 = data[1];
    temp_raw_2 = data[2];
    sample_count++;

    // 5. Delta comparison on DATA_1 byte (~0.005°C resolution per count)
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

#endif // LP_CORE_IDLE

#endif // SOC_LP_CORE_SUPPORTED
