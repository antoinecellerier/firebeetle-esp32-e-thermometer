#pragma once
// FireBeetle 2 ESP32-E + DESPI-C02 + GDEH0154Z90 (200x200 tri-color) + BMP390L.
// The only ESP32-E rig, and the only tri-color panel in the fleet.
// MAC c4:5b:be:8c:4d:b8. CH340 bridge, enumerates as /dev/ttyUSB* (a real UART:
// DTR/RTS drive EN/BOOT, so the host can reset it).
// envs: dfrobot_firebeetle2_esp32e_{debug,release}

#define USE_154_Z90
#define USE_BMP390L

// DESPI-C02: ungated the panel is dark permanently and the floor goes
// 19.4uA -> ~562uA (docs/history-store-validation.md, 2026-08-05).
#define EPD_POWER_GATE

// Required until Adafruit_NeoPixel is vendored — Thermometer.cpp includes its
// header and components/ does not carry it, so the E build does not link with
// LEDs enabled. A packaging gap, not a property of the board.
#define DISABLE_LEDS

#if !defined(IS_ULP_COCPU)
#if !defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#error "rig 'firebeetle' needs a dfrobot_firebeetle2_esp32e_* env (IDF_TARGET=esp32)"
#endif
#if defined(SEEED_XIAO_EPD_BOARD) || defined(THERMOMETER_C6_BOARD)
#error "rig 'firebeetle' is not a C6 carrier board"
#endif
#endif
