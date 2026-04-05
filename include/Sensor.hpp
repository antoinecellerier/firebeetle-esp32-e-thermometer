#pragma once

// Sentinel value meaning "no valid previous temperature available".
// Used by ReadUlpTemperature to skip plausibility checks on first reading.
#define TEMP_NO_PREVIOUS (-999.0f)

class Sensor
{
    public:
        virtual float GetTemperatureC() = 0;

        // ULP support — sensors override these if they support ULP polling.
        // Default: no ULP support.
        virtual bool SupportsUlp() { return false; }
        virtual void InitializeUlp() {}
        virtual bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) { return false; }
};
