#include "Arduino.h"
#include "SPI.h"

#include "driver/gpio.h"

SerialShim Serial;

void pinMode(uint8_t pin, uint8_t mode)
{
    gpio_config_t cfg = {};
    cfg.pin_bit_mask = 1ULL << pin;
    switch (mode)
    {
    case OUTPUT:
        cfg.mode = GPIO_MODE_OUTPUT;
        break;
    case INPUT_PULLUP:
        cfg.mode = GPIO_MODE_INPUT;
        cfg.pull_up_en = GPIO_PULLUP_ENABLE;
        break;
    case INPUT:
    default:
        cfg.mode = GPIO_MODE_INPUT;
        break;
    }
    gpio_config(&cfg);
}

void digitalWrite(uint8_t pin, uint8_t val)
{
    // Buffered SPI bytes must land before any pin change — GxEPD2 toggles
    // DC/CS via GPIO between transfer() calls (see SPIClass::transfer)
    SPI.flushPending();
    gpio_set_level((gpio_num_t)pin, val);
}

int digitalRead(uint8_t pin)
{
    SPI.flushPending(); // e.g. BUSY polls must observe all written data
    return gpio_get_level((gpio_num_t)pin);
}
