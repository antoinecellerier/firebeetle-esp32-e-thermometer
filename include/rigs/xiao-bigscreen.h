#pragma once
// XIAO ESP32-C6 + DESPI-C02 + GDEH0576T81 (920x680, the 5.76" HD panel) + BMP581.
// MAC 58:e6:c5:13:9b:e4. USB-Serial-JTAG.
// envs: seeed_xiao_esp32c6_{debug,release}

#define USE_576_T81
#define USE_BMP58x

// DESPI-C02: ungated the panel is dark permanently and the floor collapses.
#define EPD_POWER_GATE

#if !defined(IS_ULP_COCPU)
#if !defined(ARDUINO_XIAO_ESP32C6)
#error "rig 'xiao-bigscreen' needs a seeed_xiao_esp32c6_* env (IDF_TARGET=esp32c6)"
#endif
// This rig is the plain XIAO on a DESPI-C02: neither carrier-board variant.
#if defined(SEEED_XIAO_EPD_BOARD)
#error "rig 'xiao-bigscreen' is on a DESPI-C02, not the Seeed ePaper shield"
#endif
#if defined(THERMOMETER_C6_BOARD)
#error "rig 'xiao-bigscreen' is a stock XIAO, not the custom thermometer-c6 board"
#endif
#endif
