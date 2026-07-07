#!/usr/bin/env python3
"""Generate thermometer-c6.kicad_sch (+ .kicad_pro, BOM CSV) from circuit.py.

Connectivity is computed, never drawn: every pin of every component either
appears in exactly one net (rendered as a wire stub + global label / power
symbol placed at the pin's exact connection point) or in the NC list
(rendered as a no_connect marker). The generator aborts on any pin left over
or any net referencing a nonexistent pin. All symbol instances are placed at
rotation 0, unmirrored, so pin transforms are exact by construction:
sheet = (origin_x + pin_x, origin_y - pin_y).
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

GRID = 1.27  # mil50 grid
STUB = 3.81  # wire stub length from pin, mm


def uid(key):
    return str(uuid.uuid5(NAMESPACE, "thermometer-c6/" + key))


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def check_grid(v, what):
    if abs(v - round(v / GRID) * GRID) > 1e-4:
        raise SystemExit(f"OFF-GRID: {what} = {v}")
    return round(v, 4)


class Placed:
    def __init__(self, comp, symbol, x, y):
        self.comp = comp
        self.symbol = symbol
        self.x = x
        self.y = y

    def pin_pos(self, number):
        p = self.symbol.pin(number)
        return (round(self.x + p.x, 4), round(self.y - p.y, 4))

    def pin_dir(self, number):
        """Outward direction (away from body) in sheet space, degrees
        (0=right, 90=screen-up, 180=left, 270=screen-down).

        Symbol-space pin angle a points from the connection tip toward the
        body; outward is a+180. The Y flip into sheet space negates the sine
        component, and with this dict convention (90 -> -y) the outward
        vector (cos(a+180), -sin(a+180)) is exactly the vector of sheet
        angle a+180. (Using 180-a instead coincides for horizontal pins but
        inverts vertical ones — the probe only had horizontal-pin ICs, so
        the collision checker is what caught it.)
        """
        p = self.symbol.pin(number)
        return (p.angle + 180) % 360


def effects(size=1.27, justify=None, hide=False):
    e = ["effects", ["font", ["size", size, size]]]
    if justify:
        e.append(["justify", justify])
    if hide:
        e.append(["hide", "yes"])
    return e


def build_schematic(circuit):
    comps = circuit.COMPONENTS
    nets = circuit.NETS
    nc = set(circuit.NC)
    power_syms = circuit.POWER_SYMBOLS  # net -> power lib_id

    # ---- load symbols -------------------------------------------------
    symbols = {}
    for c in comps:
        if c["lib_id"] not in symbols:
            symbols[c["lib_id"]] = kicad_sym.load_symbol(c["lib_id"], LOCAL_LIB)
    for lib_id in set(power_syms.values()) | {"power:PWR_FLAG"}:
        symbols[lib_id] = kicad_sym.load_symbol(lib_id, LOCAL_LIB)

    by_ref = {c["ref"]: c for c in comps}
    if len(by_ref) != len(comps):
        raise SystemExit("duplicate references in COMPONENTS")

    # ---- coverage check: every pin in exactly one net or NC -----------
    want = {}
    for name, pins in nets.items():
        if len(pins) < 2:
            raise SystemExit(f"net {name} has fewer than 2 pins")
        for ref, pin in pins:
            key = (ref, str(pin))
            if key in want:
                raise SystemExit(f"pin {key} in nets {want[key]} and {name}")
            want[key] = name
    for key in nc:
        key = (key[0], str(key[1]))
        if key in want:
            raise SystemExit(f"pin {key} both in net {want[key]} and NC")
        want[key] = None

    have = set()
    for c in comps:
        for p in symbols[c["lib_id"]].pins:
            have.add((c["ref"], p.number))
    want_keys = set(want)
    missing = want_keys - have
    uncovered = have - want_keys
    if missing:
        raise SystemExit(f"nets reference nonexistent pins: {sorted(missing)}")
    if uncovered:
        raise SystemExit(f"pins not assigned to any net or NC: {sorted(uncovered)}")

    # ---- placement -----------------------------------------------------
    # Zones laid out on a coarse grid; components within a zone flow in rows.
    placed = {}
    zone_boxes = {}
    sheet_w = 900.0
    margin = 20.0
    cursor_x, cursor_y = margin, margin
    row_h = 0.0

    zones = []
    for c in comps:
        if c["zone"] not in zones:
            zones.append(c["zone"])

    zone_origin = {}
    zx, zy = margin, margin
    zone_col_h = 0.0
    for z in zones:
        zcomps = [c for c in comps if c["zone"] == z]
        # estimate zone size from symbol bounding boxes
        boxes = []
        for c in zcomps:
            s = symbols[c["lib_id"]]
            xs = [p.x for p in s.pins] or [0]
            ys = [p.y for p in s.pins] or [0]
            w = max(xs) - min(xs) + 2 * STUB + 26
            h = max(ys) - min(ys) + 2 * STUB + 16
            boxes.append((c, w, h, -min(xs), max(ys)))
        # flow rows inside the zone, max zone width 240
        zone_w_max = 250.0
        cx, cy = 0.0, 8.0
        rh = 0.0
        zone_w = 0.0
        for c, w, h, offx, offy in boxes:
            if cx + w > zone_w_max and cx > 0:
                cx = 0.0
                cy += rh
                rh = 0.0
            c["_rel"] = (cx + offx + STUB + 10, cy + offy + STUB + 8)
            cx += w
            rh = max(rh, h)
            zone_w = max(zone_w, cx)
        zone_h = cy + rh + 6
        if zx + zone_w > sheet_w - margin and zx > margin:
            zx = margin
            zy += zone_col_h + 14
            zone_col_h = 0.0
        zone_origin[z] = (zx, zy)
        zone_boxes[z] = (zx - 4, zy - 2, zx + zone_w + 4, zy + zone_h + 2)
        zx += zone_w + 16
        zone_col_h = max(zone_col_h, zone_h)

    for c in comps:
        ox, oy = zone_origin[c["zone"]]
        rx, ry = c.pop("_rel")
        placed[c["ref"]] = Placed(c, symbols[c["lib_id"]],
                                  snap(ox + rx), snap(oy + ry))

    # ---- emit ----------------------------------------------------------
    sch = ["kicad_sch",
           ["version", 20231120],
           ["generator", Q("thermometer-c6-generate")],
           ["uuid", Q(ROOT_UUID)],
           ["paper", Q("A1")],
           ["title_block",
            ["title", Q("ESP32-C6 Ultra-Low-Power E-Paper Thermometer")],
            ["rev", Q("A")],
            ["company", Q("")],
            ["comment", 1, Q("Universal 24-pin Good Display EPD, gated booster, RESE 0.47/2.2/3 solder-select")],
            ["comment", 2, Q("LDO power tree (buck-cliff avoidance), load-sharing USB-C, high-side switched battery divider")],
            ["comment", 3, Q("Generated by generator/generate.py from circuit.py - do not edit by hand")]]]

    lib_block = ["lib_symbols"]
    for lib_id in sorted(symbols):
        lib_block.append(symbols[lib_id].node)
    sch.append(lib_block)

    wires = []
    labels = []
    noconnects = []
    extra_syms = []

    def emit_wire(p1, p2, key):
        wires.append(["wire", ["pts", ["xy", p1[0], p1[1]], ["xy", p2[0], p2[1]]],
                      ["stroke", ["width", 0], ["type", "default"]],
                      ["uuid", Q(uid("wire/" + key))]])

    pwr_seq = [0]

    def emit_power(lib_id, net, pos, key):
        s = symbols[lib_id]
        ppin = s.pins[0]
        pwr_seq[0] += 1
        pref = "#FLG%03d" % pwr_seq[0] if lib_id == "power:PWR_FLAG" \
            else "#PWR%03d" % pwr_seq[0]
        # place so the power pin's connection point lands exactly on pos
        px, py = pos[0] - ppin.x, pos[1] + ppin.y
        node = ["symbol", ["lib_id", Q(lib_id)], ["at", px, py, 0], ["unit", 1],
                ["exclude_from_sim", "no"], ["in_bom", "no"], ["on_board", "yes"],
                ["dnp", "no"], ["uuid", Q(uid("pwr/" + key))],
                ["property", Q("Reference"), Q(pref),
                 ["at", px, py, 0], effects(hide=True)],
                ["property", Q("Value"), Q(net), ["at", px, py + 3.5, 0], effects()],
                ["property", Q("Footprint"), Q(""), ["at", px, py, 0], effects(hide=True)],
                ["property", Q("Datasheet"), Q(""), ["at", px, py, 0], effects(hide=True)],
                ["pin", Q(ppin.number), ["uuid", Q(uid("pwrpin/" + key))]],
                ["instances", ["project", Q(PROJECT_NAME),
                               ["path", Q("/" + ROOT_UUID),
                                ["reference", Q(pref)],
                                ["unit", 1]]]]]
        extra_syms.append(node)

    def emit_label(net, pos, angle, key):
        justify = {0: "left", 90: "left", 180: "right", 270: "right"}[angle]
        labels.append(["global_label", Q(net), ["shape", "input"],
                       ["at", pos[0], pos[1], angle],
                       effects(justify=justify),
                       ["uuid", Q(uid("label/" + key))]])

    pwr_flagged = set()
    for name, pins in sorted(nets.items()):
        for ref, pin in pins:
            pin = str(pin)
            pl = placed[ref]
            tip = pl.pin_pos(pin)
            d = pl.pin_dir(pin)
            dx, dy = {0: (STUB, 0), 90: (0, -STUB), 180: (-STUB, 0), 270: (0, STUB)}[d % 360]
            end = (round(tip[0] + dx, 4), round(tip[1] + dy, 4))
            key = f"{name}/{ref}.{pin}"
            emit_wire(tip, end, key)
            if name in power_syms:
                emit_power(power_syms[name], name, end, key)
            else:
                emit_label(name, end, int(d % 360), key)
        # PWR_FLAG on power nets that need one (declared in circuit.py)
        if name in circuit.PWR_FLAG_NETS and name not in pwr_flagged:
            pwr_flagged.add(name)
            ref0, pin0 = pins[0]
            pl = placed[ref0]
            tip = pl.pin_pos(str(pin0))
            d = pl.pin_dir(str(pin0))
            dx, dy = {0: (STUB, 0), 90: (0, -STUB), 180: (-STUB, 0), 270: (0, STUB)}[d % 360]
            end = (round(tip[0] + dx, 4), round(tip[1] + dy, 4))
            emit_power("power:PWR_FLAG", name, end, "flag/" + name)

    for ref, pin in sorted(nc):
        pos = placed[ref].pin_pos(str(pin))
        noconnects.append(["no_connect", ["at", pos[0], pos[1]],
                           ["uuid", Q(uid(f"nc/{ref}.{pin}"))]])

    # geometric self-check: every wire endpoint sits on-grid... pins of ICs
    # are on the symbol grid; origins snapped, so tips are on-grid too.
    for w in wires:
        for xy in sexp.children(w[1], "xy"):
            check_grid(xy[1], "wire x")
            check_grid(xy[2], "wire y")

    # collision check: KiCad connects anything whose electrical point
    # coincides with another net's point or lies on its wire segment. Every
    # such cross-net coincidence is a silent net merge — abort on any.
    net_points = {}   # (x, y) -> set of net names
    net_segments = []  # (net, p1, p2) axis-aligned stubs

    def add_point(net, p):
        net_points.setdefault(p, set()).add(net)

    for name, pins in nets.items():
        for ref, pin in pins:
            pl = placed[ref]
            tip = pl.pin_pos(str(pin))
            d = pl.pin_dir(str(pin))
            dx, dy = {0: (STUB, 0), 90: (0, -STUB), 180: (-STUB, 0), 270: (0, STUB)}[d % 360]
            end = (round(tip[0] + dx, 4), round(tip[1] + dy, 4))
            add_point(name, tip)
            add_point(name, end)
            net_segments.append((name, tip, end))
    for ref, pin in nc:
        add_point(f"<NC {ref}.{pin}>", placed[ref].pin_pos(str(pin)))
    # unconnected graphic pins of power symbols have no electrical presence;
    # power symbol pins coincide with stub ends of their own net by design.

    merges = []
    for p, names in net_points.items():
        if len(names) > 1:
            merges.append(f"point {p} shared by nets {sorted(names)}")
    for name, p1, p2 in net_segments:
        (x1, y1), (x2, y2) = p1, p2
        for q, qnames in net_points.items():
            for qn in qnames:
                if qn == name:
                    continue
                qx, qy = q
                if x1 == x2 == qx and min(y1, y2) - 1e-6 <= qy <= max(y1, y2) + 1e-6:
                    merges.append(f"net {qn} point {q} lies on {name} stub {p1}-{p2}")
                elif y1 == y2 == qy and min(x1, x2) - 1e-6 <= qx <= max(x1, x2) + 1e-6:
                    merges.append(f"net {qn} point {q} lies on {name} stub {p1}-{p2}")
    if merges:
        raise SystemExit("GEOMETRIC NET MERGES:\n  " + "\n  ".join(sorted(set(merges))))

    # component instances
    for c in comps:
        pl = placed[c["ref"]]
        s = symbols[c["lib_id"]]
        x, y = pl.x, pl.y
        node = ["symbol", ["lib_id", Q(c["lib_id"])], ["at", x, y, 0], ["unit", 1],
                ["exclude_from_sim", "no"],
                ["in_bom", "no" if c.get("dnp") else "yes"], ["on_board", "yes"],
                ["dnp", "yes" if c.get("dnp") else "no"],
                ["uuid", Q(uid("sym/" + c["ref"]))],
                ["property", Q("Reference"), Q(c["ref"]),
                 ["at", x, y - _top_of(s) - 4.5, 0], effects()],
                ["property", Q("Value"), Q(c["value"]),
                 ["at", x, y - _top_of(s) - 2.0, 0], effects()],
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
        extra_syms.append(node)

    # zone titles + boxes
    texts = []
    for z, (x1, y1, x2, y2) in zone_boxes.items():
        texts.append(["text", Q(z), ["exclude_from_sim", "no"],
                      ["at", snap(x1 + 1.27), snap(y1 + 1.27), 0],
                      effects(size=2.54, justify="left"),
                      ["uuid", Q(uid("ztext/" + z))]])
        texts.append(["rectangle", ["start", snap(x1), snap(y1)], ["end", snap(x2), snap(y2)],
                      ["stroke", ["width", 0.1], ["type", "dash"]],
                      ["fill", ["type", "none"]],
                      ["uuid", Q(uid("zbox/" + z))]])

    sch.extend(noconnects)
    sch.extend(wires)
    sch.extend(labels)
    sch.extend(texts)
    sch.extend(extra_syms)
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    return sch


def _top_of(symbol):
    return max((p.y for p in symbol.pins), default=0)


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
    sch = build_schematic(circuit)
    out = os.path.join(PROJECT_DIR, PROJECT_NAME + ".kicad_sch")
    with open(out, "w") as f:
        f.write(sexp.dumps(sch))
    write_project()
    write_bom(circuit)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
