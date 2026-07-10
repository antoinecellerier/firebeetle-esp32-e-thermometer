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

## Reproduce
```
make route            # greedy baseline: 12 stragglers, byte-identical
make route-pf         # negotiated-congestion (Stage 1)
python3 verify/drc_summary.py --gate
```
Diagnostics were run inline (see git history / the session); the two
routability probes are the load-bearing evidence.
