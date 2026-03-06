// Compensation formula and calibration coefficient quantization derived from:
//   DFRobot_BMP3XX library — https://github.com/DFRobot/DFRobot_BMP3XX
//   Copyright (c) 2010 DFRobot Co.Ltd (http://www.dfrobot.com)
//   Licensed under the MIT License
// See DFRobot_BMP3XX.cpp lines 267-274 (quantization) and 313-326 (compensation).

#include "BMP390LCompensation.h"

#include <math.h>
#include "Wire.h"

#define BMP390L_CALIB_REG_ADDR 0x31
#define BMP390L_CALIB_DATA_LEN 21
#define BMP390L_I2C_ADDRESS    0x77


bool bmp390l_read_calibration(TwoWire &wire, struct BMP390LCalib *calib)
{
  wire.beginTransmission(BMP390L_I2C_ADDRESS);
  wire.write(BMP390L_CALIB_REG_ADDR);
  if (wire.endTransmission(false) != 0)
    return false;

  if (wire.requestFrom((uint8_t)BMP390L_I2C_ADDRESS, (uint8_t)BMP390L_CALIB_DATA_LEN) != BMP390L_CALIB_DATA_LEN)
    return false;

  uint8_t regData[BMP390L_CALIB_DATA_LEN];
  for (int i = 0; i < BMP390L_CALIB_DATA_LEN; i++)
    regData[i] = wire.read();

  // Quantize temperature coefficients (same formula as DFRobot_BMP3XX.cpp lines 267-274)
  uint16_t rawT1 = (uint16_t)regData[1] << 8 | regData[0];
  uint16_t rawT2 = (uint16_t)regData[3] << 8 | regData[2];
  int8_t   rawT3 = (int8_t)regData[4];

  calib->parT1 = (float)rawT1 / powf(2.0f, -8.0f);  // = rawT1 * 256
  calib->parT2 = (float)rawT2 / powf(2.0f, 30.0f);
  calib->parT3 = (float)rawT3 / powf(2.0f, 48.0f);

  return true;
}


float bmp390l_compensate_temperature(const struct BMP390LCalib *calib,
                                     uint8_t raw_0, uint8_t raw_1, uint8_t raw_2)
{
  uint32_t uncomp_temp = (uint32_t)raw_0 | ((uint32_t)raw_1 << 8) | ((uint32_t)raw_2 << 16);

  float partial1 = (float)uncomp_temp - calib->parT1;
  float partial2 = partial1 * calib->parT2;
  float temp_c   = partial2 + partial1 * partial1 * calib->parT3;

  return temp_c;
}
