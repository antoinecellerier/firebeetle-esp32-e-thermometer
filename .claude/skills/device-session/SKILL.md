---
name: device-session
description: >-
  Procedure for working with a physically connected board — flashing, capturing a
  boot log over serial, backing up or injecting the flash archive, PPK2 power
  measurement, and returning the device to a clean state. Use whenever a board is
  attached and the task involves uploading firmware, reading serial output,
  running tools/history.py against hardware, taking a power measurement, or
  interpreting an on-device symptom. Also use before asking the user to rewire
  anything.
---

# Working on a connected board

Read the section you need. Don't hand-roll a pyserial reset-and-capture
snippet — `tools/devserial.py` is that.

## 0. Before touching anything

**Is the board doing something you would destroy?** A drift soak, an
accumulating archive, a running power measurement. Any esptool operation —
including `history.py backup` — enters download mode, which presents as
`rst:0x1 POWERON_RESET` and **wipes RTC state**: boot counters, the in-progress
hour, the drift window. Harvest at the end of a run, not during one. Ask before
interrupting a soak.

**Does `include/local-secrets.h` match what is wired?** Flashing a mismatched
panel or sensor config panic-loops at ~600ms and looks like a huge sleep floor on
the PPK2. The tell is a stale e-paper frame — old `GIT_HASH`, old time. Back the
file up before swapping it, and restore it after:

```bash
cp include/local-secrets.h /tmp/.../local-secrets.h.bak
grep -E '^#define (USE_|MY_TZ)' include/local-secrets.h   # what is selected now
```

`include/local-secrets.h` is the ground truth for what is *configured*; the
header of `docs/history-store-validation.md` records which rig the validation log
assumes. Reconcile the two against what is physically wired before flashing.

## 1. Ports differ by board

Enumerate rather than assume a node — the numbering depends on what else is
plugged in:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; ls -l /dev/serial/by-id/ 2>/dev/null
```

What matters is *which bridge* you are talking to, and that is a property of the
board:

- **A real UART bridge** (CP2102/CH340, enumerates as `ttyUSB`) — baud is real,
  and DTR/RTS drive EN/BOOT, so the host can reset the chip. This is the
  FireBeetle.
- **USB-Serial-JTAG** (native, enumerates as `ttyACM`) — baud is ignored, and the
  device **re-enumerates on reset**, so a held-open port dies mid-capture. That
  is normal, not a failure; reopen it. This is the C6 boards.

`devserial.py` picks a port automatically when you don't pass `--port`.

## 2. Flash

```bash
~/.platformio/penv/bin/pio run -e dfrobot_firebeetle2_esp32e_debug -t upload
```

Extra flags go through the environment, and they change what the panel shows:

```bash
PLATFORMIO_BUILD_FLAGS="-DPPK2_DEBUG -DDISABLE_SERIAL" ~/.platformio/penv/bin/pio run -e ... -t upload
```

**`pio run -t upload` resets the board on exit, so the boot banner is usually
already gone by the time you attach.** To capture it, upload with the reset
suppressed and drive reset from the reader instead:

```bash
~/.platformio/penv/bin/esptool --before default_reset --after no_reset write_flash ...
python3 tools/devserial.py boot --grep "Boot count|HistoryStore"
```

esptool auto-detects the port when `--port` is omitted; pass it explicitly only
when more than one board is plugged in.

**Say what you flashed.** Every flash, erase or inject gets reported as env +
`PLATFORMIO_BUILD_FLAGS` + git hash, and appended to
`docs/history-store-validation.md`. Debug flags change what the panel shows, so
an unrecorded build makes every later observation ambiguous.

## 3. Read serial

```bash
python3 tools/devserial.py boot                    # DTR/RTS reset, then stream
python3 tools/devserial.py boot --grep "Boot count|base snapshot|rst:"
python3 tools/devserial.py watch                   # attach without resetting
```

`watch` is the one to use on a board you must not disturb. `boot` resets, so it
wipes RTC — see section 0.

Release builds may set `DISABLE_SERIAL`; there will be no output and that is not
a fault.

## 4. Reading the panel

Full-refresh panels take **tens of seconds** — the tri-colour Z90 is the slowest
of the ones in use. Don't reset the board inside that window, and don't conclude
"no refresh" before the panel's own busy window has elapsed plus settle time.
Per-panel measured timings are in `docs/notes.md`.

When asking the user to check the display, give the exact expected string so the
answer is yes/no — "should show `<hash>` with no badges", not "check it looks
right".

## 5. Is it healthy, or boot looping?

**A base snapshot only gets written at the first deep sleep**, so its existence
proves the device completed boot → render → sleep:

```bash
~/.platformio/penv/bin/python3 tools/history.py backup
# then, on the resulting image:
~/.platformio/penv/bin/python3 tools/history.py dump <img> --drift
```

`base (none — journal only)` after a full settle window means **boot loop**, not
"hasn't slept yet" — the two look identical on the panel, which still holds the
last frame it managed to render.

## 6. Inject a synthetic archive

For testing restore and rendering without waiting days:

```bash
tools/hstest/hstest --inject ...        # argument list: the --inject block in tools/hstest/hstest.cpp
~/.platformio/penv/bin/python3 tools/history.py restore <out.bin>
```

The image is built by the real store code, so it cannot disagree with the
firmware's format. `restore` is MAC-checked, so the image has to be stamped with
the target device's MAC (`esptool read_mac`).

**Build without `MOCK_DISPLAY_DATA`.** It fills RTC history in RAM, which takes
precedence over anything restored from flash, so the panel shows plausible data
that never came from the archive — a false pass that is hard to spot.

## 7. PPK2

Source-meter mode, plus digital channels for correlation, built with
`-DPPK2_DEBUG`.

### Confirm the connection before anything is energised — every time

**The PPK2 exposes no VOUT sense.** Nothing in software can detect which rail
the leads are on, so this cannot be automated away and cannot be carried over
from an earlier step in the same session.

Before any live capture, and before any step that energises the DUT, make the
user **state and confirm the physical connection**, and give them the exact
thing to check so the answer is yes/no. The failure mode is not a bad
measurement: the source meter spans 0.8-5.0 V, the BAT pads want 3.0-4.2 V, and
the 3V3 rail feeds the MCU, panel and sensor directly against the C6's
datasheet absolute-max VDD of **3.6 V**. Battery voltage onto that rail destroys
all three at once.

`tools/ppk2.py` enforces what it can:

- **Ampere meter is the default** — the PPK2 does not source at all, so no rail
  can be over-volted however the leads are attached. Use it whenever the board
  is externally powered.
- Sourcing needs an explicit `--rail {bat,3v3}`, is **clamped per rail as a
  refusal rather than a clip**, and demands a typed confirmation naming the
  connection. A rail that differs from the last sourced run forces a re-confirm.
- An inrush ceiling cuts power on a gross fault, but samples arrive USB-buffered
  so reaction is tens of ms — that catches a short, **not** a marginal
  over-volt. Do not treat it as protection.

Prefer a physical guard over any of the above: visually distinct or
differently-keyed harnesses for BAT vs 3V3. Note also that **the hat's JST2 is
not a battery input** — energising it gives a ~0.2 ms 14 mA inrush and then
nothing, which reads exactly like a dead board. Probe the XIAO's soldered BAT
connector, which also bypasses the shield's ETA9740 path and its ~330-500 µA.

**Read the `PPK2_DEBUG` block in `include/app_common.h` for the current pin
assignments before wiring anything.** It defines which GPIO drives which PPK2
digital channel and what each one signals, and documents where those GPIOs land
per board — the same numbers sit on different headers on the custom C6, and some
are mutually exclusive with the UART console or USB. Don't work from a pinout
quoted anywhere else, including here.

`PPK2_DEBUG_ULP_GPIO` is a separate opt-in: it keeps RTC peripherals powered in
deep sleep, which raises the floor. Enable it only when you need that trace.

Practicalities:

- **Check the probe orientation first** when a digital lane reads flat.
  `ppk2_selftest()` under `PPK2_DEBUG` emits a known pattern that settles whether
  the firmware side is working, before you go looking for a bug.
- A marker must be wide enough to see at the window in use: **12 ms is ~6 px at a
  3 s window.** Use ≥300 ms preambles.
- **Never derive a charge figure from a screenshot.** Export the capture to CSV
  and run `tools/ppk2.py csv <file>`: it integrates charge over regions
  delimited by the firmware's own D0/D1 edges, so the numbers stop depending on
  where a selection was dragged. It also checks the `ppk2_selftest()` fingerprint
  and reports swapped lanes. The archive flush and the panel refresh both drive
  D1 — the flush is the one preceded by three 50 ms blips.
  For the phases that carry **no** marker (the one-time archive format, the WiFi
  exchange), locate them with `--profile 500` and then bracket them with
  `--from/--to`. Falling back to asking for a selection's average current and
  duration is acceptable only when no CSV export is available.
- Batch physical asks. Finish all USB-only work before requesting a rewire, and
  ask for the whole wiring change in one message.

## 8. On-device anomaly triage — physical causes first

This rig fails mechanically about as often as it fails in firmware, and the
mechanical failures are silent. Enumerate these before forming a firmware
hypothesis:

1. **`EPD_POWER_GATE` fails silently** — an unplugged display-enable jumper looks
   exactly like a rendering bug.
2. **PPK2 probe orientation** — a flipped board puts the probe on the wrong lane.
3. `local-secrets.h` mismatch (section 0).
4. Supply handover — with a battery attached, unplugging USB is *not* a power
   cycle, and RTC state persists.

## 9. Return to a clean state

```bash
~/.platformio/penv/bin/esptool erase_flash
~/.platformio/penv/bin/pio run -e <env> -t upload
```

Then confirm, and record it in `docs/history-store-validation.md`:

- the boot log reports boot count 1 against a clean (non-`-dirty`) hash,
- the store finds no base snapshot, then writes a fresh one at the first sleep,
- a `history.py backup` decodes to an empty archive,
- `include/local-secrets.h` is restored from the backup,
- debug `#define`s and `PLATFORMIO_BUILD_FLAGS` are reverted (see CLAUDE.md).

Compare against the previous clean-state entry in the validation log rather than
against literal strings quoted here — the log lines move with the code.
