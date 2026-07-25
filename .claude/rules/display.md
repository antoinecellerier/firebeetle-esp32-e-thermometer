---
paths:
  - "src/DisplayRenderer.cpp"
  - "src/Display.cpp"
  - "include/Display.h"
  - "include/DisplayRenderer.h"
  - "include/displays.h"
  - "include/MockData.h"
  - "tools/sim/**"
---

# Display and renderer rules

## The gate

**After any display/rendering change, run the simulator and look at the PNGs
before considering the work done:**

```bash
make -C tools/sim screenshots     # all sizes + all badge states -> tools/mock_*.png
```

It compiles `DisplayRenderer.cpp` natively with `g++` and shares all `include/`
headers with the firmware, so it is the fastest feedback loop by a wide margin.
The `mock_*_<state>.png` variants exist so badge and overflow behaviour is
visible without a device — add a variant when you add a badge state.

## Chart styling

- Primary curve (avg): thick solid.
- Envelope (min/max): arc-length dotted via `draw_spline_dotted()`, ~2px spacing.
- Large displays render the hourly avg curve plus the min/max envelope; small
  displays derive daily min/max/avg from the hourly data at render time.

## Status line and badges

This is width arithmetic against a hard limit, and it is where renderer bugs
concentrate. The invariants:

- **Measure with `gfx.setTextWrap(false)`.** With wrap enabled `text_width()`
  saturates at the canvas width, so every overflow test reads true.
- **A badge that can be split must have the `+` overflow marker's width reserved
  up front** — including when it is the last badge in the queue.
- **Lab-build badges outrank everything and can never be dropped.** `! DEBUG` /
  `! DUMMY` / `! MOCK` say the frame is not a production build; if the overflow
  marker can displace them, the ranking is wrong.
- Clamp accumulated `snprintf` return values before using them as `n - pos` —
  the subtraction is unsigned and underflows to ~`SIZE_MAX`.

## Mock data masks the real thing

`MOCK_DISPLAY_DATA` fills the RTC history in RAM, which takes precedence over
anything restored from flash. When validating a flash restore or an injected
archive on device, build **without** it — otherwise the panel shows plausible
data that never came from the archive.
