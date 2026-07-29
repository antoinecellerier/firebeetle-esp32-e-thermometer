# PathFinder experiment — results (branch `pathfinder-experiment`)

Negotiated-congestion router built per LAYOUT-PLAN §5 / the quirky-rabbit plan.
Developed in a worktree; **not merged, not adopted.** Greedy `route.py` is
untouched behaviourally (the refactor is verified byte-identical).

## What was built
- `route.py` refactor (committed): additive `cell_cost` A* hook + `route_one`
  extracted from `route_all`. **Greedy output byte-identical, same 12
  stragglers** — proven safe.
- `verify/drc_summary.py` (committed): text DRC digest; `--gate` classifies
  REAL (clearance/width/hole) vs DEFERRED (dangling/unconnected) vs WAIVED
  (M6 thermal / M7 silk). Baseline board: **REAL=0**.
- `generator/pathfind.py`: negotiated-congestion loop. Two-grid cost model
  (route-exact violation-proximity grid for A* pricing; territory grid for
  real-overlap detection), history, warm start, straggler-priority freeze,
  min-rip cleanup, placement-bottleneck report. `make route-pf`.

## Decisive diagnostic (route.py-exact hard legality)
- Each straggler routed **individually** against *authored copper only* (all 35
  free nets absent): **10 of 11 succeed**; only **XTAL_32K_P fails** — it is
  boxed by *immovable authored* copper (PWR_EN x17.75 column, +3V3 elbow) +
  cap placement. Exactly the LAYOUT-PLAN prediction. → XTAL needs Stage 2
  (movable authored copper) or a placement move; routing alone cannot fix it.
- Each straggler against *authored + the 35 settled nets*: only **1 of 11**
  (VBUS_SENSE) succeeds. → the other 10 are boxed by the *settled free-net
  copper*, i.e. corridor contention, not by each other.

## Stage-1 result (authored copper immovable): does NOT beat greedy
The board is at capacity with authored copper fixed. Every strategy lands at
>= greedy's 12:
- Global soft negotiation (40 iters): over-use plateaus ~13k; cleanup → ~15
  stragglers.
- Straggler-priority freeze: froze 10, free nets can't clear residual (the 10
  were routed simultaneously and overlap each other) → >= 12.
- Sequential-hard priority (stragglers placed first, hard, then free nets):
  only 5 stragglers place mutually-legal; then **6 free-net failures including
  +3V3, ~EPD_VGH, EPD_GDR** (stragglers-first starves the power/HV nets that
  greedy routes first). TOTAL = 12, and a *worse* set (breaks power).

**Conclusion:** with authored copper immovable the corridors cannot carry more
than the current 35 routed nets, regardless of order or negotiation. Each
straggler is routable alone; collectively they and the free nets contend for
the same saturated corridors. The win requires **Stage 2** (demote non-pinned
authored copper to movable — the anchor sweep) and/or **placement** changes
(XTAL's C10/R9 + cap column). Go/no-go criterion (a) "strictly more terminals
than greedy" is **not met** by Stage 1.

## Stage 2 (movable authored copper) — feasibility PROVEN
`--stage2` demotes anchored authored copper (the 28 nets authored AND in
ROUTE_PLAN, minus EPD_VCC) to negotiable; pinned = EPD_VCC's rigid structures +
the 13 pure-authored nets + pads/keepouts. `--anchor A` keeps anchored nets near
their authored geometry (cost A per off-home cell) to preserve intent + damp
thrash.

- **All 12 stragglers, including XTAL_32K_P, route simultaneously at iteration 0**
  (`unrouted=0`). A fully-routed board EXISTS with movable authored copper.
- Acid test: XTAL routes vs *EPD_VCC-pinned-only* and vs *all-except-+3V3*.
  So **XTAL is freed by re-routing +3V3's authored elbow — NOT a placement
  problem** (contra the earlier LAYOUT-PLAN note about moving C10/R9). The caps
  alone don't block it.
- Remaining gap: the iteration-0 solution is complete but *overlapping*;
  legalizing it (separating to DRC-clean) is a solver-convergence problem. The
  soft-negotiation loop reduces overlap slowly; a clean 0-straggler board needs
  either more solver work (better rip-up scheduling / hard-legal RRR) or using
  these now-known-feasible paths to guide manual harvest.

**Bottom line:** M5 IS solvable — the 12 are not individually impossible, they
are corridor-contended, and moving non-pinned authored copper resolves it.

## Legalization attempts — none cleanly converge on this saturated board
The Stage-2 solution is complete but overlapping; three strategies to legalize
it (separate to DRC-clean) all thrash:
1. **Global soft negotiation** (Stage 1 & 2): over-use plateaus (~11-16k cells),
   doesn't reach 0 within a practical iteration budget; ~1min/iter.
2. **Hard-legal rip-up-reroute** (`--rrr`): keeps the committed set mutually
   legal, routing one net at a time and ripping the committed nets it crosses.
   **Diverges** — committed shrinks 35→17, queue grows 11→28, rips climb past
   67. Root cause: a straggler crossing a densely-packed corridor overlaps
   *many* parallel nets at once, so it rips a whole corridor's worth; each
   ripped net, re-routed into the same saturation, rips more. History can't
   outpace the cascade. Tightening the rip cost / cost-cover didn't change the
   trajectory (the saturation, not the tuning, dominates).
3. **Canonical PathFinder** (`--allnets`): reroute EVERY net each iteration in
   fixed order (the textbook convergent method; the hot-subset above is a speed
   optimisation that can stall coordinated shifts). Blocked by **performance** —
   a congestion-priced (soft) A* explores ~7× more nodes than a hard route
   (0.8s vs 0.12s) and reroute-all is ~46 nets/iter, so an iteration is minutes
   and convergence needs dozens. Speed levers added + measured, both greedy-safe
   (defaults preserve byte-identical): `route_one(fallback_mm=)` bounds the
   board-wide fallback search; `astar(hweight=)` weighted A* cuts nodes 3-5×
   (hw 2.0 → soft route 0.15s ≈ hard). Even so, dense reroute-all stays
   multi-minute/iter (many nets fall to the wide fallback once congestion prices
   their old path out).

**Assessment:** the *algorithm* is validated (Stage 2 proves a legal solution
exists; canonical negotiated-congestion is the right convergent method), but a
**practical** auto-legalizer for a board this dense needs a compiled/vectorised
router core (the pure-Python soft A* is the wall) and/or a coordinated multi-net
shift primitive (move a corridor's nets together by a lane). That is a large,
uncertain effort; the new `hweight` / `fallback_mm` knobs are reusable
regardless.

**Pragmatic path** (reliable, uses the proof): targeted manual harvest — author
the specific authored-copper moves the feasibility proof identifies, starting
with re-routing +3V3's elbow to free XTAL (high-confidence 12→11), one cluster
per `make route`, the workflow the NE-gate harvest already used.

## Reproduce
```
make route                                    # greedy baseline: 12, byte-identical
python3 generator/pathfind.py --iters 40      # Stage 1 (authored immovable)
python3 generator/pathfind.py --stage2 --anchor 0.1 --iters 30   # Stage 2
python3 verify/drc_summary.py --gate
```
Wrap perf-critical runs with `tlpctl launch --profile performance --`.
Diagnostics were run inline (git history / session); the routability probes and
the Stage-2 `unrouted=0` are the load-bearing evidence.

## Freerouting round-trip (2026-07-11) — external router, same 12 stragglers

`generator/freeroute.py` (`make freeroute`) exports a variant board to
Specctra DSN, post-processes it (0.25mm default width; `power` class 0.5mm;
`hv` class 0.3mm clearance; optional `(type fix)` on authored copper), runs
the Freerouting jar batch-mode, imports the `.ses` and DRC-summarizes the
result under the real `.kicad_dru`. KiCad's DSN export carries the antenna
keepout, the sensor via-keepouts and the GND pour (as a plane), so the
constraint fidelity is decent; only the fpc-fanout 0.18mm relaxation and the
per-area width rules are inexpressible in DSN.

Configurations tried (Freerouting 1.9.0, the version reputed to route better
than the 2.x line):

| config | result |
|---|---|
| A: full board, authored fixed | routes NOTHING new — 1.9 batch mode **skips any net containing a fixed wire** (verified: identical DSN ± fix marking flips exactly those nets), and broke EPD_VCC by ripping it |
| B: authored-only board, authored fixed | 15min41s, 31 of ~47 free nets unrouted (fix-skip poisoned all authored-copper nets) |
| A relaxed to 0.18mm clearance everywhere | no change — clearance was not the blocker |
| A all-rippable (best config) | 11.76s, otherwise DRC-clean, but **the exact baseline 12 straggler terminals remain unconnected**; partial stubs/dangling vias left on the knot nets; USB_D− and ~EPD_VPP not attempted at all |
| Freerouting 2.2.4 (any config) | `java.lang.StackOverflowError` even with `-Xss64m` — unbounded recursion on this input; unusable |

**Assessment:** Freerouting's free-angle rip-up, even with authored copper
rippable (Stage-2-level freedom), gives up on the corridor knot in seconds —
its batch rip-up depth is far shallower than what the contention needs, and
it found none of the coordinated moves the Stage-2 proof identifies (e.g. the
+3V3 elbow re-route). Third independent router to stall on the same 12
terminals; nothing worth harvesting (its rework of the routed nets is
free-angle churn with no straggler gain). Reinforces the **targeted manual
harvest** as the pragmatic path.

## Simplification probes (2026-07-11 evening) — where the density actually binds

Three DSN-space experiments quantify what makes the board hard (all Freerouting
1.9, batch, `-mp 100`; DSNs derived from `a.dsn` by script):

- **2.2.5-SNAPSHOT (2026-07-02 build)**: NPE in ShapeTree during fanout pass 3
  (`Storable.compareTo … "this.object" is null`). With 2.2.4's StackOverflow,
  the whole 2.x line is unusable on this input; 1.9 is the only viable jar.
- **No debug header** (`a-noJ5.dsn`: J5 deleted from placement + pins, its
  nets' wiring stripped so they re-route fresh): clears exactly J5's own three
  straggler terminals (EN.J5.3, DBG_IO5, VBUS_SENSE west leg) plus most of the
  west funnel — but the NE-gate cluster (CS/DC/RST/BUSY/VPP), XTAL_32K_P
  (105 wires of thrash before giving up), SCL's last 0.23mm and USB_D− are
  untouched. The header is real load but NOT the bottleneck.
- **Bare board** (`a-bare.dsn`: ALL wiring stripped — placement only, the
  "could FR have routed this board from scratch" test): 29m47s, ~24 signal
  nets unconnected, dominated by the J4/FPC ecosystem (every EPD rail + SPI
  line + the fanout-adjacent HV nets) plus power trunks. **The hand-authored
  copper is load-bearing**: the 0.18mm fanout relaxation is inexpressible in
  DSN, and FR cannot escape the 0.5mm-pitch connector under 0.2/0.3 rules.

**Spacing verdict:** spreading components would not rescue automation — the
two hard chokes are pitch-fixed (J4's 0.5mm FPC fanout; U1's NE castellated
pin gate), not inter-cluster spacing. Density between clusters is what FR
already handles (west funnel cleared once J5's load left).

## Resolution (2026-07-12): M5 closed by complete GUI hand-routing

The user hand-routed the ENTIRE board in the KiCad GUI (all non-GND nets,
DRC-clean, board grown 48×35 → 49×36, ~36% of segments rerouted vs the
autorouted baseline). Every knot the three routers stalled on fell to
interactive rip-up with human judgment. The copper was harvested wholesale
into `generator/pcb_routes.py` (HAND_ROUTED sentinel; `extract_tracks.py
--all -o`); route.py/pathfind.py remain for archaeology and a hypothetical
from-scratch re-route only. As-routed snapshot: [`archive/`](archive/). Follow-on
analysis: `verify/topo.py` + `out/topo/REPORT.md` (pour-damage ranking,
antenna-strip audit, power-via audit).

Also for the record: cluster-scoped Opus agents with the corridor facts DID
make real progress where batch autorouters could not (~EPD_VPP, EN, XTAL —
12→9 in one round, commits b51af3a/1db17ea/1773b61, all since superseded by
the hand routing). The binding lesson stands: on a board this dense the
productive split is human rip-up in the GUI + scripted harvest/gating, not
better autorouting.
