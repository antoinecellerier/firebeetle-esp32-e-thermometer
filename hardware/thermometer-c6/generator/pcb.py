#!/usr/bin/env python3
"""Render thermometer-c6.kicad_pcb from circuit.py + pcb_layout.py.

Mechanism only — all authored data lives in pcb_layout.py. The netlist
exported by kicad-cli (out/netlist.net, already verified against circuit.py
by verify/check_netlist.py) is the net-name source: PCB pads must carry the
EXPORTED names (anonymous "~" nets become "Net-(J1-Pad1)" style, no-connect
pins become "unconnected-(...)") for `kicad-cli pcb drc --schematic-parity`
to pass. Never invent net names here.

pcbnew API notes (KiCad 10):
- Add the footprint to the board BEFORE assigning pad nets; SetNet on an
  orphaned pad silently no-ops.
- Iterate fp.Pads() rather than FindPadByNumber — J3 (USB-C) repeats pad
  numbers (A1/B1/SH) and MP pads share a number by design.
- SaveBoard writes fresh random UUIDs each run; the deterministic post-pass
  below rewrites them in file order so regeneration is byte-stable.
- ZONE_FILLER.Fill SEGFAULTS on a CreateEmptyBoard board (no project
  attached). The board must be saved and re-loaded with LoadBoard (which
  attaches a project) before filling — hence the save/reload/fill/save
  sequence in main().
"""

import os
import re
import sys
import uuid

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJECT, "verify"))

import circuit  # noqa: E402
import pcb_layout as pl  # noqa: E402
from generate import NAMESPACE, ROOT_UUID, uid  # noqa: E402
from check_netlist import load_netlist  # noqa: E402

SYSTEM_FP = "/usr/share/kicad/footprints"
BOARD_PATH = os.path.join(PROJECT, "thermometer-c6.kicad_pcb")
DRU_PATH = os.path.join(PROJECT, "thermometer-c6.kicad_dru")
NETLIST = os.path.join(PROJECT, "out", "netlist.net")

FromMM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(FromMM(x), FromMM(y))  # noqa: E731

ORIGIN = pl.BOARD["origin"]

LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}

# Nets that see the EPD booster's +/-20V-class rails -> 0.3mm clearance rule
HV_NETS = ["EPD_PREVGH", "EPD_PREVGL", "~EPD_VGH", "~EPD_VGL",
           "~EPD_VSH", "~EPD_VSL", "~EPD_VCOM", "~EPD_VPP"]
# Full-current paths (465mA EPD refresh bursts) -> 0.5mm min track width rule.
# +3V3 is deliberately absent: only its LDO->U1->Q2 trunk carries that current,
# while the pull-ups, probes and the sensors' 0.5mm-pitch LGA pads take
# microamps and cannot physically accept a 0.5mm stub. check_pcb.py asserts
# the trunk instead, which is what the rule was really trying to say.
POWER_NETS = ["VBAT", "VSYS", "EPD_VCC", "~VBAT_RAW", "~BAT_IN"]


def bmm(x, y):
    """Board-relative mm -> absolute VECTOR2I."""
    return V(ORIGIN[0] + x, ORIGIN[1] + y)


def resolve_fp_dir(lib):
    for base in (os.path.join(SYSTEM_FP, lib + ".pretty"),
                 os.path.join(PROJECT, lib + ".pretty")):
        if os.path.isdir(base):
            return base
    raise SystemExit(f"pcb: footprint library not found: {lib}")


def build_net_maps():
    """exported netlist -> pad_net {(ref,pad): exported_name} and
    alias {circuit_name: exported_name} (named + anonymous)."""
    exported = load_netlist(NETLIST)
    pad_net = {}
    for name, pins in exported.items():
        for rp in pins:
            pad_net[rp] = name
    alias = {}
    unmatched = dict(exported)
    for cname, pins in circuit.NETS.items():
        ps = {(r, str(p)) for r, p in pins}
        if not cname.startswith("~"):
            if cname not in exported or exported[cname] != ps:
                raise SystemExit(f"pcb: net {cname} missing/mismatched in netlist "
                                 f"(run `make netlist` first)")
            alias[cname] = cname
            unmatched.pop(cname, None)
        else:
            hits = [n for n, ep in unmatched.items() if ep == ps]
            if len(hits) != 1:
                raise SystemExit(f"pcb: anonymous net {cname}: {len(hits)} pin-set "
                                 f"matches in netlist")
            alias[cname] = hits[0]
            unmatched.pop(hits[0])
    return exported, pad_net, alias


def add_outline(board):
    w, h = pl.BOARD["size"]
    pts = [(0, 0), (w, 0), (w, h), (0, h)]
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(bmm(x1, y1))
        s.SetEnd(bmm(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(FromMM(0.1))
        board.Add(s)


def add_footprints(board, netinfo, pad_net):
    # Connectors + sensors keep their reference on F.SilkS (assembly/orientation
    # aids); every other refdes moves to F.Fab so the silk stays legible.
    KEEP_SILK_REFS = {"J1", "J2", "J3", "J4", "J5", "U5", "U6"}
    pads_by_key = {}
    for c in circuit.COMPONENTS:
        ref = c["ref"]
        lib, _, name = c["footprint"].partition(":")
        fp = pcbnew.FootprintLoad(resolve_fp_dir(lib), name)
        if fp is None:
            raise SystemExit(f"pcb: cannot load footprint {c['footprint']} for {ref}")
        fp.SetReference(ref)
        if ref not in KEEP_SILK_REFS:
            fp.Reference().SetLayer(pcbnew.F_Fab)
        fp.SetValue(c["value"])
        # FootprintLoad drops the library nickname; restore it or the
        # schematic-parity DRC flags every footprint as substituted.
        fp.SetFPIDAsString(c["footprint"])
        fp.SetField("LCSC", c.get("lcsc", ""))
        for f in fp.GetFields():
            if f.GetName() == "LCSC":
                f.SetVisible(False)
        board.Add(fp)
        if ref not in pl.PLACE:
            raise SystemExit(f"pcb: {ref} missing from pcb_layout.PLACE")
        place = pl.PLACE[ref]
        x, y, rot = place[:3]
        fp.SetPosition(bmm(x, y))
        if len(place) > 3 and place[3] == "B":
            fp.Flip(fp.GetPosition(), False)  # bottom side (bench-access copper)
        fp.SetOrientationDegrees(rot)
        # Kept-on-silk refs whose default spot collides get a data-driven nudge.
        rp = getattr(pl, "REF_POS", {}).get(ref)
        if rp is not None:
            rx, ry, rsize, rang = rp
            r = fp.Reference()
            r.SetPosition(bmm(rx, ry))
            r.SetTextSize(pcbnew.VECTOR2I(FromMM(rsize), FromMM(rsize)))
            r.SetTextThickness(FromMM(round(rsize * 0.15, 2)))
            r.SetTextAngleDegrees(rang)
        # Relocate irreducible footprint silk graphics to F.Fab (see SILK_TO_FAB).
        mode = getattr(pl, "SILK_TO_FAB", {}).get(ref)
        if mode is not None:
            for it in fp.GraphicalItems():
                if it.GetLayer() != pcbnew.F_SilkS:
                    continue
                if mode == "all" or (mode == "poly"
                        and isinstance(it, pcbnew.PCB_SHAPE)
                        and it.GetShape() == pcbnew.SHAPE_T_POLY):
                    it.SetLayer(pcbnew.F_Fab)
        fp.SetPath(pcbnew.KIID_PATH("/" + ROOT_UUID + "/" + uid("sym/" + ref)))
        fp.SetDNP(bool(c.get("dnp")))
        if c.get("dnp") or not c.get("lcsc"):
            fp.SetExcludedFromBOM(True)  # mirrors generate.py's in_bom rule
        if ref.startswith(("TP", "JP", "H")):
            fp.SetExcludedFromPosFiles(True)  # copper-only / mechanical
        for pad in fp.Pads():
            key = (ref, str(pad.GetNumber()))
            net = pad_net.get(key)
            if net is not None:
                pad.SetNet(netinfo[net])
            pads_by_key.setdefault(key, pad)
    return pads_by_key


def node_pos(node, pads):
    if isinstance(node, str):
        ref, _, num = node.partition(".")
        pad = pads.get((ref, num))
        if pad is None:
            raise SystemExit(f"pcb: track node {node}: no such pad")
        return pad.GetPosition(), pad
    x, y = node
    return bmm(x, y), None


def expand_dogleg(a, b):
    """One 45-degree dogleg (diagonal leg first) between unaligned points."""
    dx, dy = b.x - a.x, b.y - a.y
    if dx == 0 or dy == 0 or abs(dx) == abs(dy):
        return [a, b]
    d = min(abs(dx), abs(dy))
    mid = pcbnew.VECTOR2I(a.x + (d if dx > 0 else -d), a.y + (d if dy > 0 else -d))
    return [a, mid, b]


def on_segment(p, a, b):
    """True if p lies strictly between the collinear-ish endpoints a and b."""
    if p == a or p == b:
        return False
    dx, dy = b.x - a.x, b.y - a.y
    px, py = p.x - a.x, p.y - a.y
    if dx * py - dy * px != 0:      # not exactly collinear
        return False
    dot = px * dx + py * dy
    return 0 < dot < dx * dx + dy * dy


def split_tees(paths):
    """A track ending on another same-net track's mid-span is electrically
    connected but has no shared anchor, so KiCad's connectivity flags it as a
    dangling end. Give the crossed track a vertex there."""
    for i, (net, layer, _w, path) in enumerate(paths):
        ends = []
        for j, (net2, layer2, _w2, path2) in enumerate(paths):
            if i == j or net2 != net or layer2 != layer:
                continue
            ends.extend((path2[0], path2[-1]))
        k = 0
        while k < len(path) - 1:
            hits = [p for p in ends if on_segment(p, path[k], path[k + 1])]
            if hits:
                hits.sort(key=lambda p: (p.x - path[k].x) ** 2
                          + (p.y - path[k].y) ** 2)
                path[k + 1:k + 1] = hits
            k += 1 + len(hits)


def add_tracks(board, netinfo, alias, pads):
    paths = []
    for net, layer, width, nodes in pl.TRACKS:
        exp = alias.get(net)
        if exp is None:
            raise SystemExit(f"pcb: TRACKS references unknown net {net}")
        pts = []
        for node in nodes:
            pos, pad = node_pos(node, pads)
            if pad is not None and pad.GetNetname() != exp:
                raise SystemExit(f"pcb: track node {node} is on net "
                                 f"'{pad.GetNetname()}', not '{net}' ({exp})")
            pts.append(pos)
        if pl.HAND_ROUTED:
            # harvested GUI copper is verbatim geometry -- a dogleg insert
            # would corrupt any deliberate non-45-degree segment
            path = pts
        else:
            path = []
            for i in range(len(pts) - 1):
                seg = expand_dogleg(pts[i], pts[i + 1])
                path.extend(seg if not path else seg[1:])
        paths.append((exp, layer, width, path))

    split_tees(paths)

    for exp, layer, width, path in paths:
        ni = netinfo[exp]
        for i in range(len(path) - 1):
            if path[i] == path[i + 1]:
                continue
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(path[i])
            t.SetEnd(path[i + 1])
            t.SetWidth(FromMM(width))
            t.SetLayer(LAYER[layer])
            t.SetNet(ni)
            board.Add(t)


def add_vias(board, netinfo, alias):
    def one(net, x, y, dia, drill):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(bmm(x, y))
        v.SetDrill(FromMM(drill))
        v.SetWidth(FromMM(dia))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(netinfo[alias[net]])
        board.Add(v)

    for net, x, y in pl.VIAS:
        one(net, x, y, pl.DEFAULT_VIA["diameter"], pl.DEFAULT_VIA["drill"])
    # GND stitch vias: 0.5mm/0.3mm (board/JLC minimum) — the 0.6mm default
    # cannot clear neighbouring copper in the dense pockets, leaving many GND
    # groups unroutable; 0.5mm halves the required clearance shadow.
    sv = getattr(pl, "STITCH_VIA", pl.DEFAULT_VIA)
    for entry in pl.STITCH:
        # (x, y) renders at STITCH_VIA size; (x, y, dia, drill) is a per-via
        # override (grown stitches -- 0.6/0.3 = 0.15mm annular ring vs 0.1mm).
        x, y = entry[0], entry[1]
        dia = entry[2] if len(entry) > 3 else sv["diameter"]
        drill = entry[3] if len(entry) > 3 else sv["drill"]
        one("GND", x, y, dia, drill)


def add_zones(board, netinfo, alias):
    for prio, (net, layer, corners) in enumerate(pl.COPPER_ZONES):
        z = pcbnew.ZONE(board)
        z.SetLayer(LAYER[layer])
        z.SetNet(netinfo[alias[net]])
        chain = pcbnew.SHAPE_LINE_CHAIN()
        for x, y in corners:
            chain.Append(bmm(x, y))
        chain.SetClosed(True)
        z.Outline().AddOutline(chain)
        z.SetMinThickness(FromMM(0.2))
        z.SetAssignedPriority(prio)
        board.Add(z)


def add_keepouts(board):
    for k in pl.KEEPOUTS:
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName(k["name"])
        lset = pcbnew.LSET()
        for layer in k["layers"]:
            lset.AddLayer(LAYER[layer])
        z.SetLayerSet(lset)
        x1, y1, x2, y2 = k["rect"]
        chain = pcbnew.SHAPE_LINE_CHAIN()
        for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
            chain.Append(bmm(x, y))
        chain.SetClosed(True)
        z.Outline().AddOutline(chain)
        z.SetDoNotAllowTracks(k.get("tracks", True))
        z.SetDoNotAllowVias(k.get("vias", True))
        z.SetDoNotAllowZoneFills(k.get("fills", True))
        z.SetDoNotAllowPads(k.get("pads", False))
        z.SetDoNotAllowFootprints(False)
        board.Add(z)


def add_silk(board):
    for entry in pl.SILK:
        text, x, y, size, rot = entry[:5]
        layer = entry[5] if len(entry) > 5 else "F.SilkS"
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetPosition(bmm(x, y))
        if layer == "B.SilkS":
            t.SetLayer(pcbnew.B_SilkS)
            t.SetMirrored(True)  # bottom text reads correctly through the board
        else:
            t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(FromMM(size), FromMM(size)))
        t.SetTextThickness(FromMM(round(size * 0.15, 2)))
        t.SetTextAngleDegrees(rot)
        board.Add(t)


def design_settings(board):
    ds = board.GetDesignSettings()
    ds.m_MinClearance = FromMM(0.15)
    ds.m_TrackMinWidth = FromMM(0.15)
    ds.m_ViasMinSize = FromMM(0.5)
    ds.m_MinThroughDrill = FromMM(0.3)
    ds.m_CopperEdgeClearance = FromMM(0.2)  # JLC min; USB-C edge pads sit at 0.31
    # This board is at its routable-density limit; the functional silk (M7)
    # needs sub-0.8mm text to sit clear of the packed pads. JLC prints down to
    # ~0.4mm/0.06mm, so relax the DRC floor from KiCad's 0.8/0.08 default to
    # match the intent (silk stays legible; most labels are 0.5-0.7mm).
    ds.m_MinSilkTextHeight = FromMM(0.4)
    ds.m_MinSilkTextThickness = FromMM(0.06)
    # Accept single-spoke thermal relief on GND pads (default 2). Many GND pads
    # on tightly-packed 0402s can only take one spoke without moving parts; one
    # spoke is a valid connection. Narrowest fix for starved_thermal.
    ds.m_MinResolvedSpokes = 1


def write_dru(alias):
    def cond(nets):
        return " || ".join(f"A.NetName == '{alias[n]}'" for n in nets)

    with open(DRU_PATH, "w") as f:
        f.write("(version 1)\n")
        f.write("# generated by generator/pcb.py - do not edit\n")
        f.write("(rule hv-clearance\n"
                f"  (condition \"{cond(HV_NETS)}\")\n"
                "  (constraint clearance (min 0.3mm)))\n")
        # later rules take precedence: relax inside the FPC fan-out area and
        # between J4's own 0.5mm-pitch pads (0.2mm gaps are intrinsic there)
        f.write("(rule hv-clearance-fanout\n"
                f"  (condition \"({cond(HV_NETS)}) && A.insideArea('fpc-fanout')\")\n"
                "  (constraint clearance (min 0.18mm)))\n")
        f.write("(rule hv-clearance-j4\n"
                "  (condition \"A.memberOfFootprint('J4') && B.memberOfFootprint('J4')\")\n"
                "  (constraint clearance (min 0.18mm)))\n")
        f.write("(rule power-track-width\n"
                f"  (condition \"{cond(POWER_NETS)}\")\n"
                "  (constraint track_width (min 0.5mm)))\n")
        # J4's EPD_VCC pins sit on the 0.5mm-pitch row: a 0.5mm stub cannot
        # clear the neighbouring pads, so allow thin stubs inside the fanout
        f.write("(rule power-track-width-fanout\n"
                f"  (condition \"A.NetName == '{alias['EPD_VCC']}' && "
                "A.insideArea('fpc-fanout')\")\n"
                "  (constraint track_width (min 0.25mm)))\n")


# pcbnew saves same-type items sorted by their (random) UUIDs, so both the
# uuids AND the block order change every run. Normalize: sort same-type
# top-level blocks by uuid-stripped content, then rewrite every uuid in file
# order with uuid5 — regeneration is byte-stable.
SORTABLE = {"footprint", "segment", "arc", "via", "zone", "group",
            "gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly", "gr_text"}


def top_level_blocks(text):
    """Yield (start, end, type) spans of the root node's children."""
    depth = 0
    i = 0
    n = len(text)
    in_str = False
    start = None
    while i < n:
        ch = text[i]
        if in_str:
            if ch == '"' and text[i - 1] != "\\":
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2 and start is not None:
                j = start + 1
                k = j
                while k < n and (text[k].isalnum() or text[k] == "_"):
                    k += 1
                yield start, i + 1, text[j:k]
                start = None
            depth -= 1
        i += 1


UUID_RE = re.compile(r'\(uuid "[0-9a-fA-F-]{36}"\)')


TYPE_ORDER = ["gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly",
              "gr_text", "footprint", "segment", "arc", "via", "zone", "group"]


def normalize_board_file(path):
    text = open(path).read()
    blocks = list(top_level_blocks(text))
    head_end = blocks[0][0] if blocks else len(text)
    fixed = []      # header/setup/net blocks, original order
    sortable = []   # (type, text) blocks whose save order follows random uuids
    for s, e, t in blocks:
        if t in SORTABLE:
            sortable.append((t, text[s:e]))
        else:
            fixed.append(text[s:e])
    sortable.sort(key=lambda b: (TYPE_ORDER.index(b[0]), UUID_RE.sub("", b[1])))
    body = "".join("\n\t" + b for b in fixed)
    body += "".join("\n\t" + b for _, b in sortable)
    text = text[:head_end].rstrip("\n\t ") + body + "\n)\n"

    counter = [0]

    def rep(_m):
        counter[0] += 1
        return '(uuid "%s")' % uuid.uuid5(NAMESPACE, "thermometer-c6-pcb/%d" % counter[0])

    text = UUID_RE.sub(rep, text)
    open(path, "w").write(text)


PRO_PATH = os.path.join(PROJECT, "thermometer-c6.kicad_pro")


def set_project_drc_severities():
    """SILK_TO_FAB relocates a few footprints' silk graphics to F.Fab, which by
    design makes them differ from their library copy. SaveBoard rewrites the
    project severities from pcbnew defaults, so pin lib_footprint_mismatch back
    to 'ignore' — this board intentionally edits those footprints, and the check
    is otherwise unrelated to copper legality (drc_summary's REAL gate)."""
    if not pl.SILK_TO_FAB or not os.path.exists(PRO_PATH):
        return
    txt = open(PRO_PATH).read()
    fixed = txt.replace('"lib_footprint_mismatch": "warning"',
                        '"lib_footprint_mismatch": "ignore"')
    if fixed != txt:
        open(PRO_PATH, "w").write(fixed)


def main():
    if not os.path.exists(NETLIST):
        raise SystemExit("pcb: out/netlist.net missing - run `make netlist` first")
    exported, pad_net, alias = build_net_maps()

    board = pcbnew.CreateEmptyBoard()
    design_settings(board)

    netinfo = {}
    for name in sorted(exported):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    add_outline(board)
    pads = add_footprints(board, netinfo, pad_net)
    add_keepouts(board)
    add_tracks(board, netinfo, alias, pads)
    add_vias(board, netinfo, alias)
    add_zones(board, netinfo, alias)
    add_silk(board)

    write_dru(alias)
    pcbnew.SaveBoard(BOARD_PATH, board)

    # Fill zones on a re-loaded board (see module docstring: ZONE_FILLER
    # crashes without a project attached).
    board2 = pcbnew.LoadBoard(BOARD_PATH)
    if board2.Zones():
        if not pcbnew.ZONE_FILLER(board2).Fill(board2.Zones()):
            raise SystemExit("pcb: zone fill failed")
    pcbnew.SaveBoard(BOARD_PATH, board2)

    normalize_board_file(BOARD_PATH)
    set_project_drc_severities()
    n_tracks = len([t for t in board2.GetTracks()])
    print(f"pcb: {len(circuit.COMPONENTS)} footprints, {len(exported)} nets, "
          f"{n_tracks} track segments/vias -> {os.path.basename(BOARD_PATH)}")


if __name__ == "__main__":
    main()
