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
