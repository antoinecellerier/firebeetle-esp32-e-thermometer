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

When content height < 100px (e.g. 212x104), the big font downgrades from
FreeSansBold24pt to FreeSansBold18pt.

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
Font selection is based on display dimensions:

| Element | Font | Condition |
|---|---|---|
| Temperature | FreeSansBold80pt (~140px digits) | `min(w,h) >= 400` (920x680) |
| Temperature | FreeSansBold24pt (~35px digits) | default (296x128, 200x200) |
| Temperature | FreeSansBold18pt (~26px digits) | landscape with content_h < 100 (212x104) |
| "C" suffix | Same font as temperature digits | always matches the big font |
| Sparkline Y labels | FreeSans12pt | large zones (chart_h >= 100) |
| Sparkline Y labels | TomThumb | small zones |
| Sparkline X labels | FreeSans9pt | large zones |
| Sparkline X labels | TomThumb | small zones |
| Monthly Y labels | FreeSans12pt | large zones (chart_h >= 80) |
| Monthly Y labels | TomThumb | small zones |
| Monthly X labels | FreeSans9pt | large zones |
| Monthly X labels | TomThumb | small zones |
| Info bar (battery, time) | FreeSans9pt | normal/large (w >= 160) |
| Info bar (battery, time) | Org_01 | compact (w < 160, landscape embed) |
| Footer | FreeSans9pt | large (w >= 600) |
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
- Three Catmull-Rom spline curves on large zones (chart_h >= 60): max (solid), avg (dotted every 6th pixel), min (solid)
- Single avg spline on small zones (chart_h < 60)
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
  - **Large** (w >= 600): 28px wide icon, voltage as "NNNNmV", FreeSans9pt
- Current time HH:MM right-aligned
- Icon and text vertically centered in zone
- Low battery: icon and voltage drawn in EPD_RED (falls back to black on non-3-color panels)

### Footer
- Separated from content by 1px horizontal line
- Unified format across all display sizes:
  `#N rN Nd w:X mxV.VV DateN'YY`
  - `#N` -- boot count
  - `rN` -- display refresh count
  - `Nd` or `NdMh` -- uptime in days (hours appended only when non-zero)
  - `w:X` -- wake cause (ULP, TMR, or ?)
  - `mxV.VV` -- max battery voltage ever seen (as `mx%.1fV`)
  - `b27:N` -- bad pin27 count (omitted when zero)
  - `DateN'YY` -- first boot date as "MonDD'YY" (e.g. "Mar10'25"), omitted if NTP not yet synced
- FreeSans9pt on large displays (w >= 600), Org_01 on small

## Mock Data

Compile-time flag `MOCK_DISPLAY_DATA` fills history buffers with synthetic data.
Defined in `include/MockData.h` (shared between device and simulator):

- **24h sparkline**: Piecewise linear indoor profile (20 control points) with
  variable reading density -- clustered during morning warmup and evening cooldown,
  sparse during stable daytime periods. Small deterministic noise added.
- **30-day daily**: Gradual spring warming (+0.08 degrees C/day) with a cold snap
  (days 12-16), weekend warmth bump, realistic ~3 degree C daily ranges.
- **DisplayStats**: Pre-filled with boot_count=847, refresh_count=203, 12-day uptime,
  ULP wake cause, 4200mV max battery.

## Architecture

```
include/
  Display.h            -- TempReading, DailySummary, DisplayStats structs
  DisplayRenderer.h    -- Layout/Rect structs, render function declarations
  MockData.h           -- Shared mock data generation (device + simulator)

src/
  DisplayRenderer.cpp  -- All rendering logic (shared by device + simulator)
  Display.cpp          -- GxEPD2 display driver wrapper, calls render_dashboard()
  Thermometer.cpp      -- RTC history management, data collection

tools/sim/
  sim_main.cpp         -- Host simulator using GFXcanvas1
  Makefile             -- Builds render_display binary
  stubs/               -- Minimal Arduino.h/Print.h for host compilation
```

`render_dashboard()` in `DisplayRenderer.cpp` is the single entry point. It takes an
`Adafruit_GFX&` reference, computes the layout via `compute_layout()`, then calls each
zone renderer in sequence: `render_temperature`, `render_sparkline`, `render_monthly_bars`,
`render_info`, `render_footer`. The device passes the GxEPD2 display object; the simulator
passes a GFXcanvas1. Same rendering code, pixel-perfect output.

Individual zone renderers are also declared in `DisplayRenderer.h` for direct testing.

## RTC Memory Budget

Sizes depend on `sizeof(time_t)` -- 4 bytes on ESP32 (Xtensa), 8 bytes on ESP32-C6 (RISC-V).

**TempReading** = `time_t` + `int16_t` (+ padding to align):
- ESP32: 4 + 2 + 2 pad = 8 bytes
- ESP32-C6: 8 + 2 + 6 pad = 16 bytes

**DailySummary** = `int16_t` + `int16_t` + `uint8_t` + `uint8_t` = 6 bytes (both platforms).

**BMP390LCalib** = 3 x `float` = 12 bytes.

| Data | ESP32 (32-bit time_t) | ESP32-C6 (64-bit time_t) |
|---|---|---|
| temp_history[96] (TempReading) | 768 bytes | 1536 bytes |
| daily_history[31] (DailySummary) | 186 bytes | 186 bytes |
| bmp390l_calib (BMP390LCalib) | 12 bytes | 12 bytes |
| Scalars: boot_count, display_refresh_count, previous_boot_count (3x int) | 12 bytes | 12 bytes |
| first_boot_time, next_clear_time (2x time_t) | 8 bytes | 16 bytes |
| previous_temp, min_temp_since_boot, max_temp_since_boot (3x float) | 12 bytes | 12 bytes |
| max_battery_mv, bad_pin27_count (2x uint32_t) | 8 bytes | 8 bytes |
| temp_history_count, temp_history_idx, daily_history_count, daily_history_idx, current_day (5x uint8_t) | 5 bytes | 5 bytes |
| current_day_min_x10, current_day_max_x10 (2x int16_t) | 4 bytes | 4 bytes |
| rtc_layout_version (uint32_t) | 4 bytes | 4 bytes |
| **Total** | **~1019 bytes** | **~1795 bytes** |

Well within the 8KB RTC slow memory limit.
