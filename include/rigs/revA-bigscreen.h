#pragma once
// Custom thermometer-c6 rev A (hardware/thermometer-c6) + GDEH0576T81
// (920x680, the 5.76" HD panel) + BMP581.
// envs: thermometer_c6_{debug,release,bod_probe} — this is their default rig.
//
// The target configuration for boards 2-4, whose panels are on order. Nothing
// has been flashed with it yet. Board 1 wears the 200x200 GDEY instead and
// needs RIG=revA-smallscreen — the rev A boards share one env, so that is the
// mismatch no cross-check here can catch.
// Boards 2-4 assembled, MACs unread.

#define USE_576_T81
#define USE_BMP58x

// Not optional here: the panel rail is hardware-gated through Q2, and
// Display.cpp #errors without this.
#define EPD_POWER_GATE

// Deployment default on this board — the LED only blinks on wake.
#define DISABLE_LEDS

#if !defined(IS_ULP_COCPU)
#if !defined(THERMOMETER_C6_BOARD)
#error "rig 'revA-bigscreen' needs a thermometer_c6_* env (-DTHERMOMETER_C6_BOARD)"
#endif
#if defined(SEEED_XIAO_EPD_BOARD)
#error "rig 'revA-bigscreen' is the custom board, not the Seeed ePaper shield"
#endif
#endif
