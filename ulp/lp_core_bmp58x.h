// LP core BMP58x (BMP581/BMP585) temperature polling via hardware LP I2C.
// BMP58x output is already compensated — no NVM calibration needed.
// OSR_CONFIG is written once by the main CPU in Initialize(); this loop only
// triggers forced-mode measurements.

#include "ulp_lp_core_i2c.h"

#define BMP58X_I2C_ADDR       0x47
#define BMP58X_REG_ODR_CONFIG 0x37
#define BMP58X_REG_TEMP_XLSB  0x1D

#define LP_I2C_TIMEOUT_CYCLES  5000
// Each DATA_1 count ≈ 0.004°C, so 25 ≈ 0.1°C
#define TEMP_DELTA_THRESHOLD   25

int main(void)
{
    esp_err_t ret;

    // 1. Trigger forced-mode measurement (pwr_mode = BMP5_POWERMODE_FORCED)
    uint8_t odr_cmd[2] = {BMP58X_REG_ODR_CONFIG, 0x02};
    ret = lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP58X_I2C_ADDR,
                                              odr_cmd, 2, LP_I2C_TIMEOUT_CYCLES);
    if (ret != ESP_OK) {
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
        wake_reason = 2;
        ulp_lp_core_wakeup_main_processor();
        return 0;
    }

    // 4. Store raw temperature
    temp_raw_0 = data[0];
    temp_raw_1 = data[1];
    temp_raw_2 = data[2];
    sample_count++;

    // 5. Delta comparison on DATA_1 byte (~0.004°C resolution per count)
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
