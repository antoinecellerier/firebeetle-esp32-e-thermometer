// Minimal sdkconfig for LP core binary compilation on ESP32-C6.
// Only defines needed by the LP core startup code, I2C driver, and shared memory.
#pragma once

#define CONFIG_IDF_TARGET_ESP32C6 1
#define CONFIG_IDF_TARGET_ARCH_RISCV 1

// ULP coprocessor configuration
#define CONFIG_ULP_COPROC_ENABLED 1
#define CONFIG_ULP_COPROC_TYPE_LP_CORE 1
#define CONFIG_ULP_COPROC_RESERVE_MEM 8192
#define CONFIG_ULP_SHARED_MEM 16  // sizeof(ulp_lp_core_memory_shared_cfg_t)

// Disable features to minimize dependencies
#define CONFIG_ULP_PANIC_OUTPUT_ENABLE 0
#define CONFIG_ULP_HP_UART_CONSOLE_PRINT 0
#define CONFIG_ULP_ROM_PRINT_ENABLE 0
#define CONFIG_ULP_NORESET_UNDER_DEBUG 0

// Logging (needed by hal headers that include esp_log.h)
#define CONFIG_LOG_DEFAULT_LEVEL 0   // ESP_LOG_NONE — no logging on LP core
#define CONFIG_LOG_MAXIMUM_LEVEL 0

// C6 has no LP ROM
// ESP_ROM_HAS_LP_ROM intentionally NOT defined
