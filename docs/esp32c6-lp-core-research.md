# ESP32-C6 LP Core: ULP Support Research

## Architecture Difference

The ESP32 (original) has a **ULP FSM** — a simple finite state machine programmed in assembly. The current codebase uses the HULP library to generate assembly instructions for bit-bang I2C.

The ESP32-C6 has an **LP (Low-Power) RISC-V core** instead:
- Programmable in **C** (not assembly)
- Has dedicated peripherals: **LP I2C**, LP UART, LP GPIO
- Runs as a separate ELF binary loaded into LP memory
- Much more capable — normal C code with loops, conditionals, etc.

**HULP does not support the C6** — it targets the ULP FSM instruction set only.

## LP I2C Hardware Peripheral

The C6's LP core has a **hardware I2C peripheral** (no bit-banging needed). Default LP I2C pins:
- **GPIO6** = LP I2C SDA
- **GPIO7** = LP I2C SCL

Hardware I2C is more reliable and power-efficient than HULP's bit-bang approach. The BMP390L would need to be wired to these pins.

## Programming Model

The LP core program is built as a **separate compilation unit** in ESP-IDF:

```
main/
  main.c              # main CPU code
  ulp/
    lp_core_main.c    # LP core code (runs independently during deep sleep)
```

Key APIs:
- `lp_core_i2c_master_read_from_device()` for I2C reads
- Shared variables via `ulp_` prefix (similar to current ULP FSM shared vars)
- `ulp_lp_core_wakeup_main_processor()` to wake main CPU

### Minimal LP Core BMP390L Reader

```c
// lp_core_main.c
#include "ulp_lp_core.h"
#include "ulp_lp_core_i2c.h"

#define BMP390L_ADDR 0x77
#define REG_TEMP_DATA 0x07

uint32_t temp_raw;
uint32_t wake_reason;

int main(void) {
    // Trigger forced measurement
    uint8_t cmd[] = {0x7E, 0x13};  // PWR_CTRL: temp+press+forced
    lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP390L_ADDR, cmd, 2, 100);

    // Wait for conversion (~5ms)
    // ... LP core delay ...

    // Read 3 temperature bytes
    uint8_t reg = REG_TEMP_DATA;
    uint8_t data[3];
    lp_core_i2c_master_write_to_device(LP_I2C_NUM_0, BMP390L_ADDR, &reg, 1, 100);
    lp_core_i2c_master_read_from_device(LP_I2C_NUM_0, BMP390L_ADDR, data, 3, 100);

    temp_raw = data[0] | (data[1] << 8) | (data[2] << 16);

    // Compare with previous, wake main CPU if changed
    // ...
    ulp_lp_core_wakeup_main_processor();
}
```

This is dramatically simpler than the HULP assembly macro approach.

## Framework Support

### The Challenge: pioarduino's Pre-compiled Libs

The C6 target uses the pioarduino platform fork (Arduino Core 3.x on ESP-IDF 5.x). The pre-compiled Arduino libraries ship with `CONFIG_ULP_COPROC_ENABLED=0`, so the standard ESP-IDF ULP loader functions (`ulp_lp_core_load_binary()`, `ulp_lp_core_run()`, `lp_core_i2c_master_init()`) are **missing** from the linked libraries.

### Solution: Custom Platform Fork

A fork of `platform-espressif32` at `/home/antoine/stuff/platform-espressif32` (branch `feature/lp-core-ulp-arduino`) adds LP core ULP support for Arduino-only PlatformIO projects:

- Auto-detects `ulp/` directory in the project
- Compiles LP core sources with `riscv32-esp-elf-gcc`
- Injects required sdkconfig options (`CONFIG_ULP_COPROC_ENABLED`, etc.)
- Patches `memory.ld` to reserve LP SRAM
- Generates symbol header (`ulp_main.h`) via `esp32ulp_mapgen.py`
- Adds the mapgen `.ld` to main firmware linker flags so `ulp_*` symbols resolve

C6 envs in `platformio.ini` reference the fork via `platform = /home/antoine/stuff/platform-espressif32`.

### Build Evolution (historical context)

The LP core build went through three iterations:

1. **Custom Python build script** (`scripts/build_lp_core.py`) — auto-downloaded ~30 ESP-IDF source files from GitHub, compiled with the RISC-V toolchain, generated binary + symbol headers. Worked but was complex and fragile.
2. **pioarduino `custom_sdkconfig` hybrid build** — setting `CONFIG_ULP_COPROC_ENABLED=y` triggers a hybrid compile mode that recompiles ESP-IDF libs. This pulled in managed components (esp_insights, esp_rainmaker) that need certificate files even when unused, and created other complications.
3. **Platform fork** (current) — cleanest solution. The fork handles everything transparently. No extra scripts, no managed_components issues.

### PMP and LP SRAM Access (critical gotcha)

Without `CONFIG_ULP_COPROC_ENABLED`, the ESP32-C6's PMP (Physical Memory Protection) marks LP SRAM at 0x50000000 as RX-only (no write). Any attempt to load an LP core binary at runtime causes a **Store access fault** (Guru Meditation Error, MCAUSE=0x07, MTVAL=0x50000000). The platform fork injects the required sdkconfig to fix PMP permissions.

## Current Implementation

### File Structure

```
ulp/
  lp_core_main.c             # LP core program (LP_CORE_IDLE test mode or BMP390L I2C)
src/
  sensors/BMP390LSensor.cpp   # Three compile paths: ULP FSM, LP core, no-ULP
```

### Conditional Compilation

`BMP390LSensor.cpp` uses ifdefs within a single file:
- `#if SOC_ULP_FSM_SUPPORTED` — ESP32 ULP FSM path (HULP bit-bang I2C)
- `#if SOC_LP_CORE_SUPPORTED` — ESP32-C6 LP core path (hardware LP I2C)
- Fallback — no-ULP stubs

Temperature compensation math (`BMP390LCompensation.cpp`) stays identical — it runs on the main CPU regardless of which coprocessor collects the raw ADC values.

## Compile-Time Detection

ESP-IDF provides SoC capability macros:
- `SOC_ULP_FSM_SUPPORTED` — ESP32 (original)
- `SOC_LP_CORE_SUPPORTED` — ESP32-C6, ESP32-C5
- `SOC_ULP_SUPPORTED` — any ULP variant

These can replace or complement the manual `NO_ULP` build flag.

## Status

**LP core idle mode tested on hardware.** Both ESP32-E (ULP FSM) and ESP32-C6 (LP core) targets compile and link. LP_CORE_IDLE mode (no I2C, simulated sensor timing) has been verified on a bare XIAO ESP32C6 with PPK2 power measurements (see `docs/notes.md`).

Remaining work:
- Solder BMP390L to C6 board, then switch `ulp/lp_core_main.c` from `#define LP_CORE_IDLE` to BMP390L I2C mode
- Verify LP I2C communication with BMP390L (GPIO6=SDA, GPIO7=SCL)
- Tune TEMP_DELTA_THRESHOLD (currently 20 ≈ 0.1°C) and SLEEP_INTERVAL_S (60s for production)
- Measure LP core power with real I2C transactions vs idle delay
