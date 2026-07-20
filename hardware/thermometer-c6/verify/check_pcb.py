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
 6. The board outline is closed, matches pcb_layout.BOARD, and rounds all four
    corners with R=corner_r arcs concentric with the corner insets (H1/H2).
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
REQUIRED_SILK = ["CHARGE INDOORS", "bridge one", "IBAT", "fit one", "rev "]

ORIGIN = tuple(pl.BOARD["origin"])

failures = []


def fail(msg):
    failures.append(msg)


def rel(pos):
    """Absolute VECTOR2I -> board-relative mm."""
    return (pos.x / 1e6 - ORIGIN[0], pos.y / 1e6 - ORIGIN[1])


def check_corner_arcs(board):
    """All four corners rounded R=BOARD['corner_r'], each arc a quarter turn
    centred on that corner's (r, r) inset, joined by the four straight edges.

    The centres are the point of the whole shape: H1/H2 sit on the NE/SW ones,
    so hole and edge stay concentric and the ring of material around each mount
    is uniform (r - hole_radius all the way round). A radius change, a moved
    mount or a corner that reverted to a square would each break that, and none
    of them shows up in a bounding-box check -- so assert the arcs themselves.
    """
    r = pl.BOARD.get("corner_r")
    if not r:
        fail("pcb_layout.BOARD has no corner_r: the rounded outline is part of "
             "the design, a square board is a regression")
        return
    w, h = pl.BOARD["size"]
    want = {(r, r), (w - r, r), (r, h - r), (w - r, h - r)}
    arcs, segs, other = [], [], 0
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        shape = getattr(d, "GetShape", None)
        if shape is None:
            other += 1
        elif shape() == pcbnew.SHAPE_T_ARC:
            arcs.append(d)
        elif shape() == pcbnew.SHAPE_T_SEGMENT:
            segs.append(d)
        else:
            other += 1
    if len(arcs) != 4 or len(segs) != 4 or other:
        fail(f"Edge.Cuts is {len(arcs)} arcs + {len(segs)} segments "
             f"+ {other} other, want exactly 4 arcs + 4 segments")
        return
    seen = set()
    for a in arcs:
        cx, cy = rel(a.GetCenter())
        rad = a.GetRadius() / 1e6
        ang = abs(a.GetArcAngle().AsDegrees())
        if abs(rad - r) > 0.01:
            fail(f"corner arc at ({cx:.2f},{cy:.2f}) is R{rad:.3f}, want R{r}")
        if abs(ang - 90.0) > 0.5:
            fail(f"corner arc at ({cx:.2f},{cy:.2f}) sweeps {ang:.1f} deg, want 90")
        hit = [c for c in want
               if abs(c[0] - cx) < 0.01 and abs(c[1] - cy) < 0.01]
        if hit:
            seen.add(hit[0])
        else:
            fail(f"corner arc centre ({cx:.2f},{cy:.2f}) is not a corner inset")
    for c in sorted(want - seen):
        fail(f"corner ({c[0]:.2f},{c[1]:.2f}) has no R{r} arc")
    for ref, centre in (("H1", (w - r, r)), ("H2", (r, h - r))):
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            fail(f"{ref} mounting hole missing")
            continue
        x, y = rel(fp.GetPosition())
        if abs(x - centre[0]) > 0.01 or abs(y - centre[1]) > 0.01:
            fail(f"{ref} at ({x:.2f},{y:.2f}) is not concentric with its corner "
                 f"arc at ({centre[0]:.2f},{centre[1]:.2f})")


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
    # Optional positional: the board to check (default = committed board). The
    # netlist / pcb_layout intent it is compared against is always the project's.
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    board_path = positional[0] if positional else BOARD_PATH
    board = pcbnew.LoadBoard(board_path)
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

    # 6. closed outline, expected size, four corner arcs concentric with the
    #    corner insets (H1/H2 sit on two of those centres).
    outlines = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outlines, False):
        fail("board outline is not closed")
    else:
        bb = outlines.BBox()
        w, h = bb.GetWidth() / 1e6, bb.GetHeight() / 1e6
        ew, eh = pl.BOARD["size"]
        if abs(w - ew) > 0.2 or abs(h - eh) > 0.2:
            fail(f"outline {w:.1f}x{h:.1f} != pcb_layout.BOARD {ew}x{eh}")
    check_corner_arcs(board)

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

    # 9. J4 FPC orientation guard. A 180-deg body flip (mouth-west vs mouth-east)
    #    passes BOTH netlist parity and DRC: the pads carry the intended nets
    #    whichever way the housing opens, and clearance is face-agnostic. Only
    #    the STEP/land-pattern geometry tells the two apart -- exactly the error
    #    that shipped to preview (2026-07-19 respin fixed it). Pin the geometry:
    #    contact tails / pad column WEST, mouth EAST flush with the board edge,
    #    pad 1 at the NORTH end (rot 90; pad numbering flipped to keep it north).
    j4 = next((fp for fp in board.Footprints()
               if fp.GetReference() == "J4"), None)
    if j4 is None:
        fail("J4 footprint missing")
    else:
        cx, cy = rel(j4.GetPosition())
        pads = {str(p.GetNumber()): rel(p.GetPosition())
                for p in j4.Pads() if str(p.GetNumber()) not in ("", "MP")}
        # (a) pin 1 north: pad 1 sits above (smaller y than) the body centre
        if "1" not in pads:
            fail("J4 pad 1 missing")
        elif not pads["1"][1] < cy:
            fail(f"J4 pad 1 (y={pads['1'][1]:.2f}) not north of centre y={cy:.2f}")
        # (b) contact tails west: the signal pad column is west of the body centre
        colx = pads["1"][0] if "1" in pads else cx
        if not colx < cx - 0.5:
            fail(f"J4 pad column (x={colx:.2f}) not west of centre x={cx:.2f}")
        # (c) the body opens EAST, and is the depth the part actually has.
        #     Datum = the SMT contact row. Measured from the STEP's FACE
        #     VERTICES (local.3dmodels/XUNPU_FPC-05FB-24PH20.step, bbox
        #     Y[-5.150,+0.250]): mouth face 4.95mm from the feet, rear/actuator
        #     wall 0.45mm behind them, body 5.40mm deep. A 180-deg flip makes
        #     mouth_off negative, so this catches the same error the old
        #     "reaches the east edge" test did -- but it ALSO pins the depth,
        #     which the old test could not: the footprint shipped a 7.05mm body
        #     until 2026-07-20, because bounding-boxing raw CARTESIAN_POINTs
        #     picked up LINE / AXIS2_PLACEMENT_3D origins owning no geometry
        #     (out/j3-land/ section 7). The mouth is now ~1.6mm inboard of the
        #     east edge instead of flush -- fine for an FPC, the cable just
        #     inserts deeper -- so "near the edge" is no longer the invariant.
        fabx = [rel(p)[0] for g in j4.GraphicalItems()
                if g.GetLayerName() == "F.Fab" and g.GetClass().startswith("PCB_SHAPE")
                for p in (g.GetStart(), g.GetEnd())]
        if not fabx:
            fail("J4 F.Fab body outline missing")
        else:
            mouth_off, rear_off = max(fabx) - colx, colx - min(fabx)
            if abs(mouth_off - 4.95) > 0.10:
                fail(f"J4 mouth face is {mouth_off:+.3f}mm east of the contact row, "
                     f"expected +4.95 (STEP); flipped mouth-west, or the body "
                     f"depth regressed?")
            if abs(rear_off - 0.45) > 0.10:
                fail(f"J4 rear wall is {rear_off:+.3f}mm west of the contact row, "
                     f"expected +0.45 (STEP)")
            east = pl.BOARD["size"][0]
            if max(fabx) > east:
                fail(f"J4 body (max-x={max(fabx):.2f}) overhangs the east edge "
                     f"(x={east})")

    # 9b. J3 USB-C orientation AND datum guard. Same flip trap as J4 (a 180-deg
    #     flip keeps every pad on its net and stays DRC-clean), plus the datum
    #     error that flip masked. Both are asserted against HRO's own drawing
    #     rather than against whatever the board currently says:
    #
    #       out/j3-datum/ parsed the datasheet's vector content stream and
    #       proved "5.79" is PCB EDGE -> NPTH POST CENTRELINE (not to the pad
    #       row) and "4.18" is shell-slot centre to shell-slot centre. So off
    #       the north board edge the chain is, in mm:
    #         front shell slot  2.11   (drawing 2.1078, HRO tol +-0.05)
    #         + 4.18 -> rear shell slot        (drawing 4.1716)
    #         + 3.65 -> NPTH plastic post      (STEP-measured post axis; the
    #                                           drawing's 3.6716 is the outlier)
    #         + 4.925 -> SMT pad row centre    (out/j3-land land: heel 4.200
    #                                           from the front slot + 1.45/2)
    #       Until 2026-07-20 the board read 0.695 for the front slot, i.e.
    #       1.415mm too far north, which hung the front shell pad 0.105mm OFF
    #       the board and produced the 2 copper_edge_clearance errors that the
    #       (now deleted) edge-clearance-usb-c DRU rule waived. Test (e) is that
    #       waiver's replacement: assert the pad is ON the board, so a datum
    #       regression fails here instead of being silently waived at fab time.
    j3 = next((fp for fp in board.Footprints()
               if fp.GetReference() == "J3"), None)
    if j3 is None:
        fail("J3 footprint missing")
    else:
        rot = j3.GetOrientationDegrees() % 360
        pads = {str(p.GetNumber()): rel(p.GetPosition())
                for p in j3.Pads() if str(p.GetNumber()) not in ("", "SH")}
        shell = sorted({round(rel(p.GetPosition())[1], 3)
                        for p in j3.Pads() if str(p.GetNumber()) == "SH"})
        npth = sorted({round(rel(p.GetPosition())[1], 3)
                       for p in j3.Pads() if str(p.GetNumber()) == ""})
        # (a) rotation 180 (mouth-north)
        if abs(rot - 180) > 1:
            fail(f"J3 rotation is {rot:.0f}, expected 180 (mouth-north)")
        # (b) the datasheet chain off the north board edge
        if len(shell) != 2:
            fail(f"J3: expected 2 distinct shell-slot rows, got {shell}")
        elif len(npth) != 1:
            fail(f"J3: expected 1 NPTH post row, got {npth}")
        else:
            front, rear = shell
            for got, want, what in ((front, 2.110, "front shell slot from the north edge"),
                                    (rear - front, 4.180, "front->rear shell slot span"),
                                    (npth[0] - front, 3.650, "front slot->NPTH post")):
                if abs(got - want) > 0.05:
                    fail(f"J3 {what} is {got:.3f}, expected {want:.3f} "
                         f"(HRO drawing, tol +-0.05)")
            # (c) the SMT land sits where out/j3-land put it (heel +0.250 /
            #     toe +0.350 against the measured 0.850mm solder foot)
            row = pads.get("A1")
            if row is None:
                fail("J3 pad A1 missing")
            else:
                if abs((row[1] - front) - 4.925) > 0.05:
                    fail(f"J3 pad row is {row[1] - front:.3f} from the front shell "
                         f"slot, expected 4.925 (land: heel 4.200 + 1.45/2)")
                # (d) mouth-north: the tail row is INBOARD of both shell rows
                if not row[1] > rear:
                    fail(f"J3 pad row (y={row[1]:.3f}) is not south of the rear "
                         f"shell slot (y={rear:.3f}); flipped mouth-south?")
        # (e) every shell pad is ON the board (replaces the deleted
        #     edge-clearance-usb-c waiver -- see the note above)
        for p in j3.Pads():
            if str(p.GetNumber()) != "SH":
                continue
            top = p.GetBoundingBox().GetTop() / 1e6 - ORIGIN[1]
            if top < 0:
                fail(f"J3 shell pad at x={rel(p.GetPosition())[0]:.2f} overhangs "
                     f"the north board edge by {-top:.3f}mm; J3 is placed too far "
                     f"north (datum regression)")
        # (f) the mouth itself still overhangs the north edge (edge-launch)
        fabmy = [rel(p)[1] for g in j3.GraphicalItems()
                 if g.GetLayerName() == "F.Fab" and g.GetClass().startswith("PCB_SHAPE")
                 for p in (g.GetStart(), g.GetEnd())]
        if fabmy and min(fabmy) > 0:
            fail(f"J3 mouth (F.Fab min-y={min(fabmy):.3f}) does not reach the "
                 f"north edge (y=0); is the connector flipped mouth-south?")

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
