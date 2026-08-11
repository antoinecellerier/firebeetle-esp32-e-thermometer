# Panel datasheets

Module- and controller-level docs for the e-paper panels the rigs drive. They
live here rather than under `../thermometer-c6/` because the panels are shared
across every rig — FireBeetle, XIAO, the Seeed hat and the custom board. That
board keeps its own parts' datasheets beside it, but **untracked** — including
the SSD1677 doc referenced below, which is not in the repo and has to be fetched
again from Solomon Systech.

| File | Panel | Controller | Rig |
|---|---|---|---|
| `GDEH0154Z90.pdf` | 200x200 tri-colour | SSD1681 | `firebeetle` |
| `GDEY0213M21.pdf` | 212x104 (as GDEW0213M21) | UC8151D | `revA-213m21` bench spare |
| `GDEW029I6FD.pdf` | 296x128 flexible | UC8151D | `xiao-hat` |
| `GDEH0576T81.pdf` | 920x680 | SSD2677 | `revA-bigscreen`, `xiao-bigscreen` |
| `UC8151D.pdf` | — | UC8151D chip-level | the two UC8151 panels above |

No chip-level SSD2677 doc. The SSD1677 datasheet is a relative, not the part, and
taking its pinout for the module's cost a wrong conclusion once (below).

## What they settle: panel readback

Whether a panel can answer the host is a property of its **controller**, not of
any board, so there is no single answer. Established 2026-08-05:

**Every one of these modules exposes a single serial data pin and no SDO** — M21
and I6FD call it `SDIN`, the Z90 and T81 call it `SDA`. Readback, where it
happens, is the controller driving that same pin back.

| Controller | Module data pin | Readback | Identifier |
|---|---|---|---|
| UC8151D | `SDIN`, single | **measured working** on board 2 | `0x70` REV → `LUT_REV` from OTP `0x001` |
| SSD1681 | `SDA`, single; 4-wire read procedure documented | expected working | **`0x38`: 10-byte User ID in OTP** |
| SSD2677 | `SDA`, single | **returns 0 over hardware SPI** (2026-08-11, board 2 + T81); panel capability still untested | unknown |

An earlier version of this table called the T81 doubtful "because the FPC carries
no SDO". That was wrong: `SSD1677.pdf` names `SDI`/`SDO` as separate **chip**
pins in 4-wire mode, but the module bonds a single `SDA` to the FPC, exactly like
the other three. The T81's position is therefore identical to the M21's before it
was probed — one data pin, a module datasheet that calls it an input and
documents no read — and the M21 answered anyway. Untested, not unlikely.

`0x38` matters most: the SSD1681 drives *both* 200x200 panels (the Z90 and the
GDEM0154I61 behind the GDEY0154D67 driver), so a User ID is the only thing that
tells them apart — resolution cannot, and resolution can in any case only
falsify a match, never confirm one.

**The T81 read is now known to return 0 on this rig — but that is a verdict on
the host, not on the panel.** GxEPD2's `_readData()` samples the data line from
software and is documented to work only in bit-banged mode; this build runs
hardware SPI, so nothing samples the line at all. Measured indirectly on
2026-08-11: `_Init_Full` selected the ≤5 °C waveform on a ~26 °C panel, which is
the `temp == 0` path and no other. So the panel has still never been asked; it
has only never been listened to.

That no longer costs anything, which is why the row above stops short of a
board-level conclusion. The waveform consequence is fixed twice over in firmware
— upstream guards the failed read with a 20–30 °C default (worth −48.4 % of panel
busy time, `../../docs/notes.md`), and feeding the BMP581 reading in is strictly
better than any readback: calibrated, ambient rather than a self-heating die, and
write-only so it needs no SPI-mode juggling. What a successful probe would still
buy is a cross-check of the controller's own sensor and an `SSD2677` row here
that says something. It is diagnostics now, not a fix, and it was never a board
change — see [`../thermometer-c6/README.md`](../thermometer-c6/README.md), Rev B
candidates.

## Caveats before trusting any of this

- **Module docs understate it.** GDEW0213M21 Table 3-1 lists only `SDIN` and
  documents write procedures only, yet the panel demonstrably reads back. The
  capability is the chip's; the module vendor does not promise it, so it could
  vary between batches.
- **Nothing transfers between families.** An SSD168x command set floats entirely
  on a UC8151 and vice versa — measured both ways. Every family needs its own
  probe table.
- **These PDFs carry a diagonal "GOOD DISPLAY" watermark** that text extraction
  interleaves into the tables as stray `OD`/`AY`/`PL`/`IS`/`D`/`G` tokens. It
  reads convincingly as a column — it briefly looked like an open-drain pin type
  on the T81's `SDA`. Check any pin attribute against the rendered page.
- **The UC8151 framing is unresolved.** Reads give a stable `0x70` → `01 0e`,
  but the datasheet's `CHIP_REV` is `1101b`, and it notes OTP reads return a
  dummy first packet. Usable as an opaque fingerprint; not as "the revision".

Firmware probe: `display_probe_readback()` in `src/Display.cpp`, behind
`EPD_PROBE`. It reads every command twice, against a pulldown and a pullup — a
floating line follows its pull, a driven one does not, so each run carries its
own control.
