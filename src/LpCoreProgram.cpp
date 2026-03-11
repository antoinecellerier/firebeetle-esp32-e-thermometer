// LP core loader for ESP32-C6.
//
// Reimplements ulp_lp_core_load_binary() and ulp_lp_core_run() using
// available LL/HAL inline functions, since the pioarduino Arduino libs
// don't include the ULP component.
//
// Pattern matches the official ESP-IDF lp_adc example:
// - LP core main() returns after each iteration
// - LP core startup code re-arms LP timer and halts
// - LP timer periodically wakes LP core
// - LP core explicitly calls wakeup_main_processor() when needed
//
// Reference: esp-idf/components/ulp/lp_core/lp_core.c
//            esp-idf/examples/system/ulp/lp_core/lp_adc/

#include "LpCoreProgram.h"

#if defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED && !defined(NO_ULP)

#include <string.h>
#include "soc/soc.h"
#include "hal/lp_core_ll.h"
#include "hal/i2c_ll.h"
#include "hal/i2c_hal.h"
#include "hal/misc.h"
#include "driver/rtc_io.h"
#include "soc/i2c_periph.h"
#include "esp_private/periph_ctrl.h"
#include "esp_private/esp_clk_tree_common.h"

// LP timer — for setting first wakeup and calculating ticks
#include "hal/lp_timer_ll.h"
#include "hal/lp_timer_hal.h"
#include "hal/clk_tree_ll.h"

#ifndef RTC_CLK_CAL_FRACT
#define RTC_CLK_CAL_FRACT 19
#endif

// ---------- LP I2C initialization (main CPU side) ----------

// LP I2C default pins on ESP32-C6
#define LP_I2C_SDA_PIN  GPIO_NUM_6
#define LP_I2C_SCL_PIN  GPIO_NUM_7

// I2C HAL context (static, used only during init)
static i2c_hal_context_t lp_i2c_hal;

static void lp_i2c_configure_pin(gpio_num_t pin, bool pullup_en)
{
    rtc_gpio_set_level(pin, 1); // avoid spurious start condition
    rtc_gpio_init(pin);
    rtc_gpio_set_direction(pin, RTC_GPIO_MODE_INPUT_OUTPUT_OD);
    rtc_gpio_pulldown_dis(pin);
    if (pullup_en) {
        rtc_gpio_pullup_en(pin);
    } else {
        rtc_gpio_pullup_dis(pin);
    }
}

void lp_core_i2c_setup()
{
    // Configure GPIO pins for LP I2C (SCL first to avoid spurious start)
    lp_i2c_configure_pin(LP_I2C_SCL_PIN, true);
    lp_i2c_configure_pin(LP_I2C_SDA_PIN, true);

    // Set IOMUX function for LP I2C
    const i2c_signal_conn_t *p_i2c_pin = &i2c_periph_signal[LP_I2C_NUM_0];
    rtc_gpio_iomux_func_sel(LP_I2C_SDA_PIN, p_i2c_pin->iomux_func);
    rtc_gpio_iomux_func_sel(LP_I2C_SCL_PIN, p_i2c_pin->iomux_func);

    // Enable LP I2C bus clock and reset
    PERIPH_RCC_ATOMIC() {
        lp_i2c_ll_enable_bus_clock(0, true);
        lp_i2c_ll_reset_register(0);
        i2c_hal_init(&lp_i2c_hal, LP_I2C_NUM_0);
    }

    // Clear pending interrupts
    i2c_ll_clear_intr_mask(lp_i2c_hal.dev, UINT32_MAX);

    // Initialize as I2C master
    i2c_hal_master_init(&lp_i2c_hal);

    // Internal open-drain mode
    lp_i2c_hal.dev->ctr.sda_force_out = 0;
    lp_i2c_hal.dev->ctr.scl_force_out = 0;

    // Configure clock — LP_FAST_CLK source, 400 kHz I2C
    uint32_t source_freq = 0;
    esp_clk_tree_src_get_freq_hz((soc_module_clk_t)LP_I2C_SCLK_LP_FAST,
                                  ESP_CLK_TREE_SRC_FREQ_PRECISION_APPROX,
                                  &source_freq);
    PERIPH_RCC_ATOMIC() {
        lp_i2c_ll_set_source_clk(lp_i2c_hal.dev, LP_I2C_SCLK_LP_FAST);
        i2c_hal_set_bus_timing(&lp_i2c_hal, 400000,
                                (i2c_clock_source_t)LP_I2C_SCLK_LP_FAST,
                                source_freq);
    }

    // SDA/SCL filtering (matches HP I2C defaults)
    i2c_ll_master_set_filter(lp_i2c_hal.dev, 7);

    // NACK when Rx FIFO full
    i2c_ll_master_rx_full_ack_level(lp_i2c_hal.dev, 1);

    // Sync config to LP I2C peripheral
    i2c_ll_update(lp_i2c_hal.dev);
}

// ---------- LP core binary loader ----------

void lp_core_load_binary(const uint8_t *bin, size_t size)
{
    // Stop LP core if running
    lp_core_stop();

    // Enable LP core bus clock so LP SRAM at 0x50000000 is accessible
    PERIPH_RCC_ATOMIC() {
        lp_core_ll_reset_register();
        lp_core_ll_enable_bus_clock(true);
    }

    // C6 without LP ROM: binary goes to RTC_SLOW_MEM (0x50000000)
    uint32_t *base = (uint32_t *)SOC_RTC_DRAM_LOW;

    // Zero reserved memory (including .bss), then copy binary
    memset(base, 0, LP_CORE_RESERVE_MEM);
    memcpy(base, bin, size);
}

// ---------- LP timer helpers ----------

static uint64_t lp_timer_calculate_ticks(uint64_t us)
{
    return (us * (1ULL << RTC_CLK_CAL_FRACT)) / clk_ll_rtc_slow_load_cal();
}

// Set LP timer alarm for LP core wakeup (target 1, LP interrupt path).
// Uses lp_timer_ll_clear_lp_alarm_intr_status (LP interrupt), not
// lp_timer_ll_clear_alarm_intr_status (HP interrupt).
static void lp_timer_set_wakeup(uint64_t us)
{
    uint64_t target = lp_timer_hal_get_cycle_count() + lp_timer_calculate_ticks(us);
    lp_timer_ll_clear_lp_alarm_intr_status(&LP_TIMER);
    lp_timer_ll_set_alarm_target(&LP_TIMER, 1, target);
    lp_timer_ll_set_target_enable(&LP_TIMER, 1, true);
}

// ---------- LP core start/stop ----------

void lp_core_start(uint64_t wakeup_period_us)
{
    PERIPH_RCC_ATOMIC() {
        lp_core_ll_reset_register();
        lp_core_ll_enable_bus_clock(true);
    }

    // Configure LP core behavior
    lp_core_ll_stall_at_sleep_request(true);
    lp_core_ll_rst_at_sleep_enable(true);

    // Disable debug module to save power during sleep
    lp_core_ll_debug_module_enable(false);

    // Set wake-up source: LP timer
    lp_core_ll_set_wakeup_source(LP_CORE_LL_WAKEUP_SOURCE_LP_TIMER);

    // Write sleep duration to shared memory so LP core startup code
    // can re-arm the timer after each main() return.
    uint32_t *base = (uint32_t *)SOC_RTC_DRAM_LOW;
    uint64_t *shared_mem = (uint64_t *)(base + (LP_CORE_RESERVE_MEM - LP_CORE_SHARED_MEM) / sizeof(uint32_t));
    shared_mem[0] = wakeup_period_us;                           // sleep_duration_us
    shared_mem[1] = lp_timer_calculate_ticks(wakeup_period_us); // sleep_duration_ticks

    // Set first wakeup alarm
    lp_timer_set_wakeup(wakeup_period_us);
}

void lp_core_stop()
{
    lp_core_ll_set_wakeup_source(0);
    lp_core_ll_request_sleep();
}

#endif // SOC_LP_CORE_SUPPORTED && !NO_ULP
