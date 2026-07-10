#!/usr/bin/env python3
"""PathFinder (negotiated-congestion) autorouter -> generator/pcb_routes.py.

Warm-starts from the committed pcb_routes.py, then rips up and reroutes the
contested ROUTE_PLAN nets each iteration against a shared, congestion-priced
cost grid (McMurchie-Ebeling): cells covered by >1 net accrue *history* cost so
nets negotiate apart over iterations, solving the zero-sum corridor contention a
single greedy pass cannot. Reuses route.py's clearance machinery verbatim
(build_bitmaps / stamp_* / astar / _copper_islands / route_one) -- a parallel
reimplementation of the legality rules is where the exemption-class bugs live.

Copper classes (Stage 1, ANCHOR=inf == the documented immovable baseline):
  pinned   - pads, holes, keepouts, board edge, and ALL authored pcb_layout.py
             copper: hard obstacles / fixed seeds, exactly as greedy sees them.
  free     - the ROUTE_PLAN nets' routed copper: fully negotiable, warm-started
             from committed pcb_routes.py, re-routed against congestion.
Lowering ANCHOR (Stage 2, only if Stage 1 leaves authored-boxed stragglers like
XTAL) would demote non-pinned authored copper to movable; not built yet.

The congestion state doubles as a placement diagnostic: cells with the highest
accumulated history are the board's chronic chokepoints (demand > capacity that
negotiation cannot resolve) -- report them + which refs sit nearest.

Run inside kicad's python (needs pcbnew for pad geometry):
    python3 generator/pathfind.py [--iters N] [--pres0 F] [--presmul F]
                                  [--histinc F] [--quiet]
Output contract identical to route.py: overwrites generator/pcb_routes.py and
writes out/stragglers.txt; `make route-pf` re-renders the board.
"""
import math
import os
import sys

import route as rt
from route import GRID, W, H, OX, OY, BASE_CLR, HV_CLR, VIA_R

# --- negotiation parameters (CLI-overridable) -------------------------------
ITERS = 40           # hard cap on rip-up/reroute rounds
PRES0 = 0.5          # present-sharing multiplier, iteration 0
PRES_MUL = 1.3       # grows each iteration so early sharing is cheap, late dear
PRES_CAP = 8.0       # ceiling: unbounded pres makes nets take board-long
                     # detours to dodge one cell, so history (targeted) does
                     # the late discrimination, not runaway present cost.
HIST_INC = 0.05      # history (mm) added to each over-used cell per round
PROBE_HW = 0.125     # 0.25mm-probe half-width for the route-exact cost cover
ANCHOR = math.inf    # Stage 1: authored copper immovable (fixed hard seeds)

LAYERS = ("F.Cu", "B.Cu")


# --- congestion / history grids ---------------------------------------------
class Field:
    """Per-layer negotiated-congestion state over the 0.05mm grid, with two
    distinct covers per net (see cover_of):

    cost[layer][idx] = free nets whose *violation-proximity* region covers the
        cell -- a centerline entering it means that net's copper would come
        within clearance of the covering net. This is what A* pays: it prices a
        real approaching-violation, and is 0 at legal min spacing so nets pack
        tight without penalty. hist adds on top (sticky chokepoint memory).
    over[layer][idx] = free nets whose *territory* (half the min spacing) covers
        the cell. >=2 == a genuine clearance violation; legal min-spaced
        neighbours do NOT trip it, so 'over==0' is a real convergence signal."""

    def __init__(self):
        self.cost = {l: bytearray(W * H) for l in LAYERS}
        self.over = {l: bytearray(W * H) for l in LAYERS}
        self.hist = {l: {} for l in LAYERS}
        self.cover = {}          # net -> (cost_cover, over_cover)
        self.touched = {l: set() for l in LAYERS}  # over cells ever covered

    def add(self, net, covers):
        self.cover[net] = covers
        cost_c, over_c = covers
        for l, cells in cost_c.items():
            g = self.cost[l]
            for idx in cells:
                if g[idx] < 255:
                    g[idx] += 1
        for l, cells in over_c.items():
            g = self.over[l]
            t = self.touched[l]
            for idx in cells:
                if g[idx] < 255:
                    g[idx] += 1
                t.add(idx)

    def remove(self, net):
        covers = self.cover.pop(net, None)
        if not covers:
            return
        cost_c, over_c = covers
        for l, cells in cost_c.items():
            g = self.cost[l]
            for idx in cells:
                if g[idx] > 0:
                    g[idx] -= 1
        for l, cells in over_c.items():
            g = self.over[l]
            for idx in cells:
                if g[idx] > 0:
                    g[idx] -= 1

    def overused(self):
        """{layer: set(idx)} of cells where >=2 nets' territories overlap."""
        out = {}
        for l in LAYERS:
            g = self.over[l]
            out[l] = {i for i in self.touched[l] if g[i] >= 2}
        return out

    def bump_history(self, overused, inc):
        for l, cells in overused.items():
            h = self.hist[l]
            for idx in cells:
                h[idx] = h.get(idx, 0.0) + inc

    def nets_touching(self, overused):
        """Free nets whose territory intersects an over-used cell."""
        hot = set()
        for net, (_, over_c) in self.cover.items():
            for l, cells in over_c.items():
                ov = overused.get(l)
                if ov and not cells.isdisjoint(ov):
                    hot.add(net)
                    break
        return hot

    def cell_cost(self, pres):
        """astar cell_cost callback reading the *current* cost grid + history.
        The routed net's own cover is removed before it routes, so the grids
        already exclude it -- no per-net bookkeeping in the hot loop."""
        cost, hist = self.cost, self.hist
        cF, cB = cost["F.Cu"], cost["B.Cu"]
        hF, hB = hist["F.Cu"], hist["B.Cu"]

        # scale the present term by the step length (GRID) so `pres` is a
        # dimensionless multiplier on a step: pres*cong=1 doubles that step's
        # cost. history is already in mm and accrues per cell along the path.
        gp = GRID * pres

        def cc(kind, layer, ix, iy):
            idx = iy * W + ix
            if kind == "via":  # a via occupies both layers at this cell
                return (gp * (cF[idx] + cB[idx])
                        + hF.get(idx, 0.0) + hB.get(idx, 0.0))
            g = cF if layer == "F.Cu" else cB
            h = hF if layer == "F.Cu" else hB
            return gp * g[idx] + h.get(idx, 0.0)
        return cc


# --- geometry: a net's clearance-shadow cells (mirrors rt.Bitmap.stamp_seg) --
def _rect_cells(x1, y1, x2, y2, out):
    ix1 = max(0, int(math.ceil(x1 / GRID)))
    iy1 = max(0, int(math.ceil(y1 / GRID)))
    ix2 = min(W - 1, int(math.floor(x2 / GRID)))
    iy2 = min(H - 1, int(math.floor(y2 / GRID)))
    for iy in range(iy1, iy2 + 1):
        base = iy * W
        for ix in range(ix1, ix2 + 1):
            out.add(base + ix)


def _seg_cells(x1, y1, x2, y2, infl, out):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9 or dx == 0 or dy == 0:
        _rect_cells(min(x1, x2) - infl, min(y1, y2) - infl,
                    max(x1, x2) + infl, max(y1, y2) + infl, out)
        return
    steps = max(1, int(length / (GRID * 2)))
    for i in range(steps + 1):
        t = i / steps
        px, py = x1 + dx * t, y1 + dy * t
        _rect_cells(px - infl, py - infl, px + infl, py + infl, out)


def cover_of(tracks, vias, is_hv):
    """(cost_cover, over_cover), each {layer: set(idx)}, for one net's copper.

    over_cover: centerline inflated by half-width + clr/2 -- the net's
      'territory'. Two territories overlap iff copper is closer than min spacing
      (a+b+clr), so >=2 territories on a cell == a real violation, and legal
      min-spaced neighbours do NOT overlap. This drives history + cleanup.
    cost_cover: centerline inflated by PROBE_HW + clr + half-width -- exactly
      route.py's clearance stamp for a 0.25mm probe track. A 0.25 centerline
      inside it would violate; at min spacing it sits on the boundary (cost 0),
      so nets pack to the legal limit without penalty. This is what A* prices."""
    clr = HV_CLR if is_hv else BASE_CLR
    cost = {l: set() for l in LAYERS}
    over = {l: set() for l in LAYERS}
    for net, layer, width, pts in tracks:
        hw = width / 2
        ci, oi = PROBE_HW + clr + hw, hw + clr / 2
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            _seg_cells(x1, y1, x2, y2, ci, cost[layer])
            _seg_cells(x1, y1, x2, y2, oi, over[layer])
    cvi, ovi = PROBE_HW + clr + VIA_R, VIA_R + clr / 2
    for net, x, y in vias:
        for l in LAYERS:
            _rect_cells(x - cvi, y - cvi, x + cvi, y + cvi, cost[l])
            _rect_cells(x - ovi, y - ovi, x + ovi, y + ovi, over[l])
    return ({l: c for l, c in cost.items() if c},
            {l: c for l, c in over.items() if c})


# --- warm start -------------------------------------------------------------
def load_warm_start():
    """Committed pcb_routes.py -> {net: (tracks, vias)} of free copper."""
    ns = {}
    try:
        with open(rt.OUT) as f:
            exec(compile(f.read(), rt.OUT, "exec"), ns)
    except (OSError, SyntaxError):
        return {}
    free = {}
    for t in ns.get("TRACKS", []):
        free.setdefault(t[0], ([], []))[0].append(t)
    for v in ns.get("VIAS", []):
        free.setdefault(v[0], ([], []))[1].append(v)
    return free


# --- the negotiation loop ---------------------------------------------------
def parse_straggler_hint():
    """Nets unrouted by the previous pass (out/stragglers.txt), to reroute
    fresh. A soft hint: absent -> we reroute every net at iteration 0."""
    try:
        with open(rt.STRAGGLERS) as f:
            return {ln.split(":", 1)[0].strip() for ln in f if ln.strip()}
    except OSError:
        return None


def negotiate(pads, alias, pads_by_key, params, quiet=False):
    segs0, vias0 = rt.authored_copper(pads)   # immovable authored copper
    hv_by_exp = {alias[n] for n in rt.HV_NETS}

    def is_hv(cname):
        return alias.get(cname, cname) in hv_by_exp

    # hard bitmaps per net (authored copper only; own-exempt) -- cached, since
    # authored copper never changes across iterations.
    map_cache = {}

    def hard_maps(exp, width):
        key = (exp, width)
        m = map_cache.get(key)
        if m is None:
            m = rt.build_bitmaps(pads, segs0, vias0, exp, width, alias)
            map_cache[key] = m
        return m

    # a net may have several ROUTE_PLAN entries (e.g. +3V3's 0.5mm trunk then
    # its 0.25mm branches); route them in order, chaining copper so later
    # entries seed off earlier ones -- exactly as greedy route_all does.
    entries_by_net = {}
    for e in rt.ROUTE_PLAN:
        entries_by_net.setdefault(e[0], []).append(e)
    net_order = list(entries_by_net)

    field = Field()
    free = {}          # net -> (tracks, vias)
    failed = {}        # net -> [reasons]

    def route_net(cname, pres):
        """Rip up cname, reroute all its entries against current congestion."""
        field.remove(cname)
        exp = alias.get(cname, cname)
        cc = field.cell_cost(pres)
        loc_segs, loc_vias = list(segs0), list(vias0)
        net_tr, net_vi, reasons = [], [], []
        for entry in entries_by_net[cname]:
            maps = hard_maps(exp, entry[1])
            tr, vi, fl = rt.route_one(entry, pads, alias, pads_by_key,
                                      loc_segs, loc_vias,
                                      maps_for=lambda e, w, m=maps: m,
                                      cell_cost=lambda e: cc)
            net_tr.extend(tr)
            net_vi.extend(vi)
            reasons.extend(why for _, why in fl)
        free[cname] = (net_tr, net_vi)
        if reasons:
            failed[cname] = reasons
        else:
            failed.pop(cname, None)
        field.add(cname, cover_of(net_tr, net_vi, is_hv(cname)))

    # warm start: seed the field from committed pcb_routes.py; the 35 settled
    # nets keep their copper, the stragglers (+ any net missing from the warm
    # start) route fresh against the warmed congestion at iteration 0.
    warm = load_warm_start()
    hint = parse_straggler_hint()
    for net, (tr, vi) in warm.items():
        if net in entries_by_net:
            free[net] = (tr, vi)
            field.add(net, cover_of(tr, vi, is_hv(net)))
    if hint is None:
        initial = list(net_order)
    else:
        initial = [n for n in net_order
                   if n in hint or n not in free]
    if not quiet:
        print(f"warm start: {len(free)} settled nets; routing "
              f"{len(initial)} fresh (stragglers+missing)", flush=True)
    for cname in initial:
        route_net(cname, params["pres0"])

    # Priority inversion: freeze the stragglers that placed. Greedy fails them
    # by routing them LAST into a full board; here they claim their scarce
    # corridors first and the flexible free nets negotiate AROUND them. A frozen
    # net is never rerouted and is ripped only as a last resort.
    frozen = {n for n in (hint or ()) if n not in failed and n in free
              and free[n][0]}
    if not quiet:
        print(f"froze {len(frozen)} placed stragglers: "
              f"{sorted(frozen)}", flush=True)

    for it in range(params["iters"]):
        ov = field.overused()
        n_over = sum(len(c) for c in ov.values())
        n_fail = len(failed)
        hot = (field.nets_touching(ov) | set(failed)) - frozen
        if not quiet:
            print(f"iter {it:2d}: unrouted={n_fail} overused={n_over} "
                  f"hot={len(hot)} top_hist={_top_history(field, 3)}",
                  flush=True)
        if n_over == 0 and n_fail == 0:
            break
        if it == params["iters"] - 1 or not hot:
            break
        field.bump_history(ov, params["histinc"])
        pres = min(PRES_CAP, params["pres0"] * (params["presmul"] ** (it + 1)))
        for cname in net_order:      # deterministic order
            if cname in hot:
                route_net(cname, pres)

    # guarantee a DRC-clean board: any residual over-use becomes a straggler,
    # ripping the max-coverage net but preferring free nets over frozen ones.
    resolve_overuse(field, free, failed, frozen, quiet)
    return free, failed, field


def resolve_overuse(field, free, failed, frozen, quiet):
    """Guarantee a DRC-clean board: rip nets until no territory over-use
    remains, greedily removing the net that covers the MOST over-used cells
    (a min-rip heuristic -- one bad net often owns many over-cells), but
    preferring free nets over frozen stragglers (only rip a frozen net when no
    free net touches the remaining over-use)."""
    ripped = 0
    while ripped <= 200:
        ov = field.overused()
        if not any(ov.values()):
            break
        cand = []
        for net, (_, over_c) in field.cover.items():
            cnt = sum(len(over_c.get(l, set()) & ov[l]) for l in LAYERS)
            if cnt > 0:
                cand.append((cnt, net, net in frozen))
        if not cand:
            break
        free_cand = [c for c in cand if not c[2]]
        victim = max(free_cand or cand, key=lambda c: c[0])[1]
        field.remove(victim)
        free[victim] = ([], [])
        failed.setdefault(victim, []).append("ripped: unresolved congestion")
        ripped += 1
    if ripped and not quiet:
        print(f"cleanup: ripped {ripped} net(s) to clear residual over-use")


def _top_history(field, n):
    items = []
    for l in LAYERS:
        for idx, h in field.hist[l].items():
            items.append((h, idx % W, idx // W, l))
    items.sort(reverse=True)
    return [(round(h, 1), round(x * GRID, 1), round(y * GRID, 1), l)
            for h, x, y, l in items[:n]]


# --- placement bottleneck: nearest refs to the top history cells ------------
def bottleneck_report(field, pads, n=6):
    items = []
    for l in LAYERS:
        for idx, h in field.hist[l].items():
            items.append((h, idx % W * GRID, idx // W * GRID, l))
    items.sort(reverse=True)
    lines = []
    for h, x, y, l in items[:n]:
        near = sorted(pads, key=lambda p: (p["cx"] - x) ** 2
                      + (p["cy"] - y) ** 2)[:3]
        refs = ", ".join(f"{p['ref']}.{p['num']}"
                         f"({math.hypot(p['cx']-x, p['cy']-y):.1f}mm)"
                         for p in near)
        lines.append(f"  hist={h:.1f} @({x:.1f},{y:.1f}) {l}: near {refs}")
    return lines


def main():
    argv = sys.argv[1:]

    def opt(flag, default, cast=float):
        if flag in argv:
            i = argv.index(flag)
            return cast(argv[i + 1])
        return default
    params = dict(
        iters=int(opt("--iters", ITERS)),
        pres0=opt("--pres0", PRES0),
        presmul=opt("--presmul", PRES_MUL),
        histinc=opt("--histinc", HIST_INC),
    )
    quiet = "--quiet" in argv

    rt.check_plan_covers_nets()
    pads = rt.load_pads()
    alias = rt.net_alias(pads)
    pads_by_key = {}
    for p in pads:
        pads_by_key.setdefault((p["ref"], p["num"]), []).append(p)

    prev = rt._load_prev_routes()
    free, failed, field = negotiate(pads, alias, pads_by_key, params, quiet)

    # flatten to route.py's output format, in ROUTE_PLAN order for stable diffs
    order = {e[0]: i for i, e in enumerate(rt.ROUTE_PLAN)}
    new_tracks, new_vias = [], []
    for net in sorted(free, key=lambda n: order.get(n, 1e9)):
        tr, vi = free[net]
        new_tracks.extend(tr)
        new_vias.extend(vi)

    with open(rt.OUT, "w") as f:
        f.write('"""Autorouted tracks (generator/pathfind.py) - regenerate with'
                ' `make route-pf`.\nHand-tweaks allowed: this is plain'
                ' TRACKS/VIAS data appended by pcb_layout.py."""\n\n')
        f.write("TRACKS = [\n")
        for net, layer, width, pts in new_tracks:
            f.write(f"    ({net!r}, {layer!r}, {width}, {pts!r}),\n")
        f.write("]\n\nVIAS = [\n")
        for net, x, y in new_vias:
            f.write(f"    ({net!r}, {x}, {y}),\n")
        f.write("]\n")
    print(f"\n{len(new_tracks)} track runs, {len(new_vias)} vias -> {rt.OUT}")

    failed_list = [(net, why) for net in failed for why in failed[net]]
    rt.report_delta(prev, new_tracks, new_vias, failed_list)

    print("\nplacement bottleneck (top history cells):")
    for line in bottleneck_report(field, pads):
        print(line)

    if failed_list:
        print(f"\nFAILED ({len(failed_list)}):")
        for net, why in failed_list:
            print(f"  {net}: {why}")
        sys.exit(1)


if __name__ == "__main__":
    main()
