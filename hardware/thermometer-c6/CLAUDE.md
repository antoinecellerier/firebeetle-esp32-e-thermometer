# CLAUDE.md — hardware/thermometer-c6 (custom PCB)

Read first: `README.md` (design rationale, pin map, jumper tables, bench
procedures); `LAYOUT-PLAN.md` (next-phase instructions); `BRINGUP.md`
(first-article checklist once boards arrive).

## Schematic workflow

- **IMPORTANT: never hand-edit `thermometer-c6.kicad_sch` — it is generated.**
  Edit `generator/circuit.py` (parts/nets/NC/LCSC) and `generator/layout.py`
  (placement/wires/labels), then run `make check`.
- `make check` must be fully green before committing. `LAYOUT ERRORS` output
  is a build failure by design — fix the layout, never weaken the check.
- A circuit-intent change touches three files together: `circuit.py`,
  `verify/invariants.py` (independent restatement of intent), README tables.
- After visual changes, review zones as images: `make pdf`, crop each zone
  with `pdftoppm -r 200 -png -x/-y/-W/-H` (px = mm × 200/25.4; origins/sizes
  in `layout.ZONES`), Read the PNGs, iterate until clean.

## PCB workflow

- **IMPORTANT: never hand-edit `thermometer-c6.kicad_pcb` — it is generated.**
  Authored data lives in `generator/pcb_layout.py` (PLACE / KEEPOUTS / zones;
  TRACKS/VIAS are empty since M5); `make pcb` renders the board from it plus
  `generator/pcb_routes.py`.
- **Since M5, `pcb_routes.py` IS the board's copper**: the complete GUI
  hand-routing, harvested verbatim (`HAND_ROUTED` sentinel — pcb.py renders
  it without dogleg insertion, `make route` refuses to overwrite it without
  `FORCE_REROUTE=1`; route.py/the A* survive only for archaeology and for
  a hypothetical re-route from scratch). Copper edits happen in the KiCad
  GUI per `HAND-ROUTING.md` (copy in `out/hand/`, edit, then
  `extract_tracks.py COPY --all > generator/pcb_routes.py`), or by editing
  the polyline data in `pcb_routes.py` directly for small mechanical tweaks
  — both are legitimate; DRC is the gate either way.
  `extract_tracks.py` harvests only signal copper (GND excluded);
  `verify/hand_diff.py COPY` audits every OTHER unharvested GUI edit
  (placement / GND vias+tracks / silk / copper-graphics / outline /
  signal-sync) and `--apply` mirrors placement + STITCH vias into
  `pcb_layout.py`. Run it (exit 0) before the gate.
- Gate: `make check` + DRC copper-clean (`python3 verify/drc_summary.py
  --gate`, REAL=0) + `python3 verify/check_pcb.py`. `starved_thermal` waits
  for M6's pours, `silk_*` for M7; unconnected = GND-only until the pour.
  Beware `out/drc.json` staleness — regenerate before reading it.
- **Cutting a new revision is one character**: `circuit.REV` (`generator/
  circuit.py`) is the single source of truth, consumed by `generate.py` (the
  schematic title block), `pcb_layout.SILK` (the back-silk line), `pcb.py`
  (the `FAB_STAMP` injection target) and `check_fab.py` (the stamp
  assertion). `check_pcb.py` only asserts the `"rev "` token, so it is
  revision-agnostic by design. Change `REV`, `make check`, `make fab`.
  **Only the LETTER is committed.** The hash and date cannot be — a file
  cannot contain the hash of the commit that contains it. They are injected
  at fab-export time into the throwaway `out/fab/board/` copy from a clean
  tree, which is exactly what lets `rev A 3ed40fe 2026-07-20` on a physical
  board name an exact commit; `check_fab` asserts the COMMITTED board carries
  no stamp to keep that guarantee. Never bump `REV` retroactively: the stamp
  is physically on boards already built and `archive/order-*/` describes them.
- **Fab export: `make fab`** = stamped render (`FAB_STAMP` + `PCB_OUT_DIR`
  into `out/fab/board/`, `rev A <hash> <date>` on silk) → **full-severity
  DRC** on the stamped board (`kicad-cli ... --severity-all`) gated by
  `drc_summary --gate-fab` (STRICT: passes iff REAL=0 AND DEFERRED=0, so every
  remaining violation must be explicitly waived by a scoped rule — currently
  none; the accepted WAIVED list is printed to the fab log). The J3 edge-launch
  `copper_edge_clearance` waiver was deleted on 2026-07-20: it was waiving a
  1.415mm placement error (`out/j3-datum/`), not a design intent. Fix geometry,
  don't add waivers. The raw `make drc` target still halts on ANY
  violation (routing/manual use); it is deliberately NOT a `fab` prereq. →
  gerbers/drill + `fab_cpl.py` CPL/BOM/rotation-checklist → zip →
  `verify/check_fab.py` (re-derives the same REAL=0/DEFERRED=0/waived-allowed
  DRC verdict). The committed board is **never** stamped (the guard rejects a
  dirty tree so the stamp names the exact commit); ordering steps are in
  `ORDERING.md`.
- pcbnew's zone fill is **not byte-stable**: back-to-back `pcb.py` runs can
  leave `thermometer-c6.kicad_pcb` dirty with nothing but `(xy ...)` fill
  coordinates changed. `git diff` it before believing you changed the board.
- **Stale `__pycache__` renders phantom copper**: rewriting `pcb_routes.py`
  twice within the same second with the same file size makes the old
  bytecode cache entry look valid, and the next `pcb.py` renders copper
  that is not on disk (phantom DRC shorts, gate flapping). Any tool that
  rewrites generator modules in a loop must run children with
  `PYTHONDONTWRITEBYTECODE=1` (straighten.py does); when DRC results look
  impossible, `rm -rf generator/__pycache__` and re-render before believing
  them.

### Scripting the board (pcbnew, KiCad 10)

Prefer the `verify/` tools below; write ad-hoc pcbnew only for one-off geometry
— and start it from the shared helper (board origin is (100,100); coords nm):

```python
import sys; sys.path.insert(0, "verify")
from geom import load, rel, vi, seg_width
b = load()                # committed board; load("out/hand/...", fill=False)
x, y = rel(pad.GetPosition())   # nm → board-mm, origin removed
```

- **Track vs via width differ**: `track.GetWidth()` (no arg);
  `via.GetWidth(pcbnew.F_Cu)`. Calling `GetWidth()` on a via spams
  `PCB_VIA::GetWidth called without a layer` asserts to stderr — harmless,
  drop with `2>/dev/null`.
- Element type: `t.Type() == pcbnew.PCB_VIA_T` / `PCB_TRACE_T` / `PCB_ARC_T`.
- To import a `verify/`/`generator/` module, `sys.path.insert(0, "verify")`
  then `import gnd_islands` etc.; run with `PYTHONDONTWRITEBYTECODE=1`.

`generator/pcb.py` env interface: `PCB_NO_ROUTES=1` (authored copper only),
`PCB_OUT_DIR=<dir>` (render target), `FAB_STAMP="<hash> <date>"` (silk stamp).

Toolchain present: `kicad-cli` 10.0.4, `pcbnew` python module, `inkscape`,
`convert`/`magick`, `freecad`/`freecadcmd` (lowercase), `pdftoppm`, `gs`.
Absent: `rsvg-convert`, `openscad`, `zip` (use `python3 -m zipfile`),
`pio` on PATH (it lives at `~/.platformio/penv/bin/pio`).

### What DRC actually enforces (not what `pcb.py` sets)

Netclass clearance **0.2mm** — the 0.15 board minimum is overridden by the
Default netclass. Hole-to-hole 0.25. HV nets 0.3, relaxed to 0.18 inside the
`fpc-fanout` marker area. `VBAT`/`VSYS`/`+3V3`/`EPD_VCC` and both battery `~`
nets carry a 0.5mm min-width DRU rule. Falling out of that: two 0.25mm tracks
need 0.45mm centre-to-centre; a 0.6mm via needs 0.625mm from a neighbouring
0.25mm track centre, 0.8mm from another via, and `drill/2 + 0.4` from any
other hole. Via-in-pad is fine for JLC and has solved several impossible
escapes.

### Geometry traps

- `pad.GetSize()` is **pre-rotation**. Derive every margin from
  `pad.GetBoundingBox()` (which is what `verify/pads.py` prints).
- Clearance to a pad corner is the distance to the track **segment**, not to
  its infinite line. Getting this wrong reads as a violation that isn't there,
  and hides ones that are.
- Two parallel 45° lanes 0.5mm apart in y are only **0.354mm** apart
  perpendicular. A fan-out cannot turn all its lanes at once: cascade the
  drops, one x-window each, so no lane is ever diagonal beside a diagonal.
- A bench pad on an HV net is a **2.1mm-square B.Cu wall**: 1.5mm of pad plus
  the 0.3mm HV clearance on each side. `TP6`/`TP7`/`TP10` all sit outside the
  `fpc-fanout` marker, so none of them gets the 0.18mm relaxation. `TP7` alone
  pinches the B.Cu channel south of the booster to a 0.30mm slot.
- A through-hole via inside an SMD pad still has an **F.Cu annulus**, so it
  must clear F.Cu copper crossing that pad's face, not just B.Cu. This is what
  fixes `C14.1`'s via at y23.65: `~BAT_IN` runs F.Cu at y22.9, so the annulus
  cannot sit north of 23.15 + 0.2 + 0.3.
- **route.py's `stamp_seg` rasterizes diagonals as squares**: a 45° lane's
  clearance shadow is √2× its inflation — ~0.64mm per side against a 0.25mm
  track centre, ~0.88mm against a via centre. H/V segments stamp exact rects.
  Euclidean hand-checks pass where the bitmap blocks; use `verify/who.py`
  (Chebyshev-correct) and prefer H/V authored copper beside via windows.
- **A*'s via placement is stricter than DRC**: no new via lands within
  Chebyshev 0.8mm of an existing via centre or 0.55mm of any hole. Authored
  vias bypass route.py and answer only to DRC (0.8mm pairs are fine), but
  they pin A* out of the neighbourhood — count that cost before authoring.

### The router (`generator/route.py`)

One greedy A* pass per net in `ROUTE_PLAN` order, no rip-up. Consequences:

- **Order is load-bearing.** Power before signals: `EPD_VCC` must precede J4's
  digital pins or it loses `Q2.3` outright (Q2.3's only escape is north, into
  the same B.Cu channel the digital lanes cross the booster on).
- A `ROUTE_PLAN` entry takes an optional 4th element `box=(x1,y1,x2,y2)` that
  hard-clamps A*. Reach for it when a local net takes a board-long detour and
  eats a scarce corridor (unboxed, `BOOT` runs 60mm round the south edge and
  up the only west column, which `EN` needs for `SW1`).
- Clearance bitmaps waive clearance against the routed net's **own** copper.
  Correct for copper, wrong for anything else — hence `stamp_hole()`, which is
  net-agnostic. Two bugs of exactly this shape are fixed (`on_tree()` calling
  two disjoint same-net islands connected; vias landing inside same-net PTH
  pads). Suspect the same exemption whenever the router does something illegal.
- Authored copper is obstacle **and** seed — and a seed A* may ignore, leaving
  your stub dangling. Check after each pass and trim what went unused.
- **The seed is `islands[0]`, and island order is `pcb_layout.TRACKS` order.**
  `route_all` merges every same-net island plus every unattached terminal pad;
  islands always come first, and the first one is the tree the rest grow onto.
  So authoring a second block of copper on a net that already has an authored
  block *moves the seed* if it lands earlier in `TRACKS`. Authoring an
  `L2.1`↔`C14.1` link re-seeded `EPD_VCC` at C14, and A* then hauled a 0.5mm
  B.Cu diagonal across the whole board to reach the J4 feed — `EPD_CS`,
  `EPD_DC` and `EN` died 15mm away. Any authored `EPD_VCC` copper in the west
  has to contain `Q2.3` as well, or not exist.

### IMPORTANT: authored copper is never a local edit

- An authored lane needs clearance only against other **authored** copper —
  every routed net re-places on the next pass. The exceptions are routed
  structures with a single legal window, which are de-facto rigid: EPD_VCC's
  Q2.3 escape channel (over TP8, ~x29.9..30.15 y7.9..9.2 + its diagonal to
  R17), EPD_VCC's C14 spine (the x~21.95 B.Cu vertical the C14 window
  forces), and the authored EPD_VCC staircase diagonal (x−y=26.55) that
  seals J4.12/13/14's stubs from the NE. Blocking any of these fails 5-6
  nets 15mm away (see the M5 negative-results table in LAYOUT-PLAN.md).

With no rip-up, any block you author reshuffles unrelated nets across the whole
board (one `EPD_VCC` spine broke `+3V3` and both crystal terminals 20mm away).
Change **one** thing per `make route` and read the failure **diff**, not the
count. A cluster that starves is usually a *placement* bug, not a routing one —
fix rotation and order first (the gate row and the divider ladder both had
every shared node running diagonally across their own row).

Loop that works: author a cluster in `pcb_layout.TRACKS` → check it alone with
`PCB_NO_ROUTES=1 python3 generator/pcb.py && kicad-cli pcb drc ...` → `make
route` → diff the failure list.

### Review tools (`verify/` — usage in each module's top docstring; they do NOT parse `--help`)

- `make route` writes `out/stragglers.txt` and prints only the delta vs the
  previous pass: fixed/new stragglers plus which routed nets re-placed
  (the failure list names victims; the re-placed list names candidate
  villains). Never pipe it through `tail` — the delta comes first.
- `net.py NET [NET ...]` — one net at a glance: authored TRACKS/VIAS with
  pcb_layout.py line numbers and island grouping (islands[0] = seed),
  routed copper, pads, straggler lines.
- `plot_pcb.py [--crop x1 y1 x2 y2]` — board map, courtyards, ratsnest.
- `pads.py [REF | REF.PAD | net:N | box:x1,y1,x2,y2]` — pad/courtyard geometry.
- `copper_stats.py [BOARD] [--vs REF]` — routed-copper census (segments, vias,
  per-layer/per-net length); `--vs` takes a board file or a git rev and prints
  the A/B delta with per-net movers and vias by region.
- `gnd_islands.py [BOARD] [--png OUT]` — GND connectivity + single-point-of-
  failure audit; default board is the committed one, pass `out/hand/...` to
  audit a GUI copy.
- `occupancy.py NET WIDTH OUT.png [x1 y1 x2 y2] [--via]` — what A* actually
  sees, driven by `route.py`'s own bitmaps. `PCB_NO_ROUTES=1` shows authored
  corridors, unset shows the current board. Reason about corridors from this,
  never from intuition or from the board renders.
- `freespot.py W H [--ignore=REF,..] [--near=x,y]` — courtyard-aware free
  rectangles, for deciding whether a starved part has anywhere else to go.
- `reach.py NET W OUT.png [x1 y1 x2 y2] [--seed=N] [--upto=NET]` — flood
  fill with A*'s exact move rules from island N; says which islands are
  reachable and where the flood's closest approach to each stranded one is.
  **Debug every straggler with this first.** `--upto=NET` (needs
  `PCB_NO_ROUTES=1`) reconstructs the net's true mid-pass obstacle set:
  authored copper + only the nets earlier in ROUTE_PLAN.
- `probe.py NET W [--upto=NET] SEED x,y ...` — per-cell trk/via blockage and
  flood membership (SEED = island index or `x,y,F`).
- `who.py NET W [--upto=NET] x,y [radius]` — nearby copper elements with
  distances and trk/via margins; names the culprit a bitmap can't.
- `gap.py NET W [--upto=NET] seedA seedB` — narrowest gap between two
  islands' flood regions, i.e. where one authored bridge would join them.

## Conventions & traps

- `~`-prefixed nets are anonymous: no sheet label, matched by pin set in
  check_netlist, must be fully routed (no label fallback).
- Wire diodes/FETs by function (A/K, G/S/D), never by pin number — numbering
  differs across libraries.
- Don't "simplify" the transform/field-rotation code in generate.py without
  re-running a netlist probe; KiCad rotates property text with the symbol
  and mirrors justification at effective 180°.
- Populate-exactly-one pairs: U5/U6 sensors (both addr 0x47); one RESE
  jumper (JP2/3/4); one inductor jumper (JP5/6).
- TP4 (3V3) is probe-only — RT9080 forbids back-drive; inject bench power at
  the J2/JP1 battery-side break.
- Re-verify LCSC stock at order time (thin: MINI-1, Si1308EDL; BMP581 out of
  stock → populate U6 BMP585 instead).

## Settled decisions — don't re-ask

LDO not buck; indoor-only charging 0–45°C (silkscreen); 100mA charge;
JLCPCB economy assembly; GND-first debug header without VBAT; ENIG finish;
POFV (epoxy filled & capped) via covering; **no order mark on the board**
("Remove Mark"; JLC support confirmed 2026-07-20 that the order-number-at-a-
specified-position service is discontinued, so the authored `JLCJLCJLCJLC`
back-silk token was deleted rather than left as a stale artifact).
