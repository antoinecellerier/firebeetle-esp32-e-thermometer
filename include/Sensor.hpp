#pragma once

class Sensor
{
    public:
        virtual float GetTemperatureC() = 0;

        // ULP support — sensors override these if they support ULP polling.
        // Default: no ULP support.
        virtual bool SupportsUlp() { return false; }
        virtual void InitializeUlp() {}
        virtual bool ReadUlpTemperature(float *temp_out) { return false; }
};
