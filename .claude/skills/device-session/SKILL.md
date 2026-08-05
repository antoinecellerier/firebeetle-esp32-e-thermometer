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

**Does the env you are about to flash match what is wired?** The env carries its
rig — panel, sensor, power gate, LEDs — so there is nothing to edit and nothing
to restore afterwards. Check which rig an env means, and what that rig is:

```bash
grep -A1 '^\[env:' platformio.ini | grep -B1 custom_rig   # env -> rig
head -6 include/rigs/<rig>.h                              # rig -> hardware, MAC, port
```

A rig that disagrees with its env is a compile error, so the surviving hazard is
narrower than it used to be: **right env, wrong physical board**. Boards sharing
one env (the custom rev A boards) are the case to watch. That still panic-loops
at ~600ms and looks like a huge sleep floor on the PPK2; the tell is a stale
e-paper frame — old `GIT_HASH`, old time.

`RIG=<name>` overrides for a bench swap. It leaves no state behind: the next
plain `pio run` is back on the env's own rig.

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

The USJ controller emulates DTR/RTS rather than ignoring them, and on the C6
boards **DTR reaches GPIO9 — the BOOT strap and the firmware's shutdown button**
while RTS reaches EN. So opening a port can reset the chip or park it in the ROM
bootloader (silent: no banner, and closing the port does not release it —
recovery is RST, a power cycle, or an esptool run).

**No client can prevent this on Linux**: cdc-acm raises both lines during port
activation, before userspace gets control. `devserial.py watch` releases them at
its first opportunity, which narrows the window rather than closing it; `pio
device monitor`, nrfconnect and bare pyserial do not even do that. So: attaching
a monitor is intrusive, always. On a board that is mid-soak or mid-measurement,
the only safe move is not to attach.

**The ttyACM number is not stable** — when the ESP32 drops off the bus another
device can inherit `ttyACM0`, and esptool will happily sync against it. Address
the board by `/dev/serial/by-id/*Espressif*`.

`devserial.py` picks a port automatically when you don't pass `--port`.

## 2. Flash

```bash
~/.platformio/penv/bin/pio run -e dfrobot_firebeetle2_esp32e_debug -t upload
```

Extra flags go through the environment, and they change what the panel shows.
Every macro on CLAUDE.md's revert list is read only under `src/`, so use
`PLATFORMIO_BUILD_SRC_FLAGS` — `PLATFORMIO_BUILD_FLAGS` lands on the global
SCons env and rebuilds all ~1100 IDF component objects as well:

```bash
PLATFORMIO_BUILD_SRC_FLAGS="-DPPK2_DEBUG -DDISABLE_SERIAL" ~/.platformio/penv/bin/pio run -e ... -t upload
```

Either variable is part of the project checksum, so changing it still deletes
every env's build directory — finish a flash before building anything else.

**`pio run -t upload` resets the board on exit, so the boot banner is usually
already gone by the time you attach.** To capture it, upload with the reset
suppressed and drive reset from the reader instead:

```bash
~/.platformio/penv/bin/esptool --before default_reset --after no_reset write_flash ...
python3 tools/devserial.py boot --grep "Boot count|HistoryStore"
```

esptool auto-detects the port when `--port` is omitted; pass it explicitly only
when more than one board is plugged in.

### Flashing a board that is deep-sleeping (C6)

A sleeping C6 presents **no USB device at all** — the USJ controller is
unpowered — so esptool's download-mode reset, which is what stands in for the
BOOT button on this chip, has nothing to talk to. Three ways in, cheapest first:

1. **The custom board holds the port open by itself.** With a host attached it
   runs a USB service window instead of sleeping (`! USB` badge on the panel,
   `w:USB` in the footer on the plug-in wake), so a plain `pio run -t upload`
   works unattended within a wake of plugging in. Build with
   `-DUSB_WINDOW_OBSERVE_CYCLES=N` to spend the first N of those sleeps on real
   deep sleep instead — needed whenever what you are testing *is* the sleep path,
   since a window replaces it — or `-DDISABLE_USB_WINDOW` to remove it entirely.
   Both change behaviour, so both go in the log row.
2. **Catch a wake from the host** (works on the XIAO too, no firmware support):

   ```bash
   python3 tools/devserial.py flashwait --env seeed_xiao_esp32c6_debug
   ```

   It polls the by-id path and uploads the instant the board enumerates.
3. **Park it manually**: hold BOOT, tap RST, release BOOT, with no process
   holding the port. This is what board 1 needed before the window existed.

**A manually parked chip stays parked after the upload — press RST or the new
firmware never runs.** esptool's own reset does not release the park, so the app
never starts and the panel keeps holding its last frame. That reads exactly like
"the flash didn't take", and the tells are subtle: the board stays *enumerated*
indefinitely (the ROM bootloader keeps USJ alive, where a running board would
deep-sleep and drop off the bus within seconds), esptool keeps answering, and any
archive you read back is intact but unchanged. **Enumerated-and-quiet is the
signature of a parked chip, not a booting one.** Confirm the app is live off the
panel — the git hash in the footer — not off the bus.

Any of these resets the chip and **wipes RTC** (boot counters, in-progress hour,
drift window) — inherent to download mode, not to how you entered it. The
`history` partition survives. Harvest at the end of a run, not during one.

**Say what you flashed.** Every flash, erase or inject gets reported as env +
the build-flag variable you used + git hash, and appended to
`docs/history-store-validation.md`. Debug flags change what the panel shows, so
an unrecorded build makes every later observation ambiguous.

**Read the hash off `git rev-parse HEAD` at the moment of each upload, not from
the last one you noted.** `GIT_HASH` is stamped at build time, so committing
anything between two flashes — including the log row for the first one — gives
the second rig a different hash for identical firmware. Flashing several boards
in a session and logging one hash for all of them is wrong, and the panel is
what exposes it later. When rigs must be comparable, either flash them all
before committing, or record each one's own hash and note that the difference is
docs-only.

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

### Reading a measurement — where a whole afternoon went

A measured number can be wrong in ways an estimate cannot: it can be a real
average of the wrong thing. These are the specific ways it happened here.

- **A window mean is not a device property.** Before attributing any figure to a
  mechanism, look at its *time evolution* — per-second means, not one average.
  Five sleep-floor figures spanning 26–141 µA on the C6 rig were a single
  post-wake transient averaged over windows containing different amounts of it,
  and each one got its own hardware explanation before anyone plotted it.
- **Average rates over whole duty cycles, and check the bench rate against the
  field rate.** A floor is only meaningful over complete wake-to-wake cycles.
  Bench delta wakes every ~60 s put the post-wake transient at ~40% duty; the
  field rate of 31 wakes/day puts it at ~1%, which is a 50% difference in the
  headline number.
- **Extrapolating past the longest window measured is an estimate.** Label it.
  The longest sleep window ever captured here is 163 s against a ~46 min
  deployment interval, so any deployed-floor figure is an extrapolation until a
  wake-free capture of a full interval exists.
- **Instrumentation changes what it measures.** `PPK2_DEBUG` adds a triple 50 ms
  D1 preamble to every archive persist — 300 ms of awake time, ~4–6 mC per wake.
  Compare debug figures only with debug figures, and prefer a production build for
  anything that ships in the budget.
- **Before naming a cause, check whether the suspect was present in the
  counter-example.** Digital-probe leakage, the shield's ETA9740 and the
  acquisition path were each proposed as the cause of an elevated floor, and each
  died on the same observation: the variable was present in the *low* reading too.
- **A single contradicting capture is data, not an outlier.** One flat 57 s
  window got dismissed as noise; it was the only evidence that the transient is
  not a deterministic consequence of every wake, which is still unexplained.
- **Sanity-check against the instrument's limits.** A capture here contained
  samples reading 17–20 A on an instrument that stops near 1 A, as bit-identical
  quartets at two separate times — a decode artifact, and four such samples in a
  500k-sample bin shift its mean by ~160 µA.
- **`ppk2_api` reports every conversion failure as "Measurement outside of
  range!"** from a bare `except`, so a missing decoder field (mode, vdd,
  modifiers) presents as corrupt data. `tools/ppk2.py raw` writes a sidecar with
  those fields at capture time so a stream stays decodable without the device.

## 8. On-device anomaly triage — physical causes first

This rig fails mechanically about as often as it fails in firmware, and the
mechanical failures are silent. Enumerate these before forming a firmware
hypothesis:

1. **`EPD_POWER_GATE` fails silently** — an unplugged display-enable jumper looks
   exactly like a rendering bug.
2. **PPK2 probe orientation** — a flipped board puts the probe on the wrong lane.
3. Right env, wrong physical board (section 0) — the mismatch the rig
   cross-checks cannot catch.
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
- debug `#define`s and any build-flag overrides are reverted (see CLAUDE.md).

Compare against the previous clean-state entry in the validation log rather than
against literal strings quoted here — the log lines move with the code.
