#include "UlpProgram.h"

#if !defined(NO_ULP) && defined(SOC_ULP_FSM_SUPPORTED)

#include "esp32/ulp.h"
#include "hulp.h"
#include "hulp_i2cbb.h"

// BMP390L I2C address and registers
#define BMP390L_I2C_ADDR     0x77
#define BMP390L_REG_PWR_CTRL 0x1B
#define BMP390L_REG_TEMP_0   0x07  // temperature DATA_0 (bits [7:0])
#define BMP390L_REG_TEMP_1   0x08  // temperature DATA_1 (bits [15:8])
#define BMP390L_REG_TEMP_2   0x09  // temperature DATA_2 (bits [23:16])

// Forced mode: temp_en=1, press_en=1, mode=forced (0b01) → 0x13
#define BMP390L_FORCED_MODE  0x13

// I2C pin definitions — derived from common.h (HULP needs gpio_num_t)
#define I2C_BB_SCL  ((gpio_num_t)I2C_SCL_PIN)
#define I2C_BB_SDA  ((gpio_num_t)I2C_SDA_PIN)


// Configure GPIO pins for bit-bang I2C (no hardware RTC I2C peripheral).
void ulp_configure_i2c_bitbang()
{
  hulp_configure_pin(I2C_BB_SCL, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0);
  hulp_configure_pin(I2C_BB_SDA, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0);
  hulp_peripherals_on();
}


// GPIO12 = RTC_GPIO15. In RTC_GPIO_OUT_REG, data bits start at position 14,
// so RTC_GPIO15 is at bit 14 + 15 = 29.
#define RTC_GPIO15_OUT_BIT 29

void ulp_build_and_load_program()
{
  enum {
    LABEL_DATA_AREA = 1,
    LABEL_DO_WAKE = 2,
    LABEL_NO_WAKE = 3,
  };

#ifdef ULP_TEST_NO_I2C
  // Minimal test program: no I2C, just count cycles and wake every N.
  // Proves ULP timer, RTC memory sharing, and wake mechanism work.
  const ulp_insn_t program[] = {
#ifdef PPK2_DEBUG_ULP_GPIO
    // Pulse D13/GPIO12 HIGH for the duration of ULP execution
    I_WR_REG(RTC_GPIO_OUT_W1TS_REG, RTC_GPIO15_OUT_BIT, RTC_GPIO15_OUT_BIT, 1),
    // Hold HIGH for ~1ms so it's visible on PPK2 (150 cycles ≈ 1ms at 150 kHz RTC clock)
    I_DELAY(150),
#endif
    M_MOVL(R2, LABEL_DATA_AREA),

    // Increment sample count
    I_LD(R0, R2, ULP_VAR_SAMPLE_COUNT),
    I_ADDI(R0, R0, 1),
    I_ST(R0, R2, ULP_VAR_SAMPLE_COUNT),

    // If count >= ULP_TEST_WAKE_EVERY → wake main CPU
    M_BGE(LABEL_DO_WAKE, ULP_TEST_WAKE_EVERY),
#ifdef PPK2_DEBUG_ULP_GPIO
    I_WR_REG(RTC_GPIO_OUT_W1TC_REG, RTC_GPIO15_OUT_BIT, RTC_GPIO15_OUT_BIT, 1),
#endif
    I_HALT(),

    M_LABEL(LABEL_DO_WAKE),
    // Reset counter
    I_MOVI(R0, 0),
    I_ST(R0, R2, ULP_VAR_SAMPLE_COUNT),
    // Set wake_reason = 1
    I_MOVI(R0, 1),
    I_ST(R0, R2, ULP_VAR_WAKE_REASON),
#ifdef PPK2_DEBUG_ULP_GPIO
    I_WR_REG(RTC_GPIO_OUT_W1TC_REG, RTC_GPIO15_OUT_BIT, RTC_GPIO15_OUT_BIT, 1),
#endif
    I_WAKE(),
    I_HALT(),

    // Data area sentinel (program must not end on a macro pseudo-instruction)
    M_LABEL(LABEL_DATA_AREA),
    I_HALT(),
  };

#elif defined(ULP_TEST_I2C_MINIMAL)
  // Minimal I2C test using HULP bit-bang: read chip_id, store at FIXED addresses.
  // Avoids label-based data area to rule out addressing issues.
  // Results: RTC_SLOW_MEM[200]=chip_id, [201]=0xBB(success)/0xCC(nack)/0xDD(arblost), [202]=counter
  enum {
    LBL_I2C_RD = 10,
    LBL_I2C_WR = 11,
    LBL_I2C_ARBLOST = 12,
    LBL_I2C_NACK = 13,
    LBL_READ_DONE = 14,
  };

  const ulp_insn_t program[] = {
    // Increment counter at [202] to prove ULP runs
    I_MOVI(R2, 202),
    I_LD(R0, R2, 0),
    I_ADDI(R0, R0, 1),
    I_ST(R0, R2, 0),

    // Read chip ID register (0x00, expect 0x60 for BMP390L)
    M_I2CBB_RD(LBL_READ_DONE, LBL_I2C_RD, 0x00),

    // Success: store chip_id and marker
    I_MOVI(R2, 200),
    I_ST(R0, R2, 0),        // [200] = chip_id (expect 0x60)
    I_MOVI(R0, 0xBB),
    I_ST(R0, R2, 1),        // [201] = 0xBB = success
    I_WAKE(),
    I_HALT(),

    // NACK error
    M_LABEL(LBL_I2C_NACK),
    I_MOVI(R2, 200),
    I_MOVI(R0, 0),
    I_ST(R0, R2, 0),        // [200] = 0
    I_MOVI(R0, 0xCC),
    I_ST(R0, R2, 1),        // [201] = 0xCC = NACK
    I_WAKE(),
    I_HALT(),

    // Arblost error
    M_LABEL(LBL_I2C_ARBLOST),
    I_MOVI(R2, 200),
    I_MOVI(R0, 0),
    I_ST(R0, R2, 0),        // [200] = 0
    I_MOVI(R0, 0xDD),
    I_ST(R0, R2, 1),        // [201] = 0xDD = arblost
    I_WAKE(),
    I_HALT(),

    // Bit-bang I2C subroutine
    M_INCLUDE_I2CBB(LBL_I2C_RD, LBL_I2C_WR, LBL_I2C_ARBLOST, LBL_I2C_NACK,
                    I2C_BB_SCL, I2C_BB_SDA, BMP390L_I2C_ADDR),

    // Data area (still needed for ulp_build_and_load_program)
    M_LABEL(LABEL_DATA_AREA),
    I_HALT(),
  };

#else
  // Full BMP390L I2C program using HULP bit-bang I2C.
  //
  // Flow:
  //   1. Trigger BMP390L forced-mode measurement (I2C write to PWR_CTRL)
  //   2. Wait ~7ms for conversion
  //   3. Read 3 raw temperature bytes via I2C, store in RTC memory
  //   4. Compare DATA_1 with previous value
  //   5. If |delta| >= threshold: update reference, set wake_reason=1, WAKE
  //   6. Else: increment sample count, HALT (or WAKE if ULP_ALWAYS_WAKE)
  //
  // All data stored at fixed RTC_SLOW_MEM addresses (ULP_DATA_BASE + offset).
  enum {
    LBL_I2C_RD = 10,
    LBL_I2C_WR = 11,
    LBL_I2C_ARBLOST = 12,
    LBL_I2C_NACK = 13,
    LBL_WR_DONE = 14,
    LBL_RD0_DONE = 15,
    LBL_RD1_DONE = 16,
    LBL_RD2_DONE = 17,
  };

  const ulp_insn_t program[] = {
    // 1. Trigger forced-mode measurement
    M_I2CBB_WR(LBL_WR_DONE, LBL_I2C_WR, BMP390L_REG_PWR_CTRL, BMP390L_FORCED_MODE),

    // 2. Wait ~7ms for conversion (8 MHz RTC_FAST_CLK × 0.007s = 56000 cycles)
    I_DELAY(56000),

    // 3. Read 3 raw temperature bytes
    M_I2CBB_RD(LBL_RD0_DONE, LBL_I2C_RD, BMP390L_REG_TEMP_0),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_0),

    M_I2CBB_RD(LBL_RD1_DONE, LBL_I2C_RD, BMP390L_REG_TEMP_1),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_1),

    M_I2CBB_RD(LBL_RD2_DONE, LBL_I2C_RD, BMP390L_REG_TEMP_2),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_2),

    // Increment sample count
    I_MOVI(R2, ULP_DATA_BASE),
    I_LD(R0, R2, ULP_VAR_SAMPLE_COUNT),
    I_ADDI(R0, R0, 1),
    I_ST(R0, R2, ULP_VAR_SAMPLE_COUNT),

#ifdef ULP_ALWAYS_WAKE
    // Debug: always wake main CPU so we can validate I2C readings
    I_MOVI(R0, 1),
    I_ST(R0, R2, ULP_VAR_WAKE_REASON),
    I_WAKE(),
    I_HALT(),
#else
    // 4. Delta comparison: current DATA_1 vs previous
    I_LD(R0, R2, ULP_VAR_TEMP_1),
    I_LD(R1, R2, ULP_VAR_PREV_TEMP_MSB),
    I_SUBR(R0, R0, R1),

    // Small positive delta below threshold → no_wake
    M_BL(LABEL_NO_WAKE, ULP_TEMP_DELTA_THRESHOLD),

    // R0 >= threshold. If < 0x8000 it's a genuine positive delta → do_wake
    M_BL(LABEL_DO_WAKE, 0x8000),

    // R0 >= 0x8000: negative delta (underflow). Negate to get |delta|.
    I_MOVI(R1, 0),
    I_SUBR(R0, R1, R0),
    M_BL(LABEL_NO_WAKE, ULP_TEMP_DELTA_THRESHOLD),

    M_LABEL(LABEL_DO_WAKE),
    I_MOVI(R2, ULP_DATA_BASE),
    I_LD(R0, R2, ULP_VAR_TEMP_1),
    I_ST(R0, R2, ULP_VAR_PREV_TEMP_MSB),
    I_MOVI(R0, 1),
    I_ST(R0, R2, ULP_VAR_WAKE_REASON),
    I_WAKE(),
    I_HALT(),

    M_LABEL(LABEL_NO_WAKE),
    I_HALT(),
#endif

    // I2C error handlers
    M_LABEL(LBL_I2C_NACK),
    M_LABEL(LBL_I2C_ARBLOST),
    I_MOVI(R2, ULP_DATA_BASE),
    I_MOVI(R0, 2),
    I_ST(R0, R2, ULP_VAR_WAKE_REASON),
    I_WAKE(),
    I_HALT(),

    // Bit-bang I2C subroutine
    M_INCLUDE_I2CBB(LBL_I2C_RD, LBL_I2C_WR, LBL_I2C_ARBLOST, LBL_I2C_NACK,
                    I2C_BB_SCL, I2C_BB_SDA, BMP390L_I2C_ADDR),
  };
#endif

  size_t program_size = sizeof(program) / sizeof(ulp_insn_t);
  ESP_ERROR_CHECK(ulp_process_macros_and_load(0, program, &program_size));

  // Zero the data area at fixed ULP_DATA_BASE address
  for (int i = 0; i < ULP_VAR_COUNT; i++)
    RTC_SLOW_MEM[ULP_DATA_BASE + i] = 0;
}


void ulp_start()
{
  ulp_set_wakeup_period(0, ULP_WAKEUP_PERIOD_US);
  ESP_ERROR_CHECK(ulp_run(0));
}


uint16_t ulp_read_var(size_t data_offset, enum ulp_var_offset var)
{
  return RTC_SLOW_MEM[data_offset + var] & 0xFFFF;
}

void ulp_write_var(size_t data_offset, enum ulp_var_offset var, uint16_t value)
{
  RTC_SLOW_MEM[data_offset + var] = value;
}

#endif