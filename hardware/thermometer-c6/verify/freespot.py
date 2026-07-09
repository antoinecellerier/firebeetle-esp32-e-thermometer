#!/usr/bin/env python3
"""Courtyard-aware free-rectangle finder: where can a part legally go?

Answers the question every starved routing cluster eventually poses -- "is
there anywhere else to put this?" -- before you spend an hour hand-authoring
around a placement bug. Courtyards may touch but not overlap; the board edge
keeps a 0.3mm margin; keep-out rule areas block.

A 0603 courtyard is 1.03 x 1.95 upright, 1.95 x 1.03 lying down. Get the exact
figure for a part from `verify/pads.py REF`.

Usage: python3 verify/freespot.py W H [--ignore=REF,REF] [--near=x,y]
                                      [--box=x1,y1,x2,y2]

Prints maximal rectangles of legal CENTRES for a W x H courtyard, largest
first, or nearest-first when --near is given. --ignore drops the parts you
intend to move (always include the part itself).
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]
BW, BH = pl.BOARD["size"]
EDGE = 0.3
STEP = 0.1


def obstacles(ignore):
    board = pcbnew.LoadBoard(os.path.join(PROJECT, "thermometer-c6.kicad_pcb"))
    out = []
    for fp in board.GetFootprints():
        if fp.GetReference() in ignore:
            continue
        bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        if bb.GetWidth() <= 0:
            continue
        out.append((bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY,
                    bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY))
    for k in pl.KEEPOUTS:
        if k.get("fills", True) or k.get("tracks", True):
            out.append(k["rect"])
    return out


def maximal_rects(grid, nx, ny, box):
    """Greedy peel: largest-area all-free rectangle, blank it, repeat."""
    rects = []
    for _ in range(40):
        best = None
        hist = [0] * nx
        for iy in range(ny):
            for ix in range(nx):
                hist[ix] = hist[ix] + 1 if grid[iy][ix] else 0
            stack = []
            for ix in range(nx + 1):
                cur = hist[ix] if ix < nx else 0
                start = ix
                while stack and stack[-1][1] >= cur:
                    s, h = stack.pop()
                    area = h * (ix - s)
                    if best is None or area > best[0]:
                        best = (area, s, iy - h + 1, ix - 1, iy)
                    start = s
                stack.append((start, cur))
        if not best or best[0] < 4:
            break
        _, ix1, iy1, ix2, iy2 = best
        rects.append((box[0] + ix1 * STEP, box[1] + iy1 * STEP,
                      box[0] + ix2 * STEP, box[1] + iy2 * STEP))
        for iy in range(iy1, iy2 + 1):
            for ix in range(ix1, ix2 + 1):
                grid[iy][ix] = False
    return rects


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: freespot.py W H [--ignore=..] [--near=x,y] "
                         "[--box=x1,y1,x2,y2]")
    w, h = float(sys.argv[1]), float(sys.argv[2])
    ignore, near, box = set(), None, (0.0, 0.0, BW, BH)
    for a in sys.argv[3:]:
        key, _, val = a.partition("=")
        if key == "--ignore":
            ignore = set(val.split(","))
        elif key == "--near":
            near = tuple(float(v) for v in val.split(","))
        elif key == "--box":
            box = tuple(float(v) for v in val.split(","))

    obst = obstacles(ignore)
    nx = int((box[2] - box[0]) / STEP) + 1
    ny = int((box[3] - box[1]) / STEP) + 1
    grid = [[False] * nx for _ in range(ny)]
    for iy in range(ny):
        cy = box[1] + iy * STEP
        for ix in range(nx):
            cx = box[0] + ix * STEP
            x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            if x1 < EDGE or y1 < EDGE or x2 > BW - EDGE or y2 > BH - EDGE:
                continue
            if any(not (x2 <= ox1 or x1 >= ox2 or y2 <= oy1 or y1 >= oy2)
                   for ox1, oy1, ox2, oy2 in obst):
                continue
            grid[iy][ix] = True

    rects = maximal_rects(grid, nx, ny, box)

    def dist(r):
        dx = max(r[0] - near[0], 0, near[0] - r[2])
        dy = max(r[1] - near[1], 0, near[1] - r[3])
        return (dx * dx + dy * dy) ** 0.5

    if near:
        rects.sort(key=dist)

    print(f"freespot: legal centres for a {w} x {h} courtyard"
          f"{', ignoring ' + ','.join(sorted(ignore)) if ignore else ''}")
    if not rects:
        print("  none")
    for r in rects[:15]:
        d = f"   {dist(r):6.2f}mm away" if near else ""
        print(f"  ({r[0]:6.2f},{r[1]:6.2f})-({r[2]:6.2f},{r[3]:6.2f})"
              f"  {r[2] - r[0]:5.2f} x {r[3] - r[1]:5.2f}{d}")


if __name__ == "__main__":
    main()
