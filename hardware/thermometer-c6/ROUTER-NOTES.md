# Greedy A* router (`generator/route.py`) — archaeology

**The board is hand-routed.** Since M5, `generator/pcb_routes.py` holds the
complete GUI routing (`HAND_ROUTED` sentinel) and `make route` aborts on it
rather than overwrite it. Rev A is frozen and built. `route.py` and its A* are
kept for one hypothetical: a re-route from scratch.

Nothing here is needed to edit the board today — see the `pcb-edit` skill and
`HAND-ROUTING.md` for that. This file exists so the knowledge survives, and so
nobody re-derives it the hard way if the router is ever unretired.

Companion: `PATHFINDER-NOTES.md` (the negotiated-congestion experiment, also
not adopted).

## The model

One greedy A* pass per net in `ROUTE_PLAN` order, no rip-up. Everything below
falls out of those two properties.

## Order is load-bearing

Power before signals: `EPD_VCC` must precede J4's digital pins or it loses
`Q2.3` outright — Q2.3's only escape is north, into the same B.Cu channel the
digital lanes cross the booster on.

A `ROUTE_PLAN` entry takes an optional 4th element `box=(x1,y1,x2,y2)` that
hard-clamps A*. Reach for it when a local net takes a board-long detour and eats
a scarce corridor: unboxed, `BOOT` runs 60mm round the south edge and up the
only west column, which `EN` needs for `SW1`.

## The same-net clearance waiver, and its two bugs

Clearance bitmaps waive clearance against the routed net's **own** copper.
Correct for copper, wrong for anything else — hence `stamp_hole()`, which is
net-agnostic. Two bugs of exactly this shape were found and fixed:

- `on_tree()` calling two disjoint same-net islands connected;
- vias landing inside same-net PTH pads.

Suspect the same exemption whenever the router does something illegal.

## Authored copper is obstacle **and** seed

A seed A* may ignore, leaving your stub dangling. Check after each pass and trim
what went unused.

**The seed is `islands[0]`, and island order is `pcb_layout.TRACKS` order.**
`route_all` merges every same-net island plus every unattached terminal pad;
islands always come first, and the first one is the tree the rest grow onto. So
authoring a second block of copper on a net that already has an authored block
*moves the seed* if it lands earlier in `TRACKS`.

Authoring an `L2.1`↔`C14.1` link re-seeded `EPD_VCC` at C14, and A* then hauled a
0.5mm B.Cu diagonal across the whole board to reach the J4 feed — `EPD_CS`,
`EPD_DC` and `EN` died 15mm away. Any authored `EPD_VCC` copper in the west has
to contain `Q2.3` as well, or not exist.

## Authored copper is never a local edit

An authored lane needs clearance only against other **authored** copper — every
routed net re-places on the next pass. The exceptions are routed structures with
a single legal window, which are de-facto rigid:

- `EPD_VCC`'s Q2.3 escape channel (over TP8, ~x29.9..30.15 y7.9..9.2, plus its
  diagonal to R17);
- `EPD_VCC`'s C14 spine (the x~21.95 B.Cu vertical the C14 window forces);
- the authored `EPD_VCC` staircase diagonal (x−y=26.55) that seals J4.12/13/14's
  stubs from the NE.

Blocking any of these fails 5–6 nets 15mm away (M5 negative-results table in
`LAYOUT-PLAN.md`).

With no rip-up, any block you author reshuffles unrelated nets across the whole
board — one `EPD_VCC` spine broke `+3V3` and both crystal terminals 20mm away.
Change **one** thing per `make route` and read the failure **diff**, not the
count. A cluster that starves is usually a *placement* bug, not a routing one:
fix rotation and order first. The gate row and the divider ladder both had every
shared node running diagonally across their own row.

Loop that worked: author a cluster in `pcb_layout.TRACKS` → check it alone with
`PCB_NO_ROUTES=1 python3 generator/pcb.py && kicad-cli pcb drc ...` → `make
route` → diff the failure list. `make route` wrote `out/stragglers.txt` and
printed only the delta vs the previous pass — fixed/new stragglers plus which
routed nets re-placed. The failure list names victims; the re-placed list names
candidate villains. Never pipe it through `tail`; the delta comes first.

## The router's own geometry, which is not DRC's

- **`stamp_seg` rasterizes diagonals as squares.** A 45° lane's clearance shadow
  is √2× its inflation — ~0.64mm per side against a 0.25mm track centre, ~0.88mm
  against a via centre. H/V segments stamp exact rects. Euclidean hand-checks
  pass where the bitmap blocks; use `verify/who.py` (Chebyshev-correct) and
  prefer H/V authored copper beside via windows.
- **A*'s via placement is stricter than DRC.** No new via lands within Chebyshev
  0.8mm of an existing via centre, or 0.55mm of any hole. Authored vias bypass
  `route.py` and answer only to DRC (0.8mm pairs are fine), but they pin A* out
  of the neighbourhood — count that cost before authoring.

## Debugging tools that were built for it

`verify/reach.py` first — flood fill with A*'s exact move rules from a given
island, showing where a net is walled in and its closest approach to each
stranded island. `--upto=NET` (with `PCB_NO_ROUTES=1`) reconstructs the true
mid-pass obstacle set: authored copper plus only the nets earlier in
`ROUTE_PLAN`. Then `probe.py` (per-cell blockage and flood membership),
`who.py` (names the culprit a bitmap can't) and `gap.py` (narrowest gap between
two islands, i.e. where one authored bridge would join them). `occupancy.py`
renders what A* actually sees, driven by `route.py`'s own bitmaps.

These stayed useful after the router retired — they are indexed in the
`pcb-edit` skill.
