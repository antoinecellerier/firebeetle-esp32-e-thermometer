#pragma once
// Rig template — copy this file to include/rigs/<name>.h and uncomment what is
// wired. A "rig" is one hardware configuration: board + panel + sensor + the
// flags that follow from them. This file is the list of valid options.
//
// The leading underscore keeps it out of the rig glob; selecting it is an error.
//
// Selection: each [env:...] in platformio.ini names its rig with
// `custom_rig = <name>`, so `pio run -e <env> -t upload` needs nothing else.
// `RIG=<name>` overrides for the exceptions (a bench panel swap, a second board
// on the same env). idf.py takes `-DRIG=<name>`.
//
// To add a rig:
//   1. Copy to include/rigs/<name>.h and describe the rig in the top comment,
//      including its MAC and how it enumerates. RIG_NAME is derived from the
//      filename by the generator, so there is nothing to keep in sync.
//   2. Uncomment one panel and one sensor, plus any flags below.
//   3. Fill in the cross-check block so a wrong env fails the build.
//   4. Add `custom_rig = <name>` to its env(s) in platformio.ini.
//
// To add a *panel* the project has never driven, seven places must agree:
//   1. the menu below
//   2. include/displays.h        — DISPLAY_HAS_RED / DISPLAY_ROTATION
//   3. src/Display.cpp           — the GxEPD2 driver type and its include, plus
//                                  EPD_BUSY_TIMEOUT_MS if the panel's GxEPD2
//                                  constructor does not pass the usual 10s
//   4. src/HistoryStore.cpp      — panel_name(), burned into the archive header
//   5. scripts/generate_font.py  — the DISPLAYS dict (resolution)
//   6. tools/sim/sim_main.cpp    — the displays[] table
//   7. components/gxepd2/CMakeLists.txt — the panel .cpp, or the link fails on a
//      missing vtable that names nothing useful
// Wiring for panels and sensors is in docs/wiring.md.

// --- Panel (exactly one) ---------------------------------------------------
//#define USE_154_Z90   // Tri-Color 200x200 1.54" (GDEH0154Z90) with 15s full refresh
//#define USE_154_M09   // Bi-Color 200x200 1.54" (GDEH0154M09), partial updates, 0.83s full refresh
//#define USE_154_GDEY  // Bi-Color 200x200 1.54" flexible (GDEM0154I61 via GDEY0154D67 compat driver, SSD1681)
//#define USE_213_M21   // Bi-Color 212x104 2.13" DES (GDEY0213M21) with 3s full refresh
//#define USE_290_I6FD  // Bi-Color 296x128 2.9" flexible (GDEW029I6FD, UC8151D) with partial updates
//#define USE_576_T81   // Bi-Color 920x680 5.76" HD (GDEH0576T81, SSD2677) with partial updates
//#define DISABLE_DISPLAY // no panel wired; suppresses the "no display selected" error

// --- Sensor (exactly one) --------------------------------------------------
//#define USE_BMP390L      // Bosch BMP390L, I2C 0x77, ULP-capable (FSM and LP core)
//#define USE_BMP58x       // Bosch BMP581/BMP585, I2C 0x47, ULP-capable; output already in C
//#define USE_DS18B20_PAR  // Maxim DS18B20 1-Wire, parasitic power, no ULP support
//#define USE_DUMMY_SENSOR // synthetic readings for bench work; shows "! DUMMY" on the panel

// --- Flags -----------------------------------------------------------------
// Panel VCC gated by a P-FET (GPIO13/D7 on the E, D7 on the XIAO, GPIO14 on the
// custom board). MANDATORY on every DESPI-C02 rig: ungated the panel is dark
// permanently with no diagnostic, and the sleep floor goes 19.4uA -> ~562uA.
// The Seeed ePaper shield hardwires its rail and #undefs this in Display.cpp.
//#define EPD_POWER_GATE

// Onboard status LED off. Required on the ESP32-E for now: Thermometer.cpp
// includes Adafruit_NeoPixel.h and that library is not vendored, so the build
// does not link with LEDs enabled.
//
// One path ignores this: epd_fault_blink() drives the LED anyway when the panel
// stops answering. That fault is the only one the status line cannot report —
// the panel is what broke — and release builds have no console, so the LED is
// the whole signal. C6 boards only, for the vendoring reason above.
//#define DISABLE_LEDS

// Bench knobs are NOT rig properties — pass them as build flags instead:
// DISABLE_SERIAL (already in [release]), DISABLE_WIFI, NO_ULP, MOCK_DISPLAY_DATA.

// --- Cross-check -----------------------------------------------------------
// Turns "flashed the wrong rig" into a build error. THERMOMETER_C6_BOARD and
// SEEED_XIAO_EPD_BOARD are sub-variants of ARDUINO_XIAO_ESP32C6 — both are
// defined at once — so assert on their absence too, not just on the target.
//
// The LP core sub-build compiles with -DIS_ULP_COCPU and nothing else (no board
// macros at all: IDFULPProject.cmake:107,159), so the guard below is required or
// every C6 build breaks.
#if !defined(IS_ULP_COCPU)
#if !defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E) && !defined(ARDUINO_XIAO_ESP32C6)
#error "rig template: fill in the cross-check for this rig's board"
#endif
#endif
