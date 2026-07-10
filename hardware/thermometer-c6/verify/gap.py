#!/usr/bin/env python3
"""Find the narrowest gap between two flood regions of a net's islands.

Usage: PCB_NO_ROUTES=1 gap.py NET WIDTH --upto=NET seedA seedB
Floods from island seedA and island seedB, then prints the closest pairs of
(floodA, floodB) cells and their layers -- candidate authored-bridge spots.
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
sa, sb = int(args[0]), int(args[1])

if upto is not None:
    assert os.environ.get("PCB_NO_ROUTES")
    import pcb_routes as prt
    order = []
    for e in rt.ROUTE_PLAN:
        if e[0] not in order:
            order.append(e[0])
    cut = order.index(upto)
    before = set(order[:cut])
    pl.TRACKS = pl.TRACKS + [t for t in prt.TRACKS if t[0] in before]
    pl.VIAS = pl.VIAS + [v for v in prt.VIAS if v[0] in before]

pads = rt.load_pads()
alias = rt.net_alias(pads)
segs, vias = rt.authored_copper(pads)
exp = alias.get(net, net)
maps = rt.build_bitmaps(pads, segs, vias, exp, width, alias)
islands = rt._copper_islands(segs, vias, pads, exp, alias)
W, H = rt.W, rt.H

def flood(seed_idx):
    seen = [bytearray(W * H), bytearray(W * H)]
    q = deque()
    for (l, ix, iy) in islands[seed_idx]:
        if not seen[l][iy * W + ix]:
            seen[l][iy * W + ix] = 1
            q.append((l, ix, iy))
    while q:
        l, ix, iy = q.popleft()
        lname = "F.Cu" if l == 0 else "B.Cu"
        for dx, dy in rt.DIRS:
            nx, ny = ix + dx, iy + dy
            if not (0 <= nx < W and 0 <= ny < H):
                continue
            if seen[l][ny * W + nx]:
                continue
            if rt.blocked(maps, "trk", lname, nx, ny):
                continue
            if dx and dy:
                if (rt.blocked(maps, "trk", lname, ix + dx, iy)
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
    return seen

fa, fb = flood(sa), flood(sb)
print(f"floodA[{sa}]: {sum(fa[0])+sum(fa[1])} cells, "
      f"floodB[{sb}]: {sum(fb[0])+sum(fb[1])} cells")

# collect boundary cells of each flood (cheaper pairing)
A = [(l, ix, iy) for l in (0, 1) for iy in range(H) for ix in range(W)
     if fa[l][iy * W + ix]]
B = [(l, ix, iy) for l in (0, 1) for iy in range(H) for ix in range(W)
     if fb[l][iy * W + ix]]
# grid-bucket B for speed
from collections import defaultdict
bucket = defaultdict(list)
BS = 40  # 2mm buckets
for (l, ix, iy) in B:
    bucket[(ix // BS, iy // BS)].append((l, ix, iy))

best = []
for (l, ix, iy) in A:
    bx, by = ix // BS, iy // BS
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for (ml, mx, my) in bucket.get((bx + dx, by + dy), ()):
                d2 = (ix - mx) ** 2 + (iy - my) ** 2
                best.append((d2, ix, iy, l, mx, my, ml))
best.sort()
seenpts = set()
shown = 0
for d2, ix, iy, l, mx, my, ml in best:
    key = (ix // 10, iy // 10)
    if key in seenpts:
        continue
    seenpts.add(key)
    print(f"  gap {d2 ** 0.5 * rt.GRID:.2f}mm: A({ix*rt.GRID:.2f},"
          f"{iy*rt.GRID:.2f},{'FB'[l]}) <-> B({mx*rt.GRID:.2f},"
          f"{my*rt.GRID:.2f},{'FB'[ml]})")
    shown += 1
    if shown >= 12:
        break
if not best:
    print("  floods farther than one bucket apart everywhere")
