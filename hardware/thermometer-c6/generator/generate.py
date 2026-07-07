#!/usr/bin/env python3
"""Generate thermometer-c6.kicad_sch (+ .kicad_pro, BOM CSV) from circuit.py
placed per layout.py.

Connectivity is computed, never drawn free-hand: circuit.py holds the net
map; layout.py holds per-component placement (zone, x, y, rotation) and
authored wire routes between pins. The generator:
  - resolves every route node ("REF.PIN" or an (x,y) waypoint) to exact
    coordinates, auto-inserting one L-bend for unaligned nodes,
  - refuses any route whose pin nodes span more than one net,
  - falls back to a wire stub + global label (or power symbol) for pins no
    route covers — cross-zone signals stay label-style like any datasheet,
  - places junction dots wherever >=3 same-net branches meet,
  - aborts on any cross-net geometric coincidence (point-on-point or
    point-on-segment): a silent KiCad net merge cannot survive generation,
and verify/ then re-checks the exported netlist against circuit.py.

Empirically derived instance transform (see git history for the probe):
symbol-space (px, py) -> sheet offset  rot0: (px, -py)   rot90: (-py, -px)
                                       rot180: (-px, py) rot270: (py, px)
"""

import csv
import os
import sys
import uuid

import sexp
import kicad_sym
from sexp import Quoted as Q

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
PROJECT_NAME = "thermometer-c6"
LOCAL_LIB = os.path.join(HERE, "symbols", "local.kicad_sym")

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
ROOT_UUID = str(uuid.uuid5(NAMESPACE, "thermometer-c6-root"))

GRID = 1.27
STUB = 3.81


def uid(key):
    return str(uuid.uuid5(NAMESPACE, "thermometer-c6/" + key))


def check_grid(v, what):
    if abs(v - round(v / GRID) * GRID) > 1e-4:
        raise SystemExit(f"OFF-GRID: {what} = {v}")
    return round(v, 4)


def xform(px, py, rot):
    if rot == 0:
        return (px, -py)
    if rot == 90:
        return (-py, -px)
    if rot == 180:
        return (-px, py)
    if rot == 270:
        return (py, px)
    raise SystemExit(f"unsupported rotation {rot}")


_DIR_VEC = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}
_VEC_DIR = {v: k for k, v in _DIR_VEC.items()}


class Placed:
    def __init__(self, comp, symbol, x, y, rot):
        self.comp = comp
        self.symbol = symbol
        self.x = x
        self.y = y
        self.rot = rot

    def pin_pos(self, number):
        p = self.symbol.pin(number)
        dx, dy = xform(p.x, p.y, self.rot)
        return (round(self.x + dx, 4), round(self.y + dy, 4))

    def pin_dir(self, number):
        """Outward (away from body) direction on the sheet, degrees
        (0=right, 90=screen-up, 180=left, 270=screen-down)."""
        p = self.symbol.pin(number)
        import math
        a = math.radians((p.angle + 180) % 360)
        vx, vy = round(math.cos(a)), round(math.sin(a))
        dx, dy = xform(vx, vy, self.rot)
        return _VEC_DIR[(round(dx), round(dy))]


def effects(size=1.27, justify=None, hide=False):
    e = ["effects", ["font", ["size", size, size]]]
    if justify:
        e.append(["justify", justify])
    if hide:
        e.append(["hide", "yes"])
    return e


# ---- text collision model --------------------------------------------------

CHAR_W = 1.05  # average glyph advance at the default 1.27 mm font


def bbox_label(text, pos, angle):
    """Approximate bounding box of a global label incl. its shape outline."""
    length = len(text) * CHAR_W + 2.8
    x, y = pos
    if angle == 0:
        return (x, y - 1.4, x + length, y + 1.4)
    if angle == 180:
        return (x - length, y - 1.4, x, y + 1.4)
    if angle == 90:
        return (x - 1.4, y - length, x + 1.4, y)
    return (x - 1.4, y, x + 1.4, y + length)


def bbox_text(text, x, y, justify=None):
    w = len(text) * CHAR_W
    if justify == "left":
        return (x, y - 1.0, x + w, y + 1.0)
    if justify == "right":
        return (x - w, y - 1.0, x, y + 1.0)
    return (x - w / 2, y - 1.0, x + w / 2, y + 1.0)


def bbox_overlap(a, b, pad=0.2):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0]
                or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def seg_bbox(a, b, half=0.15):
    return (min(a[0], b[0]) - half, min(a[1], b[1]) - half,
            max(a[0], b[0]) + half, max(a[1], b[1]) + half)


def body_bbox(pl):
    """Symbol body extent: union of pin base points (tip + length toward the
    body) and the symbol's drawn rectangles, padded for stroke width."""
    import math
    xs, ys = [], []
    for p in pl.symbol.pins:
        a = math.radians(p.angle)
        bx = p.x + p.length * math.cos(a)
        by = p.y + p.length * math.sin(a)
        dx, dy = xform(bx, by, pl.rot)
        xs.append(pl.x + dx)
        ys.append(pl.y + dy)
    for (x1, y1, x2, y2) in pl.symbol.rects:
        for cx_, cy_ in ((x1, y1), (x2, y2)):
            dx, dy = xform(cx_, cy_, pl.rot)
            xs.append(pl.x + dx)
            ys.append(pl.y + dy)
    if not xs:
        xs, ys = [pl.x], [pl.y]
    return (min(xs) - 1.4, min(ys) - 1.4, max(xs) + 1.4, max(ys) + 1.4)


def build_schematic(circuit, layout):
    comps = circuit.COMPONENTS
    nets = circuit.NETS
    nc = set((r, str(p)) for r, p in circuit.NC)
    power_syms = circuit.POWER_SYMBOLS

    symbols = {}
    for c in comps:
        if c["lib_id"] not in symbols:
            symbols[c["lib_id"]] = kicad_sym.load_symbol(c["lib_id"], LOCAL_LIB)
    for lib_id in set(power_syms.values()) | {"power:PWR_FLAG"}:
        symbols[lib_id] = kicad_sym.load_symbol(lib_id, LOCAL_LIB)

    by_ref = {c["ref"]: c for c in comps}
    if len(by_ref) != len(comps):
        raise SystemExit("duplicate references in COMPONENTS")

    # ---- pin -> net coverage bookkeeping --------------------------------
    net_of_pin = {}
    for name, pins in nets.items():
        if len(pins) < 2:
            raise SystemExit(f"net {name} has fewer than 2 pins")
        for ref, pin in pins:
            key = (ref, str(pin))
            if key in net_of_pin:
                raise SystemExit(f"pin {key} in two nets")
            net_of_pin[key] = name
    for key in nc:
        if key in net_of_pin:
            raise SystemExit(f"pin {key} both in net and NC")
        net_of_pin[key] = None

    have = set()
    for c in comps:
        for p in symbols[c["lib_id"]].pins:
            have.add((c["ref"], p.number))
    missing = set(net_of_pin) - have
    uncovered = have - set(net_of_pin)
    if missing:
        raise SystemExit(f"nets reference nonexistent pins: {sorted(missing)}")
    if uncovered:
        raise SystemExit(f"pins not assigned to any net or NC: {sorted(uncovered)}")

    # ---- placement -------------------------------------------------------
    placed = {}
    unplaced = [c["ref"] for c in comps if c["ref"] not in layout.PLACE]
    if unplaced:
        raise SystemExit(f"components missing from layout.PLACE: {unplaced}")
    for ref, (zone, rx, ry, rot) in layout.PLACE.items():
        if ref not in by_ref:
            raise SystemExit(f"layout.PLACE has unknown ref {ref}")
        ox, oy = layout.ZONES[zone]["origin"]
        x = check_grid(ox + rx, f"{ref} x")
        y = check_grid(oy + ry, f"{ref} y")
        placed[ref] = Placed(by_ref[ref], symbols[by_ref[ref]["lib_id"]], x, y, rot)

    # ---- authored wires --------------------------------------------------
    # route node: "REF.PIN" | (x, y) zone-relative waypoint
    wire_segments = []  # (net, p1, p2)
    routed_pins = set()

    def resolve(node, zone):
        if isinstance(node, str):
            ref, _, pin = node.partition(".")
            if ref not in placed:
                raise SystemExit(f"route references unknown component {ref}")
            return placed[ref].pin_pos(pin), (ref, pin)
        ox, oy = layout.ZONES[zone]["origin"]
        return (check_grid(ox + node[0], "wp x"), check_grid(oy + node[1], "wp y")), None

    for zone, route in layout.WIRES:
        pts = []
        pin_nets = set()
        for node in route:
            pos, pinkey = resolve(node, zone)
            if pinkey:
                if pinkey not in net_of_pin:
                    raise SystemExit(f"route pin {pinkey} unknown")
                pin_nets.add(net_of_pin[pinkey])
                routed_pins.add(pinkey)
            pts.append(pos)
        if len(pin_nets) != 1 or None in pin_nets:
            raise SystemExit(f"route {route} spans nets {pin_nets}")
        net = pin_nets.pop()
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            if a[0] != b[0] and a[1] != b[1]:
                corner = (b[0], a[1])  # horizontal, then vertical
                wire_segments.append((net, a, corner))
                wire_segments.append((net, corner, b))
            else:
                wire_segments.append((net, a, b))

    # coverage by coordinate: stacked pins (MINI-1 GND, USB VBUS pairs) are
    # covered when any pin at the same point is routed
    routed_points = {}
    for ref, pin in routed_pins:
        routed_points.setdefault(placed[ref].pin_pos(pin), set()).add(net_of_pin[(ref, pin)])
    for (ref, pin), net in net_of_pin.items():
        if net is None or (ref, pin) in routed_pins:
            continue
        pos = placed[ref].pin_pos(pin)
        if pos in routed_points:
            if net not in routed_points[pos]:
                raise SystemExit(f"stacked pin {ref}.{pin} at {pos} belongs to "
                                 f"{net} but point is routed as {routed_points[pos]}")
            routed_pins.add((ref, pin))

    # ---- authored power symbols and labels -------------------------------
    power_placements = []  # (lib_id, net, pos, rot)
    for entry in layout.POWER:
        zone, net, rx, ry = entry[:4]
        rot = entry[4] if len(entry) > 4 else 0
        ox, oy = layout.ZONES[zone]["origin"]
        pos = (check_grid(ox + rx, "pwr x"), check_grid(oy + ry, "pwr y"))
        lib_id = power_syms.get(net)
        if lib_id is None:
            raise SystemExit(f"POWER entry for net {net} has no power symbol mapping")
        power_placements.append((lib_id, net, pos, rot))

    label_placements = []  # (net, pos, angle)
    for zone, net, rx, ry, angle in layout.LABELS:
        ox, oy = layout.ZONES[zone]["origin"]
        pos = (check_grid(ox + rx, "lbl x"), check_grid(oy + ry, "lbl y"))
        if net not in nets:
            raise SystemExit(f"LABELS references unknown net {net}")
        label_placements.append((net, pos, angle))

    # ---- fallback stubs for unrouted pins ---------------------------------
    # nets named "~..." are anonymous (KiCad auto-names them; check_netlist
    # matches them by pin set) — they may not fall back, since the fallback
    # label would leak the "~" name onto the sheet.
    fallback = []  # (net, tip, end, dir)
    seen_fb = set()
    for name, pins in sorted(nets.items()):
        for ref, pin in pins:
            pin = str(pin)
            if (ref, pin) in routed_pins:
                continue
            if name.startswith("~"):
                raise SystemExit(f"anonymous net {name} has unrouted pin {ref}.{pin}")
            pl = placed[ref]
            tip = pl.pin_pos(pin)
            if (name, tip) in seen_fb:
                continue  # stacked pins (module GND, USB VBUS pairs): one stub
            seen_fb.add((name, tip))
            d = pl.pin_dir(pin)
            vx, vy = _DIR_VEC[d]
            end = (round(tip[0] + vx * STUB, 4), round(tip[1] + vy * STUB, 4))
            fallback.append((name, tip, end, d))
            wire_segments.append((name, tip, end))

    # ---- validation: power/label anchors must touch their net -------------
    def on_net_geometry(net, pos):
        for n, a, b in wire_segments:
            if n != net:
                continue
            if min(a[0], b[0]) - 1e-6 <= pos[0] <= max(a[0], b[0]) + 1e-6 and \
               min(a[1], b[1]) - 1e-6 <= pos[1] <= max(a[1], b[1]) + 1e-6 and \
               (a[0] == b[0] == pos[0] or a[1] == b[1] == pos[1] or pos in (a, b)):
                return True
        return False

    for lib_id, net, pos, rot in power_placements:
        if not on_net_geometry(net, pos):
            raise SystemExit(f"power symbol {net} at {pos} touches no {net} wire")
    for net, pos, angle in label_placements:
        if not on_net_geometry(net, pos):
            raise SystemExit(f"label {net} at {pos} touches no {net} wire")

    # every named net must carry at least one name source (label or power
    # symbol); anonymous "~" nets are named by KiCad automatically
    named = {net for _, net, _, _ in power_placements}
    named |= {net for net, _, _ in label_placements}
    named |= {f for f, _, _, d in fallback}
    for name in nets:
        if name not in named and not name.startswith("~"):
            raise SystemExit(f"net {name} has no label or power symbol anywhere")

    # ---- collision check ---------------------------------------------------
    net_points = {}

    def add_point(net, p):
        net_points.setdefault(p, set()).add(net)

    for net, a, b in wire_segments:
        add_point(net, a)
        add_point(net, b)
    for (ref, pin), net in net_of_pin.items():
        add_point(net if net else f"<NC {ref}.{pin}>", placed[ref].pin_pos(pin))

    merges = []
    for p, names in net_points.items():
        if len(names) > 1:
            merges.append(f"point {p} shared by nets {sorted(names)}")
    for net, a, b in wire_segments:
        (x1, y1), (x2, y2) = a, b
        for q, qnames in net_points.items():
            if q == a or q == b:
                continue
            for qn in qnames:
                if qn == net:
                    continue
                qx, qy = q
                if x1 == x2 == qx and min(y1, y2) - 1e-6 < qy < max(y1, y2) + 1e-6:
                    merges.append(f"net {qn} point {q} lies on {net} wire {a}-{b}")
                elif y1 == y2 == qy and min(x1, x2) - 1e-6 < qx < max(x1, x2) + 1e-6:
                    merges.append(f"net {qn} point {q} lies on {net} wire {a}-{b}")
    if merges:
        raise SystemExit("GEOMETRIC NET MERGES:\n  " + "\n  ".join(sorted(set(merges))))

    # ---- junctions ---------------------------------------------------------
    # authored power-symbol pins count as branches too: a pin lying
    # mid-segment only connects in KiCad when a junction dot is present
    for lib_id, net, pos, rot in power_placements:
        add_point(net, pos)
    junctions = set()
    for p, names in net_points.items():
        net = next(iter(names))
        branches = 0
        for n, a, b in wire_segments:
            if n != net:
                continue
            if p == a or p == b:
                branches += 1
            elif (a[0] == b[0] == p[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1])) or \
                 (a[1] == b[1] == p[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0])):
                branches += 2
        # pins at this point add branches too
        pin_count = 0
        for (ref, pin), n in net_of_pin.items():
            if n == net and placed[ref].pin_pos(str(pin)) == p:
                pin_count = 1  # stacked pins count once
                break
        if not pin_count:
            for lib_id, n_, pos, rot in power_placements:
                if n_ == net and pos == p:
                    pin_count = 1
                    break
        branches += pin_count
        if branches >= 3:
            junctions.add(p)

    # ---- field autoplacement (Reference/Value) ------------------------------
    # Greedy collision-aware placement: try above / right / below / left of
    # each symbol body, scored against wires, bodies, labels, power symbols
    # and previously placed fields. First zero-collision candidate wins.
    obstacles = []
    for net_, a_, b_ in wire_segments:
        obstacles.append(seg_bbox(a_, b_))
    bodies = {}
    for ref_, pl_ in placed.items():
        bodies[ref_] = body_bbox(pl_)
        obstacles.append(bodies[ref_])
    # zone titles are 2.54mm text — keep fields out of the title band
    for z_, zdef_ in layout.ZONES.items():
        ox_, oy_ = zdef_["origin"]
        obstacles.append((ox_ + 1.27, oy_ + 1.5, ox_ + 1.27 + len(z_) * 2.1, oy_ + 5.5))
    # pin number/name texts render along the pin outside the body outline —
    # keep fields away from the pin stems of multi-pin parts (passives hide
    # their pin numbers, so only >=3-pin symbols need this)
    import math as _math
    for ref_, pl_ in placed.items():
        if len(pl_.symbol.pins) < 3:
            continue
        for p_ in pl_.symbol.pins:
            a_ = _math.radians(p_.angle)
            bx_ = p_.x + (p_.length + 0.5) * _math.cos(a_)
            by_ = p_.y + (p_.length + 0.5) * _math.sin(a_)
            dx1, dy1 = xform(p_.x, p_.y, pl_.rot)
            dx2, dy2 = xform(bx_, by_, pl_.rot)
            x1_, y1_ = pl_.x + dx1, pl_.y + dy1
            x2_, y2_ = pl_.x + dx2, pl_.y + dy2
            obstacles.append((min(x1_, x2_) - 1.3, min(y1_, y2_) - 1.3,
                              max(x1_, x2_) + 1.3, max(y1_, y2_) + 1.3))
    label_boxes = []  # (net, bbox)
    for net_, tip_, end_, d_ in fallback:
        if net_ in power_syms:
            obstacles.append((end_[0] - 2.0, end_[1] - 6.0, end_[0] + 2.0, end_[1] + 6.0))
        else:
            label_boxes.append((net_, bbox_label(net_, end_, d_)))
    for net_, pos_, angle_ in label_placements:
        label_boxes.append((net_, bbox_label(net_, pos_, angle_)))
    for lib_id_, net_, pos_, rot_ in power_placements:
        obstacles.append((pos_[0] - 2.0, pos_[1] - 6.0, pos_[0] + 2.0, pos_[1] + 6.0))
    obstacles.extend(b for _, b in label_boxes)

    field_layout = {}
    for c in comps:
        ref = c["ref"]
        # test points hide their Value (it would duplicate the adjacent net
        # label); only the Reference needs a spot
        tp_only = c["lib_id"] == "Connector:TestPoint"
        bx1, by1, bx2, by2 = bodies[ref]
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        cands = [
            ((cx, by1 - 3.5, None), (cx, by1 - 1.3, None)),          # above
            ((bx2 + 0.8, cy - 1.2, "left"), (bx2 + 0.8, cy + 1.2, "left")),   # right
            ((cx, by2 + 1.3, None), (cx, by2 + 3.5, None)),          # below
            ((bx1 - 0.8, cy - 1.2, "right"), (bx1 - 0.8, cy + 1.2, "right")),  # left
            # far variants clear one wire/text lane beyond the near spots
            ((cx, by1 - 6.0, None), (cx, by1 - 3.8, None)),          # above-far
            ((cx, by2 + 3.8, None), (cx, by2 + 6.0, None)),          # below-far
            ((bx2 + 0.8, cy - 3.7, "left"), (bx2 + 0.8, cy - 1.3, "left")),   # right-high
            ((bx2 + 0.8, cy + 1.3, "left"), (bx2 + 0.8, cy + 3.7, "left")),   # right-low
            ((cx, by1 - 8.5, None), (cx, by1 - 6.3, None)),          # above-far2
            ((cx, by2 + 6.3, None), (cx, by2 + 8.5, None)),          # below-far2
            # diagonal quadrants — free space often lives in the corners
            ((bx1 - 0.8, by1 - 3.5, "right"), (bx1 - 0.8, by1 - 1.3, "right")),
            ((bx2 + 0.8, by1 - 3.5, "left"), (bx2 + 0.8, by1 - 1.3, "left")),
            ((bx1 - 0.8, by2 + 1.3, "right"), (bx1 - 0.8, by2 + 3.5, "right")),
            ((bx2 + 0.8, by2 + 1.3, "left"), (bx2 + 0.8, by2 + 3.5, "left")),
        ]
        if ref in layout.FIELD_POS:
            (orx, ory, orj), (ovx, ovy, ovj) = layout.FIELD_POS[ref]
            pl_ = placed[ref]
            cands.insert(0, ((pl_.x + orx, pl_.y + ory, orj),
                             (pl_.x + ovx, pl_.y + ovy, ovj)))
        best, best_score = None, None
        for cand in cands:
            (rx, ry, rj), (vx, vy, vj) = cand
            boxes = [bbox_text(ref, rx, ry, rj)]
            if not tp_only:
                boxes.append(bbox_text(c["value"], vx, vy, vj))
            score = 0
            for tb in boxes:
                for ob in obstacles:
                    if ob is bodies[ref]:
                        continue
                    if bbox_overlap(tb, ob):
                        score += 1
            if best_score is None or score < best_score:
                best, best_score = cand, score
            if score == 0:
                break
        field_layout[ref] = best
        (rx, ry, rj), (vx, vy, vj) = best
        obstacles.append(bbox_text(ref, rx, ry, rj))
        if not tp_only:
            obstacles.append(bbox_text(c["value"], vx, vy, vj))

    # ---- readability warnings (non-fatal) -----------------------------------
    warns = []
    def _on_seg(q, a, b):
        return (min(a[0], b[0]) - 1e-6 <= q[0] <= max(a[0], b[0]) + 1e-6
                and min(a[1], b[1]) - 1e-6 <= q[1] <= max(a[1], b[1]) + 1e-6
                and (a[0] == b[0] == q[0] or a[1] == b[1] == q[1]))

    for net_, a_, b_ in wire_segments:
        sb = seg_bbox(a_, b_, 0.05)
        for ref_, bb in bodies.items():
            own = any(_on_seg(placed[ref_].pin_pos(p.number), a_, b_)
                      for p in placed[ref_].symbol.pins)
            if own:
                continue
            inner = (bb[0] + 1.2, bb[1] + 1.2, bb[2] - 1.2, bb[3] - 1.2)
            if inner[0] < inner[2] and inner[1] < inner[3] and bbox_overlap(sb, inner, 0):
                warns.append(f"wire {net_} {a_}-{b_} crosses body of {ref_}")
    for lnet, lb in label_boxes:
        for ref_, bb in bodies.items():
            inner = (bb[0] + 1.0, bb[1] + 1.0, bb[2] - 1.0, bb[3] - 1.0)
            if inner[0] < inner[2] and inner[1] < inner[3] and bbox_overlap(lb, inner, 0):
                warns.append(f"label {lnet} overlaps body of {ref_}")
    if warns:
        print(f"LAYOUT WARNINGS ({len(set(warns))}):")
        for w in sorted(set(warns)):
            print("  " + w)

    # ---- emit --------------------------------------------------------------
    sch = ["kicad_sch",
           ["version", 20231120],
           ["generator", Q("thermometer-c6-generate")],
           ["uuid", Q(ROOT_UUID)],
           ["paper", Q("A2")],
           ["title_block",
            ["title", Q("ESP32-C6 Ultra-Low-Power E-Paper Thermometer")],
            ["rev", Q("A")],
            ["comment", 1, Q("Universal 24-pin Good Display EPD, gated booster, RESE 0.47/2.2/3 solder-select")],
            ["comment", 2, Q("LDO power tree (buck-cliff avoidance), load-sharing USB-C, high-side switched battery divider")],
            ["comment", 3, Q("Generated by generator/generate.py from circuit.py + layout.py - do not edit by hand")]]]

    lib_block = ["lib_symbols"]
    for lib_id in sorted(symbols):
        lib_block.append(symbols[lib_id].node)
    sch.append(lib_block)

    body = []
    seg_seen = {}
    for net, a, b in wire_segments:
        k = f"{net}/{a}/{b}"
        seg_seen[k] = seg_seen.get(k, 0) + 1
        if seg_seen[k] > 1:
            k += f"/{seg_seen[k]}"
        body.append(["wire", ["pts", ["xy", a[0], a[1]], ["xy", b[0], b[1]]],
                     ["stroke", ["width", 0], ["type", "default"]],
                     ["uuid", Q(uid("wire/" + k))]])
    for p in sorted(junctions):
        body.append(["junction", ["at", p[0], p[1]], ["diameter", 0],
                     ["color", 0, 0, 0, 0], ["uuid", Q(uid(f"junc/{p}"))]])
    for ref, pin in sorted(nc):
        pos = placed[ref].pin_pos(pin)
        body.append(["no_connect", ["at", pos[0], pos[1]],
                     ["uuid", Q(uid(f"nc/{ref}.{pin}"))]])

    just_of = {0: "left", 90: "left", 180: "right", 270: "right"}
    for net, tip, end, d in fallback:
        if net in power_syms:
            # GND graphic hangs below its anchor, others point up: flip when
            # the stub arrives from the wrong side
            if net == "GND":
                rot = 180 if d == 90 else 0
            else:
                rot = 180 if d == 270 else 0
            power_placements.append((power_syms[net], net, end, rot))
        else:
            body.append(["global_label", Q(net), ["shape", "input"],
                         ["at", end[0], end[1], d],
                         effects(justify=just_of[d]),
                         ["uuid", Q(uid(f"label/{net}/{tip}"))]])
    for net, pos, angle in label_placements:
        body.append(["global_label", Q(net), ["shape", "input"],
                     ["at", pos[0], pos[1], angle],
                     effects(justify=just_of[angle]),
                     ["uuid", Q(uid(f"albl/{net}/{pos}"))]])

    pwr_seq = [0]
    for lib_id, net, pos, rot in power_placements:
        s = symbols[lib_id]
        ppin = s.pins[0]
        dx, dy = xform(ppin.x, ppin.y, rot)
        px, py = round(pos[0] - dx, 4), round(pos[1] - dy, 4)
        pwr_seq[0] += 1
        pref = ("#FLG%03d" if lib_id == "power:PWR_FLAG" else "#PWR%03d") % pwr_seq[0]
        key = f"{net}/{pos}"
        # value text sits past the symbol graphic: GND's graphic hangs below
        # its pin (value below), the others point up (value above) — flipped
        # by rotation
        below = (net == "GND") == (rot == 0)
        vdy = 4.4 if below else -4.4
        body.append(["symbol", ["lib_id", Q(lib_id)], ["at", px, py, rot], ["unit", 1],
                     ["exclude_from_sim", "no"], ["in_bom", "no"], ["on_board", "yes"],
                     ["dnp", "no"], ["uuid", Q(uid("pwr/" + key))],
                     ["property", Q("Reference"), Q(pref), ["at", px, py, 0], effects(hide=True)],
                     ["property", Q("Value"), Q(net), ["at", px, round(py + vdy, 4), 0], effects()],
                     ["property", Q("Footprint"), Q(""), ["at", px, py, 0], effects(hide=True)],
                     ["property", Q("Datasheet"), Q(""), ["at", px, py, 0], effects(hide=True)],
                     ["pin", Q(ppin.number), ["uuid", Q(uid("pwrpin/" + key))]],
                     ["instances", ["project", Q(PROJECT_NAME),
                                    ["path", Q("/" + ROOT_UUID),
                                     ["reference", Q(pref)], ["unit", 1]]]]])

    # PWR_FLAGs: one per declared net, attached at the first fallback/authored
    # point of that net
    flagged = set()
    for net in sorted(circuit.PWR_FLAG_NETS):
        pos = None
        for l_, n_, p_, r_ in power_placements:
            if n_ == net:
                pos = p_
                break
        if pos is None:
            for n_, tip, end, d in fallback:
                if n_ == net:
                    pos = end
                    break
        if pos is None:
            for n_, a, b in wire_segments:
                if n_ == net:
                    pos = a
                    break
        if pos is None:
            raise SystemExit(f"PWR_FLAG net {net} has no attachment point")
        if net in flagged:
            continue
        flagged.add(net)
        s = symbols["power:PWR_FLAG"]
        ppin = s.pins[0]
        px, py = round(pos[0] - ppin.x, 4), round(pos[1] + ppin.y, 4)
        pwr_seq[0] += 1
        pref = "#FLG%03d" % pwr_seq[0]
        body.append(["symbol", ["lib_id", Q("power:PWR_FLAG")], ["at", px, py, 0], ["unit", 1],
                     ["exclude_from_sim", "no"], ["in_bom", "no"], ["on_board", "yes"],
                     ["dnp", "no"], ["uuid", Q(uid("flag/" + net))],
                     ["property", Q("Reference"), Q(pref), ["at", px, py, 0], effects(hide=True)],
                     ["property", Q("Value"), Q("PWR_FLAG"), ["at", px, py - 2, 0], effects(hide=True)],
                     ["property", Q("Footprint"), Q(""), ["at", px, py, 0], effects(hide=True)],
                     ["property", Q("Datasheet"), Q(""), ["at", px, py, 0], effects(hide=True)],
                     ["pin", Q(ppin.number), ["uuid", Q(uid("flagpin/" + net))]],
                     ["instances", ["project", Q(PROJECT_NAME),
                                    ["path", Q("/" + ROOT_UUID),
                                     ["reference", Q(pref)], ["unit", 1]]]]])

    # component instances
    for c in comps:
        pl = placed[c["ref"]]
        s = symbols[c["lib_id"]]
        x, y, rot = pl.x, pl.y, pl.rot
        (rx, ry, rj), (vx_, vy_, vj) = field_layout[c["ref"]]
        # property text renders at symbol_rotation + property_angle, so
        # counter-rotate 90/270 instances to keep fields horizontal (180 is
        # already normalized to readable by KiCad — counter-rotating it
        # would double-flip the text upside down). At effective 180 KiCad
        # mirrors the justification while normalizing, so swap it to get the
        # placement the autoplacer scored.
        pa = (360 - rot) % 360 if rot in (90, 270) else 0
        swap = {"left": "right", "right": "left", None: None}
        hide_value = c["lib_id"] == "Connector:TestPoint"
        node = ["symbol", ["lib_id", Q(c["lib_id"])], ["at", x, y, rot], ["unit", 1],
                ["exclude_from_sim", "no"],
                ["in_bom", "no" if c.get("dnp") else "yes"], ["on_board", "yes"],
                ["dnp", "yes" if c.get("dnp") else "no"],
                ["uuid", Q(uid("sym/" + c["ref"]))],
                ["property", Q("Reference"), Q(c["ref"]),
                 ["at", round(rx, 4), round(ry, 4), pa],
                 effects(justify=swap[rj] if rot == 180 else rj)],
                ["property", Q("Value"), Q(c["value"]),
                 ["at", round(vx_, 4), round(vy_, 4), pa],
                 effects(justify=swap[vj] if rot == 180 else vj,
                         hide=hide_value)],
                ["property", Q("Footprint"), Q(c.get("footprint", "")),
                 ["at", x, y, 0], effects(hide=True)],
                ["property", Q("Datasheet"), Q(c.get("datasheet", "~")),
                 ["at", x, y, 0], effects(hide=True)],
                ["property", Q("LCSC"), Q(c.get("lcsc", "")),
                 ["at", x, y, 0], effects(hide=True)]]
        for p in s.pins:
            node.append(["pin", Q(p.number), ["uuid", Q(uid(f"pin/{c['ref']}.{p.number}"))]])
        node.append(["instances", ["project", Q(PROJECT_NAME),
                                   ["path", Q("/" + ROOT_UUID),
                                    ["reference", Q(c["ref"])], ["unit", 1]]]])
        body.append(node)

    # zone titles + boxes
    for z, zdef in layout.ZONES.items():
        ox, oy = zdef["origin"]
        w, h = zdef["size"]
        body.append(["text", Q(z), ["exclude_from_sim", "no"],
                     ["at", round(ox + 1.27, 4), round(oy + 3.5, 4), 0],
                     effects(size=2.54, justify="left"),
                     ["uuid", Q(uid("ztext/" + z))]])
        body.append(["rectangle", ["start", round(ox, 4), round(oy, 4)],
                     ["end", round(ox + w, 4), round(oy + h, 4)],
                     ["stroke", ["width", 0.1], ["type", "dash"]],
                     ["fill", ["type", "none"]],
                     ["uuid", Q(uid("zbox/" + z))]])

    sch.extend(body)
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    return sch


def _top_of(symbol, rot):
    ys = []
    for p in symbol.pins:
        _, dy = xform(p.x, p.y, rot)
        ys.append(-dy)
    return max(ys, default=0)


def write_project():
    pro_path = os.path.join(PROJECT_DIR, PROJECT_NAME + ".kicad_pro")
    if not os.path.exists(pro_path):
        with open(pro_path, "w") as f:
            f.write('{\n  "meta": { "filename": "%s.kicad_pro", "version": 3 },\n'
                    '  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] }\n}\n'
                    % PROJECT_NAME)


def write_bom(circuit):
    path = os.path.join(PROJECT_DIR, "bom", PROJECT_NAME + "-bom.csv")
    rows = {}
    for c in circuit.COMPONENTS:
        # skip DNP and copper-only parts (test points, solder jumpers)
        if c.get("dnp") or not c.get("footprint") or not c.get("lcsc"):
            continue
        key = (c["value"], c["footprint"], c.get("lcsc", ""))
        rows.setdefault(key, []).append(c["ref"])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, footprint, lcsc), refs in sorted(rows.items(), key=lambda kv: kv[1][0]):
            w.writerow([value, ",".join(sorted(refs)), footprint, lcsc])


def main():
    sys.path.insert(0, HERE)
    import circuit
    import layout
    sch = build_schematic(circuit, layout)
    out = os.path.join(PROJECT_DIR, PROJECT_NAME + ".kicad_sch")
    with open(out, "w") as f:
        f.write(sexp.dumps(sch))
    write_project()
    write_bom(circuit)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
