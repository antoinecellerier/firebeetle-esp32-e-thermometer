#include "sensors/DS18B20Sensor.hpp"

#include "common.h"

// Don't use pin 12 / D13 for one wire as it resets the board if high on boot
#define ONE_WIRE   4 // D12

DS18B20Sensor::DS18B20Sensor()
:_oneWire(ONE_WIRE), _sensors(&_oneWire)
{}

void DS18B20Sensor::Initialize()
{
    if (_isInitialized)
        return;

    _sensors.begin();
    bool parasite = _sensors.isParasitePowerMode();
    LOGI("Parasitic power is: %d", (int)parasite);
    for (int count = 0; !parasite && count < 100; count++)
    {
        // Looks like parasite power detection is unreliable. Waiting a bit and trying again seems to fix it.
        delay(10);
        LOGI("Attempting to reinitialize to fix parasite power mode detection");
        _sensors.begin();
        parasite = _sensors.isParasitePowerMode();
        LOGI("Parasitic power is: %d", (int)parasite);
    }
    _sensors.setResolution(12);
    #define SLEEP_DURING_TEMPERATURE_READ
    #ifdef SLEEP_DURING_TEMPERATURE_READ
    // Set to non blocking to allow going to light sleep while we wait for temperature conversion in order to save power
    _sensors.setWaitForConversion(false);
    #endif

    _isInitialized = true;
}

float DS18B20Sensor::GetTemperatureC()
{
    Initialize();

    _sensors.requestTemperatures();
    #ifdef SLEEP_DURING_TEMPERATURE_READ
    LOGI("going to light sleep");
    esp_sleep_enable_timer_wakeup(_sensors.millisToWaitForConversion(_sensors.getResolution()) * 1000);
    // If the GPIO domain isn't kept on, the sensor returns an error (most likely isn't powered on during sleep)
    esp_sleep_pd_config(esp_sleep_pd_domain_t::ESP_PD_DOMAIN_RTC_PERIPH, esp_sleep_pd_option_t::ESP_PD_OPTION_ON);
    esp_light_sleep_start();
    esp_sleep_pd_config(esp_sleep_pd_domain_t::ESP_PD_DOMAIN_RTC_PERIPH, esp_sleep_pd_option_t::ESP_PD_OPTION_AUTO);
    LOGI("back from light sleep");
    #endif
    return _sensors.getTempCByIndex(0);
}