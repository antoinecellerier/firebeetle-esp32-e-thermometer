#pragma once
// Per-display, GFX-agnostic attributes for the configured panel.
//
// Single source of truth for the panel's tri-color capability and rotation —
// consumed by the GxEPD2-free renderer (DisplayRenderer.cpp, and thus the sim)
// and by Display.cpp. Dimensions deliberately live with the GxEPD2 panel class
// and the font generator instead of being duplicated here; Display.cpp
// static_asserts cross-check them.
//
// Adding a panel touches seven files; the full checklist is in
// include/rigs/_template.h, which also lists the panels themselves. This one is
// step 2: DISPLAY_HAS_RED (1 only for tri-color panels) and DISPLAY_ROTATION.
//
// Include AFTER app_common.h, which supplies the USE_* selection via device-config.h.

#if defined(USE_576_T81)
#define DISPLAY_HAS_RED  0
// 2, not 0: the panel's own scan/shift direction (PSR) puts the FPC-relative
// origin diagonally opposite where the dashboard wants it, so the frame lands
// 180° out. setRotation is a GFX coordinate transform, so correcting it here is
// free — no extra buffer, no extra refresh time (measured: unchanged ms/slices).
#define DISPLAY_ROTATION 2
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
#error "No display selected — set a USE_* panel in the rig header (or define DISABLE_DISPLAY)"
#endif
