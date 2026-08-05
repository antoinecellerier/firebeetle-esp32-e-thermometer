#pragma once
// XIAO ESP32-C6 + Seeed ePaper Driver Board + GDEW029I6FD (296x128) + BMP581.
// MAC 58:e6:c5:16:1f:08. USB-Serial-JTAG, /dev/serial/by-id/*USB_JTAG*_58:E6:C5:16:1F:08.
// envs: seeed_xiao_esp32c6_epaper_{debug,release}

#define USE_290_I6FD
#define USE_BMP58x

// No EPD_POWER_GATE: the shield hardwires 3V3 to the booster and FPC, and
// Display.cpp #undefs the macro under SEEED_XIAO_EPD_BOARD anyway.

#if !defined(IS_ULP_COCPU)
#if !defined(SEEED_XIAO_EPD_BOARD)
#error "rig 'xiao-hat' needs a seeed_xiao_esp32c6_epaper_* env (-DSEEED_XIAO_EPD_BOARD)"
#endif
#if defined(THERMOMETER_C6_BOARD)
#error "rig 'xiao-hat' is the Seeed shield, not the custom thermometer-c6 board"
#endif
#endif
