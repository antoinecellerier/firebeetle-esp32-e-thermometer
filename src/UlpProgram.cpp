// Shared ULP FSM utilities: I2C pin config, program start, RTC memory access.
// Sensor-specific programs are in UlpProgramBMP390L.cpp / UlpProgramBMP58x.cpp.

#include "UlpProgram.h"

#if !defined(NO_ULP) && defined(SOC_ULP_FSM_SUPPORTED)

#include "Arduino.h"
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


void ulp_check_data_overlap()
{
  // _rtc_force_slow_end is the linker-determined end of all RTC slow memory
  // sections (.rtc.data, .rtc.bss, .rtc.force_slow). ULP data must not overlap.
  extern uint32_t _rtc_force_slow_end;
  uintptr_t rtc_data_end   = (uintptr_t)&_rtc_force_slow_end;
  uintptr_t ulp_data_start = (uintptr_t)&RTC_SLOW_MEM[ULP_DATA_BASE];
  uintptr_t ulp_data_end   = (uintptr_t)&RTC_SLOW_MEM[ULP_DATA_BASE + ULP_VAR_COUNT];
  if (ulp_data_start < rtc_data_end)
  {
    LOGI("FATAL: ULP_DATA_BASE (word %d, 0x%08x-0x%08x) overlaps RTC data (ends 0x%08x). "
         "Increase ULP_DATA_BASE to at least %d.",
         ULP_DATA_BASE, (unsigned)ulp_data_start, (unsigned)ulp_data_end,
         (unsigned)rtc_data_end,
         (int)((&_rtc_force_slow_end - RTC_SLOW_MEM) + 1));
    abort();
  }
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
