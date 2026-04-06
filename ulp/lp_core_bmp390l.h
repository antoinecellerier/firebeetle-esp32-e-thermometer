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
