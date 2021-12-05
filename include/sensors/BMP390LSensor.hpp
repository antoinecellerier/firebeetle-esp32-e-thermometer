#pragma once
#include "Sensor.hpp"

#include "DFRobot_BMP3XX.h"

class BMP390LSensor : public Sensor
{
    public:
        BMP390LSensor();

        float GetTemperatureC();

    private:
        void Initialize();

        TwoWire _twoWire;
        DFRobot_BMP390L_I2C _sensor;

        bool _isInitialized = false;
};
