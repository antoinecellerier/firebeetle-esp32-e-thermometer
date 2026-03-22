#pragma once
#include "Sensor.hpp"
#include "local-secrets.h"

#include "DFRobot_BMP3XX.h"

#include "soc/soc_caps.h"

// ULP/LP core support: include compensation for raw ADC → °C conversion
#if (!defined(NO_ULP)) && (defined(SOC_ULP_FSM_SUPPORTED) || (defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED))
#define HAS_ULP_SUPPORT 1
#include "BMP390LCompensation.h"
#endif

class BMP390LSensor : public Sensor
{
    public:
        BMP390LSensor();

        float GetTemperatureC() override;

        bool SupportsUlp() override;
        void InitializeUlp() override;
        bool ReadUlpTemperature(float *temp_out) override;

    private:
        void Initialize();

        TwoWire _twoWire;
        DFRobot_BMP390L_I2C _sensor;

        bool _isInitialized = false;
};
