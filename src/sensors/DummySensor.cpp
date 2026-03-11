#include "sensors/DummySensor.hpp"
#include "Arduino.h"

#if !defined(NO_ULP) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
#include "LpCoreProgram.h"
#include "lp_core_main.h"
#include "lp_core_main_bin.h"
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
    lp_core_load_binary(lp_core_main_bin, lp_core_main_bin_length);
    lp_core_start((uint64_t)SLEEP_INTERVAL_S * 1000000ULL);
}

bool DummySensor::ReadUlpTemperature(float *temp_out)
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