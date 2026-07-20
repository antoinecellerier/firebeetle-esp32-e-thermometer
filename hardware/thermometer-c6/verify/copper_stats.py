#!/usr/bin/env python3
"""Copper/via census of the board, and A-vs-B diff across revisions.

Counts routed copper only (tracks + vias; zones/pours are excluded -- they are
regenerated fill, not authored routing). Per-net lengths sum both layers.

Usage: python3 verify/copper_stats.py [BOARD] [--vs REF] [--nets N]
  BOARD   board file; default thermometer-c6.kicad_pcb
  --vs    baseline to compare against: a board file OR a git rev (the board
          file is read from that rev, e.g. --vs 9100758)
  --nets  how many per-net movers to list in a diff (default 15)
"""

import collections
import os
import subprocess
import sys
import tempfile

import pcbnew

from geom import DEFAULT_BOARD, PROJECT, rel

BOARD_IN_REPO = "hardware/thermometer-c6/thermometer-c6.kicad_pcb"
REGIONS = [("FPC/east x>36", 36, 0, 48, 35),
           ("USB/north y<9", 0, 0, 48, 9),
           ("west x<20", 0, 0, 20, 35)]


def census(path):
    """Segment/via counts, per-layer and per-net copper length, via positions."""
    b = pcbnew.LoadBoard(path)
    out = dict(segs=0, arcs=0, vias=0, f=0.0, b=0.0,
               nets=collections.Counter(), vpos=[], drills=collections.Counter())
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            out["vias"] += 1
            out["vpos"].append(rel(t.GetPosition()))
            out["drills"][round(t.GetDrill() / 1e6, 2)] += 1
            continue
        out["segs"] += 1
        if t.Type() == pcbnew.PCB_ARC_T:
            out["arcs"] += 1
        length = t.GetLength() / 1e6
        out["nets"][t.GetNetname()] += length
        if t.GetLayer() == pcbnew.F_Cu:
            out["f"] += length
        elif t.GetLayer() == pcbnew.B_Cu:
            out["b"] += length
    return out


def resolve(ref, keep):
    """A board path as given, or the board file extracted from a git rev."""
    if os.path.exists(ref):
        return ref
    blob = subprocess.run(["git", "show", f"{ref}:{BOARD_IN_REPO}"],
                          cwd=PROJECT, capture_output=True, text=True)
    if blob.returncode:
        sys.exit(f"copper_stats: {ref} is neither a file nor a git rev with a board")
    fd, path = tempfile.mkstemp(suffix=".kicad_pcb", dir=keep)
    with os.fdopen(fd, "w") as fh:
        fh.write(blob.stdout)
    return path


def report(c, label):
    print(f"=== {label} ===")
    print(f"  segments {c['segs']} (arcs {c['arcs']})   vias {c['vias']} "
          f"drills {dict(c['drills'])}")
    print(f"  copper  F {c['f']:.1f}mm  B {c['b']:.1f}mm  total {c['f'] + c['b']:.1f}mm")


def diff(pre, cur, nets):
    print("\n=== delta (current vs baseline) ===")
    rows = [("segments", pre["segs"], cur["segs"]), ("vias", pre["vias"], cur["vias"]),
            ("F.Cu mm", pre["f"], cur["f"]), ("B.Cu mm", pre["b"], cur["b"]),
            ("total mm", pre["f"] + pre["b"], cur["f"] + cur["b"])]
    for name, a, b in rows:
        pct = 100 * (b - a) / a if a else 0
        print(f"  {name:9} {a:8.1f} -> {b:8.1f}   {b - a:+8.1f} ({pct:+.1f}%)")

    allnets = set(pre["nets"]) | set(cur["nets"])
    shorter = sum(1 for n in allnets if cur["nets"][n] < pre["nets"][n] - 0.5)
    longer = sum(1 for n in allnets if cur["nets"][n] > pre["nets"][n] + 0.5)
    print(f"\n  nets shorter {shorter}   longer {longer}   "
          f"~unchanged {len(allnets) - shorter - longer}   (of {len(allnets)})")

    print(f"\n=== biggest per-net movers (mm, top {nets}) ===")
    movers = sorted(allnets, key=lambda n: -abs(cur["nets"][n] - pre["nets"][n]))
    for n in movers[:nets]:
        a, b = pre["nets"][n], cur["nets"][n]
        if abs(b - a) < 0.05:
            break
        print(f"  {b - a:+7.1f}   {n:32} {a:7.1f} -> {b:7.1f}")

    print("\n=== vias by region ===")
    for name, x1, y1, x2, y2 in REGIONS:
        inside = lambda vs: sum(1 for (x, y) in vs if x1 <= x <= x2 and y1 <= y <= y2)
        a, b = inside(pre["vpos"]), inside(cur["vpos"])
        print(f"  {name:15} {a:4} -> {b:4}   ({b - a:+d})")
    print(f"  {'TOTAL':15} {pre['vias']:4} -> {cur['vias']:4} "
          f"  ({cur['vias'] - pre['vias']:+d})")


def main(argv):
    board, baseline, nets = DEFAULT_BOARD, None, 15
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--vs":
            i += 1
            baseline = argv[i]
        elif argv[i] == "--nets":
            i += 1
            nets = int(argv[i])
        else:
            rest.append(argv[i])
        i += 1
    if rest:
        board = rest[0]

    cur = census(board)
    if not baseline:
        report(cur, os.path.basename(board))
        return
    with tempfile.TemporaryDirectory() as keep:
        pre = census(resolve(baseline, keep))
    report(pre, f"baseline {baseline}")
    report(cur, f"current {os.path.basename(board)}")
    diff(pre, cur, nets)


if __name__ == "__main__":
    main(sys.argv[1:])
