#pragma once
// Custom thermometer-c6 rev A (hardware/thermometer-c6) + GDEY0213M21
// (212x104, the 2.13" DES panel) + BMP581.
//
// BENCH RIG, not a deployment: the 2.13" panel is a 2021-era prototype spare
// (USE_213_M21 dates to 361248f, 2021-11-26) kept for panel-fault work. It
// exists so a mismatched-panel run has a control — proving the panel is
// electrically alive is what separates "wrong driver" from "dead panel", and
// without it a BUSY reading means nothing.
//
// No env selects it. Ask for it explicitly, and expect the upload gate to
// object, since it is by definition a panel swap:
//
//     ALLOW_RIG_CHANGE=1 RIG=revA-213m21 pio run -e thermometer_c6_debug -t upload
//
// 24-pin 0.5mm FPC, the same Good Display pinout the board's connector carries,
// so the as-shipped JP2 0.47Ω + JP5 10µH needs no change (README: 10µH is proven
// on all panels).
//
// Board 2 MAC 98:88:e0:75:48:10, USB-Serial-JTAG.

#define USE_213_M21
#define USE_BMP58x

// Not optional here: the panel rail is hardware-gated through Q2, and
// Display.cpp #errors without this.
#define EPD_POWER_GATE

// Left on: this rig only ever runs attended, on USB, and the panel-fault blink
// is one of the things being exercised.
//#define DISABLE_LEDS

#if !defined(IS_ULP_COCPU)
#if !defined(THERMOMETER_C6_BOARD)
#error "rig 'revA-213m21' needs a thermometer_c6_* env (-DTHERMOMETER_C6_BOARD)"
#endif
#if defined(SEEED_XIAO_EPD_BOARD)
#error "rig 'revA-213m21' is the custom board, not the Seeed ePaper shield"
#endif
#endif
