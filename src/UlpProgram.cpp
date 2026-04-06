// Shared ULP FSM utilities: I2C pin config, program start, RTC memory access.
// Sensor-specific programs are in UlpProgramBMP390L.cpp / UlpProgramBMP58x.cpp.

#include "UlpProgram.h"

#if !defined(NO_ULP) && defined(SOC_ULP_FSM_SUPPORTED)

#include "esp32/ulp.h"
#include "hulp.h"

#define I2C_BB_SCL  ((gpio_num_t)I2C_SCL_PIN)
#define I2C_BB_SDA  ((gpio_num_t)I2C_SDA_PIN)


// Configure GPIO pins for bit-bang I2C (no hardware RTC I2C peripheral).
void ulp_configure_i2c_bitbang()
{
  hulp_configure_pin(I2C_BB_SCL, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0);
  hulp_configure_pin(I2C_BB_SDA, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0);
  hulp_peripherals_on();
}


void ulp_start()
{
  ulp_set_wakeup_period(0, ULP_WAKEUP_PERIOD_US);
  ESP_ERROR_CHECK(ulp_run(0));
}


uint16_t ulp_read_var(size_t data_offset, enum ulp_var_offset var)
{
  return RTC_SLOW_MEM[data_offset + var] & 0xFFFF;
}

void ulp_write_var(size_t data_offset, enum ulp_var_offset var, uint16_t value)
{
  RTC_SLOW_MEM[data_offset + var] = value;
}

#endif
