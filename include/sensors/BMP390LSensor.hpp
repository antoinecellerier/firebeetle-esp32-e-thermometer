#pragma once
#include "Sensor.hpp"
#include "local-secrets.h"

#include "I2cBus.h"
#include "BMP390LCompensation.h"

#include "soc/soc_caps.h"

#if (!defined(NO_ULP)) && (defined(SOC_ULP_FSM_SUPPORTED) || (defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED))
#define HAS_ULP_SUPPORT 1
#endif

class BMP390LSensor : public Sensor
{
    public:
        BMP390LSensor();

        float GetTemperatureC() override;

        bool SupportsUlp() override;
        void InitializeUlp() override;
        bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) override;

    private:
        void Initialize();

        I2cBus _i2c;

        bool _isInitialized = false;
};
