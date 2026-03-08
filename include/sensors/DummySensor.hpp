#pragma once
#include "Sensor.hpp"

class DummySensor : public Sensor
{
    public:
        DummySensor();

        float GetTemperatureC();
};
