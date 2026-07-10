#!/usr/bin/env python3
"""Who blocks this cell? Lists copper elements near a point with margins.

Usage: PCB_NO_ROUTES=1 who.py NET WIDTH --upto=NET x,y [radius]
For each nearby copper element (segment/via/pad) of another net, prints the
distance from the point, the clearance a track-center of NET would need
(trk) and a via-center would need (via), and whether each is violated.
"""
import os, sys, math

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "generator"))
os.chdir(PROJECT)

import pcb_layout as pl  # noqa
import route as rt       # noqa

net, width = sys.argv[1], float(sys.argv[2])
upto = None
args = []
for a in sys.argv[3:]:
    if a.startswith("--upto="):
        upto = a.split("=")[1]
    else:
        args.append(a)
px, py = (float(v) for v in args[0].split(","))
rad = float(args[1]) if len(args) > 1 else 1.5

if upto is not None:
    assert os.environ.get("PCB_NO_ROUTES")
    import pcb_routes as prt
    order = []
    for e in rt.ROUTE_PLAN:
        if e[0] not in order:
            order.append(e[0])
    before = set(order[:order.index(upto)])
    pl.TRACKS = pl.TRACKS + [t for t in prt.TRACKS if t[0] in before]
    pl.VIAS = pl.VIAS + [v for v in prt.VIAS if v[0] in before]

pads = rt.load_pads()
alias = rt.net_alias(pads)
segs, vias = rt.authored_copper(pads)
exp = alias.get(net, net)
hw = width / 2

def seg_dist(x, y, x1, y1, x2, y2):
    """Chebyshev distance to the segment for diagonal runs -- route.py's
    stamp_seg stamps squares along the segment, so a 45-degree lane shadows
    sqrt(2)x wider than euclidean. H/V segments stamp exact rects."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 or dy == 0:
        ex = max(min(x1, x2) - x, 0, x - max(x1, x2))
        ey = max(min(y1, y2) - y, 0, y - max(y1, y2))
        return max(ex, ey) if (dx or dy) else max(abs(x - x1), abs(y - y1))
    best = 1e18
    steps = max(1, int(math.hypot(dx, dy) / 0.1))
    for i in range(steps + 1):
        t = i / steps
        best = min(best, max(abs(x - x1 - t * dx), abs(y - y1 - t * dy)))
    return best

def clr_for(onet):
    o = alias.get(onet, onet)
    if o == exp:
        return None
    if exp in {alias.get(n, n) for n in rt.HV_NETS} or o in {alias.get(n, n) for n in rt.HV_NETS}:
        return rt.HV_CLR
    return rt.BASE_CLR

rows = []
for (onet, layer, shw, x1, y1, x2, y2) in segs:
    c = clr_for(onet)
    if c is None:
        continue
    d = seg_dist(px, py, x1, y1, x2, y2) - shw
    if d < rad:
        rows.append((d, f"seg {onet} {layer} w{shw*2:.2f} ({x1},{y1})-({x2},{y2})", c))
for (onet, x, y) in vias:
    c = clr_for(onet)
    if c is None:
        continue
    d = math.hypot(px - x, py - y) - rt.VIA_R
    if d < rad:
        rows.append((d, f"via {onet} ({x},{y})", c))
for p in pads:
    c = clr_for(p["net"])
    if c is None:
        continue
    # bbox distance (approx)
    dx = max(p["x1"] - px, 0, px - p["x2"])
    dy = max(p["y1"] - py, 0, py - p["y2"])
    d = math.hypot(dx, dy)
    if d < rad:
        lyr = ("F" if p["F"] else "") + ("B" if p["B"] else "")
        rows.append((d, f"pad {p['ref']}.{p['num']} {p['net']} {lyr} bbox", c))

rows.sort()
print(f"point ({px},{py}) net={net} w={width}; margin = dist - clearance-needed")
for d, desc, c in rows[:18]:
    trk_need = c + hw
    via_need = c + rt.VIA_R
    t = "TRKX" if d < trk_need else "    "
    v = "VIAX" if d < via_need else "    "
    print(f"  d={d:6.3f} trk_need={trk_need:.3f}{t} via_need={via_need:.3f}{v}  {desc}")
