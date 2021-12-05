#pragma once
#include "Sensor.hpp"

#include "OneWire.h"
#include "DallasTemperature.h"

class DS18B20Sensor : public Sensor
{
    public:
        DS18B20Sensor();

        float GetTemperatureC();

    private:
        void Initialize();

        OneWire _oneWire;
        DallasTemperature _sensors;

        bool _isInitialized = false;
};
