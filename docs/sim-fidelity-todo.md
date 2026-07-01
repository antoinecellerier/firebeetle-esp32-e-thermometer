# Simulator fidelity — follow-ups

Gaps where `tools/sim` renders a narrower or different path than the real
device, so a display bug can pass the emulator. Surfaced while fixing the
stale-font oversized-temperature bug (commit "Fix stale font_config.h …").

Not yet implemented — tracked here.

## 1. Sim can't show tri-color (and red looks dead on the device)

The sim renders into a 1-bit `GFXcanvas1`, and `EPD_RED` is undefined in the
native build so it falls back to `EPD_BLACK` (`DisplayRenderer.cpp:32`). So the
emulator can never distinguish red from black.

Worse, the same is true on the **real** firmware: the per-panel
`#define EPD_RED GxEPD_RED` lives in `Display.cpp`, but the only use
(`bat_color`, `DisplayRenderer.cpp:872`) is a *different* translation unit that
compiles with `EPD_RED == EPD_BLACK`. So the low-battery icon renders black on
the tri-color Z90, not red. Same "two copies must agree across a TU boundary"
pattern as the font bug.

- [ ] Confirm on hardware that the low-battery icon is black (not red).
- [ ] Make the red color reach `DisplayRenderer.cpp` — e.g. define `EPD_RED` as
      a raw RGB565 value in a shared header keyed on the `USE_154_Z90` panel
      macro (no GxEPD2 dependency needed in the renderer).
- [ ] Give the sim a 2-bit/color canvas (or a second red plane) so red vs black
      is visible in the PNGs.

## 2. Sim only ever renders one temperature (22.3°C)

`sim_main.cpp` hard-codes 22.3°C for every scenario. It never exercises
negative (`-5.2C`), single-digit (`5.9C`), or 3-digit (`100.0C`) strings. The
font width heuristic in `generate_font.py`
(`width_pt = temp_zone_w * 0.9 / 4.8`) assumes an `XX.XC` width, so a
wider/narrower string could clip or misalign on-device and the sim would never
reveal it — the same layout blind spot as the font bug.

- [ ] Add temperature variants to the sim scenarios (negative, 1-digit,
      3-digit, and a max-width case) across all panel sizes.

## 3. Native 64-bit g++ vs 32-bit target

The sim compiles with host g++: `long`/pointers are 8 bytes vs 4 on the ESP32.
Chart/time-axis arithmetic and any `long`-based math can diverge. Low risk for
pure pixel layout, real for time math.

- [ ] Consider `-m32`, or fixed-width types (`int32_t`) in time/axis math, so
      the sim exercises the same integer widths as the device.

## 4. Three dimension tables must stay in sync

Panel dimensions live in three independent places that must agree:
`generate_font.py` `DISPLAYS`, `sim_main.cpp` `displays[]`, and the real
`display.init` rotation. The new runtime guard (`FONT_CONFIG_W/H` in
`Display.cpp`) now catches a font-table-vs-panel mismatch on-device, but the
sim's table is still a separate copy.

- [ ] Generate the sim's panel table from the same source as `DISPLAYS`
      (or share one list) so a new/rotated panel can't drift between them.
