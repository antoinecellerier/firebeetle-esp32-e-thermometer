#pragma once
// Custom thermometer-c6 rev A (hardware/thermometer-c6) + GDEH0576T81
// (920x680, the 5.76" HD panel) + BMP581.
// envs: thermometer_c6_{debug,release,bod_probe} — this is their default rig.
//
// The deployment configuration for boards 2-4. Panels arrived 2026-08-11 and
// board 2 drove one that day — on the factory bridges (JP2 0.47R + JP5 10uH),
// no rework. Board 1 wears the 200x200 GDEY instead and needs
// RIG=revA-smallscreen — the rev A boards share one env, so that is the
// mismatch no cross-check here can catch.
// Boards 2-4 assembled, all three brought up and rendering. MACs read off the
// USB-JTAG serial (the archive header records the EUI-64 form, see
// store_write_header()):
//   board 2  98:88:e0:75:48:10  (2026-08-05)
//   board 3  98:88:e0:75:47:94  (2026-08-12)
//   board 4  10:bd:a3:a8:d3:64  (2026-08-12)
// Board 3's MAC differs from board 1's (98:88:e0:75:47:9c, revA-smallscreen) in
// the last byte only — read it fully before assuming which board is on the bus.
//
// This panel's FPC contacts face the BACK, opposite every other panel here, so
// J4 must stay a dual-contact socket (FPC-05FB-24PH20).

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
