#pragma once
// Custom thermometer-c6 rev A (hardware/thermometer-c6) + GDEM0154I61
// (200x200, via the GDEY0154D67 compat driver) + BMP581.
//
// Board 1, on battery soak since 2026-07-31. It shares its envs with
// revA-bigscreen, which is their default, so this rig must be asked for:
//
//     RIG=revA-smallscreen pio run -e thermometer_c6_release -t upload
//
// Board 1 MAC 98:88:e0:75:47:9c, USB-Serial-JTAG.

#define USE_154_GDEY
#define USE_BMP58x

// Not optional here: the panel rail is hardware-gated through Q2, and
// Display.cpp #errors without this.
#define EPD_POWER_GATE

// LED wake blinks withdrawn for the soak.
#define DISABLE_LEDS

#if !defined(IS_ULP_COCPU)
#if !defined(THERMOMETER_C6_BOARD)
#error "rig 'revA-smallscreen' needs a thermometer_c6_* env (-DTHERMOMETER_C6_BOARD)"
#endif
#if defined(SEEED_XIAO_EPD_BOARD)
#error "rig 'revA-smallscreen' is the custom board, not the Seeed ePaper shield"
#endif
#endif
