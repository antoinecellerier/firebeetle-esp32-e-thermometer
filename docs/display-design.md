# E-Paper Display Design

## Overview

Dashboard-style layout with a large, distance-readable temperature as the primary element,
two trend charts (24-hour Catmull-Rom sparkline and 30-day spline curves), battery/time info,
and a compact debug footer. The layout adapts to all supported display sizes via proportional
zone computation -- no hardcoded coordinates per display.

## Display Sizes

| Panel | Resolution (after rotation) | Layout | Rotation |
|---|---|---|---|
| USE_290_I6FD (2.9") | 296x128 | Landscape | 1 |
| USE_213_M21 (2.13") | 212x104 | Landscape | 1 |
| USE_154_Z90 (1.54" 3-color) | 200x200 | Stacked | 2 |
| USE_154_M09 (1.54") | 200x200 | Stacked | 2 |
| USE_154_GDEY (1.54") | 200x200 | Stacked | 2 |
| USE_576_T81 (5.76") | 920x680 | Stacked | 0 |

## Layout Zones

The layout is determined by aspect ratio: `landscape = (width > height * 1.5)`.

### Landscape (296x128, 212x104)

```
+----------------------------------+------------------------------------------+
|                                  |  23 .....  .  .  .  .     .              |
|         22.3 C                   |                 .  . .  . . .            |
|                                  |  18                                      |
|                                  +------------------------------------------+
|                                  |  25  ~max~     ~avg(dotted)~    ~min~    |
|  [bat] 3.84V          13:42     |  16                                      |
+----------------------------------+------------------------------------------+
| #847 r203 12d w:ULP 4.20V Mar10                                            |
+----------------------------------------------------------------------------+
```

- **Temperature**: left 45% width, full content height
- **Sparkline**: right 55% width, top 62% of content height
- **Monthly chart**: right 55% width, bottom 38% (skipped if content height < 110px)
- **Info bar**: embedded at bottom of temp zone (compact Org_01 font)
- **Footer**: bottom 10px, full width

The temperature font is sized from this zone's dimensions, not picked by a
height threshold — see Typography.

### Stacked (200x200, 920x680)

```
+-------------------------------+
|           22.3 C              |
+-------------------------------+
| 23 .....  .  .  .     .      |
|              .  . . . .       |
| 18                            |
+-------------------------------+
| 25  ~max~  ~avg(dotted)~ ~min~|
| 16                            |
+-------------------------------+
| [bat] 3842mV          13:42  |
+-------------------------------+
| #847 r203 12d w:ULP 4.20V    |
+-------------------------------+
```

Stacked zone proportions (large display, remaining height >= 400px after info + footer):
- **Temperature**: 25%
- **Sparkline**: 42%
- **Monthly chart**: 33% (remainder)
- **Info bar**: 30px fixed
- **Footer**: 24px fixed

Stacked zone proportions (small display, remaining < 400px):
- **Temperature**: 38%
- **Sparkline**: 38%
- **Monthly chart**: 24% (remainder)
- **Info bar**: 22px fixed
- **Footer**: 12px fixed

## Typography

All text is rendered at `setTextSize(1)` -- no integer scaling, no aliasing artifacts.

The temperature font is **generated per panel**, not chosen from this table.
`scripts/generate_font.py` recomputes the point size from the temperature zone's
own dimensions — height constraint fills ~80% of the zone at ~1.4px per pt, width
constraint fits `XX.X C` at ~4.8px per pt, whichever is smaller, capped at 80pt by
`GFXglyph`'s `int8_t yOffset`. It emits `include/generated/font_config.h`, and the
renderer looks the panel up in it via `get_temp_font(w, h)`. Sizes that land on a
library font (9/12/18/24pt) reuse it; the rest are generated. So the point size for
a given panel is whatever the generator last computed — read `font_config.h`, don't
assume. `tools/sim` runs the generator with `--all` so one binary carries every
panel's font.

Everything else comes from this table:

| Element | Font | Condition |
|---|---|---|
| "C" suffix | Same font as temperature digits | always matches the big font |
| Sparkline Y labels | FreeSans12pt | large zones (chart_h >= 100) |
| Sparkline Y labels | TomThumb | small zones |
| Sparkline X labels | FreeSans9pt | large zones |
| Sparkline X labels | TomThumb | small zones |
| Monthly Y labels | FreeSans12pt | large zones (chart_h >= 80) |
| Monthly Y labels | TomThumb | small zones |
| Monthly X labels | FreeSans9pt | large zones |
| Monthly X labels | TomThumb | small zones |
| Info bar (battery, time) | FreeSans12pt | large (w >= 600) |
| Info bar (battery, time) | FreeSans9pt | normal (160 <= w < 600) |
| Info bar (battery, time) | Org_01 | compact (w < 160, landscape embed) |
| Footer | FreeSans12pt | large (zone w >= 600) |
| Footer | Org_01 | small |

## Data Points

### Temperature Zone
- Current reading centered with "C" suffix (same big font as digits, 12px gap)
- Vertically and horizontally centered in zone
- No trend arrow, no delta, no min/max -- just the number

### 24-Hour Sparkline
- Fixed 24h time window, readings plotted at true timestamps
- Catmull-Rom spline interpolation for smooth curves
- Line breaks at gaps > 4 hours
- Y-axis auto-scaled with 15% proportional padding (minimum 0.3), 1 degree C minimum range
- Current reading marked with filled dot (radius 4 large, 2 small)
- Thicker line (2px) on large displays (chart_h >= 100)
- Spline resolution: 16 steps/segment large, 8 medium, 4 small
- Adaptive gridline step: 1 degree when chart_h >= 100 and range <= 8, else 2; on small charts `max(2, range/2)`
- Dotted gridlines (8px spacing large, 5px small)
- X-axis labels at 6-hour wall-clock marks (0h, 6h, 12h, 18h), shown only when chart_h > 30

### 30-Day Monthly Chart
- Two rendering paths based on display width:
  - **Large displays** (chart_w >= 400, e.g. 920x680): hourly resolution showing all 720 HourlyEntry
    points as three Catmull-Rom splines — avg (solid thick), max (arc-length dotted), min (arc-length dotted).
    Daily temperature cycles and transient events are visible.
  - **Small displays** (chart_w < 400): daily summaries derived from hourly data at render time.
    Three splines — avg (solid thick), max (arc-length dotted), min (arc-length dotted) on large zones
    (chart_h >= 60); single avg spline on small zones.
- Arc-length dotted lines use `draw_spline_dotted` (~2px spacing) for envelope (min/max) curves
- Thick lines (2px) on large zones (chart_h >= 80)
- Skipped entirely if zone height < 20px
- Y range: overall min/max with 0.5-degree padding, 1 degree C minimum span
- Adaptive gridline step: same logic as sparkline
- Y labels suppressed near bottom edge to avoid overlap with X-axis date labels
- X-axis date labels every 7th day in "Mar 7" format (month abbreviation + day number)
- Date labels shown only when chart_h > 20 and total_pts > 7

### Info Bar
- Battery icon with proportional fill level (3000-4200mV range, nub on right end)
- Three tiers based on zone width:
  - **Compact** (w < 160, landscape embed): 12px wide icon, voltage as "X.XXV", Org_01 font
  - **Normal** (160 <= w < 600): 18px wide icon, voltage as "NNNNmV", FreeSans9pt
  - **Large** (w >= 600): 28px wide icon, voltage as "NNNNmV", FreeSans12pt
- Date and time right-aligned, longest variant that fits the space left by the
  battery text: `Mon D YYYY  HH:MM`, then `Mon D  HH:MM`, then `HH:MM` alone.
  The date is skipped entirely pre-NTP (year < 2024), so a bogus clock never
  prints a bogus date.
- Icon and text vertically centered in zone
- Low battery: icon and voltage drawn in EPD_RED (falls back to black on non-3-color panels)

### Footer
- Separated from content by 1px horizontal line
- Same field set on every display size. `build_footer_text()` is the source of
  truth — it has gained fields more than once, so read it rather than trusting a
  format string here. In emission order:
  - `#N` -- boot count
  - `rN` -- display refresh count
  - `lpN` -- LP core wake count (always present; structurally 0 on ULP FSM boards,
    which don't populate it)
  - `eN` -- LP error count, omitted when zero
  - `uN` -- ULP reinit count, omitted unless > 1
  - `Nd` or `NdMh` -- uptime in days (hours appended only when non-zero)
  - `w:X` -- wake cause: `ULP`, `TMR`, `USB`, or `?`. An unmapped cause prints the
    raw bitmap as `?<hex>` so a new wake source is identifiable off the panel
  - `mxV.VV` -- max battery voltage ever seen (as `mx%.1fV`)
  - `b27:N` -- bad pin27 count, omitted when zero
  - the git hash of the build
  - first boot date as `MonDD'YY`, omitted until NTP has synced
  - `sN` -- age since the last successful NTP sync (`45m`/`7h`/`21d`), which is how
    a silently failing resync shows up
- Narrow footers clip. `render_status_indicators()` measures the footer up to and
  including the hash, and re-emits the hash as a badge when that already overflows
  the zone — so the build stays identifiable even when the tail is cut. On 200x200
  the line ends around `mx`, which means the date and sync age are **not**
  panel-readable there; don't send a reader to the footer for them.
- FreeSans12pt when the footer zone is >= 600 wide, Org_01 otherwise

## Mock Data

Compile-time flag `MOCK_DISPLAY_DATA` fills history buffers with synthetic data.
Defined in `include/MockData.h` (shared between device and simulator):

- **24h sparkline**: Piecewise linear indoor profile (20 control points) with
  variable reading density -- clustered during morning warmup and evening cooldown,
  sparse during stable daytime periods. Small deterministic noise added.
- **30-day hourly**: 720 HourlyEntry values generated from a gradual spring warming
  profile (+0.08 degrees C/day) with a cold snap (days 12-16), weekend warmth bump,
  realistic ~3 degree C daily ranges. Includes in-progress hour accumulator.
- **DisplayStats**: Pre-filled with boot_count=847, refresh_count=203, 12-day uptime,
  ULP wake cause, 4200mV max battery.

## Architecture

```
include/
  Display.h            -- TempReading, HourlyEntry, DisplayStats structs
  DisplayRenderer.h    -- Layout/Rect structs, render function declarations
  MockData.h           -- Shared mock data generation (device + simulator)

src/
  DisplayRenderer.cpp  -- All rendering logic (shared by device + simulator)
  Display.cpp          -- GxEPD2 display driver wrapper, calls render_dashboard()
  Thermometer.cpp      -- RTC history management, data collection

tools/sim/
  sim_main.cpp         -- Host simulator, renders into a GFXcanvas16
  Makefile             -- Builds render_display binary
  stubs/               -- Host-side shims (Arduino.h/Print.h, the Adafruit bus
                          headers, and a generated/ that pins the rig)
```

`render_dashboard()` in `DisplayRenderer.cpp` is the single entry point. It takes an
`Adafruit_GFX&` reference, computes the layout via `compute_layout()`, then calls each
zone renderer in sequence: `render_temperature`, `render_status_indicators`,
`render_sparkline`, `render_monthly_chart`, `render_info`, `render_footer`. The device
passes the GxEPD2 display object; the simulator passes a GFXcanvas16 — 16-bit so the
tri-color red path is visible. Same rendering code, pixel-perfect output.

Individual zone renderers are also declared in `DisplayRenderer.h` for direct testing.

## RTC Memory Budget

`sizeof(time_t)` is 8 bytes on both ESP32 (Xtensa) and ESP32-C6 (RISC-V), which is
why the sparkline stores its own timestamp rather than a `time_t`.

**TempReading** = `uint32_t` (unix time, good until 2106) + `int16_t`, packed:
- Both platforms: 4 + 2 = 6 bytes per entry — 320 entries in the same 1920
  bytes that 192 entries needed with a `time_t` timestamp.

The sparkline buffer is a linear array (oldest first), not a ring. When full,
`TempHistory.h` drops the oldest point if it's outside the 24h window (the
common case in stable periods); otherwise it drops the interior point with the
smallest Visvalingam triangle area, so noisy periods lose redundant wiggle
detail instead of truncating the chart's 24h span.

**IMPORTANT:** RTC slow memory (8KB at 0x50000000) is shared between `RTC_DATA_ATTR`
variables and the ULP program/data. `ULP_DATA_BASE` must be set past the end of all
`.rtc.data`/`.rtc.force_slow` sections — the post-build script `post_build_check_rtc.py`
verifies this automatically.

**HourlyEntry** = 3 x `int16_t` = 6 bytes (both platforms).

**BMP390LCalib** = 3 x `float` = 12 bytes.

The two buffers dominate and are fixed by their own geometry: `temp_history[320]`
at 6 bytes each is 1920 bytes, `hourly_history[720]` at 6 bytes each is 4320. The
rest is scalars, and there are enough of them now — drift telemetry, crash
forensics, USB-window state — that enumerating them here only produces a total that
disagrees with the binary.

**For the actual figure, read the RTC column of `docs/footprint.md`**: it is measured
from `firmware.elf` per stage and per board, so it cannot silently drift. Adding an
`RTC_DATA_ATTR` variable is not free — it shifts `historical_data` and eats
`ULP_DATA_BASE` headroom, which has run tight on ESP32-E. `post_build_check_rtc.py`
prints the remaining margin on every build; `.claude/rules/rtc-state.md` has the rules
for changing any of it.
