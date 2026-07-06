#pragma once
#include "Sensor.hpp"
#include "app_common.h" // local-secrets.h + HAS_ULP_SUPPORT

#include "I2cBus.h"
#include "BMP390LCompensation.h"

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
