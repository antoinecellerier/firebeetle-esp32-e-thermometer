#pragma once

// Standalone BMP390L temperature compensation
//
// The compensation formula and calibration coefficient quantization in this file
// are derived from the DFRobot_BMP3XX library:
//   https://github.com/DFRobot/DFRobot_BMP3XX
//   Copyright (c) 2010 DFRobot Co.Ltd (http://www.dfrobot.com)
//   Licensed under the MIT License
//   Author: qsjhyy (yihuan.huang@dfrobot.com)
//
// Specifically, the quantization factors (lines 267-274 of DFRobot_BMP3XX.cpp)
// and the temperature compensation formula (lines 313-326) were extracted and
// simplified for use without the full library, so the main CPU can convert raw
// ADC values read by the ULP from RTC memory into °C.

#include <stdint.h>

class I2cBus;  // forward declare

#define BMP390L_I2C_ADDRESS 0x77

// Quantized calibration coefficients for temperature compensation
// Stored in RTC memory so they persist across deep sleep cycles
struct BMP390LCalib {
  float parT1;
  float parT2;
  float parT3;
};

// Read raw calibration bytes from BMP390L and quantize into float coefficients.
// Must be called with the I2C bus already initialised.
bool bmp390l_read_calibration(I2cBus &bus, struct BMP390LCalib *calib);

// Compensate a raw 24-bit temperature ADC value to °C.
// raw_0, raw_1, raw_2 are the three bytes from DATA_0 (0x07), DATA_1, DATA_2.
float bmp390l_compensate_temperature(const struct BMP390LCalib *calib,
                                     uint8_t raw_0, uint8_t raw_1, uint8_t raw_2);

// Trigger a forced-mode conversion and read compensated temperature via raw I2C.
// Caller must have called bus.begin() beforehand.  Returns false on I2C error.
bool bmp390l_direct_read(I2cBus &bus, const struct BMP390LCalib *calib, float *temp_out);
