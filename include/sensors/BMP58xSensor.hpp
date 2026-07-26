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
        void InitializeUlp(bool cold_boot = true) override;
        void StopUlp() override;
        bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) override;

        // The single raw->°C funnel for every path, hence public and static:
        // the file-scope direct-read helper converts through it too.
        static float RawToTempC(uint8_t xlsb, uint8_t lsb, uint8_t msb);

    private:
        void Initialize();
        bool ReadRegister(uint8_t reg, uint8_t *buf, size_t len);
        bool WriteRegister(uint8_t reg, uint8_t value);

        I2cBus _i2c;

        bool _isInitialized = false;
        // Whether the part answered with a chip ID this session. Not RTC state on
        // purpose: it must be re-established after every deep sleep, since what it
        // certifies is that the sensor is on the bus *now*.
        bool _identified = false;
};
