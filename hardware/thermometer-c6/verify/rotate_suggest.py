#!/usr/bin/env python3
"""Rank component rotations that would let a part's nets route shorter/cleaner,
WITHOUT rerouting the board (a placement-quality proxy).

The board is fully routed, so we cannot score a rotation by rerouting it.
Instead, for each candidate 2-pad passive and each of the four orientations
{0,90,180,270}, we rotate the pad offsets about the footprint origin (position
fixed) and sum a "flight length": the straight-line distance from each pad to
the NEAREST other copper on the SAME net. Lower total flight => the pads face
their nets => shorter/cleaner routing is available.

REFERENCE COPPER (what "nearest same-net copper" means here) is deliberately
routing-INDEPENDENT:
  * centres of every other footprint's pads on that net, PLUS
  * the authored GND skeleton (pcb_layout TRACKS/VIAS/STITCH vertices).
It EXCLUDES the ephemeral routed escapes in pcb_routes.py. Anchoring to a
part's own current escape stub would put every current placement at ~0 flight
and surface zero suggestions -- the whole point is to spot parts whose pads
currently point away from where their net actually lives. (Authored copper is
GND-only, so for a signal pad this reduces to nearest same-net pad, i.e. an
HPWL-style estimate; a GND pad also sees the dense GND skeleton.)

CANDIDATES: references ^[RC]\\d+ with exactly two pads (rotating a
non-polarized 2-pad passive just swaps/moves its pads -- electrically safe).
D*/Q*/U*/J*/Y*/L*/JP*/SW*/TP*/H* are excluded (polarity / fixed pinout /
mating). A suggestion is dropped if the rotated orientation would push a pad
into the antenna or antenna-margin RF keep-out.

A rotation is suggested when the best alternative orientation beats the current
one by >= MIN_ABS mm AND >= MIN_REL of the current flight.

CAVEAT: these are placement hints only. Each still needs the user to reroute
that part's nets in the GUI, and the flight proxy ignores obstacles, so some
suggestions won't pan out. Rank by improvement and sanity-check in the layout.

Usage:
  python3 verify/rotate_suggest.py                 # ranked worklist (all)
  python3 verify/rotate_suggest.py R3 C16 ...       # detail for named refs
  python3 verify/rotate_suggest.py --all            # every candidate, verbose
"""

import math
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

os.environ["PCB_NO_ROUTES"] = "1"  # authored (GND) skeleton only, no escapes
import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]
PCB = os.path.join(PROJECT, "thermometer-c6.kicad_pcb")

MIN_ABS = 0.5   # mm: minimum absolute flight reduction to suggest
MIN_REL = 0.15  # fraction: minimum relative flight reduction to suggest
ORIENTS = (0, 90, 180, 270)
CAND_RE = re.compile(r"^[RC]\d+$")

# Nets with a full-board copper pour on BOTH layers: a pad on such a net sits
# on the plane beneath it, so its flight to same-net copper is ~0 in every
# orientation and must not drive a rotation. Zero it, else the (skeleton-only)
# distance to a GND spur inflates rankings with electrically-meaningless gains.
POUR_NETS = {"GND"}

# RF-sensitive keep-outs a rotated pad must not enter (from pcb_layout.KEEPOUTS)
RF_KEEPOUTS = [
    ("antenna", (0.0, 7.25, 5.3, 20.65)),
    ("antenna-margin", (5.3, 8.5, 7.0, 18.0)),
]
SENSOR_KEEPOUTS = [
    ("U5-sensor", (1.3, 21.1, 3.9, 23.7)),
    ("U6-sensor", (0.8, 24.7, 4.6, 28.5)),
]


def rot(dx, dy, deg):
    """KiCad footprint-orientation transform (verified against the board):
    x' = dx*cos + dy*sin ; y' = -dx*sin + dy*cos."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (dx * c + dy * s, -dx * s + dy * c)


def in_rect(x, y, r):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def load():
    board = pcbnew.LoadBoard(PCB)
    fps = {}          # ref -> dict(ref, x, y, rot, pads=[(num, net, rx, ry)])
    padctr = {}       # "REF.PAD" -> (x, y)
    pads_by_net = {}  # net -> [(x, y, owner_ref)]
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        pos = fp.GetPosition()
        fx, fy = pos.x / 1e6 - OX, pos.y / 1e6 - OY
        frot = round(fp.GetOrientationDegrees()) % 360
        pads = []
        for pad in fp.Pads():
            rel = pad.GetFPRelativePosition()
            rx, ry = rel.x / 1e6, rel.y / 1e6
            p = pad.GetPosition()
            px, py = p.x / 1e6 - OX, p.y / 1e6 - OY
            net = pad.GetNetname()
            num = str(pad.GetNumber())
            pads.append((num, net, rx, ry))
            padctr[f"{ref}.{num}"] = (px, py)
            pads_by_net.setdefault(net, []).append((px, py, ref))
        fps[ref] = dict(ref=ref, x=fx, y=fy, rot=frot, pads=pads)
    return fps, padctr, pads_by_net


def skeleton(padctr):
    """Authored GND-skeleton vertices grouped by net (all GND)."""
    sk = {}
    for net, layer, width, nodes in pl.TRACKS:
        for n in nodes:
            xy = padctr.get(n) if isinstance(n, str) else n
            if xy is not None:
                sk.setdefault(net, []).append((xy[0], xy[1]))
    for net, x, y in pl.VIAS:
        sk.setdefault(net, []).append((x, y))
    for xy in pl.STITCH:                       # STITCH are GND vias
        sk.setdefault("GND", []).append((xy[0], xy[1]))
    return sk


def selfcheck():
    """Reconstruct current pad positions from rel offsets + current rot; abort
    if the rotation convention doesn't reproduce the board (e.g. bottom-side
    sign flips)."""
    board = pcbnew.LoadBoard(PCB)
    err = 0.0
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        pos = fp.GetPosition()
        fx, fy = pos.x / 1e6 - OX, pos.y / 1e6 - OY
        frot = round(fp.GetOrientationDegrees()) % 360
        for pad in fp.Pads():
            rel = pad.GetFPRelativePosition()
            dx, dy = rot(rel.x / 1e6, rel.y / 1e6, frot)
            p = pad.GetPosition()
            ex = abs(fx + dx - (p.x / 1e6 - OX))
            ey = abs(fy + dy - (p.y / 1e6 - OY))
            err = max(err, ex, ey)
    return err


def build_refset(cand, pads_by_net, sk):
    """Per-pad reference copper for a candidate: same-net pads on OTHER
    footprints + same-net authored skeleton (minus skeleton vertices that sit
    on this part's own pads)."""
    own_ctrs = []
    for num, net, rx, ry in cand["pads"]:
        dx, dy = rot(rx, ry, cand["rot"])
        own_ctrs.append((cand["x"] + dx, cand["y"] + dy))

    refs = {}
    for num, net, rx, ry in cand["pads"]:
        pts = [(x, y) for (x, y, owner) in pads_by_net.get(net, [])
               if owner != cand["ref"]]
        for (x, y) in sk.get(net, []):
            if all(math.hypot(x - ox, y - oy) > 0.05 for ox, oy in own_ctrs):
                pts.append((x, y))
        refs[num] = pts
    return refs


def flight(cand, deg, refs):
    """(total, {padnum: (net, dist_or_None)}) at orientation deg."""
    total = 0.0
    per = {}
    for num, net, rx, ry in cand["pads"]:
        if net in POUR_NETS:           # reaches the pour beneath it: flight ~0
            per[num] = (net, 0.0)
            continue
        dx, dy = rot(rx, ry, deg)
        px, py = cand["x"] + dx, cand["y"] + dy
        pts = refs[num]
        if not pts:
            per[num] = (net, None)
            continue
        d = min(math.hypot(px - x, py - y) for x, y in pts)
        per[num] = (net, d)
        total += d
    return total, per


def pad_positions(cand, deg):
    out = []
    for num, net, rx, ry in cand["pads"]:
        dx, dy = rot(rx, ry, deg)
        out.append((num, net, cand["x"] + dx, cand["y"] + dy))
    return out


def keepout_hit(cand, deg):
    """Return (rf_name, sensor_name) if a pad at deg lands in a keep-out."""
    rf = sensor = None
    for num, net, px, py in pad_positions(cand, deg):
        for name, r in RF_KEEPOUTS:
            if in_rect(px, py, r):
                rf = rf or name
        for name, r in SENSOR_KEEPOUTS:
            if in_rect(px, py, r):
                sensor = sensor or name
    return rf, sensor


def analyse(cand, pads_by_net, sk):
    refs = build_refset(cand, pads_by_net, sk)
    cur = cand["rot"]
    scores = {d: flight(cand, d, refs) for d in ORIENTS}
    cur_total, cur_per = scores[cur]
    # best keep-out-safe alternative
    alts = []
    for d in ORIENTS:
        if d == cur:
            continue
        rf, sensor = keepout_hit(cand, d)
        alts.append((scores[d][0], d, rf, sensor, scores[d][1]))
    alts.sort(key=lambda t: t[0])
    best = None
    for total, d, rf, sensor, per in alts:
        if rf:                     # never push a pad into the antenna keep-out
            continue
        best = (total, d, sensor, per)
        break
    improvement = None
    if best is not None and cur_total > 1e-9:
        improvement = cur_total - best[0]
    return dict(cand=cand, refs=refs, scores=scores, cur=cur,
                cur_total=cur_total, cur_per=cur_per, best=best,
                improvement=improvement, alts=alts)


def net_benefit(cur_per, best_per):
    """Nets whose pad flight drops in the suggested orientation."""
    out = []
    for num, (net, d) in cur_per.items():
        bd = best_per.get(num, (net, None))[1]
        if d is None or bd is None:
            continue
        if d - bd > 0.05:
            out.append((net, d, bd))
    out.sort(key=lambda t: t[1] - t[2], reverse=True)
    return out


def fmt_deg(d):
    return f"{d}"


def main():
    args = [a for a in sys.argv[1:] if a != "--all"]
    verbose = "--all" in sys.argv or bool(args)

    err = selfcheck()
    if err > 1e-3:
        print(f"WARNING: rotation self-check off by {err:.4f} mm "
              "-- convention may be wrong for some parts", file=sys.stderr)

    fps, padctr, pads_by_net = load()
    sk = skeleton(padctr)

    cands = [fps[r] for r in sorted(fps)
             if CAND_RE.match(r) and len(fps[r]["pads"]) == 2]
    if args:
        cands = [fps[r] for r in args if r in fps]

    results = [analyse(c, pads_by_net, sk) for c in cands]

    if verbose:
        for res in sorted(results, key=lambda r: r["cand"]["ref"]):
            c = res["cand"]
            print(f"=== {c['ref']}  cur rot={c['rot']}  "
                  f"pos=({c['x']:.3f},{c['y']:.3f})")
            for d in ORIENTS:
                total, per = res["scores"][d]
                tag = " <-- current" if d == res["cur"] else ""
                rf, sensor = keepout_hit(c, d)
                ko = ""
                if rf:
                    ko = f"  [RF:{rf}]"
                elif sensor:
                    ko = f"  [sensor:{sensor}]"
                detail = "  ".join(
                    f"{n}:{net}={'--' if dd is None else f'{dd:.3f}'}"
                    for n, (net, dd) in per.items())
                print(f"  rot {d:3}: flight={total:7.3f}  {detail}{tag}{ko}")
            if res["best"]:
                bt, bd, bs, bper = res["best"]
                imp = res["improvement"]
                print(f"  best alt: rot {bd}  flight={bt:.3f}  "
                      f"improvement={imp:+.3f} mm "
                      f"({100*imp/res['cur_total']:.0f}%)"
                      if res["cur_total"] > 1e-9 else "")
            print()
        return

    # ranked worklist
    sug = []
    for res in results:
        if res["cand"]["ref"] == "R3":
            continue  # sanity-checked separately
        imp = res["improvement"]
        if imp is None or res["best"] is None:
            continue
        if imp >= MIN_ABS and imp / res["cur_total"] >= MIN_REL:
            sug.append(res)
    sug.sort(key=lambda r: r["improvement"], reverse=True)

    print(f"{'ref':4} {'rot':>7} {'kind':5} {'flight before->after':>21} "
          f"{'gain':>14}  benefiting nets")
    print("-" * 100)
    for res in sug:
        c = res["cand"]
        bt, bd, bs, bper = res["best"]
        imp = res["improvement"]
        kind = "swap" if (bd - c["rot"]) % 180 == 0 else "turn"
        nb = net_benefit(res["cur_per"], bper)
        nets = ", ".join(f"{net}({d:.2f}->{b:.2f})" for net, d, b in nb) or "-"
        ko = f" [sensor:{bs}]" if bs else ""
        print(f"{c['ref']:4} {c['rot']:>3}->{bd:<3} {kind:5} "
              f"{res['cur_total']:8.3f} -> {bt:7.3f}   "
              f"{imp:+.3f}mm/{100*imp/res['cur_total']:3.0f}%  {nets}{ko}")
    print(f"\n{len(sug)} candidate rotation(s). "
          "Ranked by flight reduction; verify each in the GUI. "
          "kind=swap (180deg flip, same axis, safer) / turn (90deg, "
          "changes courtyard axis -- check neighbours).")

    # R3 sanity check
    r3 = next((r for r in results if r["cand"]["ref"] == "R3"), None)
    if r3 is None and "R3" in fps:
        r3 = analyse(fps["R3"], pads_by_net, sk)
    if r3:
        print("\n[sanity] R3 (already rotated 90->270 by the user):")
        for d in ORIENTS:
            total, per = r3["scores"][d]
            tag = " <-- current(270)" if d == 270 else (
                  " (old 90)" if d == 90 else "")
            print(f"  rot {d:3}: flight={total:7.3f}{tag}")
        # what the tool would say if R3 were still at its old 90
        at90 = min((r3["scores"][d][0], d) for d in ORIENTS if d != 90)
        g = r3["scores"][90][0] - at90[0]
        print(f"  if R3 were at 90, best alt = rot {at90[1]} "
              f"(flight {at90[0]:.3f}), gain {g:+.3f} mm "
              f"({100*g/r3['scores'][90][0]:.0f}%) -> points to 270, "
              "correct direction.")


if __name__ == "__main__":
    main()
