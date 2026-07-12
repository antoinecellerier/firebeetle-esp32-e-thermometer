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

Since M5 the whole board is hand-routed and `pcb_routes.py` is the copper
source of truth — harvest wholesale:

```bash
python3 generator/extract_tracks.py out/hand/thermometer-c6.kicad_pcb --all \
    -o generator/pcb_routes.py
python3 generator/pcb.py     # re-render, then gate (step 5)
```

Always use `-o` (atomic write) — **never a shell `>` redirect**, which
truncates `pcb_routes.py` before the harvester's own imports run.
Anonymous nets are renamed to their `~` names automatically (needs
`out/netlist.net`; run `make netlist` once if missing). Per-net mode
(`... NET [NET ...]`, prints entries for pasting) still exists for
surgical work.

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
make check
python3 verify/drc_summary.py --gate   # REAL=0 required
python3 verify/check_pcb.py            # trunk width, keep-out intersects
```

Unconnected items must be GND-only (the M6 pour owns GND). Beware stale
`out/drc.json` — regenerate before reading it. (`make route` is retired:
it aborts on the HAND_ROUTED sentinel.)

## 6. Commit

Commit `pcb_layout.py` + regenerated `pcb_routes.py` + board file together
(one cluster per commit, imperative message). If a pass leaves dangling
authored copper on a *routed* net, the router bypassed your stub — delete it.

## Debugging a stubborn net

`verify/reach.py NET W out.png` first (flood fill from the seed island —
shows exactly where it is walled in), then `who.py`/`gap.py`/`occupancy.py`
(see CLAUDE.md "Review tools"). Corridor truths live in LAYOUT-PLAN.md's M5
survey; router semantics (seeding, ordering, boxes) in CLAUDE.md.
