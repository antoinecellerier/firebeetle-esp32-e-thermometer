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
# PCB_OUT_DIR renders a standalone mini-project (board + .kicad_dru + .kicad_pro)
# into a separate directory for fab export; default writes the committed board.
# The netlist input is always read from the project tree.
OUT_DIR = os.environ.get("PCB_OUT_DIR", PROJECT)
BOARD_PATH = os.path.join(OUT_DIR, "thermometer-c6.kicad_pcb")
DRU_PATH = os.path.join(OUT_DIR, "thermometer-c6.kicad_dru")
NETLIST = os.path.join(PROJECT, "out", "netlist.net")

FromMM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(FromMM(x), FromMM(y))  # noqa: E731

ORIGIN = pl.BOARD["origin"]

LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu,
         "F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS}

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


MODEL_3D_BASE = "${KIPRJMOD}/local.3dmodels/"


def _vec3(t):
    v = pcbnew.VECTOR3D()
    v.x, v.y, v.z = (float(n) for n in t)
    return v


def attach_3d_model(fp, fpid):
    """Override the footprint's 3D model per pcb_layout.MODELS_3D (footprints
    whose library .kicad_mod has no resolvable model). No-op for the rest."""
    spec = getattr(pl, "MODELS_3D", {}).get(fpid)
    if spec is None:
        return
    fn, off, rot, scl = spec
    fp.Models().clear()
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = MODEL_3D_BASE + fn
    m.m_Offset = _vec3(off)
    m.m_Rotation = _vec3(rot)
    m.m_Scale = _vec3(scl)
    m.m_Show = True
    fp.Models().push_back(m)


def add_footprints(board, netinfo, pad_net):
    # Connectors + sensors keep their reference on F.SilkS (assembly/orientation
    # aids); every other refdes moves to F.Fab so the silk stays legible. J2 is
    # excluded: its courtyard is boxed on all four sides (J1/JP1/D5/edge), leaving
    # a ~1mm south strip that cannot hold both a >=0.8mm refdes and the required
    # "PPK2" function label — the function label wins, the refdes lives on F.Fab.
    # J4 (EPD FPC) is excluded too: its west courtyard edge is pinched to <0.7mm
    # by JP4/C6/D4 and its body/pads fill the east, so no >=0.8mm refdes fits on
    # exposed silk; the footprint's pin-1 silk mark stays for orientation.
    # J3 (USB-C) is excluded: its footprint-default refdes sits on the north
    # overhang OFF the board outline (y<0), so it moves to F.Fab (off silk).
    KEEP_SILK_REFS = {"J1", "J5", "U5", "U6"}
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
        attach_3d_model(fp, c["footprint"])
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
            r.SetTextThickness(FromMM(max(0.15, round(rsize * 0.15, 2))))
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


SILK_HJUST = {"L": pcbnew.GR_TEXT_H_ALIGN_LEFT,
              "C": pcbnew.GR_TEXT_H_ALIGN_CENTER,
              "R": pcbnew.GR_TEXT_H_ALIGN_RIGHT}
SILK_VJUST = {"T": pcbnew.GR_TEXT_V_ALIGN_TOP,
              "C": pcbnew.GR_TEXT_V_ALIGN_CENTER,
              "B": pcbnew.GR_TEXT_V_ALIGN_BOTTOM}


def add_silk(board):
    # FAB_STAMP appends a fab-export tag (git hash + date) to the "rev A" silk
    # line; empty/unset leaves the committed silk untouched.
    stamp = os.environ.get("FAB_STAMP", "").strip()
    stamped = 0
    for entry in pl.SILK:
        text, x, y, size, rot = entry[:5]
        if stamp:
            n = text.count("\nrev A\n")
            if n:
                text = text.replace("\nrev A\n", f"\nrev A {stamp}\n")
                stamped += n
        layer = entry[5] if len(entry) > 5 else "F.SilkS"
        # Optional horizontal/vertical justification (default centre/centre).
        # Single-line labels stay centre-anchored; the two multi-line corner
        # blocks anchor at a corner (top-left / top-right) so their lines align
        # cleanly toward their own board edge and \n-wrapped text lands where
        # authored in the GUI. Mirrored (B.SilkS) blocks store the justify
        # verbatim -- SetMirrored does not flip it here.
        hjust = entry[6] if len(entry) > 6 else "C"
        vjust = entry[7] if len(entry) > 7 else "C"
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetPosition(bmm(x, y))
        if layer == "B.SilkS":
            t.SetLayer(pcbnew.B_SilkS)
            t.SetMirrored(True)  # bottom text reads correctly through the board
        else:
            t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(FromMM(size), FromMM(size)))
        # Legibility floor: >=0.8mm silk needs >=0.15mm strokes (JLCPCB reliable
        # minimum) or it prints thin/broken; enforce it regardless of size*0.15.
        t.SetTextThickness(FromMM(max(0.15, round(size * 0.15, 2))))
        t.SetTextAngleDegrees(rot)
        # Set justify only when non-default so single-line silk stays byte-stable.
        if hjust != "C":
            t.SetHorizJustify(SILK_HJUST[hjust])
        if vjust != "C":
            t.SetVertJustify(SILK_VJUST[vjust])
        board.Add(t)
    if stamp and stamped != 1:
        raise SystemExit("pcb: FAB_STAMP found no unique 'rev A' silk line")


def add_silk_shapes(board):
    """Silk GRAPHIC outlines from pl.SILK_SHAPES (see its docstring): a "rect"
    entry renders as one unfilled SHAPE_T_RECT, a "line" entry as one
    SHAPE_T_SEGMENT, on the given silk layer at the given line width."""
    silk_layer = {"F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS}
    for entry in getattr(pl, "SILK_SHAPES", []):
        kind, x1, y1, x2, y2 = entry[:5]
        layer = entry[5] if len(entry) > 5 else "F.SilkS"
        width = entry[6] if len(entry) > 6 else 0.15
        s = pcbnew.PCB_SHAPE(board)
        if kind == "rect":
            s.SetShape(pcbnew.SHAPE_T_RECT)
        elif kind == "line":
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        else:
            raise SystemExit(f"pcb: SILK_SHAPES unknown kind {kind!r}")
        s.SetStart(bmm(x1, y1))
        s.SetEnd(bmm(x2, y2))
        s.SetLayer(silk_layer[layer])
        s.SetWidth(FromMM(width))
        if hasattr(s, "SetFilled"):
            s.SetFilled(False)
        board.Add(s)


def design_settings(board):
    ds = board.GetDesignSettings()
    ds.m_MinClearance = FromMM(0.15)
    ds.m_TrackMinWidth = FromMM(0.15)
    ds.m_ViasMinSize = FromMM(0.5)
    ds.m_MinThroughDrill = FromMM(0.3)
    # JLCPCB 2-layer economy minimums (make DRC a real fab gate):
    ds.m_CopperEdgeClearance = FromMM(0.3)  # JLC copper-to-edge floor
    ds.m_HoleToHoleMin = FromMM(0.5)        # JLC hole-to-hole (edge-to-edge) floor
    ds.m_SolderMaskMinWidth = FromMM(0.1)   # JLC mask sliver / web floor (was 0 = off)
    # Via annular ring: keep JLC's 0.3/0.5 via preset floor (0.10mm ring). The
    # dense GND-stitch pockets cannot all fit a 0.6mm pad, and JLC accepts the
    # 0.3mm-drill/0.5mm-pad standard preset; grow_stitch.py fattens to 0.6/0.3
    # (0.15mm ring) only where DRC still clears, leaving the boxed ones at 0.5.
    ds.m_ViasMinAnnularWidth = FromMM(0.10)
    # Legibility-first silk (M7c): every authored label is >=0.8mm/0.15mm (JLCPCB
    # reliable-silk minimum), so DRC ENFORCES that floor rather than relaxing it.
    # set_project_drc_severities() mirrors these into the .kicad_pro rules that
    # kicad-cli actually reads.
    ds.m_MinSilkTextHeight = FromMM(0.8)
    ds.m_MinSilkTextThickness = FromMM(0.15)
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
        # (No J3 edge_clearance exception. The former 'edge-clearance-usb-c' rule
        # waived 2 copper_edge_clearance errors on the front shell pads, which
        # were the SYMPTOM of a placement error, not a property of an edge-launch
        # part: out/j3-datum/ showed HRO's "5.79" datum lands on the NPTH post
        # centreline, so J3 belonged 1.415mm further south. Before the move the
        # front shell pad hung 0.105mm OFF the board edge and its drill left a
        # 0.095mm web; after it, the web is 1.510mm and both violations vanish on
        # their own. Do not reinstate -- a J3 edge_clearance error now means the
        # placement regressed.)
        # Global hole-to-hole is 0.5mm (JLC). Relax it to 0.25mm between holes
        # of the SAME net: a drill-breakout there can only merge already-common
        # copper, so there is no short risk (JLC accepts same-net hole spacing
        # below the diff-net floor). Dense GND-stitch/via-in-pad pockets rely on
        # this; diff-net pairs still get the tightened 0.5mm.
        f.write("(rule hole-to-hole-samenet\n"
                "  (condition \"A.NetName == B.NetName\")\n"
                "  (constraint hole_to_hole (min 0.25mm)))\n")
        f.write("(rule power-track-width\n"
                f"  (condition \"{cond(POWER_NETS)}\")\n"
                "  (constraint track_width (min 0.5mm)))\n")
        # J4's EPD_VCC pins sit on the 0.5mm-pitch row: a 0.5mm stub cannot
        # clear the neighbouring pads, so allow thin stubs inside the fanout
        f.write("(rule power-track-width-fanout\n"
                f"  (condition \"A.NetName == '{alias['EPD_VCC']}' && "
                "A.insideArea('fpc-fanout')\")\n"
                "  (constraint track_width (min 0.25mm)))\n")
        # The JP1<->IBAT link cue (pcb_layout.SILK_SHAPES) deliberately runs its
        # ends into JP1's and J2's silk boxes so the break reads as "connects
        # here". Scope a negative silk_clearance to the 'silk-merge' rule area
        # (a DRC-only F.SilkS marker in the pad-free gap between the two boxes,
        # pcb_layout.KEEPOUTS) so those intended overlaps don't trip silk_overlap
        # while every silk clash elsewhere still gates. KiCad's silk checker DOES
        # consult custom silk_clearance rules; A.insideArea matches the whole line
        # because it threads through the marker, so its box-region overlaps clear
        # too. -0.3mm also covers the marker outline's own overlaps with the
        # neighbouring silk. A per-violation DRC exclusion is rejected: it keys on
        # UUIDs, which pcb.py renumbers every run, so it would silently detach.
        f.write("(rule silk-merge\n"
                "  (condition \"A.insideArea('silk-merge')\")\n"
                "  (constraint silk_clearance (min -0.3mm)))\n")
        # The rev-A/github build-stamp footer (pcb_layout.SILK, B.SilkS NW-corner
        # block) is edge-pinned and can't shrink, so its east end unavoidably
        # clips J3's west shell column (both SH pads + the west NPTH mask
        # aperture -- re-verified 2026-07-20 against the datum-correct placement
        # by rendering with this rule removed). Its position is cosmetic, so waive
        # silk_over_copper only there, scoped to the 'footer-silk-j3' rule area
        # (pcb_layout.KEEPOUTS) in the footer's pad-free WEST portion. Same idiom
        # as silk-merge: A.insideArea matches the WHOLE footer object because it
        # threads the marker, so the negative silk_clearance covers the footer's
        # clip over J3 (silk_clearance governs the "silk clipped by solder mask"
        # check too -- a global negative min zeroes it), while the marker's own
        # outline sits over bare back copper and trips nothing. memberOfFootprint
        # does NOT work here: the derived solder-mask shape is not a J3 member.
        f.write("(rule footer-silk-j3\n"
                "  (condition \"A.insideArea('footer-silk-j3')\")\n"
                "  (constraint silk_clearance (min -0.5mm)))\n")


def write_fp_lib_table():
    """For a PCB_OUT_DIR export, emit an fp-lib-table so the standalone
    mini-project resolves the project-local footprint library under DRC.
    The source table's ${KIPRJMOD} is rewritten to the project's absolute
    path — local.pretty stays in the source tree, not the export dir. The
    committed project dir keeps its own tracked table untouched."""
    if os.path.abspath(OUT_DIR) == os.path.abspath(PROJECT):
        return
    src = os.path.join(PROJECT, "fp-lib-table")
    if not os.path.exists(src):
        return
    txt = open(src).read().replace("${KIPRJMOD}", PROJECT)
    open(os.path.join(OUT_DIR, "fp-lib-table"), "w").write(txt)


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


PRO_PATH = os.path.join(OUT_DIR, "thermometer-c6.kicad_pro")


def set_project_drc_severities():
    """Fix up the .kicad_pro that SaveBoard rewrites from pcbnew defaults:

    1. lib_footprint_mismatch -> 'ignore': SILK_TO_FAB relocates a few
       footprints' silk graphics to F.Fab, which by design makes them differ
       from their library copy; the check is unrelated to copper legality.
    2. min_text_height=0.8mm / min_text_thickness=0.15mm: enforce the M7c
       legibility floor in the rules kicad-cli actually reads (SaveBoard should
       carry the design-setting values over, but pin them explicitly so the DRC
       floor never silently regresses to a pcbnew default)."""
    if not os.path.exists(PRO_PATH):
        return
    txt = open(PRO_PATH).read()
    # Targeted line edits only (preserve KiCad's exact JSON formatting so the
    # committed diff stays minimal and regeneration is byte-stable).
    subs = [
        (r'("lib_footprint_mismatch":\s*)"warning"', r'\1"ignore"'),
        (r'("min_text_height":\s*)[0-9.]+', r'\g<1>0.8'),
        (r'("min_text_thickness":\s*)[0-9.]+', r'\g<1>0.15'),
    ]
    fixed = txt
    for pat, rep in subs:
        fixed = re.sub(pat, rep, fixed)
    if fixed != txt:
        open(PRO_PATH, "w").write(fixed)


def main():
    if not os.path.exists(NETLIST):
        raise SystemExit("pcb: out/netlist.net missing - run `make netlist` first")
    os.makedirs(OUT_DIR, exist_ok=True)
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
    add_silk_shapes(board)

    write_dru(alias)
    write_fp_lib_table()
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
    stamp = os.environ.get("FAB_STAMP", "").strip()
    print(f"pcb: {len(circuit.COMPONENTS)} footprints, {len(exported)} nets, "
          f"{n_tracks} track segments/vias -> {os.path.basename(BOARD_PATH)}"
          + (f" [stamp: {stamp}]" if stamp else ""))


if __name__ == "__main__":
    main()
