# Simulator fidelity — follow-ups

Gaps where `tools/sim` renders a narrower or different path than the real
device, so a display bug can pass the emulator. Surfaced while fixing the
stale-font oversized-temperature bug (commit "Fix stale font_config.h …").

## Resolved

### Tri-color red (was: sim can't show red, and red was dead on device)

Fixed in "Restore tri-color red…" and "Collocate per-panel attributes…":
- `EPD_RED` now has a single definition in `DisplayRenderer.cpp`, gated by
  `DISPLAY_HAS_RED` (from `include/displays.h`) — the low-battery icon renders
  red on the Z90 again, and temperatures ≥30 °C render red too.
- The sim renders into a 16-bit color canvas (`GFXcanvas16` → PPM → PNG via
  ImageMagick), so red is visible; a `_hot` scenario exercises it.

One binary renders all four sizes, so it compiles a single `DISPLAY_HAS_RED` —
every size is drawn as if it were the tri-color panel. That is deliberate: it is
what keeps the red path exercised at all. It also means the sim cannot show you
how a bi-color panel degrades the same frame. Until 2026-08-05 the flag followed
whichever rig the developer had last built for a device, and `make screenshots`
had been quietly emitting mono PNGs while this section claimed otherwise;
`tools/sim/stubs/generated/rig_config.h` now pins the rig.

## Open

### 1. Sim only ever renders a couple of temperatures

`sim_main.cpp` now covers 22.3 °C and a 31.5 °C hot case, but still never
exercises negative (`-5.2C`), single-digit (`5.9C`), or 3-digit (`100.0C`)
strings. The font width heuristic in `generate_font.py`
(`width_pt = temp_zone_w * 0.9 / 4.8`) assumes an `XX.XC` width, so a
wider/narrower string could clip or misalign on-device and the sim would never
reveal it — the same layout blind spot as the font bug.

- [ ] Add temperature variants to the sim scenarios (negative, 1-digit,
      3-digit, and a max-width case) across all panel sizes.

### 2. Native 64-bit g++ vs 32-bit target

The sim compiles with host g++: `long`/pointers are 8 bytes vs 4 on the ESP32.
Chart/time-axis arithmetic and any `long`-based math can diverge. Low risk for
pure pixel layout, real for time math.

- [ ] Consider `-m32`, or fixed-width types (`int32_t`) in time/axis math, so
      the sim exercises the same integer widths as the device.

### 3. The sim's panel table is still a separate copy

`include/displays.h` holds each panel's tri-color flag and rotation, and
on-device `static_assert`s tie the generated font's dimensions and
`displays.h`'s tri-color flag to the GxEPD2 panel class — so font ↔ GxEPD2 (and
has_red) can't drift silently. Panel dimensions themselves still live in two
places outside that net: `generate_font.py`'s `DISPLAYS` dict (Python) and
`sim_main.cpp`'s `displays[]`. The sim table in particular is unchecked — a
wrong entry there only ever shows in the sim.

- [ ] Feed `sim_main.cpp` (and ideally `generate_font.py`) from a single source
      — e.g. parse `displays.h`, or emit a small generated table — so a
      new/rotated panel can't drift between them.
