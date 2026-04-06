#pragma once
#include "Sensor.hpp"
#include "local-secrets.h"

#include "Wire.h"

#include "soc/soc_caps.h"

// ULP/LP core support — no compensation needed for BMP58x (output is already in °C)
#if (!defined(NO_ULP)) && (defined(SOC_ULP_FSM_SUPPORTED) || (defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED))
#define HAS_ULP_SUPPORT 1
#endif

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

        TwoWire _twoWire;

        bool _isInitialized = false;
};
