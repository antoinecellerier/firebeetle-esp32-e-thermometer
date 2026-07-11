# Hand placing & routing workflow (KiCad GUI → generator harvest)

The generated `thermometer-c6.kicad_pcb` is never hand-edited. All GUI work
happens on a copy; results flow back into `generator/pcb_layout.py` and are
re-rendered. Worklist: `out/stragglers.txt` (12 terminals as of 2026-07-11).

**Division of labour:** steps 1–2 (and 4's GUI half) are the human part.
Steps 3, 5, 6 and the PLACE mirroring are mechanical — tell Claude which
nets you routed / which refs you moved and where the copy lives (default
`out/hand/`), and it ports everything back, gates, and commits.

## 0. Preconditions

```bash
make check          # must be fully green
make pcb            # fresh render of placement + checked-in routes
```

## 1. Make the working copy

```bash
mkdir -p out/hand
cp thermometer-c6.kicad_pcb thermometer-c6.kicad_pro thermometer-c6.kicad_dru out/hand/
```

Open `out/hand/thermometer-c6.kicad_pcb`. Same basenames = the GUI DRC
enforces the real rules (0.2mm netclass clearance, HV 0.3mm, 0.18mm inside
the `fpc-fanout` area, 0.5mm power widths). `out/` is gitignored.

## 2. Route in the GUI

- Targets: the terminals in `out/stragglers.txt`. Ignore GND ratsnest —
  it waits for the M6 pour.
- Route the NE-gate cluster (`EPD_CS`/`EPD_DC`/`EPD_RST`/`EPD_BUSY`/
  `~EPD_VPP`) in one sitting: the five contend for the same gate, partial
  harvests there invalidate each other.
- You may rip and re-route existing *routed* copper freely (it is
  regenerated every `make route` anyway). Treat *authored* copper as
  expensive to move (see `verify/net.py NET` — authored islands are listed
  with their `pcb_layout.py` line numbers).

## 3. Harvest tracks/vias back into the generator

```bash
python3 generator/extract_tracks.py out/hand/thermometer-c6.kicad_pcb NET [NET ...]
```

Paste the printed TRACKS/VIAS entries into `generator/pcb_layout.py` —
**never into `pcb_routes.py`** (that file is overwritten wholesale by
`make route`). Anonymous nets print under their exported KiCad names
(`Net-(J1-Pin_1)` style); rename to the `~` names `pcb_layout.py` uses.

## 4. Placement tweaks (two traps)

- Nothing harvests placement. Mirror moved footprints into
  `pcb_layout.PLACE` by hand: entries are `(x, y, rot[, "B"])` in
  **board-relative mm, origin (100,100)** — subtract 100 from each
  KiCad-shown absolute coordinate. Rotation is
  `SetOrientationDegrees` semantics (what the GUI shows).
- Authored TRACKS/VIAS are absolute coordinates and do **not** follow a
  moved component. Moving anything inside a hand-authored cluster (FPC
  fanout, booster core, NE-gate copper, EPD_VCC spine) orphans that copper;
  it must be re-authored. Cheapest tweaks are in the all-A* west/center
  signal field; the east side is expensive.
- Known negative result: moving C10/R9 does NOT free `XTAL_32K_P` — its box
  is +3V3's authored elbow (PATHFINDER-NOTES Stage-2 acid test).

## 5. Gate every iteration

```bash
make route          # re-places all free nets around the new authored copper
make drc            # real rules incl. fanout relaxation
```

Read the straggler **delta** that `make route` prints (fixed/new + which
nets re-placed) — one cluster per iteration, otherwise failures 15mm away
are unattributable. `make check` before committing.

## 6. Commit

Commit `pcb_layout.py` + regenerated `pcb_routes.py` + board file together
(one cluster per commit, imperative message). If a pass leaves dangling
authored copper on a *routed* net, the router bypassed your stub — delete it.

## Debugging a stubborn net

`verify/reach.py NET W out.png` first (flood fill from the seed island —
shows exactly where it is walled in), then `who.py`/`gap.py`/`occupancy.py`
(see CLAUDE.md "Review tools"). Corridor truths live in LAYOUT-PLAN.md's M5
survey; router semantics (seeding, ordering, boxes) in CLAUDE.md.
