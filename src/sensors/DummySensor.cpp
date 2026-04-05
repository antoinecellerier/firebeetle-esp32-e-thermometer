#include "sensors/DummySensor.hpp"
#include "Arduino.h"

#if !defined(NO_ULP) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
#include "ulp_lp_core.h"
#include "ulp_main.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");
#endif

DummySensor::DummySensor()
{}

float DummySensor::GetTemperatureC()
{
    return 12.3;
}

#if !defined(NO_ULP) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED

bool DummySensor::SupportsUlp()
{
    return true;
}

void DummySensor::InitializeUlp()
{
    LOGI("Starting LP core (idle mode, no I2C)");
    uint32_t wakeup_us = (uint32_t)SLEEP_INTERVAL_S * 1000000U;
    ESP_ERROR_CHECK(ulp_lp_core_load_binary(ulp_main_bin_start,
                                            (ulp_main_bin_end - ulp_main_bin_start)));
    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER,
        .lp_timer_sleep_duration_us = wakeup_us,
    };
    ESP_ERROR_CHECK(ulp_lp_core_run(&cfg));
}

bool DummySensor::ReadUlpTemperature(float *temp_out, float previous_temp)
{
    uint32_t reason = ulp_wake_reason;
    ulp_wake_reason = 0;
    if (reason != 1) return false;
    // Return fake temperature based on raw value
    *temp_out = (ulp_temp_raw_1 == 0x80) ? 22.0f : 18.0f;
    LOGI("LP core dummy temp: %.1f (sample_count=%d)", *temp_out, (int)ulp_sample_count);
    return true;
}

#endif