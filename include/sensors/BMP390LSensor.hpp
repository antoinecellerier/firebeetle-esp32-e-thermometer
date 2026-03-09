#pragma once
#include "Sensor.hpp"

#include "DFRobot_BMP3XX.h"

#ifndef NO_ULP
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
