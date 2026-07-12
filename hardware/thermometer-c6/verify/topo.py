#!/usr/bin/env python3
"""Per-net copper topology metrics for the generated board (reads pcbnew).

Single board:  topo.py BOARD.kicad_pcb [--json OUT]
  Per net (GND and unconnected-* skipped): total track length, via count,
  F/B per-layer length, a coarse occupancy cell set (2mm grid x layer) and
  region-occupancy lengths for the named corridors below. A pour-damage score
  = B.Cu length + 3*via_count, with copper inside the antenna-strip counted
  twice, ranks nets by how much they cost the GND pour and crowd the antenna.

Diff:  topo.py A.kicad_pcb B.kicad_pcb [--json OUT]
  Per net: Jaccard similarity of the two occupancy cell sets (verdict
  same-topology > 0.6, else differs), with both boards' metrics side by side.

Board-relative coords = absolute mm minus (100,100). All lengths in mm.
"""
import json
import math
import sys

import pcbnew

ORIGIN = (100.0, 100.0)
GRID = 2.0  # mm occupancy cell edge
BIG = 1e9
SIM_SAME = 0.6

# board-relative rectangles (x1,y1,x2,y2); open sides use +-BIG
REGIONS = {
    "antenna-strip": (-BIG, 6, 8, 22),
    "west-funnel":   (8, 21, 20, 34),
    "ne-gate":       (13, 6, 20, 11),
    "center-band":   (20, 9, 34, 17),
    "fanout":        (39, 7, 49, 26),
    "east-strip":    (48, -BIG, BIG, BIG),
    "south-strip":   (-BIG, 35, BIG, BIG),
}


def skip(n):
    return (not n) or n == "GND" or n.startswith("unconnected-")


def inrect(x, y, r):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def rel(p):
    return (p.x / 1e6 - ORIGIN[0], p.y / 1e6 - ORIGIN[1])


def cell(x, y, layer):
    return (int(math.floor(x / GRID)), int(math.floor(y / GRID)), layer)


def metrics(path):
    """{net: dict of metrics} for one board."""
    board = pcbnew.LoadBoard(path)
    nets = {}

    def get(name):
        return nets.setdefault(name, dict(
            track_len=0.0, vias=0, len_F=0.0, len_B=0.0, cells=set(),
            regions={k: 0.0 for k in REGIONS}, bcu_antenna=0.0, via_antenna=0))

    for t in board.GetTracks():
        name = t.GetNetname()
        if skip(name):
            continue
        m = get(name)
        if t.GetClass() == "PCB_VIA":
            m["vias"] += 1
            x, y = rel(t.GetPosition())
            m["cells"].add(cell(x, y, "F"))
            m["cells"].add(cell(x, y, "B"))
            if inrect(x, y, REGIONS["antenna-strip"]):
                m["via_antenna"] += 1
            continue
        lyr = "B" if t.GetLayer() == pcbnew.B_Cu else "F"
        (x1, y1), (x2, y2) = rel(t.GetStart()), rel(t.GetEnd())
        seglen = math.hypot(x2 - x1, y2 - y1)
        m["track_len"] += seglen
        m["len_B" if lyr == "B" else "len_F"] += seglen
        steps = max(1, int(seglen / 0.1))
        sub = seglen / steps
        for i in range(steps):
            t0, t1 = i / steps, (i + 1) / steps
            mx = x1 + (x2 - x1) * (t0 + t1) / 2
            my = y1 + (y2 - y1) * (t0 + t1) / 2
            m["cells"].add(cell(mx, my, lyr))
            for k, r in REGIONS.items():
                if inrect(mx, my, r):
                    m["regions"][k] += sub
                    if k == "antenna-strip" and lyr == "B":
                        m["bcu_antenna"] += sub

    for m in nets.values():
        m["pour_damage"] = (m["len_B"] + 3 * m["vias"]
                            + m["bcu_antenna"] + 3 * m["via_antenna"])
    return nets


def jaccard(a, b):
    if not a and not b:
        return 1.0
    u = len(a | b)
    return len(a & b) / u if u else 1.0


def jsonable(m):
    d = {k: v for k, v in m.items() if k != "cells"}
    d["cells"] = sorted([list(c[:2]) + [c[2]] for c in m["cells"]])
    return d


def print_single(nets):
    order = sorted(nets, key=lambda n: -nets[n]["pour_damage"])
    print(f"{'net':24}{'pour':>7}{'trk':>7}{'B.Cu':>7}{'via':>4}"
          f"{'antL':>6}{'antV':>5}  regions(len)")
    for i, n in enumerate(order):
        m = nets[n]
        regs = " ".join(f"{k.split('-')[0]}={v:.1f}"
                        for k, v in m["regions"].items() if v > 0.05)
        mark = " *" if i < 5 else ""
        print(f"{n[:24]:24}{m['pour_damage']:7.1f}{m['track_len']:7.1f}"
              f"{m['len_B']:7.1f}{m['vias']:4d}"
              f"{m['regions']['antenna-strip']:6.1f}{m['via_antenna']:5d}"
              f"  {regs}{mark}")
    print("  (* = top-5 simplification worklist)")


def print_diff(na, nb):
    allnets = sorted(set(na) | set(nb),
                     key=lambda n: -na.get(n, nb.get(n))["pour_damage"])
    print(f"{'net':24}{'sim':>6} {'verdict':13}"
          f"{'poA':>6}{'poB':>6}{'viA':>4}{'viB':>4}"
          f"{'BA':>6}{'BB':>6}{'antA':>6}{'antB':>6}")
    empty = dict(pour_damage=0, vias=0, len_B=0.0, cells=set(),
                 regions={"antenna-strip": 0.0})
    for n in allnets:
        a, b = na.get(n, empty), nb.get(n, empty)
        s = jaccard(a["cells"], b["cells"])
        verdict = "same-topology" if s > SIM_SAME else "DIFFERS"
        print(f"{n[:24]:24}{s:6.2f} {verdict:13}"
              f"{a['pour_damage']:6.1f}{b['pour_damage']:6.1f}"
              f"{a['vias']:4d}{b['vias']:4d}"
              f"{a['len_B']:6.1f}{b['len_B']:6.1f}"
              f"{a['regions']['antenna-strip']:6.1f}"
              f"{b['regions']['antenna-strip']:6.1f}")


def main():
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1]
        del args[i:i + 2]
    if not 1 <= len(args) <= 2:
        raise SystemExit(__doc__.strip())

    if len(args) == 1:
        nets = metrics(args[0])
        print_single(nets)
        if out:
            with open(out, "w") as f:
                json.dump({n: jsonable(m) for n, m in nets.items()}, f, indent=1)
    else:
        na, nb = metrics(args[0]), metrics(args[1])
        print_diff(na, nb)
        if out:
            data = {}
            for n in set(na) | set(nb):
                a, b = na.get(n), nb.get(n)
                data[n] = dict(
                    sim=jaccard(a["cells"] if a else set(),
                                b["cells"] if b else set()),
                    A=jsonable(a) if a else None,
                    B=jsonable(b) if b else None)
            with open(out, "w") as f:
                json.dump(data, f, indent=1)


if __name__ == "__main__":
    main()
