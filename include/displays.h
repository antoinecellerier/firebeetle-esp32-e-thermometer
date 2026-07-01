#pragma once
// Per-display, GFX-agnostic attributes for the configured panel.
//
// Single source of truth for the panel's tri-color capability and rotation —
// consumed by the GxEPD2-free renderer (DisplayRenderer.cpp, and thus the sim)
// and by Display.cpp. Dimensions deliberately live with the GxEPD2 panel class
// and the font generator instead of being duplicated here; Display.cpp
// static_asserts cross-check them.
//
// To add a new display:
//   1. Add a block below: DISPLAY_HAS_RED (1 only for tri-color panels) and
//      DISPLAY_ROTATION.
//   2. Add the GxEPD2 driver type + include in Display.cpp (library-coupled;
//      some panels, e.g. USE_576_T81, must be heap-allocated).
//   3. Add the resolution to the DISPLAYS dict in scripts/generate_font.py and
//      the displays[] table in tools/sim/sim_main.cpp.
//
// Include AFTER common.h, which supplies the USE_* selection via local-secrets.h.

#if defined(USE_576_T81)
#define DISPLAY_HAS_RED  0
#define DISPLAY_ROTATION 0
#elif defined(USE_290_I6FD)
#define DISPLAY_HAS_RED  0
#define DISPLAY_ROTATION 1
#elif defined(USE_213_M21)
#define DISPLAY_HAS_RED  0
#define DISPLAY_ROTATION 1
#elif defined(USE_154_Z90)
#define DISPLAY_HAS_RED  1   // tri-color (black/white/red)
#define DISPLAY_ROTATION 2
#elif defined(USE_154_M09)
#define DISPLAY_HAS_RED  0
#define DISPLAY_ROTATION 2
#elif defined(USE_154_GDEY)
#define DISPLAY_HAS_RED  0
#define DISPLAY_ROTATION 2
#elif !defined(DISABLE_DISPLAY)
#error "No display selected — set a USE_* panel in local-secrets.h (or define DISABLE_DISPLAY)"
#endif
