#include "sensors/BMP390LSensor.hpp"
#include "common.h"

#include "DFRobot_BMP3XX.h"

BMP390LSensor::BMP390LSensor()
:_twoWire(0), _sensor(&_twoWire)
{}

void BMP390LSensor::Initialize()
{
    if (_isInitialized)
        return;

    _twoWire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    _sensor.begin();
    // resolution when using ultra low precision & forced sampling:
    // temperature 0.0050 °C
    // pressure 2.64 Pa
    // 4µA IDD
    // measurment time ~5ms
    // CASE_SAMPLING_MODE(eUltraLowPrecision, ePressEN | eTempEN | eForcedMode, ePressOSRMode1 | eTempOSRMode1, BMP3XX_ODR_0P01_HZ, BMP3XX_IIR_CONFIG_COEF_0)
    _sensor.setSamplingMode(_sensor.eUltraLowPrecision);
    #ifdef CURRENT_ALTITUDE_M
    _sensor.calibratedAbsoluteDifference(CURRENT_ALTITUDE_M);
    #endif

    _isInitialized = true;
}

float BMP390LSensor::GetTemperatureC()
{
    Initialize();

    // BMP390L forced mode: the sensor takes one measurement then returns to
    // sleep.  Initialize() configures the sampling parameters (OSR, ODR, IIR)
    // once; here we just re-trigger a conversion so the data registers contain
    // a fresh reading.  Without this, readTempC() can return 0.0 °C from
    // stale/empty registers.
    _sensor.setPWRMode(DFRobot_BMP3XX::ePressEN | DFRobot_BMP3XX::eTempEN |
                       DFRobot_BMP3XX::eForcedMode);

    return _sensor.readTempC();
}