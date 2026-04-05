#pragma once
#include "Sensor.hpp"
#include "common.h"
#include "soc/soc_caps.h"

class DummySensor : public Sensor
{
    public:
        DummySensor();

        float GetTemperatureC();

#if !defined(NO_ULP) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
        bool SupportsUlp() override;
        void InitializeUlp() override;
        bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) override;
#endif
};
