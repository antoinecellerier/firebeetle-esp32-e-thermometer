// Compensation formula and calibration coefficient quantization derived from:
//   DFRobot_BMP3XX library — https://github.com/DFRobot/DFRobot_BMP3XX
//   Copyright (c) 2010 DFRobot Co.Ltd (http://www.dfrobot.com)
//   Licensed under the MIT License
// See DFRobot_BMP3XX.cpp lines 267-274 (quantization) and 313-326 (compensation).

#include "BMP390LCompensation.h"

#include <math.h>
#include "I2cBus.h"
#include "Sensor.hpp"
#include "app_common.h"

#define BMP390L_CALIB_REG_ADDR 0x31
#define BMP390L_CALIB_DATA_LEN 21


bool bmp390l_read_calibration(I2cBus &bus, struct BMP390LCalib *calib)
{
  uint8_t regData[BMP390L_CALIB_DATA_LEN];
  if (!bus.readReg(BMP390L_I2C_ADDRESS, BMP390L_CALIB_REG_ADDR, regData, BMP390L_CALIB_DATA_LEN))
    return false;

  // Quantize temperature coefficients (same formula as DFRobot_BMP3XX.cpp lines 267-274)
  uint16_t rawT1 = (uint16_t)regData[1] << 8 | regData[0];
  uint16_t rawT2 = (uint16_t)regData[3] << 8 | regData[2];
  int8_t   rawT3 = (int8_t)regData[4];

  calib->parT1 = (float)rawT1 / powf(2.0f, -8.0f);  // = rawT1 * 256
  calib->parT2 = (float)rawT2 / powf(2.0f, 30.0f);
  calib->parT3 = (float)rawT3 / powf(2.0f, 48.0f);

  return true;
}


// Every path compensates here — direct read, ULP FSM and LP core — so this is the
// one place that has to recognise a raw code no live sensor produces. Returning the
// sentinel lets the plausibility gate the callers already apply reject it, instead
// of each path needing its own copy of the test.
float bmp390l_compensate_temperature(const struct BMP390LCalib *calib,
                                     uint8_t raw_0, uint8_t raw_1, uint8_t raw_2)
{
  uint32_t uncomp_temp = (uint32_t)raw_0 | ((uint32_t)raw_1 << 8) | ((uint32_t)raw_2 << 16);
  if (TEMP_RAW24_IS_BUS_ARTIFACT(uncomp_temp))
    return TEMP_NO_PREVIOUS;

  // With a zeroed calibration block every term below multiplies out to exactly
  // 0.0 C for any raw code — a plausible room temperature that no downstream gate
  // can distinguish from a real one. parT1 is the sentinel the callers already use
  // for "calibration not read yet" (bmp390l_calib is RTC_DATA_ATTR, so a panic or
  // battery swap zeroes it, and a failed calibration read leaves it that way).
  if (calib->parT1 == 0.0f)
    return TEMP_NO_PREVIOUS;

  float partial1 = (float)uncomp_temp - calib->parT1;
  float partial2 = partial1 * calib->parT2;
  float temp_c   = partial2 + partial1 * partial1 * calib->parT3;

  return temp_c;
}


// BMP390L register addresses
#define BMP390L_REG_PWR_CTRL 0x1B
#define BMP390L_REG_TEMP_0   0x07

// Trigger forced-mode conversion and read compensated temperature via raw I2C.
// Uses the same compensation as the ULP path.
bool bmp390l_direct_read(I2cBus &bus, const struct BMP390LCalib *calib, float *temp_out)
{
  // Trigger forced-mode conversion: temp_en=1, press_en=1, mode=forced (0b00010011)
  if (!bus.writeReg(BMP390L_I2C_ADDRESS, BMP390L_REG_PWR_CTRL, 0x13))
    return false;

  sleep_ms(10);  // conversion takes ~5ms at ultra-low precision

  // Burst-read 3 temperature bytes (DATA_0..DATA_2 at 0x07..0x09)
  uint8_t raw[3];
  if (!bus.readReg(BMP390L_I2C_ADDRESS, BMP390L_REG_TEMP_0, raw, 3))
    return false;

  *temp_out = bmp390l_compensate_temperature(calib, raw[0], raw[1], raw[2]);
  return true;
}
