#!/usr/bin/env python3
"""Grid A* autorouter for the remaining nets -> generator/pcb_routes.py.

Routes every listed net on a 0.05mm grid (F.Cu/B.Cu, 45-degree moves, via
hops) against the real clearance rules: 0.2mm netclass, 0.3mm around HV
nets outside the fpc-fanout marker area, 0.18mm inside it, board-edge 0.2,
keepout rule areas. Authored copper in pcb_layout.py is obstacle/seed; the
result is written as plain TRACKS/VIAS data to pcb_routes.py (checked in,
hand-tweakable) which pcb_layout.py appends. Re-run only via `make route`;
`make pcb` just consumes the checked-in file, so builds stay deterministic.

Run inside kicad's python (needs pcbnew for pad geometry):
    python3 generator/route.py
"""
import heapq
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

os.environ["PCB_NO_ROUTES"] = "1"  # route against authored copper only
import circuit  # noqa: E402
import pcb_layout as pl  # noqa: E402

GRID = 0.05
W = int(round(pl.BOARD["size"][0] / GRID))  # 960
H = int(round(pl.BOARD["size"][1] / GRID))  # 700
OX, OY = pl.BOARD["origin"]

VIA_R = pl.DEFAULT_VIA["diameter"] / 2
VIA_COST = 1.5          # mm-equivalent per via
BEND_COST = 0.02        # keep runs straight
EDGE_CLR = 0.2
BASE_CLR = 0.2
HV_CLR = 0.3
HV_CLR_RELAXED = 0.18
MARKER = (39.5, 8.0, 48.0, 25.5)   # fpc-fanout rule area

HV_NETS = {"EPD_PREVGH", "EPD_PREVGL", "~EPD_VGH", "~EPD_VGL",
           "~EPD_VSH", "~EPD_VSL", "~EPD_VCOM", "~EPD_VPP"}

# (net, width, terminals-or-None[, box]) routed in this order; None = all pins
# from circuit.py not already on the authored tree. Terminal order is routing
# order: the first one seeds the tree when no authored copper exists, so a
# scarce escape (J4's 0.5mm pitch) is claimed before the far end pulls the
# tree away. `box` clamps the A* search to a rectangle. GND -> the M6 pour.
#
# Ordering rationale: hardest first. J4's fan-out corridor, then the wide
# power nets, then long cross-board runs, then everything local. Nets routed
# late get whatever copper is left, so anything that fails moves up.
ROUTE_PLAN = [
    # --- J4 fan-out. 0.3mm HV clearance in a 0.5mm-pitch escape is the
    # scarcest resource: each entry names its J4 pin first so the escape is
    # claimed before the far terminal drags the tree away. Within each group
    # the pins go free-edge inwards (north group N->S, south group S->N), so
    # an early escape never fences a later one against the connector body.
    ("EPD_GDR", 0.25, [("J4", "2"), ("Q3", "1"), ("R13", "1"), ("TP8", "1")]),
    ("EPD_RESE", 0.25, [("J4", "3"), ("TP9", "1")]),   # sense leg + bench TP
    ("~EPD_VGL", 0.25, [("J4", "4"), ("C19", "1")]),
    ("~EPD_VGH", 0.25, [("J4", "5"), ("C20", "1")]),
    ("~EPD_VCOM", 0.25, [("J4", "24"), ("C25", "1"), ("TP10", "1")]),
    ("EPD_PREVGL", 0.25, [("J4", "23"), ("TP7", "1")]),
    ("~EPD_VSL", 0.25, [("J4", "22"), ("C24", "1")]),
    ("EPD_PREVGH", 0.25, [("J4", "21"), ("TP6", "1")]),
    ("~EPD_VSH", 0.25, [("J4", "20"), ("C23", "1")]),
    ("~EPD_VPP", 0.25, [("J4", "19"), ("C22", "1")]),
    ("~EPD_VDD", 0.25, [("J4", "18"), ("C21", "1")]),
    # --- 0.5mm power through the booster neck, before the signals fill it.
    # Q2's pads are adjacent, so its drain (EPD_VCC) claims copper first, then
    # the gate network (0.55mm pad gaps, no room for a 0.5mm neighbour).
    # This must precede the J4 digital pins, not follow them: Q2.3's only
    # escape is north (its own gate/source pads wall the south) into the same
    # B.Cu channel over TP8 that the six digital lanes cross the booster on.
    # Routed after them, EPD_VCC loses Q2.3 and TP5.1 outright.
    ("EPD_VCC", 0.5, [("Q2", "3"), ("C15", "1"), ("L1", "1"), ("TP5", "1"),
                      ("C14", "1"), ("L2", "1")]),
    # --- J4 digital pins. Descending: the bundle lands on U1's NE corner
    # (pin 24 MOSI, pin 25 SCK), so the nearest U1 pin is served first and
    # the later ones fan west along the north row behind it. Each run dives
    # under the authored EPD_VCC diagonal on its way across.
    ("EPD_MOSI", 0.25, [("J4", "14"), ("U1", "24")]),
    ("EPD_SCK", 0.25, [("J4", "13"), ("U1", "25")]),
    ("EPD_CS", 0.25, [("J4", "12"), ("U1", "26")]),
    ("EPD_DC", 0.25, [("J4", "11"), ("U1", "27")]),
    ("EPD_RST", 0.25, [("J4", "10"), ("R17", "2"), ("U1", "28")]),
    ("EPD_BUSY", 0.25, [("J4", "9"), ("U1", "29")]),
    ("~EPD_GATE", 0.25, None),
    ("EPD_PWR_EN", 0.25, None),
    # +3V3 trunk: LDO -> U1 -> the panel load switch, the only stretch that
    # carries the 465mA refresh burst (verify/check_pcb.py asserts its width)
    ("+3V3", 0.5, [("Q2", "2"), ("U1", "3"), ("C7", "1"), ("C8", "1"),
                   ("U2", "5"), ("C3", "1"), ("C4", "1")]),
    # +3V3 branches: gate network, pull-ups, probe pads, debug header and the
    # sensor block. Microamps, and 0.5mm cannot escape U5's LGA pitch anyway.
    ("+3V3", 0.25, None),
    # --- USB (the connector fan-out itself is authored in pcb_layout)
    ("USB_D-", 0.25, None),
    ("USB_D+", 0.25, None),
    # crystal
    ("XTAL_32K_P", 0.25, None),
    ("XTAL_32K_N", 0.25, None),
    # sensors / divider / straps / LED / buttons / charger / debug
    ("SDA", 0.25, None),
    ("SCL", 0.25, None),
    ("VBAT_ADC", 0.25, None),
    ("VDIV_EN", 0.25, None),
    ("~VDIV_TOP", 0.25, None),
    ("~VDIV_PGATE", 0.25, None),
    ("VBUS_SENSE", 0.25, [("R22", "2"), ("R23", "1"), ("U1", "9"), ("J5", "6")]),
    ("CHG_STAT", 0.25, None),
    ("~CHG_LED_A", 0.25, None),
    ("~CHG_PROG", 0.25, None),
    # BOOT is boxed to U1's north-east quadrant. R7 sits 13mm from U1.23 with
    # the crystal block and the +3V3 B.Cu trunk between them, so unboxed A*
    # reaches R7.2 the only way left: 60mm around the board's south edge and up
    # the 0.3mm-wide B.Cu column between the antenna keep-out and the VSYS
    # lane -- the single west corridor EN needs for SW1. R7.2 stays unrouted
    # until R7 moves; a straggler here is cheaper than EN losing its only lane.
    ("BOOT", 0.25, [("U1", "23"), ("R7", "2"), ("SW2", "1")],
     (7.8, 0.0, 21.6, 24.5)),
    ("EN", 0.25, [("U1", "8"), ("C9", "1"), ("R6", "2"), ("SW1", "1"),
                  ("J5", "3")]),
    ("LED_STATUS", 0.25, None),
    ("~LED_A", 0.25, None),
    ("DBG_TX", 0.25, None),
    ("DBG_RX", 0.25, None),
    ("DBG_IO5", 0.25, None),
    ("DBG_IO8", 0.25, None),
    ("VBUS", 0.4, None),
    ("VBAT", 0.5, None),
    ("VSYS", 0.5, None),
]

# Nets deliberately absent from ROUTE_PLAN: GND (M6 pour) and the booster-core
# nets hand-authored in pcb_layout.TRACKS. check_plan_covers_nets() enforces it.

OUT = os.path.join(HERE, "pcb_routes.py")


# --- geometry helpers -------------------------------------------------------
def cell(x, y):
    return int(round(x / GRID)), int(round(y / GRID))


def mm(ix, iy):
    return round(ix * GRID, 3), round(iy * GRID, 3)


def is_hv(net):
    return net in HV_NETS


def inside_marker(x, y):
    return MARKER[0] <= x <= MARKER[2] and MARKER[1] <= y <= MARKER[3]


class Bitmap:
    """One bit per grid cell, rect/disc stamping with mm coords."""

    def __init__(self):
        self.b = bytearray(W * H)

    def stamp_rect(self, x1, y1, x2, y2):
        # centre-sampling: a cell is blocked iff its centre point violates.
        # Optimistic by at most half a cell; the real DRC arbitrates.
        ix1 = max(0, int(math.ceil(x1 / GRID)))
        iy1 = max(0, int(math.ceil(y1 / GRID)))
        ix2 = min(W - 1, int(math.floor(x2 / GRID)))
        iy2 = min(H - 1, int(math.floor(y2 / GRID)))
        if ix2 < ix1 or iy2 < iy1:
            return
        row = b"\x01" * (ix2 - ix1 + 1)
        for iy in range(iy1, iy2 + 1):
            base = iy * W
            self.b[base + ix1:base + ix2 + 1] = row

    def stamp_seg(self, x1, y1, x2, y2, infl):
        """Inflated capsule, conservatively as stamped squares."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-9 or dx == 0 or dy == 0:
            self.stamp_rect(min(x1, x2) - infl, min(y1, y2) - infl,
                            max(x1, x2) + infl, max(y1, y2) + infl)
            return
        steps = max(1, int(length / (GRID * 2)))
        for i in range(steps + 1):
            t = i / steps
            px, py = x1 + dx * t, y1 + dy * t
            self.stamp_rect(px - infl, py - infl, px + infl, py + infl)

    def get(self, ix, iy):
        return self.b[iy * W + ix]


# --- collect obstacles from the generated board + authored layout -----------
def load_pads():
    board = pcbnew.LoadBoard(os.path.join(PROJECT, "thermometer-c6.kicad_pcb"))
    pads = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            layers = pad.GetLayerSet().Seq()
            pads.append(dict(
                ref=ref, num=str(pad.GetNumber()), net=pad.GetNetname(),
                cx=pad.GetPosition().x / 1e6 - OX,
                cy=pad.GetPosition().y / 1e6 - OY,
                x1=bb.GetLeft() / 1e6 - OX, y1=bb.GetTop() / 1e6 - OY,
                x2=bb.GetRight() / 1e6 - OX, y2=bb.GetBottom() / 1e6 - OY,
                F=pcbnew.F_Cu in layers, B=pcbnew.B_Cu in layers))
    return pads


def expand_dogleg(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) < 1e-9 or abs(dy) < 1e-9 or abs(abs(dx) - abs(dy)) < 1e-9:
        return [a, b]
    d = min(abs(dx), abs(dy))
    mid = (a[0] + (d if dx > 0 else -d), a[1] + (d if dy > 0 else -d))
    return [a, mid, b]


def authored_copper(pads):
    """[(net, layer, halfw, x1,y1,x2,y2)] segments + [(net,x,y)] vias from
    pcb_layout plus pcb_routes accumulated so far (via pl reload semantics:
    we only read pl.TRACKS/pl.VIAS, the caller appends routed results)."""
    pad_by_key = {(p["ref"], p["num"]): (p["cx"], p["cy"]) for p in pads}
    # exported-name mapping not needed here: circuit names are consistent
    # within pcb_layout, and obstacles only need net identity
    segs = []
    for net, layer, width, nodes in pl.TRACKS:
        pts = []
        for n in nodes:
            if isinstance(n, str):
                ref, _, num = n.partition(".")
                pts.append(pad_by_key[(ref, num)])
            else:
                pts.append(n)
        path = []
        for i in range(len(pts) - 1):
            ext = expand_dogleg(pts[i], pts[i + 1])
            path.extend(ext if not path else ext[1:])
        for i in range(len(path) - 1):
            segs.append((net, layer, width / 2,
                         path[i][0], path[i][1], path[i + 1][0], path[i + 1][1]))
    vias = [(net, x, y) for net, x, y in pl.VIAS]
    return segs, vias


# circuit-name <-> exported-name: pads carry exported names; anonymous "~"
# circuit nets need resolution by pin membership.
def net_alias(pads):
    by_pin = {(p["ref"], p["num"]): p["net"] for p in pads}
    alias = {}
    for cname, pins in circuit.NETS.items():
        exp = by_pin.get((pins[0][0], str(pins[0][1])))
        alias[cname] = exp if exp else cname
    return alias


def build_bitmaps(pads, segs, vias, net_exp, width, alias):
    """Track bitmaps (strict + relaxed HV variants) and via bitmaps."""
    hw = width / 2
    routed_hv = net_exp in {alias[n] for n in HV_NETS}

    def infl_for(onet, base_extra):
        if onet == net_exp:
            return None
        c = BASE_CLR
        onet_hv = onet in {alias[n] for n in HV_NETS}
        if routed_hv or onet_hv:
            c = HV_CLR
        return c + base_extra

    def relaxed_for(onet, base_extra):
        if onet == net_exp:
            return None
        c = BASE_CLR
        onet_hv = onet in {alias[n] for n in HV_NETS}
        if routed_hv or onet_hv:
            c = HV_CLR_RELAXED
        return c + base_extra

    maps = {}
    for kind, extra in (("trk", hw), ("via", VIA_R)):
        for variant, get_clr in (("strict", infl_for), ("relax", relaxed_for)):
            for layer in ("F.Cu", "B.Cu"):
                maps[(kind, variant, layer)] = Bitmap()

    def stamp(layer_flags, onet, x1, y1, x2, y2, seg=False, shw=0.0):
        for kind, extra in (("trk", hw), ("via", VIA_R)):
            for variant, get_clr in (("strict", infl_for),
                                     ("relax", relaxed_for)):
                clr = get_clr(onet, extra)
                if clr is None:
                    continue
                i = clr + shw
                for layer in layer_flags:
                    bm = maps[(kind, variant, layer)]
                    if seg:
                        bm.stamp_seg(x1, y1, x2, y2, i)
                    else:
                        bm.stamp_rect(x1 - i, y1 - i, x2 + i, y2 + i)

    for p in pads:
        # HV relaxation keys off the HV item's position: an HV *obstacle*
        # outside the marker forces 0.3 regardless of where we route, so
        # only relax when the obstacle itself sits inside the marker
        onet_hv = p["net"] in {alias[n] for n in HV_NETS}
        obstacle_in = inside_marker(p["cx"], p["cy"])
        layers = [l for l, f in (("F.Cu", p["F"]), ("B.Cu", p["B"])) if f]
        if not layers:  # NPTH: block both
            layers = ["F.Cu", "B.Cu"]
        if onet_hv and not obstacle_in and not routed_hv:
            # relaxation would be wrong here: stamp strict into both variants
            for kind, extra in (("trk", hw), ("via", VIA_R)):
                for variant in ("strict", "relax"):
                    i = HV_CLR + extra
                    for layer in layers:
                        maps[(kind, variant, layer)].stamp_rect(
                            p["x1"] - i, p["y1"] - i, p["x2"] + i, p["y2"] + i)
            continue
        stamp(layers, p["net"], p["x1"], p["y1"], p["x2"], p["y2"])

    for net, layer, shw, x1, y1, x2, y2 in segs:
        stamp([layer], alias.get(net, net), x1, y1, x2, y2, seg=True, shw=shw)
    for net, x, y in vias:
        stamp(["F.Cu", "B.Cu"], alias.get(net, net),
              x - VIA_R, y - VIA_R, x + VIA_R, y + VIA_R)

    # keepouts + board edge
    for k in pl.KEEPOUTS:
        x1, y1, x2, y2 = k["rect"]
        kinds = []
        if k.get("tracks", True):
            kinds.append("trk")
        if k.get("vias", True):
            kinds.append("via")
        for kind in kinds:
            extra = hw if kind == "trk" else VIA_R
            for variant in ("strict", "relax"):
                for layer in k["layers"]:
                    maps[(kind, variant, layer)].stamp_rect(
                        x1 - extra, y1 - extra, x2 + extra, y2 + extra)
    bw, bh = pl.BOARD["size"]
    for kind, extra in (("trk", hw), ("via", VIA_R)):
        m = EDGE_CLR + extra
        for variant in ("strict", "relax"):
            for layer in ("F.Cu", "B.Cu"):
                bm = maps[(kind, variant, layer)]
                bm.stamp_rect(-1, -1, bw + 1, m)
                bm.stamp_rect(-1, bh - m, bw + 1, bh + 1)
                bm.stamp_rect(-1, -1, m, bh + 1)
                bm.stamp_rect(bw - m, -1, bw + 1, bh + 1)
    return maps


DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
LAYER_IDX = {"F.Cu": 0, "B.Cu": 1}


MARKER_CELLS = (int(MARKER[0] / GRID), int(MARKER[1] / GRID),
                int(MARKER[2] / GRID), int(MARKER[3] / GRID))


def blocked(maps, kind, layer, ix, iy):
    mx1, my1, mx2, my2 = MARKER_CELLS
    variant = "relax" if (mx1 <= ix <= mx2 and my1 <= iy <= my2) else "strict"
    return maps[(kind, variant, layer)].b[iy * W + ix]


def astar(maps, starts, goals, max_pop=1_500_000, margin_mm=8.0, box=None):
    """starts: [(layer, ix, iy)]; goals: set of (layer, ix, iy).

    The search is clamped to the terminals' bounding box grown by margin_mm,
    or to `box` (board mm) when given — a hard fence, not a hint.
    """
    if not goals:
        return None
    gx1 = min(g[1] for g in goals)
    gx2 = max(g[1] for g in goals)
    gy1 = min(g[2] for g in goals)
    gy2 = max(g[2] for g in goals)
    glayers = {g[0] for g in goals}

    def h(l, ix, iy):
        # octile distance to the goal bounding box: O(1) and admissible
        dx = max(gx1 - ix, 0, ix - gx2)
        dy = max(gy1 - iy, 0, iy - gy2)
        d = (max(dx, dy) + 0.4142 * min(dx, dy)) * GRID
        if l not in glayers:
            d += VIA_COST
        return d

    if box is not None:
        bx1, by1 = max(0, cell(box[0], 0)[0]), max(0, cell(0, box[1])[1])
        bx2, by2 = min(W - 1, cell(box[2], 0)[0]), min(H - 1, cell(0, box[3])[1])
    else:
        margin = int(margin_mm / GRID)
        sx = [s[1] for s in starts]
        sy = [s[2] for s in starts]
        bx1 = max(0, min(gx1, min(sx)) - margin)
        bx2 = min(W - 1, max(gx2, max(sx)) + margin)
        by1 = max(0, min(gy1, min(sy)) - margin)
        by2 = min(H - 1, max(gy2, max(sy)) + margin)

    open_q = []
    best_g = {}
    push_n = 0
    for (l, ix, iy) in starts:
        st = (l, ix, iy)
        best_g[st] = 0.0
        heapq.heappush(open_q, (h(l, ix, iy), push_n, 0.0, st, None, 8))
        push_n += 1
    came = {}
    pops = 0
    while open_q:
        f, _, g, st, parent, d = heapq.heappop(open_q)
        if st in came:
            continue
        came[st] = parent
        pops += 1
        if pops > max_pop:
            return None
        l, ix, iy = st
        if st in goals:
            path = []
            cur = st
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            path.reverse()
            return path
        lname = "F.Cu" if l == 0 else "B.Cu"
        for di, (dx, dy) in enumerate(DIRS):
            nx, ny = ix + dx, iy + dy
            if not (bx1 <= nx <= bx2 and by1 <= ny <= by2):
                continue
            if blocked(maps, "trk", lname, nx, ny):
                continue
            if dx and dy:  # no corner cutting
                if (blocked(maps, "trk", lname, ix + dx, iy)
                        or blocked(maps, "trk", lname, ix, iy + dy)):
                    continue
            step = GRID * (1.4142 if dx and dy else 1.0)
            ng = g + step + (BEND_COST if d != 8 and d != di else 0.0)
            nst = (l, nx, ny)
            if ng < best_g.get(nst, 1e18):
                best_g[nst] = ng
                push_n += 1
                heapq.heappush(open_q,
                               (ng + h(l, nx, ny), push_n, ng, nst, st, di))
        # via hop
        ol = 1 - l
        olname = "F.Cu" if ol == 0 else "B.Cu"
        if (not blocked(maps, "via", "F.Cu", ix, iy)
                and not blocked(maps, "via", "B.Cu", ix, iy)
                and not blocked(maps, "trk", olname, ix, iy)):
            ng = g + VIA_COST
            nst = (ol, ix, iy)
            if ng < best_g.get(nst, 1e18):
                best_g[nst] = ng
                push_n += 1
                heapq.heappush(open_q,
                               (ng + h(ol, ix, iy), push_n, ng, nst, st, 8))
    return None


def path_to_tracks(path, net, width):
    """Collapse grid path into segments + vias (board-relative mm)."""
    tracks, vias = [], []
    run = [path[0]]
    for st in path[1:]:
        if st[0] != run[-1][0]:  # layer change = via
            pt = mm(run[-1][1], run[-1][2])
            vias.append((net, pt[0], pt[1]))
            tracks.append((net, run))
            run = [st]
        else:
            run.append(st)
    tracks.append((net, run))
    out = []
    for net_, run_ in tracks:
        if len(run_) < 2:
            continue
        layer = "F.Cu" if run_[0][0] == 0 else "B.Cu"
        pts = [mm(run_[0][1], run_[0][2])]
        for i in range(1, len(run_) - 1):
            d0 = (run_[i][1] - run_[i - 1][1], run_[i][2] - run_[i - 1][2])
            d1 = (run_[i + 1][1] - run_[i][1], run_[i + 1][2] - run_[i][2])
            if d0 != d1:
                pts.append(mm(run_[i][1], run_[i][2]))
        pts.append(mm(run_[-1][1], run_[-1][2]))
        out.append((net_, layer, width, pts))
    return out, vias


def check_plan_covers_nets():
    """Every net must be routed, authored, or explicitly exempt — a net that
    is in neither ROUTE_PLAN nor pcb_layout.TRACKS is silently never routed."""
    planned = {e[0] for e in ROUTE_PLAN}
    authored = {t[0] for t in pl.TRACKS}
    missing = sorted(set(circuit.NETS) - planned - authored - {"GND"})
    if missing:
        raise SystemExit("route: nets in neither ROUTE_PLAN nor pcb_layout."
                         "TRACKS: " + ", ".join(missing))


def _copper_islands(segs, vias, pads, exp, alias):
    """Connected components of net `exp`'s copper, as sets of grid cells.

    Cells of one track are adjacent by construction (half-grid sampling); a via
    shorts the two layers at its cell; a pad shorts every same-net cell landing
    on it (that is what joins two tracks meeting at a pad)."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def add(c):
        parent.setdefault(c, c)
        return c

    for net_, layer, shw, x1, y1, x2, y2 in segs:
        if alias.get(net_, net_) != exp:
            continue
        li = LAYER_IDX[layer]
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / (GRID * 0.5)))
        prev = None
        for i in range(steps + 1):
            t = i / steps
            c = add((li, *cell(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)))
            if prev is not None and prev != c:
                union(prev, c)
            prev = c
    for net_, x, y in vias:
        if alias.get(net_, net_) != exp:
            continue
        c = cell(x, y)
        union(add((0, *c)), add((1, *c)))
    for p in pads:
        if p["net"] != exp:
            continue
        ix1, iy1 = cell(p["x1"], p["y1"])
        ix2, iy2 = cell(p["x2"], p["y2"])
        layers = ([0] if p["F"] else []) + ([1] if p["B"] else [])
        anchor = None
        for li in layers:
            for ix in range(ix1, ix2 + 1):
                for iy in range(iy1, iy2 + 1):
                    c = (li, ix, iy)
                    if c not in parent:
                        continue
                    if anchor is None:
                        anchor = c
                    else:
                        union(anchor, c)

    out = {}
    for c in parent:
        out.setdefault(find(c), set()).add(c)
    return list(out.values())


def route_all(entries, pads, alias, pads_by_key, verbose):
    """Route `entries` in order against the authored copper. Returns
    (tracks, vias, failed); `failed` is [(circuit_net, reason)]."""
    segs, vias = authored_copper(pads)

    new_tracks, new_vias, failed = [], [], []

    for entry in entries:
        cname, width, terminals = entry[:3]
        box = entry[3] if len(entry) > 3 else None
        exp = alias.get(cname, cname)
        pins = circuit.NETS.get(cname)
        if pins is None:
            failed.append((cname, "unknown net"))
            continue
        if terminals is None:
            terminals = [(r, str(n)) for r, n in pins]
        # Same-net copper, grouped into ISLANDS. Touching same-net copper does
        # not mean connected: two authored stubs on one net (a J4 escape and a
        # U1 escape, say) are two islands, and treating either as "the tree"
        # silently leaves the net open. Union-find the copper; then every
        # island, plus every terminal pad that no island touches, is a node
        # that must be merged into one tree.
        islands = _copper_islands(segs, vias, pads, exp, alias)

        def island_of(p):
            ix1, iy1 = cell(p["x1"], p["y1"])
            ix2, iy2 = cell(p["x2"], p["y2"])
            layers = ([0] if p["F"] else []) + ([1] if p["B"] else [])
            for i, isl in enumerate(islands):
                if any((li, ix, iy) in isl for li in layers
                       for ix in range(ix1, ix2 + 1)
                       for iy in range(iy1, iy2 + 1)):
                    return i
            return None

        term_pads = []
        for (ref, num) in terminals:
            group = pads_by_key.get((ref, num))
            if not group:
                failed.append((cname, f"missing pad {ref}.{num}"))
                continue
            term_pads.extend(group)
        if not term_pads and not islands:
            continue
        maps = build_bitmaps(pads, segs, vias, exp, width, alias)

        def pad_cells(p, free_only=True):
            """Grid cells safely on the pad's copper (inset past rounded
            corners) for A* starts / tree seeds."""
            layers = ([0] if p["F"] else []) + ([1] if p["B"] else [])
            ins = 0.2 * min(p["x2"] - p["x1"], p["y2"] - p["y1"])
            ix1, iy1 = cell(p["x1"] + ins, p["y1"] + ins)
            ix2, iy2 = cell(p["x2"] - ins, p["y2"] - ins)
            cx, cy = cell(p["cx"], p["cy"])
            out = []
            for li in layers:
                lname = "F.Cu" if li == 0 else "B.Cu"
                got = False
                for ix in range(max(0, ix1), min(W - 1, ix2) + 1):
                    for iy in range(max(0, iy1), min(H - 1, iy2) + 1):
                        if not free_only or not blocked(maps, "trk", lname,
                                                        ix, iy):
                            out.append((li, ix, iy))
                            got = True
                if not got:  # fully blocked by neighbours: allow centre
                    out.append((li, cx, cy))
            return out

        # nodes to merge: (label, pad_or_None, island_index_or_None). An island
        # starts A* from all of its copper, so a path leaves from its cheapest
        # cell -- typically an authored stub's far tip, leaving nothing dangling.
        pad_isl = {id(p): island_of(p) for p in term_pads}
        nodes = []
        for i, isl in enumerate(islands):
            first = sorted(isl)[0]
            nodes.append((f"island@{first[1] * GRID:.1f},{first[2] * GRID:.1f}",
                          None, i))
        nodes += [(f"{p['ref']}.{p['num']}", p, None)
                  for p in term_pads if pad_isl[id(p)] is None]
        if not nodes:
            continue

        def starts_of(pad, idx):
            return sorted(islands[idx]) if idx is not None else pad_cells(pad)

        tree = set()
        merged = set()

        def absorb(idx, cells):
            if idx is not None:
                merged.add(idx)
                tree.update(islands[idx])
            tree.update(cells)

        _, pad0, idx0 = nodes.pop(0)
        absorb(idx0, [] if idx0 is not None
               else pad_cells(pad0, free_only=False))

        # Retry the stragglers while any node still makes progress: a later
        # node's copper often opens a route the tree lacked before.
        pending = nodes
        while pending:
            stuck, progress = [], False
            for node in pending:
                label, pad, idx = node
                if idx in merged:
                    continue  # an earlier path already pulled this island in
                starts = starts_of(pad, idx)
                goals = tree
                if box is not None:
                    goals = {g for g in tree
                             if box[0] <= g[1] * GRID <= box[2]
                             and box[1] <= g[2] * GRID <= box[3]}
                path = astar(maps, starts, goals, box=box)
                if path is None and box is None:
                    # the 8mm terminal-bbox clamp forbids long detours
                    path = astar(maps, starts, goals, margin_mm=1e4)
                if path is None:
                    stuck.append(node)
                    continue
                progress = True
                tr, vi = path_to_tracks(path, cname, width)
                for t in tr:
                    new_tracks.append(t)
                    for i in range(len(t[3]) - 1):
                        (x1, y1), (x2, y2) = t[3][i], t[3][i + 1]
                        segs.append((cname, t[1], width / 2, x1, y1, x2, y2))
                for v in vi:
                    new_vias.append(v)
                    vias.append(v)
                absorb(idx, [(st[0], st[1], st[2]) for st in path])
                if verbose:
                    print(f"routed {cname} -> {label} "
                          f"({len(tr)} runs, {len(vi)} vias)", flush=True)
            if not progress:
                for label, _, _ in stuck:
                    failed.append((cname, f"no path to {label}"))
                break
            pending = stuck
    return new_tracks, new_vias, failed


def main():
    check_plan_covers_nets()
    pads = load_pads()
    alias = net_alias(pads)
    # J3/J4/SW1/SW2 repeat pad numbers (USB-C dual row, switch legs, FPC
    # mounting pads): one number can mean several pads, all needing copper.
    pads_by_key = {}
    for p in pads:
        pads_by_key.setdefault((p["ref"], p["num"]), []).append(p)

    new_tracks, new_vias, failed = route_all(ROUTE_PLAN, pads, alias,
                                             pads_by_key, verbose=True)
    with open(OUT, "w") as f:
        f.write('"""Autorouted tracks (generator/route.py) - regenerate with'
                ' `make route`.\nHand-tweaks allowed: this is plain'
                ' TRACKS/VIAS data appended by pcb_layout.py."""\n\n')
        f.write("TRACKS = [\n")
        for net, layer, width, pts in new_tracks:
            f.write(f"    ({net!r}, {layer!r}, {width}, {pts!r}),\n")
        f.write("]\n\nVIAS = [\n")
        for net, x, y in new_vias:
            f.write(f"    ({net!r}, {x}, {y}),\n")
        f.write("]\n")
    print(f"\n{len(new_tracks)} track runs, {len(new_vias)} vias -> {OUT}")
    if failed:
        print("FAILED:")
        for net, why in failed:
            print(f"  {net}: {why}")
        sys.exit(1)


if __name__ == "__main__":
    main()
