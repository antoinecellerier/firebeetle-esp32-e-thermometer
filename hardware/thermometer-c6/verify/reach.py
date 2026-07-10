#!/usr/bin/env python3
"""Flood-fill reachability using route.py's own bitmaps and move rules.

Usage: reach.py NET WIDTH OUT.png [x1 y1 x2 y2] [--seed=N]

Seeds BFS from island N (default 0, = the A* tree seed) of NET's authored+
routed copper, using exactly astar()'s move rules (8-dir, corner-cut ban,
via hops needing via-free on BOTH layers and trk-free on the other layer).
Prints, for every other island, whether it is reachable and if not the
closest approach of the flood to that island (the chokepoint).

Colors: dark = board; green tint = reachable F only; blue tint = reachable
B only; white = reachable both; yellow = seed island; magenta = unreached
island copper; cyan = reached island copper.
"""
import os, sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "generator"))
_CWD = os.getcwd()
os.chdir(PROJECT)

import pcb_layout as pl  # noqa
import route as rt       # noqa
from PIL import Image    # noqa

def main():
    net, width, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    if not os.path.isabs(out):
        out = os.path.join(_CWD, out)
    rest = [a for a in sys.argv[4:] if not a.startswith("--")]
    seed_idx = 0
    upto = None
    for a in sys.argv[4:]:
        if a.startswith("--seed="):
            seed_idx = int(a.split("=")[1])
        if a.startswith("--upto="):
            upto = a.split("=")[1]
    if upto is not None:
        # mid-pass board state: authored copper + nets routed BEFORE `upto`.
        # Requires PCB_NO_ROUTES=1 so pl.TRACKS is authored-only here.
        assert os.environ.get("PCB_NO_ROUTES"), "--upto needs PCB_NO_ROUTES=1"
        import pcb_routes as prt
        order = []
        for e in rt.ROUTE_PLAN:
            if e[0] not in order:
                order.append(e[0])
        cut = order.index(upto)
        before = set(order[:cut])
        pl.TRACKS = pl.TRACKS + [t for t in prt.TRACKS if t[0] in before]
        pl.VIAS = pl.VIAS + [v for v in prt.VIAS if v[0] in before]
        print(f"mid-pass state: authored + {len(before)} nets routed "
              f"before {upto}")
    bw, bh = pl.BOARD["size"]
    crop = tuple(float(v) for v in rest[:4]) if len(rest) >= 4 else (0, 0, bw, bh)

    pads = rt.load_pads()
    alias = rt.net_alias(pads)
    segs, vias = rt.authored_copper(pads)
    exp = alias.get(net, net)
    maps = rt.build_bitmaps(pads, segs, vias, exp, width, alias)
    islands = rt._copper_islands(segs, vias, pads, exp, alias)
    print(f"{len(islands)} islands:")
    for i, isl in enumerate(islands):
        first = sorted(isl)[0]
        print(f"  [{i}] @{first[1]*rt.GRID:.2f},{first[2]*rt.GRID:.2f} "
              f"({len(isl)} cells)")

    W, H = rt.W, rt.H
    seen = [bytearray(W * H), bytearray(W * H)]
    q = deque()
    for (l, ix, iy) in islands[seed_idx]:
        if not seen[l][iy * W + ix]:
            seen[l][iy * W + ix] = 1
            q.append((l, ix, iy))
    # also flood outward from island cells even if the cell itself is
    # "blocked" (own copper is waived, so it shouldn't be, but be safe)
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

    reached_cells = sum(seen[0]) + sum(seen[1])
    print(f"flooded {reached_cells} cells from island[{seed_idx}]")
    for i, isl in enumerate(islands):
        if i == seed_idx:
            continue
        hit = any(seen[l][iy * W + ix] for (l, ix, iy) in isl)
        if hit:
            print(f"  island[{i}]: REACHED")
        else:
            best = None
            for (l, ix, iy) in isl:
                for jl in (0, 1):
                    pass
            # closest approach: scan all reached cells vs island cells (coarse)
            isl_pts = [(ix, iy) for (_, ix, iy) in isl]
            bestd, bestp = 1e18, None
            step = 4
            for iy in range(0, H, 1):
                row0 = seen[0][iy * W:(iy + 1) * W]
                row1 = seen[1][iy * W:(iy + 1) * W]
                for ix in range(0, W, 1):
                    if not (row0[ix] or row1[ix]):
                        continue
                    for (jx, jy) in isl_pts[::step]:
                        d = (ix - jx) ** 2 + (iy - jy) ** 2
                        if d < bestd:
                            bestd, bestp = d, (ix, iy, jx, jy)
            if bestp:
                ix, iy, jx, jy = bestp
                print(f"  island[{i}]: UNREACHED, closest approach "
                      f"{(bestd ** 0.5) * rt.GRID:.2f}mm: flood@"
                      f"({ix*rt.GRID:.2f},{iy*rt.GRID:.2f}) vs island@"
                      f"({jx*rt.GRID:.2f},{jy*rt.GRID:.2f})")
            else:
                print(f"  island[{i}]: UNREACHED (flood empty?)")

    cx1, cy1 = rt.cell(crop[0], crop[1])
    cx2, cy2 = rt.cell(crop[2], crop[3])
    SCALE = 4
    img = Image.new("RGB", ((cx2 - cx1) * SCALE, (cy2 - cy1) * SCALE))
    px = img.load()
    isl_map = {}
    for i, isl in enumerate(islands):
        for (l, ix, iy) in isl:
            isl_map[(ix, iy)] = i
    for iy in range(cy1, cy2):
        for ix in range(cx1, cx2):
            f = seen[0][iy * W + ix]
            b = seen[1][iy * W + ix]
            if (ix, iy) in isl_map:
                i = isl_map[(ix, iy)]
                c = ((255, 220, 0) if i == seed_idx
                     else (0, 220, 220) if (f or b) else (255, 0, 255))
            elif f and b:
                c = (255, 255, 255)
            elif f:
                c = (90, 200, 90)
            elif b:
                c = (90, 120, 255)
            else:
                fb = rt.blocked(maps, "trk", "F.Cu", ix, iy)
                bb = rt.blocked(maps, "trk", "B.Cu", ix, iy)
                c = ((25, 25, 25) if fb and bb else (90, 40, 40) if fb
                     else (40, 40, 90))
            for sy in range(SCALE):
                for sx in range(SCALE):
                    px[(ix - cx1) * SCALE + sx, (iy - cy1) * SCALE + sy] = c
    # 1mm grid
    for gx in range(int(crop[0]) + 1, int(crop[2]) + 1):
        X = int((gx / rt.GRID - cx1) * SCALE)
        if 0 <= X < img.width:
            for Y in range(img.height):
                r, g, b2 = px[X, Y]
                px[X, Y] = (r, min(255, g + 60 if gx % 5 == 0 else g + 30), b2)
    for gy in range(int(crop[1]) + 1, int(crop[3]) + 1):
        Y = int((gy / rt.GRID - cy1) * SCALE)
        if 0 <= Y < img.height:
            for X in range(img.width):
                r, g, b2 = px[X, Y]
                px[X, Y] = (r, min(255, g + 60 if gy % 5 == 0 else g + 30), b2)
    img.save(out)
    print(f"wrote {out} crop={crop}")

main()
