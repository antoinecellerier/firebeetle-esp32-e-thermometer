#include "sensors/BMP390LSensor.hpp"
#include "common.h"

#include "DFRobot_BMP3XX.h"

#ifdef HAS_ULP_SUPPORT
#include "BMP390LCompensation.h"
RTC_DATA_ATTR struct BMP390LCalib bmp390l_calib = {};
#endif

// --- ULP FSM path (ESP32 original, HULP bit-bang I2C) ---
#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
#include "UlpProgram.h"

#ifdef PPK2_DEBUG_ULP_GPIO
#include "driver/rtc_io.h"
#endif
#endif

// --- LP core path (ESP32-C6, hardware LP I2C) ---
// Only include LP core binary/symbols when BMP390L is the active sensor,
// otherwise DummySensor provides its own LP core binary.
#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP390L)
#include "ulp_lp_core.h"
#include "lp_core_i2c.h"
#include "ulp_main.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");
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
#ifdef HAS_ULP_SUPPORT
    return true;
#else
    return false;
#endif
}

// ============================================================
// InitializeUlp — two implementations, selected at compile time
// ============================================================

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
// --- ESP32 ULP FSM path (HULP bit-bang I2C) ---

void BMP390LSensor::InitializeUlp()
{
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
    LOGI("ULP started with %d µs wakeup period", (int)ULP_WAKEUP_PERIOD_US);
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP390L)
// --- ESP32-C6 LP core path (hardware LP I2C) ---

void BMP390LSensor::InitializeUlp()
{
    LOGI("Initialising LP core for BMP390L polling");

    // Read calibration on first boot — stored in RTC memory, survives deep sleep
    if (bmp390l_calib.parT1 == 0.0f)
    {
        Initialize(); // ensure I2C is up
        if (!bmp390l_read_calibration(_twoWire, &bmp390l_calib))
        {
            LOGI("ERROR: Failed to read BMP390L calibration data. LP core will not start.");
            return;
        }
        LOGI("BMP390L calibration: parT1=%.2f parT2=%.10f parT3=%.15f",
             bmp390l_calib.parT1, bmp390l_calib.parT2, bmp390l_calib.parT3);
    }
    else
    {
        LOGI("BMP390L calibration loaded from RTC memory");
    }

    // Release digital I2C — LP I2C will take over the pins
    _twoWire.end();
    _isInitialized = false;
    delay(10);

    // Configure LP I2C hardware peripheral (GPIO6=SDA, GPIO7=SCL)
    lp_core_i2c_cfg_t i2c_cfg = LP_CORE_I2C_DEFAULT_CONFIG();
    ESP_ERROR_CHECK(lp_core_i2c_master_init(LP_I2C_NUM_0, &i2c_cfg));

    // Load and start the LP core binary
    uint64_t wakeup_us = (uint64_t)SLEEP_INTERVAL_S * 1000000ULL;
    ESP_ERROR_CHECK(ulp_lp_core_load_binary(ulp_main_bin_start,
                                            (ulp_main_bin_end - ulp_main_bin_start)));
    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER,
        .lp_timer_sleep_duration_us = (uint32_t)wakeup_us,
    };
    ESP_ERROR_CHECK(ulp_lp_core_run(&cfg));

    LOGI("LP core started with %d µs wakeup period", (int)wakeup_us);
}

#else
// --- No ULP support ---

void BMP390LSensor::InitializeUlp() {}

#endif

// ============================================================
// ReadUlpTemperature — two implementations
// ============================================================

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
// --- ESP32 ULP FSM path ---

bool BMP390LSensor::ReadUlpTemperature(float *temp_out)
{
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
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP390L)
// --- ESP32-C6 LP core path ---

bool BMP390LSensor::ReadUlpTemperature(float *temp_out)
{
    // Read shared variables from LP core (via generated symbol addresses)
    uint32_t reason = ulp_wake_reason;
    uint32_t samples = ulp_sample_count;

    // Clear for next cycle
    ulp_wake_reason = 0;
    ulp_sample_count = 0;

    uint32_t raw_0 = ulp_temp_raw_0;
    uint32_t raw_1 = ulp_temp_raw_1;
    uint32_t raw_2 = ulp_temp_raw_2;

    LOGI("LP core wake (reason=%d): raw temp=%02x %02x %02x, samples=%d",
         (int)reason, (int)raw_2, (int)raw_1, (int)raw_0, (int)samples);

    if (reason == 2)
    {
        LOGI("LP core I2C error, falling back to normal boot path");
        return false;
    }

    *temp_out = bmp390l_compensate_temperature(&bmp390l_calib,
                                                (uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("LP core compensated temp: %.2f °C", *temp_out);
    return true;
}

#else
// --- No ULP support ---

bool BMP390LSensor::ReadUlpTemperature(float *temp_out)
{
    return false;
}

#endif
