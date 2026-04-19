// ULP FSM program for BMP58x (BMP581/BMP585) temperature polling via HULP bit-bang I2C.
//
// BMP58x output is already compensated — no NVM calibration needed.
// OSR_CONFIG is written once by the main CPU in Initialize(); this loop only
// triggers forced-mode measurements.
//
// Flow:
//   1. Trigger forced-mode measurement via I2C write to ODR_CONFIG
//   2. Wait ~2ms for conversion
//   3. Read 3 temperature bytes via I2C, store in RTC memory
//   4. Compare DATA_1 with previous value
//   5. If |delta| >= threshold: update reference, set wake_reason=1, WAKE
//   6. Else: increment sample count, HALT (or WAKE if ULP_ALWAYS_WAKE)

#include "UlpProgram.h"

#if !defined(NO_ULP) && defined(SOC_ULP_FSM_SUPPORTED) && defined(USE_BMP58x)

#include "esp32/ulp.h"
#include "hulp.h"
#include "hulp_i2cbb.h"

#define BMP58X_I2C_ADDR       0x47
#define BMP58X_REG_ODR_CONFIG 0x37
#define BMP58X_REG_TEMP_XLSB  0x1D
#define BMP58X_REG_TEMP_LSB   0x1E
#define BMP58X_REG_TEMP_MSB   0x1F
// pwr_mode = BMP5_POWERMODE_FORCED per Bosch bmp5_defs.h
#define BMP58X_FORCED_MODE    0x02

#define I2C_BB_SCL  ((gpio_num_t)I2C_SCL_PIN)
#define I2C_BB_SDA  ((gpio_num_t)I2C_SDA_PIN)

void ulp_build_and_load_program()
{
  enum {
    LABEL_DO_WAKE = 2,
    LABEL_NO_WAKE = 3,
    LBL_I2C_RD = 10,
    LBL_I2C_WR = 11,
    LBL_I2C_ARBLOST = 12,
    LBL_I2C_NACK = 13,
    LBL_WR_ODR_DONE = 15,
    LBL_RD0_DONE = 16,
    LBL_RD1_DONE = 17,
    LBL_RD2_DONE = 18,
  };

  const ulp_insn_t program[] = {
    // 1. Trigger forced-mode measurement
    M_I2CBB_WR(LBL_WR_ODR_DONE, LBL_I2C_WR, BMP58X_REG_ODR_CONFIG, BMP58X_FORCED_MODE),

    // 2. Wait ~2ms for conversion (8 MHz RTC_FAST_CLK × 0.002s = 16000 cycles)
    I_DELAY(16000),

    // 3. Read 3 temperature bytes (XLSB, LSB, MSB)
    M_I2CBB_RD(LBL_RD0_DONE, LBL_I2C_RD, BMP58X_REG_TEMP_XLSB),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_0),

    M_I2CBB_RD(LBL_RD1_DONE, LBL_I2C_RD, BMP58X_REG_TEMP_LSB),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_1),

    M_I2CBB_RD(LBL_RD2_DONE, LBL_I2C_RD, BMP58X_REG_TEMP_MSB),
    I_MOVI(R2, ULP_DATA_BASE),
    I_ST(R0, R2, ULP_VAR_TEMP_2),

    // Increment sample count
    I_MOVI(R2, ULP_DATA_BASE),
    I_LD(R0, R2, ULP_VAR_SAMPLE_COUNT),
    I_ADDI(R0, R0, 1),
    I_ST(R0, R2, ULP_VAR_SAMPLE_COUNT),

#ifdef ULP_ALWAYS_WAKE
    I_MOVI(R0, 1),
    I_ST(R0, R2, ULP_VAR_WAKE_REASON),
    I_WAKE(),
    I_HALT(),
#else
    // 4. Delta comparison: current DATA_1 vs previous
    I_LD(R0, R2, ULP_VAR_TEMP_1),
    I_LD(R1, R2, ULP_VAR_PREV_TEMP_MSB),
    I_SUBR(R0, R0, R1),

    M_BL(LABEL_NO_WAKE, ULP_TEMP_DELTA_THRESHOLD),
    M_BL(LABEL_DO_WAKE, 0x8000),

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
                    I2C_BB_SCL, I2C_BB_SDA, BMP58X_I2C_ADDR),
  };

  size_t program_size = sizeof(program) / sizeof(ulp_insn_t);
  ESP_ERROR_CHECK(ulp_process_macros_and_load(0, program, &program_size));

  for (int i = 0; i < ULP_VAR_COUNT; i++)
    RTC_SLOW_MEM[ULP_DATA_BASE + i] = 0;
}

#endif
