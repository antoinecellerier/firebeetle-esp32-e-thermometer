#include "sensors/BMP390LSensor.hpp"
#include "app_common.h"

#include <math.h>
#include "esp_attr.h"

// Calibration is needed by both the HP direct-read path and the ULP path.
// Stored in RTC memory so it persists across deep sleep cycles.
RTC_DATA_ATTR struct BMP390LCalib bmp390l_calib = {};

// BMP390L config registers (addresses/values per Bosch datasheet; sampling
// setup matches the former DFRobot eUltraLowPrecision mode: 1x temp/press
// oversampling, IIR filter off, forced mode)
#define BMP390L_REG_OSR    0x1C
#define BMP390L_REG_IIR    0x1F

// --- ULP FSM path (ESP32 original, HULP bit-bang I2C) ---
#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
#include "UlpProgram.h"
#include "driver/rtc_io.h"
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
{}

void BMP390LSensor::Initialize()
{
    if (_isInitialized)
        return;

    _i2c.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    sleep_ms(5); // ~2ms startup time after power-up

    // Ultra-low precision sampling (was DFRobot eUltraLowPrecision):
    // temperature resolution 0.0050 °C, measurement time ~5ms, 4µA IDD
    _i2c.writeReg(BMP390L_I2C_ADDRESS, BMP390L_REG_OSR, 0x00); // 1x temp + press OSR
    _i2c.writeReg(BMP390L_I2C_ADDRESS, BMP390L_REG_IIR, 0x00); // IIR filter off

    if (bmp390l_calib.parT1 == 0.0f &&
        !bmp390l_read_calibration(_i2c, &bmp390l_calib))
    {
        LOGI("ERROR: failed to read BMP390L calibration data");
    }

    _isInitialized = true;
}

float BMP390LSensor::GetTemperatureC()
{
    Initialize();

    // Forced mode: bmp390l_direct_read() triggers one conversion, waits, and
    // reads + compensates the result (same compensation as the ULP path).
    float temp;
    if (!bmp390l_direct_read(_i2c, &bmp390l_calib, &temp))
    {
        // The sentinel, not 0.0f: 0.0 °C is a plausible room temperature, so a
        // failed read returning it is indistinguishable from a real measurement.
        LOGI("ERROR: failed to read BMP390L temperature");
        return TEMP_NO_PREVIOUS;
    }
    return temp;
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

void BMP390LSensor::InitializeUlp(bool cold_boot)
{
#ifdef ULP_TEST_NO_I2C
    LOGI("Initialising ULP coprocessor (TEST MODE: counter only, no I2C)");
#else
    LOGI("Initialising ULP coprocessor for BMP390L polling");

    // Calibration is read once and kept in RTC memory across deep sleep. A
    // recovery reload clears it so it must be re-read: it doubles as this
    // sensor's proof of presence, and a cached copy would let an absent part go
    // on producing compensated numbers from an undriven bus — the hole the
    // chip-ID check closes for BMP58x. Readings stay rejected until one lands,
    // because bmp390l_compensate_temperature() refuses to work without it.
    if (!cold_boot)
        bmp390l_calib.parT1 = 0.0f;

    if (bmp390l_calib.parT1 == 0.0f)
    {
        Initialize();
        if (bmp390l_calib.parT1 == 0.0f)
        {
            LOGI("ERROR: Failed to read BMP390L calibration data");
            if (cold_boot)
            {
                LOGI("ULP will not start");
                return;
            }
            // On recovery, start it anyway: the ULP compares raw bytes and needs no
            // calibration, so it can keep polling and wake the CPU when the sensor
            // returns.
        }
        else
        {
            LOGI("BMP390L calibration: parT1=%.2f parT2=%.10f parT3=%.15f",
                 bmp390l_calib.parT1, bmp390l_calib.parT2, bmp390l_calib.parT3);
        }
    }
    else
    {
        LOGI("BMP390L calibration loaded from RTC memory");
    }

    // Release digital I2C before switching pins to ULP bit-bang
    _i2c.end();
    _isInitialized = false;
    sleep_ms(10);

    i2c_bus_recover(I2C_SDA_PIN, I2C_SCL_PIN);

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

    // ulp_build_and_load_program() zeroes the shared variables, and the program
    // treats a zero reference as "no reference yet" and seeds it from the first
    // sample — giving a delta of 0 and no wake. That is right on a cold boot, where
    // it prevents a phantom refresh, and wrong after a recovery reload, where it
    // suppresses precisely the wake that would notice the sensor is back and leaves
    // the panel blanked until the hourly safety net. Any non-zero reference skips
    // the seeding, so the first real sample produces a large delta and wakes.
    if (!cold_boot)
        ulp_write_var(ULP_DATA_BASE, ULP_VAR_PREV_TEMP_MSB, 1);

    ulp_start();
    LOGI("ULP started with %d µs wakeup period", (int)ULP_WAKEUP_PERIOD_US);
}

void BMP390LSensor::StopUlp()
{
    // Nothing to halt for the bus's sake: the FSM bit-bangs over RTC GPIOs, and
    // release_i2c_pins_to_hp() takes those back before the CPU reads.
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP390L)
// --- ESP32-C6 LP core path (hardware LP I2C) ---

void BMP390LSensor::InitializeUlp(bool cold_boot)
{
    LOGI("Initialising LP core for BMP390L polling");

    // A recovery reload re-establishes identity. The calibration block lives in RTC
    // memory and outlives the fault, so trusting the cache would let an absent
    // sensor go on producing compensated numbers from an undriven bus — the same
    // hole the chip-ID check closes for BMP58x. Clearing it forces a fresh read,
    // and bmp390l_compensate_temperature() rejects every reading until one lands.
    if (!cold_boot)
        bmp390l_calib.parT1 = 0.0f;

    if (bmp390l_calib.parT1 == 0.0f)
    {
        Initialize();
        if (bmp390l_calib.parT1 == 0.0f)
        {
            LOGI("ERROR: Failed to read BMP390L calibration data");
            if (cold_boot)
            {
                LOGI("LP core will not start");
                return;
            }
            // On recovery, start it anyway: the coprocessor compares raw bytes and
            // needs no calibration, so it can keep polling and wake the CPU when the
            // sensor comes back. Readings stay rejected until calibration reads.
        }
        else
        {
            LOGI("BMP390L calibration: parT1=%.2f parT2=%.10f parT3=%.15f",
                 bmp390l_calib.parT1, bmp390l_calib.parT2, bmp390l_calib.parT3);
        }
    }
    else
    {
        LOGI("BMP390L calibration loaded from RTC memory");
    }

    // Release digital I2C — LP I2C will take over the pins
    _i2c.end();
    _isInitialized = false;
    sleep_ms(10);

    // Configure LP I2C hardware peripheral (GPIO6=SDA, GPIO7=SCL)
    // LP_CORE_I2C_DEFAULT_CONFIG() uses C designated initializers — not valid in C++
    lp_core_i2c_cfg_t i2c_cfg = {};
    i2c_cfg.i2c_pin_cfg.sda_io_num = LP_I2C_SDA_IO;
    i2c_cfg.i2c_pin_cfg.scl_io_num = LP_I2C_SCL_IO;
    i2c_cfg.i2c_pin_cfg.sda_pullup_en = true;
    i2c_cfg.i2c_pin_cfg.scl_pullup_en = true;
    i2c_cfg.i2c_timing_cfg.clk_speed_hz = 400000;
    i2c_cfg.i2c_src_clk = LP_I2C_SCLK_LP_FAST;
    ESP_ERROR_CHECK(lp_core_i2c_master_init(LP_I2C_NUM_0, &i2c_cfg));

    // Load and start the LP core binary.
    //
    // ulp_lp_core_load_binary() memsets the whole CONFIG_ULP_COPROC_RESERVE_MEM
    // region before copying the program — that is how it initialises .bss — so
    // nothing in LP RAM survives a reload. The wake and error counters have to be
    // carried across by hand or they never accumulate past one reload, and the
    // "! LP" badge needs several errors against a wake count before it fires.
    //
    // prev_temp_msb is deliberately NOT carried: left at zero the first sample
    // produces a large delta and wakes the CPU, which is what makes a repaired
    // sensor noticed within one LP period instead of at the hourly safety net.
    uint64_t wakeup_us = (uint64_t)SLEEP_INTERVAL_S * 1000000ULL;
    const uint32_t saved_wakes  = cold_boot ? 0 : ulp_lp_wake_count;
    const uint32_t saved_errors = cold_boot ? 0 : ulp_lp_error_count;
    const uint32_t saved_err    = cold_boot ? 0 : ulp_last_lp_error;
    const uint32_t saved_op     = cold_boot ? 0 : ulp_last_lp_op;

    ESP_ERROR_CHECK(ulp_lp_core_load_binary(ulp_main_bin_start,
                                            (ulp_main_bin_end - ulp_main_bin_start)));

    ulp_lp_wake_count  = saved_wakes;
    ulp_lp_error_count = saved_errors;
    ulp_last_lp_error  = saved_err;
    ulp_last_lp_op     = saved_op;
    ulp_sample_count   = 0;
    ulp_wake_reason    = 0;

    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER,
        .lp_timer_sleep_duration_us = (uint32_t)wakeup_us,
    };
    ESP_ERROR_CHECK(ulp_lp_core_run(&cfg));

    LOGI("LP core started with %d µs wakeup period", (int)wakeup_us);
}

void BMP390LSensor::StopUlp()
{
    // Halts the core so it cannot start an LP I2C transaction while the CPU is
    // using the same pins. InitializeUlp() reloads and restarts it.
    ulp_lp_core_stop();
}

#else
// --- No ULP support ---

void BMP390LSensor::InitializeUlp(bool cold_boot) { (void)cold_boot; }

void BMP390LSensor::StopUlp() {}

#endif

// ============================================================
// ReadUlpTemperature — two implementations
// ============================================================

#ifdef HAS_ULP_SUPPORT
// Maximum plausible temperature jump (°C) between consecutive readings.
// If a ULP reading differs from the previous by more than this, we do a
// direct I2C re-read to verify.
#define TEMP_REREAD_DELTA   5.0f
// Tolerance for confirming a suspicious ULP reading via direct I2C re-read.
// BMP390L noise is ~0.05°C; 0.5°C gives margin for thermal drift between reads.
#define TEMP_REREAD_CONFIRM 0.5f

// Verify a suspicious ULP temperature by doing a direct I2C re-read.
// Returns true if *temp was accepted or corrected, false if verification failed.
// unused when another sensor owns the ULP (e.g. USE_BMP58x on C6)
__attribute__((unused))
static bool verify_ulp_temp(I2cBus &bus, float *temp)
{
    bus.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    float reread;
    bool ok = bmp390l_direct_read(bus, &bmp390l_calib, &reread);
    bus.end();
    if (!ok)
    {
        LOGI("Direct I2C re-read failed, discarding suspicious ULP value");
        return false;
    }
    LOGI("Direct I2C re-read: %.2f °C", reread);
    if (!temp_is_plausible(reread))
    {
        LOGI("Re-read %.2f is outside %.0f..%.0f — discarding both",
             reread, TEMP_PLAUSIBLE_MIN_C, TEMP_PLAUSIBLE_MAX_C);
        return false;
    }
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

// The ULP bit-bang holds SDA/SCL as RTC GPIOs across deep sleep, and I2cBus cannot
// drive them in that state. Every path that gives up on the ULP reading falls
// through to a direct read in setup(), so each one has to hand the pins back — a
// failure return that skips this leaves the fall-through unable to reach the sensor.
static void release_i2c_pins_to_hp()
{
    rtc_gpio_deinit((gpio_num_t)I2C_SDA_PIN);
    rtc_gpio_deinit((gpio_num_t)I2C_SCL_PIN);
}

bool BMP390LSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
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
        release_i2c_pins_to_hp();
        return false;
    }

    *temp_out = bmp390l_compensate_temperature(&bmp390l_calib,
                                                (uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("ULP compensated temp: %.2f °C", *temp_out);
    if (!temp_is_plausible(*temp_out))
    {
        LOGI("ULP compensated temp %.2f outside %.0f..%.0f — rejecting", *temp_out,
             TEMP_PLAUSIBLE_MIN_C, TEMP_PLAUSIBLE_MAX_C);
        release_i2c_pins_to_hp();
        return false;
    }

#ifdef TEST_CORRUPT_ULP_TEMP
    LOGI("TEST: corrupting ULP temp %.2f → %.2f", *temp_out, *temp_out + 50.0f);
    *temp_out += 50.0f;
#endif

    if (previous_temp != TEMP_NO_PREVIOUS && fabsf(*temp_out - previous_temp) > TEMP_REREAD_DELTA)
    {
        LOGI("Suspicious ULP temp %.2f (previous %.2f, delta %.2f) — verifying",
             *temp_out, previous_temp, *temp_out - previous_temp);
        release_i2c_pins_to_hp();
        if (!verify_ulp_temp(_i2c, temp_out))
            return false;
    }

    return true;
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP390L)
// --- ESP32-C6 LP core path ---

bool BMP390LSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
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
    if (!temp_is_plausible(*temp_out))
    {
        LOGI("LP core compensated temp %.2f outside %.0f..%.0f — rejecting", *temp_out,
             TEMP_PLAUSIBLE_MIN_C, TEMP_PLAUSIBLE_MAX_C);
        return false;
    }

#ifdef TEST_CORRUPT_ULP_TEMP
    LOGI("TEST: corrupting LP core temp %.2f → %.2f", *temp_out, *temp_out + 50.0f);
    *temp_out += 50.0f;
#endif

    if (previous_temp != TEMP_NO_PREVIOUS && fabsf(*temp_out - previous_temp) > TEMP_REREAD_DELTA)
    {
        LOGI("Suspicious LP core temp %.2f (previous %.2f, delta %.2f) — verifying",
             *temp_out, previous_temp, *temp_out - previous_temp);
        // C6 LP I2C uses dedicated pins — no RTC GPIO deinit needed
        if (!verify_ulp_temp(_i2c, temp_out))
            return false;
    }

    return true;
}

#else
// --- No ULP support ---

bool BMP390LSensor::ReadUlpTemperature(float *temp_out, float previous_temp)
{
    return false;
}

#endif
