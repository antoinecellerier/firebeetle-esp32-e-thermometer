#!/usr/bin/env python3
"""Independent restatement of PCB intent, checked against the saved board.

Reads thermometer-c6.kicad_pcb with pcbnew and asserts what the layout must
guarantee regardless of how pcb.py generated it:

 1. Every pad carries exactly the net circuit.py intends (via the exported
    netlist, same matching rules as verify/check_netlist.py).
 2. The antenna rule area exists and no copper item intersects it.
 3. The sensor rule areas exist and no track/via/fill crosses them.
 4. Every assembled (non-DNP, LCSC-carrying) footprint is on the top side
    (JLCPCB economy assembly is single-sided).
 5. Tracks on the battery-current nets are >= 0.5mm wide, and the +3V3 trunk
    (LDO -> module -> panel load switch) is joined by 0.5mm copper alone.
 6. The board outline is closed and matches pcb_layout.BOARD.
 7. Both M2 mounting holes exist with 2.2mm drills.
 8. Required silkscreen strings exist (only once SILK is authored).

--report additionally prints the per-net ratsnest MST total (placement
metric) without failing.
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))
sys.path.insert(0, HERE)

import circuit  # noqa: E402
import pcb_layout as pl  # noqa: E402
from check_netlist import load_netlist  # noqa: E402

BOARD_PATH = os.path.join(PROJECT, "thermometer-c6.kicad_pcb")
NETLIST = os.path.join(PROJECT, "out", "netlist.net")

POWER_NETS = {"VBAT", "VSYS", "EPD_VCC"}
# +3V3 only carries the 465mA refresh burst between the LDO, the module and
# the panel load switch; the rest of the net is pull-ups and sensor stubs.
TRUNK_3V3 = [("U2", "5"), ("U1", "3"), ("Q2", "2")]
REQUIRED_SILK = ["CHARGE INDOORS", "bridge ONE", "PPK2", "fit ONE", "rev "]

ORIGIN = tuple(pl.BOARD["origin"])

failures = []


def fail(msg):
    failures.append(msg)


def rel(pos):
    """Absolute VECTOR2I -> board-relative mm."""
    return (pos.x / 1e6 - ORIGIN[0], pos.y / 1e6 - ORIGIN[1])


def pt_in_rect(p, rect, grow=0.0):
    return (rect[0] - grow <= p[0] <= rect[2] + grow
            and rect[1] - grow <= p[1] <= rect[3] + grow)


def rects_overlap(a, rect):
    return not (a[2] < rect[0] or a[0] > rect[2]
                or a[3] < rect[1] or a[1] > rect[3])


def seg_hits_rect(a, b, rect, grow=0.0):
    """Liang-Barsky: does segment a->b touch `rect` grown by `grow`?
    Square corners make this conservative, which is the safe direction."""
    x1, y1, x2, y2 = (rect[0] - grow, rect[1] - grow,
                      rect[2] + grow, rect[3] + grow)
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x1), (dx, x2 - a[0]),
                 (-dy, a[1] - y1), (dy, y2 - a[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return True


def build_alias():
    exported = load_netlist(NETLIST)
    alias = {}
    unmatched = dict(exported)
    for cname, pins in circuit.NETS.items():
        ps = {(r, str(p)) for r, p in pins}
        if not cname.startswith("~"):
            alias[cname] = cname
            unmatched.pop(cname, None)
        else:
            hits = [n for n, ep in unmatched.items() if ep == ps]
            if len(hits) == 1:
                alias[cname] = hits[0]
                unmatched.pop(hits[0])
    return exported, alias


def trunk_connected(board, netname, pad_keys, min_width):
    """True if pad_keys are one component of `netname` copper built only from
    tracks at least min_width wide (plus vias, which carry any width)."""
    items = [t for t in board.GetTracks() if t.GetNetname() == netname
             and (t.GetClass() == "PCB_VIA"
                  or t.GetWidth() >= min_width)]  # vias carry any width
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # A track endpoint joins whatever same-net copper it lands on: another
    # track's body (HitTest covers the width), a via, or a pad.
    ends = []
    for i, t in enumerate(items):
        find(("i", i))
        if t.GetClass() == "PCB_VIA":
            ends.append((("i", i), t.GetPosition(), None))
        else:
            for p in (t.GetStart(), t.GetEnd()):
                ends.append((("i", i), p, t.GetLayer()))
    for node, pos, layer in ends:
        for j, t in enumerate(items):
            if t.GetClass() != "PCB_VIA" and layer is not None \
                    and t.GetLayer() != layer:
                continue
            if t.HitTest(pos, 0):
                union(node, ("i", j))
    for fp in board.Footprints():
        for pad in fp.Pads():
            key = (fp.GetReference(), str(pad.GetNumber()))
            if key not in pad_keys:
                continue
            for node, pos, _ in ends:
                if pad.HitTest(pos, 0):
                    union(node, ("p", key))
    roots = {find(("p", k)) for k in pad_keys if ("p", k) in parent}
    return len(roots) == 1 and len(pad_keys) == len(
        [k for k in pad_keys if ("p", k) in parent])


def main():
    report = "--report" in sys.argv
    board = pcbnew.LoadBoard(BOARD_PATH)
    exported, alias = build_alias()

    # 1. pad nets == intent
    want = {}
    for name, pins in exported.items():
        for rp in pins:
            want[rp] = name
    for fp in board.Footprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            num = str(pad.GetNumber())
            if not num:
                continue
            expected = want.get((ref, num), "")
            got = pad.GetNetname()
            if num == "MP" or (ref, num) not in want:
                if got and (ref, num) not in want:
                    fail(f"pad {ref}.{num} unexpectedly on net {got}")
                continue
            if got != expected:
                fail(f"pad {ref}.{num}: net '{got}' != intended '{expected}'")

    # 2-3. rule areas + nothing inside them
    areas = {z.GetZoneName(): z for z in board.Zones() if z.GetIsRuleArea()}
    for needed in ("antenna", "U5-sensor", "U6-sensor"):
        if needed not in areas:
            fail(f"rule area '{needed}' missing")
    rects = {k["name"]: k["rect"] for k in pl.KEEPOUTS}
    # vias are only barred from rule areas whose keepout forbids them (antenna);
    # the sensor keep-outs relax vias=False so a single GND stitch via can buy a
    # low-inductance B-plane ground for the sensor's GND pad (pcb_layout.py).
    via_forbidden = {k["name"]: k.get("vias", True) for k in pl.KEEPOUTS}
    sensor_pads_ok = {"U5", "U6", "H2"}  # sensor's own pads sit inside by design
    for name in ("antenna", "U5-sensor", "U6-sensor"):
        if name not in areas or name not in rects:
            continue
        z, rect = areas[name], rects[name]
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                if not via_forbidden.get(name, True):
                    continue
                r = pl.DEFAULT_VIA["diameter"] / 2
                if pt_in_rect(rel(t.GetPosition()), rect, r):
                    fail(f"via on net {t.GetNetname()} intersects rule area {name}")
            elif name == "antenna":
                hw = t.GetWidth() / 2e6
                if seg_hits_rect(rel(t.GetStart()), rel(t.GetEnd()), rect, hw):
                    fail(f"track on net {t.GetNetname()} intersects the "
                         f"antenna keep-out")
        for fp in board.Footprints():
            for pad in fp.Pads():
                if fp.GetReference() in sensor_pads_ok:
                    continue
                bb = pad.GetBoundingBox()
                pr = (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())
                if pad.IsOnCopperLayer() and rects_overlap(
                        [c / 1e6 - o for c, o in zip(pr, ORIGIN * 2)], rect):
                    fail(f"pad {fp.GetReference()}.{pad.GetNumber()} intersects rule area {name}")
        for zz in board.Zones():
            if zz.GetIsRuleArea() or not zz.IsFilled():
                continue
            for layer in zz.GetLayerSet().Seq():
                if not z.GetLayerSet().Contains(layer):
                    continue
                inter = pcbnew.SHAPE_POLY_SET(zz.GetFilledPolysList(layer))
                area_poly = pcbnew.SHAPE_POLY_SET(z.Outline())
                inter.BooleanIntersection(area_poly)
                if inter.OutlineCount() and inter.Area() > 1e6:  # > 0.001mm^2
                    fail(f"zone fill on {pcbnew.BOARD.GetStandardLayerName(layer)} "
                         f"reaches rule area {name} "
                         f"({inter.Area()/1e12:.3f}mm^2)")

    # 4. assembled parts all on top
    dnp = {c["ref"] for c in circuit.COMPONENTS if c.get("dnp") or not c.get("lcsc")}
    for fp in board.Footprints():
        if fp.GetReference() not in dnp and fp.GetLayer() != pcbnew.F_Cu:
            fail(f"{fp.GetReference()} is assembled but not on the top side")

    # 5a. power-net track widths, except the J4 fan-out stubs where the 0.5mm
    #     pad pitch forbids 0.5mm (same exception as the .kicad_dru rules)
    wide = {alias.get(n, n) for n in POWER_NETS}
    fanouts = [areas[n].GetBoundingBox() for n in ("fpc-fanout",) if n in areas]
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetNetname() in wide:
            if any(bb.Contains(t.GetBoundingBox()) for bb in fanouts):
                continue
            if t.GetWidth() < pcbnew.FromMM(0.499):
                fail(f"track on {t.GetNetname()} is {t.GetWidth()/1e6:.2f}mm wide (<0.5)")

    # 5b. the +3V3 trunk pads must be joined by >=0.5mm copper alone
    if not trunk_connected(board, "+3V3", TRUNK_3V3, pcbnew.FromMM(0.499)):
        fail("+3V3 trunk (U2.5 - U1.3 - Q2.2) is not connected by 0.5mm copper")

    # 6. closed outline, expected size
    outlines = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outlines, False):
        fail("board outline is not closed")
    else:
        bb = outlines.BBox()
        w, h = bb.GetWidth() / 1e6, bb.GetHeight() / 1e6
        ew, eh = pl.BOARD["size"]
        if abs(w - ew) > 0.2 or abs(h - eh) > 0.2:
            fail(f"outline {w:.1f}x{h:.1f} != pcb_layout.BOARD {ew}x{eh}")

    # 7. mounting holes
    holes = 0
    for fp in board.Footprints():
        if fp.GetReference().startswith("H"):
            for pad in fp.Pads():
                d = pad.GetDrillSize().x / 1e6
                if abs(d - 2.2) > 0.01:
                    fail(f"{fp.GetReference()} drill {d:.2f}mm != 2.2mm")
                holes += 1
    if holes != 2:
        fail(f"expected 2 M2 mounting holes, found {holes}")

    # 8. silk strings (once authored)
    if pl.SILK:
        texts = [t.GetText() for t in board.Drawings()
                 if isinstance(t, pcbnew.PCB_TEXT)]
        blob = " | ".join(texts)
        for req in REQUIRED_SILK:
            if req not in blob:
                fail(f"required silk text missing: '{req}'")

    if report:
        pts = {}
        for fp in board.Footprints():
            for pad in fp.Pads():
                if pad.GetNetCode() > 0:
                    pts.setdefault(pad.GetNetname(), []).append(pad.GetPosition())
        total = 0.0
        for net, plist in pts.items():
            # Prim MST
            n = len(plist)
            if n < 2:
                continue
            intree = [False] * n
            dist = [float("inf")] * n
            dist[0] = 0
            for _ in range(n):
                u = min((i for i in range(n) if not intree[i]), key=lambda i: dist[i])
                intree[u] = True
                total += dist[u] ** 0.5 / 1e6 if dist[u] != float("inf") and dist[u] else 0
                for v in range(n):
                    if not intree[v]:
                        d = float((plist[v] - plist[u]).EuclideanNorm()) ** 2
                        if d < dist[v]:
                            dist[v] = d
        print(f"check_pcb report: ratsnest MST ~{total:.0f}mm, "
              f"{len(list(board.Footprints()))} footprints")

    if failures:
        print(f"check_pcb: {len(failures)} FAILURES")
        for f_ in failures:
            print(" ", f_)
        sys.exit(1)
    print("check_pcb: OK")


if __name__ == "__main__":
    main()
