#include "sensors/BMP390LSensor.hpp"
#include "common.h"

#include "DFRobot_BMP3XX.h"

#ifndef NO_ULP
#include "UlpProgram.h"
#include "BMP390LCompensation.h"

#ifdef PPK2_DEBUG_ULP_GPIO
#include "driver/rtc_io.h"
#endif

RTC_DATA_ATTR bool ulp_running = false;
RTC_DATA_ATTR struct BMP390LCalib bmp390l_calib = {};
#endif

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

bool BMP390LSensor::SupportsUlp()
{
#ifndef NO_ULP
    return true;
#else
    return false;
#endif
}

void BMP390LSensor::InitializeUlp()
{
#ifndef NO_ULP
#ifdef ULP_TEST_NO_I2C
    LOGI("Initialising ULP coprocessor (TEST MODE: counter only, no I2C)");
#else
    LOGI("Initialising ULP coprocessor for BMP390L polling");

    // Only read calibration on first boot — it's stored in RTC memory and survives deep sleep
    if (bmp390l_calib.parT1 == 0.0f)
    {
        Initialize(); // ensure I2C is up
        if (!bmp390l_read_calibration(_twoWire, &bmp390l_calib))
        {
            LOGI("ERROR: Failed to read BMP390L calibration data. ULP will not start.");
            return;
        }
        LOGI("BMP390L calibration: parT1=%.2f parT2=%.10f parT3=%.15f",
             bmp390l_calib.parT1, bmp390l_calib.parT2, bmp390l_calib.parT3);
    }
    else
    {
        LOGI("BMP390L calibration loaded from RTC memory");
    }

    // Release digital I2C before switching pins to ULP bit-bang
    _twoWire.end();
    _isInitialized = false;
    delay(10);

    // I2C bus recovery: 9 SCL clocks + STOP condition.
    // Wire.end() may leave a slave holding SDA low.
    pinMode(I2C_SCL_PIN, OUTPUT);
    pinMode(I2C_SDA_PIN, INPUT_PULLUP);
    for (int i = 0; i < 9; i++)
    {
        digitalWrite(I2C_SCL_PIN, LOW);
        delayMicroseconds(5);
        digitalWrite(I2C_SCL_PIN, HIGH);
        delayMicroseconds(5);
        if (digitalRead(I2C_SDA_PIN))
            break;
    }
    // Generate STOP condition (SDA low→high while SCL high)
    pinMode(I2C_SDA_PIN, OUTPUT);
    digitalWrite(I2C_SDA_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(I2C_SDA_PIN, HIGH);
    delayMicroseconds(5);

    // Configure GPIO pins for HULP bit-bang I2C (bypasses hardware RTC I2C peripheral)
    ulp_configure_i2c_bitbang();
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
    // Configure D13/GPIO12 as RTC GPIO output so the ULP can toggle it
    rtc_gpio_init(GPIO_NUM_12);
    rtc_gpio_set_direction(GPIO_NUM_12, RTC_GPIO_MODE_OUTPUT_ONLY);
    rtc_gpio_set_level(GPIO_NUM_12, 0);
    // RTC peripherals must stay powered during deep sleep for ULP GPIO access
    esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);
#endif

    // Build and load ULP program into RTC slow memory, then start
    ulp_build_and_load_program();
    ulp_start();
    ulp_running = true;
    LOGI("ULP started with %d µs wakeup period", (int)ULP_WAKEUP_PERIOD_US);
#endif
}

bool BMP390LSensor::ReadUlpTemperature(float *temp_out)
{
#ifndef NO_ULP
    uint16_t wake_reason = ulp_read_var(ULP_DATA_BASE, ULP_VAR_WAKE_REASON);
    uint16_t samples = ulp_read_var(ULP_DATA_BASE, ULP_VAR_SAMPLE_COUNT);
    ulp_write_var(ULP_DATA_BASE, ULP_VAR_WAKE_REASON, 0);
    ulp_write_var(ULP_DATA_BASE, ULP_VAR_SAMPLE_COUNT, 0);

    uint16_t raw_0 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_0);
    uint16_t raw_1 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_1);
    uint16_t raw_2 = ulp_read_var(ULP_DATA_BASE, ULP_VAR_TEMP_2);

    LOGI("ULP wake (reason=%d): raw temp=%02x %02x %02x, samples=%d",
         wake_reason, raw_2, raw_1, raw_0, samples);

    if (wake_reason == 2)
    {
        LOGI("ULP I2C error, falling back to normal boot path");
        return false;
    }

    *temp_out = bmp390l_compensate_temperature(&bmp390l_calib,
                                                (uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("ULP compensated temp: %.2f °C", *temp_out);
    return true;
#else
    return false;
#endif
}
