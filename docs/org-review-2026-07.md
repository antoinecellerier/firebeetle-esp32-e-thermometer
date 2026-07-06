# Config & code organization review — 2026-07-06

Full-project review (build config, application code, components/tooling).
Philosophy applied: no refactoring for its own sake — only items with concrete
maintenance payoff are listed as actionable. Everything checked and found
deliberate is recorded in "Verified fine" so future reviews don't re-flag it.

## Actionable (clear payoff)

Status 2026-07-06: items 1, 2, 4, 5, 6 applied same day (LP mode now derives
from local-secrets.h via relative include; HAS_ULP_SUPPORT moved to
app_common.h; CPU-freq/ULP-enable hoisted to common sdkconfig.defaults; ULP
loader tail extracted as ulp_load_program(); .ignore added; dead test/
removed). Item 3 (hardware/) deliberately deferred — still needs a
track-vs-ignore decision.

### 1. LP-core sensor selection can silently disagree with local-secrets.h
`ulp/lp_core_main.c:20` hardcodes `#define LP_CORE_BMP58X` because the ULP
sub-build doesn't inherit the main project's build_flags/includes. The HP side
selects via `USE_*` in `local-secrets.h`. Two independent selectors, kept in
sync by hand: switch `local-secrets.h` to `USE_BMP390L` on the C6 and the LP
core keeps polling the BMP58x at 0x47 — wrong-sensor runtime failure, no build
error. Latent today only because BMP390L-on-C6 is shelved (byte-wrap TODO in
`lp_core_bmp390l.h`).

**Fix**: pass the LP mode from `src/CMakeLists.txt` (the `ulp_embed_binary`
block) as a compile definition derived from the same `USE_*` selection; or at
minimum an `#error` cross-check / prominent keep-in-sync banner at line 20.
Effort medium; verify with a C6 build.

### 2. `HAS_ULP_SUPPORT` defined per-sensor but consumed as a SoC capability
Identical `#define HAS_ULP_SUPPORT 1` in `include/sensors/BMP390LSensor.hpp:11`
and `BMP58xSensor.hpp:11`; its body only tests
`SOC_ULP_FSM_SUPPORTED`/`SOC_LP_CORE_SUPPORTED`. `Thermometer.cpp` sees it only
by luck of include order (active sensor header included before first use). A
new sensor that forgets the define — or an include reorder — silently drops the
ULP branches.

**Fix**: define once in `app_common.h` next to the `soc/soc_caps.h` include,
delete both copies. Effort low, risk low.

### 3. `hardware/` is neither tracked nor ignored — and the KiCad source isn't versioned anywhere
`?? hardware/` in every `git status`. Contents are mostly generated artifacts
(`fp-info-cache`, `__pycache__/*.pyc`, `*.rpt`, KiCad backup zips, `.kicad_prl`)
plus 4 vendor PDFs. The actual design source (`.kicad_pro/.kicad_sch/.kicad_pcb`,
and the `generate_schematic.py` whose orphaned `.pyc` exists) is absent — the
board design currently has no version control at all, only KiCad's local zip
backups. A stray `git add hardware/` would commit the junk.

**Fix**: either track the source (PDFs + KiCad files + `generate_schematic.py`)
with a `hardware/.gitignore` for `fp-info-cache`, `__pycache__/`, `*-backups/`,
`*.kicad_prl`, `*.rpt` — or add `hardware/` to the root `.gitignore` if it's
intentionally out-of-repo. Don't leave it in limbo.

### 4. CPU-freq (and ULP-enable) duplicated across both per-target sdkconfig files
`CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_80=y` and `CONFIG_ULP_COPROC_ENABLED=y` appear
in both `sdkconfig.defaults.esp32` and `sdkconfig.defaults.esp32c6`, yet "CPU
fixed at 80MHz" is documented as a project-wide invariant (CLAUDE.md). Change
one board's clock, forget the other, and the invariant silently breaks.

**Fix**: hoist both into the common `sdkconfig.defaults`; keep only the ULP
*type* (FSM vs LP_CORE) and `CONFIG_ESPTOOLPY_FLASHSIZE_4MB` (a per-board
hardware fact) per-target. Effort trivial.

### 5. Shared ULP FSM loader tail duplicated byte-for-byte
`UlpProgramBMP390L.cpp:242-258` and `UlpProgramBMP58x.cpp:145-161` are identical
(`ulp_process_macros_and_load`, degrade-on-SIZE_TOO_BIG, RTC_SLOW_MEM zeroing).
`UlpProgram.cpp` already exists for exactly this kind of shared FSM code.

**Fix**: hoist into `UlpProgram.cpp` as `ulp_load_program(program, words)`.
Instruction arrays stay per-sensor. Re-check `check_ulp_size.py` (127/128 words).

### 6. Optional: `.rgignore` for submodule working trees
ripgrep/IDE indexing sees 763 files, 639 (84%) under `components/*/upstream/`
(gxepd2 bitmaps alone: 41MB / 362k lines). `git grep` is unaffected (skips
submodules), but `rg` hits ~13× more files than tracked code. A tracked
`.ignore`/`.rgignore` excluding `components/*/upstream/` (or at least
`{examples,extras,src/bitmaps}`) cuts the noise with zero build impact.
Do NOT prune the trees — `GxEPD2_BW.h` includes every panel header, and the
submodule-update workflow depends on them being intact.

## Judgment calls (documented seams; leave unless touched anyway)

- **Thermometer.cpp split (1262 lines)**: mostly cohesive — battery, history,
  sleep, NTP state all couple through ~30 shared `RTC_DATA_ATTR` globals via
  `make_display_stats()`/`reset_rtc_state()`. The two clean cut lines if it
  ever needs splitting: crash forensics (`:147-252`, self-contained, only
  touches its own `.rtc_noinit` struct) → `CrashLog.{h,cpp}`; WiFi/NTP
  (`:510-732`, already fully inside `#ifndef DISABLE_WIFI`) → `net_time.cpp`.
  Not worth doing preemptively.
- **Board pin defs scattered**: 24 `#if defined(ARDUINO_...)` blocks; pin
  tables split across `app_common.h` (I2C, PPK2 debug), `Display.cpp` (EPD),
  `Thermometer.cpp` (LED `:813`, shutdown button `:893`). A single
  `board_pins.h` would help a third board, but EPD pins next to the GxEPD2
  instantiation is good locality. Revisit only if a third board lands.
- **verify_ulp_temp() duplicated** between `BMP390LSensor.cpp:220` and
  `BMP58xSensor.cpp:241` (plus `TEMP_REREAD_*` constants). The re-read
  plausibility logic is correctness-relevant and maintained 2×. Cleanest slice:
  shared `verify_ulp_temp(bus, reread_fn)` with the direct read as callback.
  Benign at two sensors; extract only when touching that logic.
- **`Display.h` grown beyond its name**: also holds the persistence data model
  (`TempReading`, `HourlyEntry`, history sizes, `CrashStage`, sentinels), so
  `TempHistory.h`/`MockData.h` include it just for the types. If ever touched,
  split a small `TempTypes.h`. Marginal payoff alone.
- **`bad_pin27`/`b27` naming** is ESP32-E-specific (button is GPIO9 on C6);
  on-screen diagnostics mislead on C6. Rename to board-neutral (`btn`) costs an
  `RTC_STATE_VERSION` bump — fold into the next bump rather than forcing one.
- **`test/`** is dead stock-PlatformIO scaffolding (boilerplate README from
  2023; real tests are `tools/sim`). Delete or ignore — inert either way.
- **`ULP_TEST_I2C_MINIMAL` scaffolding** (`UlpProgramBMP390L.cpp:77-126`,
  ~50 lines, BMP390L only): `#elif`-excluded from real builds; deletable if
  chip-id bring-up is done.
- **`.h` vs `.hpp`** mixed (`Sensor.hpp`, `sensors/*.hpp` vs everything else
  `.h`). Cosmetic; unify only in a sweep, or never.
- **platformio.ini env structure** — DONE 2026-07-06: the `[env:debug]` /
  `[env:release]` / `[env:<board>]` mixins were converted to plain (non-env:)
  base sections. That removed the half-configured buildable base envs AND made
  `extends` inherit board/build_type/build_flags reliably, collapsing the
  per-env re-declarations. Resolved configs verified with `pio project config`
  for all six envs; both debug envs rebuilt clean.
- **Regroup board pin defs into one header** (`board_pins.h`, code analog of
  docs/wiring.md): agreed good idea but deferred — no clear value until a
  third board or a re-pin; EPD pins next to the GxEPD2 instantiation is good
  locality today.

## Verified fine (checked — do not re-flag)

Build/config:
- Generated `sdkconfig.<env>` correctly gitignored (`sdkconfig.*` +
  `!sdkconfig.defaults*` negations verified with `git check-ignore`); only the
  3 authored defaults are tracked.
- `partitions.csv` consistently referenced from both `board_build.partitions`
  and `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`.
- `build_flags = ${env:debug.build_flags}` substitution is the documented
  workaround for the `extends` limitation.
- Script wiring clean: `pre_build_fonts.py` (pre), `post_build_check_rtc.py` +
  `check_ulp_size.py` (post); `generate_font.py` dual-pathed intentionally
  (PIO every build, idf.py once via `if(NOT EXISTS)`).
- `debug_init_break = tbreak setup` is valid — `setup()` exists at
  `Thermometer.cpp:1150`, not Arduino residue.
- `.gitignore` overall: no generated/binary cruft tracked; repo 16.5 MiB,
  dominated by legitimate `docs/*.png` measurement captures.

Components/tooling:
- gxepd2 / adafruit_gfx / hulp are **shallow git submodules pinned by SHA**
  (fork branches noted in `.gitmodules`) — the 362k-line bitmap bulk never
  enters this repo's history; main repo tracks ~2 files per component.
- `arduino_shim`: 447 lines, documented; the 2-line `Adafruit_I2CDevice.h` /
  `WProgram.h` stubs are load-bearing (satisfy upstream includes without
  patching the submodule).
- `tools/sim`: compiles the real `src/DisplayRenderer.cpp` + shared `include/`;
  mock PNGs are gitignored and regenerated by `make screenshots` (no stale-PNG
  risk); sim's own `stubs/` intentionally differ from arduino_shim (host vs
  device needs).
- readme.md, docs/wiring.md, footprint.md, notes.md all current post-espidf
  migration; Arduino mentions are labeled history.

Code:
- `Display.cpp` ⟷ `DisplayRenderer.cpp` split: driver/pin coupling quarantined,
  renderer GFX-only and sim-shared, `static_assert` cross-checks on panel
  color/fonts. The project's best seam — don't disturb.
- `DisplayStats` marshalled once by value in `make_display_stats()` — why the
  sim works. `displays.h` single source of truth with add-a-display checklist.
- `app_common.h` is NOT a god-header: heavy IDF includes are inside
  `#ifdef ESP_PLATFORM`; host sim sees only LOGI + pin macros.
- RTC versioning (`version` + `self_addr` + `RTC_STATE_VERSION`) well designed.
- LP-core implementation-in-header pattern (`lp_core_*.h` included by
  `lp_core_main.c`) is justified: single-TU ULP sub-build, one `main()`. The
  wart is only the sensor selection (actionable #1), not the pattern.
- Debug hooks (`CRASH_TEST_BOOT`, `MOCK_DISPLAY_DATA`, `ULP_TEST_*`,
  `TEST_CORRUPT_ULP_TEMP`) all `#ifdef`-gated, off by default.
- `DS18B20Sensor` intentionally shelved (guard never defined; would need a
  OneWire port) — documented, not a working option.
