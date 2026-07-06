#pragma once
#include "Sensor.hpp"
#include "app_common.h" // local-secrets.h + HAS_ULP_SUPPORT

#include "I2cBus.h"

class BMP58xSensor : public Sensor
{
    public:
        BMP58xSensor();

        float GetTemperatureC() override;

        bool SupportsUlp() override;
        void InitializeUlp() override;
        bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) override;

    private:
        void Initialize();
        bool ReadRegister(uint8_t reg, uint8_t *buf, size_t len);
        bool WriteRegister(uint8_t reg, uint8_t value);
        float RawToTempC(uint8_t xlsb, uint8_t lsb, uint8_t msb);

        I2cBus _i2c;

        bool _isInitialized = false;
};
