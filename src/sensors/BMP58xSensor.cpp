#include "sensors/BMP58xSensor.hpp"
#include "common.h"

#include "Arduino.h"
#include <math.h>

// BMP58x register map
#define BMP58X_I2C_ADDR       0x47
#define BMP58X_REG_CHIP_ID    0x01
#define BMP58X_REG_TEMP_XLSB  0x1D
#define BMP58X_REG_OSR_CONFIG 0x36
#define BMP58X_REG_ODR_CONFIG 0x37

// Chip IDs
#define BMP581_CHIP_ID 0x50
#define BMP585_CHIP_ID 0x51

// OSR_CONFIG: 1x temperature oversampling, pressure disabled
#define BMP58X_OSR_TEMP_1X 0x00
// ODR_CONFIG: forced mode (mode bits [1:0] = 0b01)
#define BMP58X_FORCED_MODE 0x01

// --- ULP FSM path (ESP32 original, HULP bit-bang I2C) ---
#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
#include "UlpProgram.h"
#include "driver/rtc_io.h"
#endif

// --- LP core path (ESP32-C6, hardware LP I2C) ---
#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP58x)
#include "ulp_lp_core.h"
#include "lp_core_i2c.h"
#include "ulp_main.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");
#endif


BMP58xSensor::BMP58xSensor()
:_twoWire(0)
{}

bool BMP58xSensor::ReadRegister(uint8_t reg, uint8_t *buf, size_t len)
{
    _twoWire.beginTransmission(BMP58X_I2C_ADDR);
    _twoWire.write(reg);
    if (_twoWire.endTransmission() != 0)
        return false;
    if (_twoWire.requestFrom((uint8_t)BMP58X_I2C_ADDR, (uint8_t)len) != (int)len)
        return false;
    for (size_t i = 0; i < len; i++)
        buf[i] = _twoWire.read();
    return true;
}

bool BMP58xSensor::WriteRegister(uint8_t reg, uint8_t value)
{
    _twoWire.beginTransmission(BMP58X_I2C_ADDR);
    _twoWire.write(reg);
    _twoWire.write(value);
    return _twoWire.endTransmission() == 0;
}

// BMP58x outputs already-compensated temperature as 24-bit signed, 1/65536 °C per LSB
float BMP58xSensor::RawToTempC(uint8_t xlsb, uint8_t lsb, uint8_t msb)
{
    uint32_t raw = (uint32_t)xlsb | ((uint32_t)lsb << 8) | ((uint32_t)msb << 16);
    if (raw & 0x800000)
        raw |= 0xFF000000; // sign-extend 24→32 bits
    return (int32_t)raw / 65536.0f;
}

void BMP58xSensor::Initialize()
{
    if (_isInitialized)
        return;

    _twoWire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

    uint8_t chip_id;
    if (ReadRegister(BMP58X_REG_CHIP_ID, &chip_id, 1))
    {
        if (chip_id == BMP581_CHIP_ID)
            LOGI("BMP581 detected (chip ID 0x%02x)", chip_id);
        else if (chip_id == BMP585_CHIP_ID)
            LOGI("BMP585 detected (chip ID 0x%02x)", chip_id);
        else
            LOGI("WARNING: unexpected BMP58x chip ID 0x%02x", chip_id);
    }
    else
    {
        LOGI("WARNING: failed to read BMP58x chip ID");
    }

    _isInitialized = true;
}

float BMP58xSensor::GetTemperatureC()
{
    Initialize();

    // Configure 1x oversampling, pressure disabled
    WriteRegister(BMP58X_REG_OSR_CONFIG, BMP58X_OSR_TEMP_1X);
    // Trigger forced-mode measurement
    WriteRegister(BMP58X_REG_ODR_CONFIG, BMP58X_FORCED_MODE);
    delay(3); // conversion ~1.6ms at 1x OSR

    uint8_t data[3];
    if (!ReadRegister(BMP58X_REG_TEMP_XLSB, data, 3))
    {
        LOGI("ERROR: failed to read BMP58x temperature");
        return 0.0f;
    }

    return RawToTempC(data[0], data[1], data[2]);
}

bool BMP58xSensor::SupportsUlp()
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

void BMP58xSensor::InitializeUlp()
{
#ifdef ULP_TEST_NO_I2C
    LOGI("Initialising ULP coprocessor (TEST MODE: counter only, no I2C)");
#else
    LOGI("Initialising ULP coprocessor for BMP58x polling");

    // No calibration read needed — BMP58x output is already compensated

    // Release digital I2C before switching pins to ULP bit-bang
    _twoWire.end();
    _isInitialized = false;
    delay(10);

    // I2C bus recovery: 9 SCL clocks + STOP condition
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
    pinMode(I2C_SDA_PIN, OUTPUT);
    digitalWrite(I2C_SDA_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(I2C_SDA_PIN, HIGH);
    delayMicroseconds(5);

    ulp_configure_i2c_bitbang();
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
    rtc_gpio_init(GPIO_NUM_12);
    rtc_gpio_set_direction(GPIO_NUM_12, RTC_GPIO_MODE_OUTPUT_ONLY);
    rtc_gpio_set_level(GPIO_NUM_12, 0);
    esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);
#endif

    ulp_build_and_load_program();
    ulp_start();
    LOGI("ULP started with %d µs wakeup period", (int)ULP_WAKEUP_PERIOD_US);
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP58x)
// --- ESP32-C6 LP core path (hardware LP I2C) ---

void BMP58xSensor::InitializeUlp()
{
    LOGI("Initialising LP core for BMP58x polling");

    // No calibration read needed — BMP58x output is already compensated

    _twoWire.end();
    _isInitialized = false;
    delay(10);

    lp_core_i2c_cfg_t i2c_cfg = LP_CORE_I2C_DEFAULT_CONFIG();
    ESP_ERROR_CHECK(lp_core_i2c_master_init(LP_I2C_NUM_0, &i2c_cfg));

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

void BMP58xSensor::InitializeUlp() {}

#endif

// ============================================================
// ReadUlpTemperature — two implementations
// ============================================================

#ifdef HAS_ULP_SUPPORT
#define TEMP_REREAD_DELTA   5.0f
#define TEMP_REREAD_CONFIRM 0.5f

// Direct I2C re-read for plausibility verification
static bool bmp58x_direct_read(TwoWire &wire, float *temp_out)
{
    wire.beginTransmission(BMP58X_I2C_ADDR);
    wire.write(BMP58X_REG_OSR_CONFIG);
    wire.write(BMP58X_OSR_TEMP_1X);
    if (wire.endTransmission() != 0)
        return false;

    wire.beginTransmission(BMP58X_I2C_ADDR);
    wire.write(BMP58X_REG_ODR_CONFIG);
    wire.write(BMP58X_FORCED_MODE);
    if (wire.endTransmission() != 0)
        return false;

    delay(3);

    wire.beginTransmission(BMP58X_I2C_ADDR);
    wire.write(BMP58X_REG_TEMP_XLSB);
    if (wire.endTransmission() != 0)
        return false;
    if (wire.requestFrom((uint8_t)BMP58X_I2C_ADDR, (uint8_t)3) != 3)
        return false;

    uint8_t data[3];
    for (int i = 0; i < 3; i++)
        data[i] = wire.read();

    uint32_t raw = (uint32_t)data[0] | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16);
    if (raw & 0x800000)
        raw |= 0xFF000000;
    *temp_out = (int32_t)raw / 65536.0f;
    return true;
}

static bool verify_ulp_temp(TwoWire &wire, float *temp)
{
    wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    float reread;
    bool ok = bmp58x_direct_read(wire, &reread);
    wire.end();
    if (!ok)
    {
        LOGI("Direct I2C re-read failed, discarding suspicious ULP value");
        return false;
    }
    LOGI("Direct I2C re-read: %.2f °C", reread);
    if (fabsf(reread - *temp) <= TEMP_REREAD_CONFIRM)
    {
        LOGI("Re-read confirms ULP value, accepting %.2f", *temp);
    }
    else
    {
        LOGI("Re-read disagrees (ULP=%.2f, I2C=%.2f), using I2C value", *temp, reread);
        *temp = reread;
    }
    return true;
}
#endif

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
// --- ESP32 ULP FSM path ---

bool BMP58xSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
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

    *temp_out = RawToTempC((uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("ULP temp: %.2f °C", *temp_out);

#ifdef TEST_CORRUPT_ULP_TEMP
    LOGI("TEST: corrupting ULP temp %.2f → %.2f", *temp_out, *temp_out + 50.0f);
    *temp_out += 50.0f;
#endif

    if (previous_temp != TEMP_NO_PREVIOUS && fabsf(*temp_out - previous_temp) > TEMP_REREAD_DELTA)
    {
        LOGI("Suspicious ULP temp %.2f (previous %.2f, delta %.2f) — verifying",
             *temp_out, previous_temp, *temp_out - previous_temp);
        rtc_gpio_deinit((gpio_num_t)I2C_SDA_PIN);
        rtc_gpio_deinit((gpio_num_t)I2C_SCL_PIN);
        if (!verify_ulp_temp(_twoWire, temp_out))
            return false;
    }

    return true;
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP58x)
// --- ESP32-C6 LP core path ---

bool BMP58xSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
{
    uint32_t reason = ulp_wake_reason;
    uint32_t samples = ulp_sample_count;

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

    *temp_out = RawToTempC((uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("LP core temp: %.2f °C", *temp_out);

#ifdef TEST_CORRUPT_ULP_TEMP
    LOGI("TEST: corrupting LP core temp %.2f → %.2f", *temp_out, *temp_out + 50.0f);
    *temp_out += 50.0f;
#endif

    if (previous_temp != TEMP_NO_PREVIOUS && fabsf(*temp_out - previous_temp) > TEMP_REREAD_DELTA)
    {
        LOGI("Suspicious LP core temp %.2f (previous %.2f, delta %.2f) — verifying",
             *temp_out, previous_temp, *temp_out - previous_temp);
        if (!verify_ulp_temp(_twoWire, temp_out))
            return false;
    }

    return true;
}

#else
// --- No ULP support ---

bool BMP58xSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
{
    return false;
}

#endif
