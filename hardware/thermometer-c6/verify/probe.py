#!/usr/bin/env python3
"""Probe flood membership + blockage at points.

Usage: PCB_NO_ROUTES=1 probe.py NET WIDTH --upto=NET SEED x,y ...
Prints, for each point: trk/via blockage per layer and whether the flood
from island SEED reaches it on each layer.
"""
import os, sys
from collections import deque

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
seed = args[0]  # island index, or "x,y,L" point seed
pts = [tuple(float(v) for v in a.split(",")) for a in args[1:]]

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
maps = rt.build_bitmaps(pads, segs, vias, exp, width, alias)
islands = rt._copper_islands(segs, vias, pads, exp, alias)
W, H = rt.W, rt.H

seen = [bytearray(W * H), bytearray(W * H)]
q = deque()
if "," in seed:
    sx, sy, sl = seed.split(",")
    l = 0 if sl.upper() == "F" else 1
    ix, iy = rt.cell(float(sx), float(sy))
    seen[l][iy * W + ix] = 1
    q.append((l, ix, iy))
else:
    for (l, ix, iy) in islands[int(seed)]:
        seen[l][iy * W + ix] = 1
        q.append((l, ix, iy))
while q:
    l, ix, iy = q.popleft()
    lname = "F.Cu" if l == 0 else "B.Cu"
    for dx, dy in rt.DIRS:
        nx, ny = ix + dx, iy + dy
        if not (0 <= nx < W and 0 <= ny < H) or seen[l][ny * W + nx]:
            continue
        if rt.blocked(maps, "trk", lname, nx, ny):
            continue
        if dx and dy and (rt.blocked(maps, "trk", lname, ix + dx, iy)
                          or rt.blocked(maps, "trk", lname, ix, iy + dy)):
            continue
        seen[l][ny * W + nx] = 1
        q.append((l, nx, ny))
    ol = 1 - l
    olname = "F.Cu" if ol == 0 else "B.Cu"
    if (not seen[ol][iy * W + ix]
            and not rt.blocked(maps, "via", "F.Cu", ix, iy)
            and not rt.blocked(maps, "via", "B.Cu", ix, iy)
            and not rt.blocked(maps, "trk", olname, ix, iy)):
        seen[ol][iy * W + ix] = 1
        q.append((ol, ix, iy))

for (x, y) in pts:
    ix, iy = rt.cell(x, y)
    tf = rt.blocked(maps, "trk", "F.Cu", ix, iy)
    tb = rt.blocked(maps, "trk", "B.Cu", ix, iy)
    vf = rt.blocked(maps, "via", "F.Cu", ix, iy)
    vb = rt.blocked(maps, "via", "B.Cu", ix, iy)
    ff = seen[0][iy * W + ix]
    fb = seen[1][iy * W + ix]
    print(f"({x},{y}): trkF={'X' if tf else '.'} trkB={'X' if tb else '.'} "
          f"viaF={'X' if vf else '.'} viaB={'X' if vb else '.'} "
          f"floodF={'Y' if ff else 'n'} floodB={'Y' if fb else 'n'}")
