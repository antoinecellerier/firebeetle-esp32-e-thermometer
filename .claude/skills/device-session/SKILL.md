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

Rig on the bench as of 2026-07: FireBeetle 2 ESP32-E + BMP390L + GDEH0154Z90
(`USE_154_Z90` + `USE_BMP390L`), `dfrobot_firebeetle2_esp32e_debug`.

## 1. Ports differ by board

| Board | Device | Bridge | Notes |
|---|---|---|---|
| FireBeetle 2 ESP32-E | `/dev/ttyUSB0` | CP2102/CH340 | real UART, 115200, DTR/RTS drive EN/BOOT |
| XIAO C6 / custom C6 | `/dev/ttyACM*` | USB-Serial-JTAG | baud ignored; **re-enumerates on reset**, so a held-open port dies |

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; ls -l /dev/serial/by-id/ 2>/dev/null
```

On the C6 the port disappearing mid-capture is normal, not a failure — reopen it.

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
~/.platformio/penv/bin/esptool --port /dev/ttyUSB0 --baud 921600 \
  --before default_reset --after no_reset write_flash ...
python3 tools/devserial.py boot --grep "Boot count|HistoryStore"
```

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

The Z90 takes **~21 s** to render. Don't reset the board inside that window, and
don't conclude "no refresh" before it elapses plus the settle time.

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
tools/hstest/hstest --inject <part-size> <mac-hex> <now-epoch> <out.bin> [ramp] [hours]
~/.platformio/penv/bin/python3 tools/history.py restore <out.bin>
```

The image is built by the real store code, so it cannot disagree with the
firmware's format. `restore` is MAC-checked — pass the target device's MAC
(`esptool read_mac`).

**Build without `MOCK_DISPLAY_DATA`.** It fills RTC history in RAM, which takes
precedence over anything restored from flash, so the panel shows plausible data
that never came from the archive — a false pass that is hard to spot.

## 7. PPK2

Source-meter mode, plus digital channels for correlation. With `-DPPK2_DEBUG`:

- **D0 ← GPIO17** (D10 on the FireBeetle silkscreen): HIGH while the CPU is awake.
- **D1 ← GPIO16** (D11): HIGH during display refresh.
- `PPK2_DEBUG_ULP_GPIO` adds D2 ← GPIO12 but keeps RTC peripherals powered in
  deep sleep, which raises the floor. Enable it only when you need it.

Practicalities:

- **Check the probe orientation first** when a digital lane reads flat.
  `ppk2_selftest()` under `PPK2_DEBUG` emits a known pattern that settles whether
  the firmware side is working, before you go looking for a bug.
- A marker must be wide enough to see at the window in use: **12 ms is ~6 px at a
  3 s window.** Use ≥300 ms preambles.
- **Never derive a charge figure from a screenshot.** Ask the user for the
  selection window's average current and duration, and say exactly which region
  to select.
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
~/.platformio/penv/bin/esptool --port /dev/ttyUSB0 erase_flash
~/.platformio/penv/bin/pio run -e dfrobot_firebeetle2_esp32e_debug -t upload
```

Then confirm, and record it in `docs/history-store-validation.md`:

- boot log shows `Boot count: 1 [<hash>]` with no `-dirty`,
- `HistoryStore: no valid base snapshot` then `base snapshot seq 1`,
- `history.py backup` reports `0 hourly, 1 sparkline, 0 drift`,
- `include/local-secrets.h` restored from the backup,
- debug `#define`s and `PLATFORMIO_BUILD_FLAGS` reverted (see CLAUDE.md).
