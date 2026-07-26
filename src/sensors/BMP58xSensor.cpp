#include "sensors/BMP58xSensor.hpp"
#include "app_common.h"

#include <math.h>

// BMP58x register map
#define BMP58X_I2C_ADDR       0x47
#define BMP58X_REG_CHIP_ID    0x01
#define BMP58X_REG_INT_CONFIG 0x14
#define BMP58X_REG_TEMP_XLSB  0x1D
#define BMP58X_REG_OSR_CONFIG 0x36
#define BMP58X_REG_ODR_CONFIG 0x37

// Chip IDs
#define BMP581_CHIP_ID 0x50
#define BMP585_CHIP_ID 0x51

// OSR_CONFIG: 1x temperature oversampling, pressure disabled
#define BMP58X_OSR_TEMP_1X 0x00
// ODR_CONFIG: forced mode (pwr_mode = BMP5_POWERMODE_FORCED per Bosch bmp5_defs.h)
#define BMP58X_FORCED_MODE 0x02
// INT_CONFIG: int_en=1 + push-pull + active-high + pad_int_drv=0. With no
// sources routed (INT_SOURCE stays 0) the pad is actively parked at its
// inactive level (low) — required on the custom thermometer-c6 board where
// INT is unconnected (hardware/thermometer-c6/README.md bench notes), and
// harmless on breakouts that ground INT (parked low = GND).
#define BMP58X_INT_PARKED 0x0A

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
{}

bool BMP58xSensor::ReadRegister(uint8_t reg, uint8_t *buf, size_t len)
{
    return _i2c.readReg(BMP58X_I2C_ADDR, reg, buf, len);
}

bool BMP58xSensor::WriteRegister(uint8_t reg, uint8_t value)
{
    return _i2c.writeReg(BMP58X_I2C_ADDR, reg, value);
}

// BMP58x outputs already-compensated temperature as 24-bit signed, 1/65536 °C per LSB.
//
// Every path converts here — direct read, ULP FSM and LP core — so this is the one
// place that has to recognise a raw code no live sensor produces. Returning the
// sentinel lets the plausibility gate the callers already apply reject it, instead
// of each path needing its own copy of the test.
float BMP58xSensor::RawToTempC(uint8_t xlsb, uint8_t lsb, uint8_t msb)
{
    uint32_t raw = (uint32_t)xlsb | ((uint32_t)lsb << 8) | ((uint32_t)msb << 16);
    if (TEMP_RAW24_IS_BUS_ARTIFACT(raw))
        return TEMP_NO_PREVIOUS;
    if (raw & 0x800000)
        raw |= 0xFF000000; // sign-extend 24→32 bits
    return (int32_t)raw / 65536.0f;
}

void BMP58xSensor::Initialize()
{
    if (_isInitialized)
        return;

    _i2c.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    sleep_ms(5); // BMP58x needs ~2ms after power-up before I2C is ready

    // The chip ID is the only positive evidence that a BMP58x is on the bus, and
    // it is what separates a real measurement from a number an undriven bus
    // produced. A floating SDA yields values that pass every range and artifact
    // test — 0x7F8000 reads as a perfectly formed 127.5 °C — so identity has to
    // gate the reading rather than merely be logged.
    uint8_t chip_id;
    _identified = false;
    if (ReadRegister(BMP58X_REG_CHIP_ID, &chip_id, 1))
    {
        if (chip_id == BMP581_CHIP_ID)
        {
            LOGI("BMP581 detected (chip ID 0x%02x)", chip_id);
            _identified = true;
        }
        else if (chip_id == BMP585_CHIP_ID)
        {
            LOGI("BMP585 detected (chip ID 0x%02x)", chip_id);
            _identified = true;
        }
        else
        {
            LOGI("WARNING: unexpected BMP58x chip ID 0x%02x — not trusting readings",
                 chip_id);
        }
    }
    else
    {
        LOGI("WARNING: failed to read BMP58x chip ID — not trusting readings");
    }

    WriteRegister(BMP58X_REG_OSR_CONFIG, BMP58X_OSR_TEMP_1X);
    WriteRegister(BMP58X_REG_INT_CONFIG, BMP58X_INT_PARKED);

    _isInitialized = true;
}

float BMP58xSensor::GetTemperatureC()
{
    Initialize();

    if (!_identified)
        return TEMP_NO_PREVIOUS;

    // Trigger forced-mode measurement (OSR configured once in Initialize())
    WriteRegister(BMP58X_REG_ODR_CONFIG, BMP58X_FORCED_MODE);
    sleep_ms(3); // conversion ~1.6ms at 1x OSR

    uint8_t data[3];
    if (!ReadRegister(BMP58X_REG_TEMP_XLSB, data, 3))
    {
        // The sentinel, not 0.0f: 0.0 °C is a plausible room temperature, so a
        // failed read returning it is indistinguishable from a real measurement.
        LOGI("ERROR: failed to read BMP58x temperature");
        return TEMP_NO_PREVIOUS;
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

void BMP58xSensor::InitializeUlp(bool cold_boot)
{
#ifdef ULP_TEST_NO_I2C
    LOGI("Initialising ULP coprocessor (TEST MODE: counter only, no I2C)");
#else
    LOGI("Initialising ULP coprocessor for BMP58x polling");

    // No calibration read needed — BMP58x output is already compensated.
    // Ensure chip ID + OSR_CONFIG have been written via digital I2C before
    // handing the bus off to ULP bit-bang (idempotent if already initialised).
    Initialize();

    // Release digital I2C before switching pins to ULP bit-bang
    _i2c.end();
    _isInitialized = false;
    sleep_ms(10);

    i2c_bus_recover(I2C_SDA_PIN, I2C_SCL_PIN);

    ulp_configure_i2c_bitbang();
#endif

#ifdef PPK2_DEBUG_ULP_GPIO
    rtc_gpio_init(GPIO_NUM_12);
    rtc_gpio_set_direction(GPIO_NUM_12, RTC_GPIO_MODE_OUTPUT_ONLY);
    rtc_gpio_set_level(GPIO_NUM_12, 0);
    esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);
#endif

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

void BMP58xSensor::StopUlp()
{
    // Nothing to halt for the bus's sake: the FSM bit-bangs over RTC GPIOs, and
    // release_i2c_pins_to_hp() takes those back before the CPU reads.
}

#elif defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && defined(USE_BMP58x)
// --- ESP32-C6 LP core path (hardware LP I2C) ---

void BMP58xSensor::InitializeUlp(bool cold_boot)
{
    LOGI("Initialising LP core for BMP58x polling");

    // No calibration read needed — BMP58x output is already compensated.
    // Ensure chip ID + OSR_CONFIG have been written via digital I2C before
    // handing the bus off to LP I2C (idempotent if already initialised).
    Initialize();

    _i2c.end();
    _isInitialized = false;
    sleep_ms(10);

    // LP_CORE_I2C_DEFAULT_CONFIG() uses C designated initializers — not valid in C++
    lp_core_i2c_cfg_t i2c_cfg = {};
    i2c_cfg.i2c_pin_cfg.sda_io_num = LP_I2C_SDA_IO;
    i2c_cfg.i2c_pin_cfg.scl_io_num = LP_I2C_SCL_IO;
    i2c_cfg.i2c_pin_cfg.sda_pullup_en = true;
    i2c_cfg.i2c_pin_cfg.scl_pullup_en = true;
    i2c_cfg.i2c_timing_cfg.clk_speed_hz = 400000;
    i2c_cfg.i2c_src_clk = LP_I2C_SCLK_LP_FAST;
    ESP_ERROR_CHECK(lp_core_i2c_master_init(LP_I2C_NUM_0, &i2c_cfg));

    uint64_t wakeup_us = (uint64_t)SLEEP_INTERVAL_S * 1000000ULL;

    // ulp_lp_core_load_binary() memsets the whole CONFIG_ULP_COPROC_RESERVE_MEM
    // region before copying the program — that is how it initialises .bss — so
    // nothing in LP RAM survives a reload on its own. Carry the shared state
    // across by hand: the wake/error counters have to keep accumulating for the
    // "! LP" badge to ever reach its threshold, and prev_temp_c is the delta
    // reference, which reset to 0.0 makes a sensor sitting at any other
    // temperature look like a large change and wake the CPU every LP period.
    //
    // On a cold boot there is nothing to carry: the symbols hold uninitialised
    // SRAM, and the memset is exactly what is wanted.
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
    // Consumed by the CPU on the wake that led here; always starts clean.
    ulp_sample_count   = 0;
    ulp_wake_reason    = 0;
    // Deliberately NOT carried across, for two reasons. It is the delta reference
    // the LP core wakes on, and a reload only happens after something went wrong —
    // so the reference may well be garbage the LP core latched from a floating bus
    // during the fault. Carrying that forward can leave it within
    // TEMP_DELTA_THRESHOLD_C of the real room temperature, in which case a
    // repaired sensor produces no delta, never wakes the CPU, and the panel stays
    // blanked until the hourly safety net. Resetting to 0.0 — below anything this
    // sensor reads indoors — guarantees the next sample wakes the CPU and the
    // reading is re-evaluated. The cost is a wake per LP period while a fault
    // persists, which is accepted for a case that is rare and either clears on the
    // next reading or is terminal.
    ulp_prev_temp_c    = 0.0f;

    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER,
        .lp_timer_sleep_duration_us = (uint32_t)wakeup_us,
    };
    ESP_ERROR_CHECK(ulp_lp_core_run(&cfg));

    LOGI("LP core started with %d µs wakeup period", (int)wakeup_us);
}

void BMP58xSensor::StopUlp()
{
    // Halts the core so it cannot start an LP I2C transaction while the CPU is
    // using the same pins. InitializeUlp() reloads and restarts it.
    ulp_lp_core_stop();
}

#else
// --- No ULP support ---

void BMP58xSensor::InitializeUlp(bool cold_boot) { (void)cold_boot; }

void BMP58xSensor::StopUlp() {}

#endif

// ============================================================
// ReadUlpTemperature — two implementations
// ============================================================

#ifdef HAS_ULP_SUPPORT
#define TEMP_REREAD_DELTA   5.0f
#define TEMP_REREAD_CONFIRM 0.5f

// Direct I2C re-read for plausibility verification
// (OSR was already configured in Initialize() before ULP/LP-core took over the bus)
//
// Returns false only when the bus transfer failed, so the caller can tell an I2C
// failure from a sensor that answered with a value — the distinction the whole
// verification exists to make, and one that is lost if this folds the plausibility
// test into its return. *temp_out carries whatever was read, sentinel included.
static bool bmp58x_direct_read(I2cBus &bus, float *temp_out)
{
    // Identity first: this runs on the coprocessor path, which never calls
    // Initialize(), so it is the only place the re-read can establish that the
    // reply is coming from a sensor rather than from an undriven bus.
    uint8_t chip_id;
    if (!bus.readReg(BMP58X_I2C_ADDR, BMP58X_REG_CHIP_ID, &chip_id, 1))
        return false;
    if (chip_id != BMP581_CHIP_ID && chip_id != BMP585_CHIP_ID)
    {
        LOGI("Re-read: chip ID 0x%02x is not a BMP58x — no sensor on the bus", chip_id);
        return false;
    }

    if (!bus.writeReg(BMP58X_I2C_ADDR, BMP58X_REG_ODR_CONFIG, BMP58X_FORCED_MODE))
        return false;

    sleep_ms(3);

    uint8_t data[3];
    if (!bus.readReg(BMP58X_I2C_ADDR, BMP58X_REG_TEMP_XLSB, data, 3))
        return false;

    *temp_out = BMP58xSensor::RawToTempC(data[0], data[1], data[2]);
    return true;
}

static bool verify_ulp_temp(I2cBus &bus, float *temp)
{
    bus.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    float reread;
    bool ok = bmp58x_direct_read(bus, &reread);
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
        release_i2c_pins_to_hp();
        return false;
    }

    *temp_out = RawToTempC((uint8_t)raw_0, (uint8_t)raw_1, (uint8_t)raw_2);
    LOGI("ULP temp: %.2f °C", *temp_out);
    if (!temp_is_plausible(*temp_out))
    {
        LOGI("ULP temp %.2f outside %.0f..%.0f — rejecting", *temp_out,
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
    if (!temp_is_plausible(*temp_out))
    {
        LOGI("LP core temp %.2f outside %.0f..%.0f — rejecting", *temp_out,
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
        if (!verify_ulp_temp(_i2c, temp_out))
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
