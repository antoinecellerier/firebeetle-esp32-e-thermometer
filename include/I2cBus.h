#pragma once

// Thin I2C master wrapper over the ESP-IDF i2c_master driver (driver/i2c_master.h).
// Replaces Arduino TwoWire so sensor code compiles under both Arduino-ESP32 3.x
// (which ships IDF 5.x) and pure ESP-IDF.

#include <stdint.h>
#include <stddef.h>
#include "driver/i2c_master.h"

class I2cBus
{
public:
    // Default 100 kHz matches the previous Arduino Wire default.
    bool begin(int sda, int scl, uint32_t hz = 100000);
    void end();

    bool writeReg(uint8_t addr, uint8_t reg, uint8_t value);
    // Write register address, then read len bytes (repeated start)
    bool readReg(uint8_t addr, uint8_t reg, uint8_t *buf, size_t len);

private:
    i2c_master_dev_handle_t dev(uint8_t addr);

    i2c_master_bus_handle_t _bus = nullptr;
    i2c_master_dev_handle_t _dev = nullptr;
    uint8_t _devAddr = 0;
    uint32_t _hz = 100000;
};

// I2C bus recovery: 9 SCL clocks + STOP condition, bit-banged via the GPIO
// driver. Releasing the bus (end()) may leave a slave holding SDA low.
void i2c_bus_recover(int sda_pin, int scl_pin);
