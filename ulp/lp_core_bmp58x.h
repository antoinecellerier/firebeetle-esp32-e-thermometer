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
#define TEMP_DELTA_THRESHOLD_C 0.1f

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
