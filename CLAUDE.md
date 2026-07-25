<!-- House rules for THIS file. Block-level HTML comments are stripped before
  CLAUDE.md is injected into context, so this note costs no session tokens and
  is visible only when the file is opened.
  - Keep it lean. Target <= ~130 lines of *loaded* content (Claude Code docs
    cap CLAUDE.md at < 200). Shorter files get better adherence (bloat ->
    ignored rules). Prune one stale line before adding one.
  - Each bullet is a rule NOT derivable from the code and worth re-stating
    every session. Long rationale -> docs/; multi-step procedure -> a skill;
    guidance that only matters for some files -> .claude/rules/<topic>.md
    with a `paths:` frontmatter glob (those cost nothing until a matching file
    is touched).
  - Run /claude-md-audit before committing any change to this file. -->

# CLAUDE.md

## Build & test

```bash
~/.platformio/penv/bin/pio run -e dfrobot_firebeetle2_esp32e_debug   # ESP32-E (default env)
~/.platformio/penv/bin/pio run -e seeed_xiao_esp32c6_debug           # C6
~/.platformio/penv/bin/pio run -e thermometer_c6_debug               # custom rev A board
make -C tools/sim screenshots      # render all display sizes -> tools/mock_*.png
make -C tools/hstest [sample]      # HistoryStore checks, host-only; `sample` also gates the Python decoder
```

`pio` is not on `PATH`. Env list and build-system rationale: `docs/build-system.md`.

## Working on hardware

Use the `/device-session` skill for anything involving a connected board. Four
facts that do damage when unknown:

- **`include/local-secrets.h` must match the wired panel/sensor before any
  upload.** A mismatch panic-loops at ~600ms and looks like a huge sleep floor on
  the PPK2; a stale frame (old GIT_HASH/time) is the tell.
- **esptool and `history.py` enter download mode, which resets the chip and wipes
  RTC** (`rst:0x1 POWERON_RESET`) — destroying the boot counters, in-progress
  hour and drift window you may be measuring.
- **A base snapshot's existence proves a full boot->render->sleep cycle.**
  `base (none — journal only)` after a settle window means boot loop, not
  "hasn't slept yet".
- **`EPD_POWER_GATE` fails silently.** On any on-device anomaly, enumerate
  physical causes (jumpers, probe orientation, panel rail) before firmware ones.

## Numbers are measured, not guessed

- Timing and energy estimates here have a poor track record — off by 3-10x in
  both directions, once shipping a watchdog boot-loop. **Label any figure you did
  not measure as an estimate**, in comments and docs alike.
- **With hardware attached this is a gate**: instrument new deadline-bound paths
  (task watchdog, EPD busy wait, battery budget) with `ms_now()` and measure
  before committing. Without that board/panel, say so and mark it unmeasured — as
  `docs/notes.md` already does.
- Never derive a charge figure from a PPK2 screenshot. Ask for the selection
  window's average current and duration, and say which region to select.
- **Device-intrinsic costs get precise figures; environment-dependent ones get an
  order of magnitude and their driver named.** A base snapshot is fixed work
  (170ms @ 41.94mA = 7.14mC). Refresh cadence is not — being delta-triggered it
  tracks how volatile the room is, from a handful of refreshes on a stable day to
  tens per day in a heatwave with the windows open. Reason with what survives
  that spread: refreshes beat the sleep floor by ~an order of magnitude, so the
  budget is single-digit coulombs/day, not the microamp floor.
- Logbooks, in order of authority: `docs/notes.md` (power), `docs/clock-drift.md`
  (drift), `docs/footprint.md` (size/build time — append a row after significant
  changes), `docs/history-store-validation.md` (proven on hardware). Read the log
  before quoting a number; carry its date and conditions with the figure.

## Build system (pure ESP-IDF)

`framework = espidf` on the stock platform, no Arduino and no fork; `idf.py`
works too. Rationale, traps and the env list: `docs/build-system.md`. Two rules
worth carrying everywhere: **`history` is pinned at flash offset 0x10000** (moving
its start orphans years of archive), and **sensor/display selection lives in
`include/local-secrets.h`** (gitignored — see `local-secrets-example.h`), not in
platformio.ini.

## Subsystem rules

Path-scoped, loaded when their files are touched — read before editing:
`.claude/rules/build.md` (platformio.ini, CMake, partitions, sdkconfig),
`.claude/rules/history-store.md` (flash archive + host tooling),
`.claude/rules/display.md` (renderer, badges, simulator),
`.claude/rules/ulp.md` (ULP FSM / LP core),
`.claude/rules/rtc-state.md` (RTC memory, version bumps).
The custom PCB has its own `hardware/thermometer-c6/CLAUDE.md`: generated KiCad
schematic (`make check` gates everything), never hand-edit the `.kicad_sch`.
Next phase there: `hardware/thermometer-c6/LAYOUT-PLAN.md`.

## Code conventions

- Board-specific code: `#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)` /
  `#elif defined(ARDUINO_XIAO_ESP32C6)` / `#else #error`
- ULP variant: `SOC_ULP_FSM_SUPPORTED` (ESP32-E) vs `SOC_LP_CORE_SUPPORTED` (C6);
  unified `HAS_ULP_SUPPORT` macro
- Temperature storage: `int16_t` x 10 (223 = 22.3°C)
- **History outlives RTC**: `src/HistoryStore.cpp` mirrors the sparkline, hourly
  ring and drift block to the `history` partition, surviving reflash, panic and
  battery swap. Only `esptool erase_flash` destroys it. `tools/history.py` backs
  it up, restores it and decodes it on the host.
- **Nothing is recorded without a plausible clock** (`time_is_plausible()`).
  Entries are filed by clock hour, so a 1970 timestamp would file them ~54 years
  before everything stored; the device shows restored history and `! NOSYNC`.

## Commit style

Imperative present tense, no conventional-commit prefixes:
```
Restore ULP safety-net timer for periodic housekeeping wakeups
Migrate C6 to pure framework=espidf on stock platform, drop fork
```

## IMPORTANT: Revert debug changes before committing

Check for and revert temporary debug state before any cleanup or feature commit:
test `#define`s (`LP_CORE_IDLE`, `MOCK_DISPLAY_DATA`, `PPK2_DEBUG`,
`HISTORY_BASE_EVERY_WAKE`), temporary build_flags, hardcoded test values. Past
sessions have had regressions from debug changes leaking into commits.

## Workflow preferences

- **Research before implementing**: explain options first and wait for a
  go-ahead. Once direction is agreed, execute without confirming each step.
- **Batch questions to the end of a work item; don't block mid-run.** Prefer a
  short prose question carrying a recommendation over AskUserQuestion cards,
  unless the choice really is 2-4 discrete alternatives.
- **Sequence hardware requests**: finish all USB-only work before asking for a
  rewire, and group physical asks into one message. When asking the user to read
  the panel, give the exact expected string so the reply is yes/no.
- **Say what is on the device.** After any flash, erase or inject, state env +
  `PLATFORMIO_BUILD_FLAGS` + git hash and append it to
  `docs/history-store-validation.md` — debug flags change what the panel shows,
  so an unrecorded build makes every later observation ambiguous.
- **Incremental commits** at natural checkpoints; don't batch large changes, and
  don't propose rewriting local git history — the user asks when they want it.
- **Simplify aggressively**: if there's a simpler approach, propose it.
- **Parse crash logs and serial output** directly — the user pastes raw Guru
  Meditation dumps, build warnings and PPK2 observations without commentary.
- **Keep responses short**: lead with the fix, skip recaps and skip basics about
  ESP32, I2C, deep sleep or PlatformIO. The user is an experienced embedded dev.
- **Delegate the grind**: long build/flash/serial loops and bulk analysis go to a
  subagent with a tight report-back contract, or the session hits compaction.
