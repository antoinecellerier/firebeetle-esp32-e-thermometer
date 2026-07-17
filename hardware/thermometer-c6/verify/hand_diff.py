#!/usr/bin/env python3
"""Audit every unharvested GUI edit in the hand-editing round-trip.

The user edits out/hand/thermometer-c6.kicad_pcb in the KiCad GUI. Only signal
copper is harvested back (extract_tracks.py --all, which EXCLUDES GND); every
other edit -- placement, GND vias/tracks, silk, copper graphics, outline -- is
hand-mirrored into the generator and has been forgotten before. This tool
compares the hand board against the authored generator source and reports what
is not yet mirrored, per category:

  A. placement       PLACE vs board footprint pos/rot/side
  B. existence       PLACE keys vs board refs (both directions)
  C. copper graphics free PCB_SHAPE / PCB_TEXT on F.Cu/B.Cu (extract only reads
                     GetTracks(), so a graphic "trace" is silently dropped)
  D. GND vias        board GND vias vs STITCH
  E. GND tracks      board GND segments vs pcb_layout.TRACKS polylines
  F. silk            free silk PCB_TEXT vs SILK + REF_POS reference-text drift
  G. signal copper   board non-GND copper vs pcb_routes.py (extract_tracks sync)
  H. outline         Edge.Cuts bbox vs BOARD origin+size

Usage: python3 verify/hand_diff.py [BOARD] [--apply]
  BOARD defaults to out/hand/thermometer-c6.kicad_pcb.
  --apply mirrors PLACE (placement) + STITCH (GND vias) into
  generator/pcb_layout.py by text surgery. B/C/E/F/G/H are report-only.
Exit 0 = fully mirrored, exit 1 = unharvested differences.
"""

import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))
sys.path.insert(0, HERE)

# pcb_layout appends pcb_routes copper into its TRACKS unless PCB_NO_ROUTES is
# set; hand_diff needs the two SEPARATE (authored GND vs harvested signal), so
# import pcb_layout with routes suppressed and pcb_routes on its own.
os.environ["PCB_NO_ROUTES"] = "1"
import pcb_layout as pl  # noqa: E402
import circuit  # noqa: E402
from check_netlist import load_netlist  # noqa: E402

DEFAULT_BOARD = os.path.join(PROJECT, "out", "hand", "thermometer-c6.kicad_pcb")
LAYOUT_PY = os.path.join(PROJECT, "generator", "pcb_layout.py")
NETLIST = os.path.join(PROJECT, "out", "netlist.net")

OX, OY = pl.BOARD["origin"]
FromMM = pcbnew.FromMM
LAYER_NAME = {pcbnew.F_Cu: "F.Cu", pcbnew.B_Cu: "B.Cu"}
LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
SILK_LAYER = {"F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS}

POS_EPS = 5e-5   # mm: below any real GUI move
SILK_EPS = 0.02  # mm: silk / reference-text move threshold


# --- number formatting (match pcb_layout.py's authored style) ----------------

def _fmt(v, nd):
    s = f"{v:.{nd}f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def fmt_coord(v):
    """PLACE coordinate: up to 4dp, trailing zeros stripped, one decimal kept."""
    return _fmt(v, 4)


def fmt3(v):
    """STITCH coordinate/size: up to 3dp (extract_tracks precision)."""
    return _fmt(v, 3)


def rel_mm(pos):
    return (pos.x / 1e6 - OX, pos.y / 1e6 - OY)


# --- authored net alias (circuit "~" name -> exported KiCad name) -------------

def build_alias():
    """{circuit_net: exported_net}; None if the netlist is unavailable."""
    if not os.path.exists(NETLIST):
        return None
    exported = load_netlist(NETLIST)
    alias, unmatched = {}, dict(exported)
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
    return alias


# --- authored copper segment reconstruction (replicates pcb.py) --------------
# pcb.py renders HAND_ROUTED TRACKS verbatim (no dogleg) then split_tees()
# inserts a vertex wherever another same-net/same-layer polyline's endpoint
# lands mid-segment. Reproduce that so a clean board compares clean.

def _node_nm(node, padctr):
    if isinstance(node, str):
        ref, _, num = node.partition(".")
        p = padctr.get((ref, num))
        if p is None:
            raise SystemExit(f"hand_diff: track node {node}: no such pad")
        return (p.x, p.y)
    return (FromMM(OX + node[0]), FromMM(OY + node[1]))


def _on_seg(p, a, b):
    if p == a or p == b:
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    px, py = p[0] - a[0], p[1] - a[1]
    if dx * py - dy * px != 0:
        return False
    dot = px * dx + py * dy
    return 0 < dot < dx * dx + dy * dy


def _split_tees(paths):
    for i, (net, layer, _w, path) in enumerate(paths):
        ends = []
        for j, (net2, layer2, _w2, path2) in enumerate(paths):
            if i == j or net2 != net or layer2 != layer:
                continue
            ends.extend((path2[0], path2[-1]))
        k = 0
        while k < len(path) - 1:
            hits = [p for p in ends if _on_seg(p, path[k], path[k + 1])]
            if hits:
                hits.sort(key=lambda p: (p[0] - path[k][0]) ** 2
                          + (p[1] - path[k][1]) ** 2)
                path[k + 1:k + 1] = hits
            k += 1 + len(hits)


def authored_segments(routes, padctr):
    """Segment set {(net, layer, width, frozenset{p1,p2})} for pl.TRACKS (GND)
    plus routes.TRACKS (signal), reproducing pcb.py's split_tees output. net
    stays the circuit name (translate to exported before comparing to a board)."""
    paths = []
    for net, layer, width, nodes in list(pl.TRACKS) + list(routes.TRACKS):
        paths.append([net, layer, round(width, 3),
                      [_node_nm(n, padctr) for n in nodes]])
    _split_tees(paths)
    segs = set()
    for net, layer, width, path in paths:
        for a, b in zip(path, path[1:]):
            if a == b:
                continue
            segs.add((net, layer, width, frozenset((a, b))))
    return segs


def board_segments(board):
    """Board track segment set, same key shape (net = exported name)."""
    segs = set()
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            continue
        s, e = t.GetStart(), t.GetEnd()
        segs.add((t.GetNetname(), LAYER_NAME.get(t.GetLayer(), "?"),
                  round(t.GetWidth() / 1e6, 3),
                  frozenset(((s.x, s.y), (e.x, e.y)))))
    return segs


# --- report -------------------------------------------------------------------

class Report:
    def __init__(self):
        self.dirty = False
        self.place_edits = []    # (ref, nx, ny, nrot, nside_bool)
        self.stitch_add = []     # (x, y, dia, drill)
        self.stitch_del = []     # authored STITCH tuple

    def section(self, title, lines):
        if lines:
            self.dirty = True
            print(f"{title}:")
            for ln in lines:
                print(f"    {ln}")
        else:
            print(f"{title}: clean")


def courtyard_bbox(fp):
    side = pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu else pcbnew.F_CrtYd
    bb = fp.GetCourtyard(side).BBox()
    if bb.GetWidth() <= 0 or bb.GetHeight() <= 0:
        return None
    return (bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY,
            bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY)


def authored_copper_points():
    """Board-relative points of absolute-coordinate authored copper (GND TRACKS
    polyline vertices, VIAS, STITCH vias) -- the copper a move would orphan."""
    pts = []
    for _net, _layer, _w, nodes in pl.TRACKS:
        for n in nodes:
            if not isinstance(n, str):
                pts.append(("trk", n[0], n[1]))
    for entry in getattr(pl, "VIAS", []):
        pts.append(("via", entry[1], entry[2]))
    for entry in pl.STITCH:
        pts.append(("stitch", entry[0], entry[1]))
    return pts


def check_placement(board, rep):
    lines = []
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    copper_pts = authored_copper_points()
    for ref, place in pl.PLACE.items():
        fp = by_ref.get(ref)
        if fp is None:
            continue  # existence handled in section B
        ox, oy, orot = place[:3]
        oside = place[3] if len(place) > 3 else None
        nx, ny = rel_mm(fp.GetPosition())
        nrot = round(fp.GetOrientationDegrees()) % 360
        nside = "B" if fp.GetLayer() == pcbnew.B_Cu else None
        dx, dy = nx - ox, ny - oy
        moved = (abs(dx) > POS_EPS or abs(dy) > POS_EPS
                 or nrot != orot % 360 or nside != oside)
        if not moved:
            continue
        os_ = f', "{oside}"' if oside else ""
        ns_ = f', "{nside}"' if nside else ""
        lines.append(
            f"{ref}: ({fmt_coord(ox)}, {fmt_coord(oy)}, {orot}{os_}) -> "
            f"({fmt_coord(nx)}, {fmt_coord(ny)}, {nrot}{ns_})  "
            f"[dx={round(dx, 4):+g} dy={round(dy, 4):+g} "
            f"drot={nrot - orot % 360:+d}]")
        if nrot % 90 != 0:
            lines.append(f"  SUSPICIOUS: board rotation {nrot} not a multiple of 90")
        cbb = courtyard_bbox(fp)
        if cbb is not None:
            # courtyard translated back to the authored (pre-move) position:
            # authored copper inside it is what the move leaves behind
            sx, sy = ox - nx, oy - ny
            old = (cbb[0] + sx, cbb[1] + sy, cbb[2] + sx, cbb[3] + sy)
            orph = [(k, x, y) for k, x, y in copper_pts
                    if old[0] <= x <= old[2] and old[1] <= y <= old[3]]
            for k, x, y in orph:
                lines.append(f"  WARN: orphans authored {k} ({fmt3(x)}, {fmt3(y)}) "
                             f"in old courtyard")
        rep.place_edits.append((ref, nx, ny, nrot, bool(nside)))
    rep.section("A. placement", lines)


def check_existence(board, rep):
    lines = []
    board_refs = {fp.GetReference() for fp in board.GetFootprints()}
    place_refs = set(pl.PLACE)
    for ref in sorted(place_refs - board_refs):
        lines.append(f"{ref}: in PLACE but absent on board (GUI-deleted footprint)")
    for ref in sorted(board_refs - place_refs):
        lines.append(f"{ref}: on board but not in PLACE (circuit.py owns existence)")
    rep.section("B. existence", lines)


def check_copper_graphics(board, rep):
    lines = []
    for d in board.GetDrawings():
        if not isinstance(d, (pcbnew.PCB_SHAPE, pcbnew.PCB_TEXT)):
            continue
        if d.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        bb = d.GetBoundingBox()
        r = (bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY,
             bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY)
        kind = "PCB_TEXT" if isinstance(d, pcbnew.PCB_TEXT) else "PCB_SHAPE"
        lines.append(f"{kind} on {LAYER_NAME.get(d.GetLayer(), '?')} "
                     f"bbox ({r[0]:.3f},{r[1]:.3f})-({r[2]:.3f},{r[3]:.3f})")
    if lines:
        lines.append("draw tracks, not graphic lines -- extract_tracks only "
                     "reads GetTracks()")
    rep.section("C. copper graphics", lines)


def check_stitch(board, rep):
    lines = []
    sv = getattr(pl, "STITCH_VIA", pl.DEFAULT_VIA)
    dflt = (round(sv["diameter"], 3), round(sv["drill"], 3))

    board_via = {}
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND":
            x, y = rel_mm(t.GetPosition())
            board_via[(round(x, 3), round(y, 3))] = (
                round(t.GetFrontWidth() / 1e6, 3),
                round(t.GetDrillValue() / 1e6, 3))
    auth_via = {}
    for entry in pl.STITCH:
        x, y = round(entry[0], 3), round(entry[1], 3)
        if len(entry) > 3:
            auth_via[(x, y)] = (round(entry[2], 3), round(entry[3], 3))
        else:
            auth_via[(x, y)] = dflt

    for pos in sorted(board_via.keys() - auth_via.keys()):
        dia, drill = board_via[pos]
        if (dia, drill) == dflt:
            tup = f"({fmt3(pos[0])}, {fmt3(pos[1])})"
        else:
            tup = f"({fmt3(pos[0])}, {fmt3(pos[1])}, {fmt3(dia)}, {fmt3(drill)})"
        lines.append(f"added GND via -> STITCH {tup},")
        rep.stitch_add.append((pos[0], pos[1], dia, drill))
    for pos in sorted(auth_via.keys() - board_via.keys()):
        dia, drill = auth_via[pos]
        entry = (pos[0], pos[1]) if (dia, drill) == dflt else (pos[0], pos[1], dia, drill)
        lines.append(f"removed GND via {tuple_str(entry)}")
        rep.stitch_del.append(entry)
    for pos in sorted(board_via.keys() & auth_via.keys()):
        if board_via[pos] != auth_via[pos]:
            lines.append(f"GND via ({fmt3(pos[0])}, {fmt3(pos[1])}) size "
                         f"{auth_via[pos]} -> {board_via[pos]} (report-only)")
    rep.section("D. GND vias", lines)


def tuple_str(entry):
    return "(" + ", ".join(fmt3(v) for v in entry) + ")"


def check_gnd_tracks(board, padctr, routes, rep):
    auth = {s for s in authored_segments(routes, padctr) if s[0] == "GND"}
    brd = {s for s in board_segments(board) if s[0] == "GND"}
    added, removed = brd - auth, auth - brd
    lines = []
    if added or removed:
        lines.append(f"+{len(added)} board segment(s), -{len(removed)} "
                     f"authored segment(s); GND polylines are re-authored by hand")
        shown = 0
        for tag, segset in (("+", added), ("-", removed)):
            for net, layer, w, pts in sorted(
                    segset, key=lambda s: sorted(s[3])):
                if shown >= 20:
                    break
                (ax, ay), (bx, by) = sorted(pts)
                lines.append(f"  {tag} {layer} {w}mm "
                             f"({ax/1e6-OX:.3f},{ay/1e6-OY:.3f})-"
                             f"({bx/1e6-OX:.3f},{by/1e6-OY:.3f})")
                shown += 1
        extra = len(added) + len(removed) - min(20, len(added) + len(removed))
        if extra > 0:
            lines.append(f"  +{extra} more")
    rep.section("E. GND tracks", lines)


def board_silk_texts(board):
    out = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() in (
                pcbnew.F_SilkS, pcbnew.B_SilkS):
            x, y = rel_mm(d.GetPosition())
            out.append(dict(text=d.GetText(),
                            layer="B.SilkS" if d.GetLayer() == pcbnew.B_SilkS
                            else "F.SilkS", x=x, y=y,
                            rot=round(d.GetTextAngleDegrees()) % 360,
                            size=round(d.GetTextHeight() / 1e6, 3)))
    return out


def check_silk(board, rep):
    lines = []
    board_texts = board_silk_texts(board)
    used = [False] * len(board_texts)
    for entry in pl.SILK:
        text, x, y, size, rot = entry[:5]
        layer = entry[5] if len(entry) > 5 else "F.SilkS"
        cands = [(i, t) for i, t in enumerate(board_texts)
                 if not used[i] and t["text"] == text and t["layer"] == layer]
        if not cands:
            lines.append(f"deleted {layer} {text!r} "
                         f"(authored at {fmt3(x)},{fmt3(y)})")
            continue
        i, t = min(cands, key=lambda c: (c[1]["x"] - x) ** 2 + (c[1]["y"] - y) ** 2)
        used[i] = True
        dx, dy = t["x"] - x, t["y"] - y
        if abs(dx) > SILK_EPS or abs(dy) > SILK_EPS or t["rot"] != rot % 360 \
                or abs(t["size"] - size) > 1e-3:
            lines.append(f"moved {layer} {text!r}: ({fmt3(x)},{fmt3(y)}) -> "
                         f"({fmt3(t['x'])},{fmt3(t['y'])}) "
                         f"[d={dx:+.3g},{dy:+.3g} drot={t['rot'] - rot % 360:+d} "
                         f"size {size}->{t['size']}] (justify not round-tripped)")
    for i, t in enumerate(board_texts):
        if not used[i]:
            lines.append(f"added {t['layer']} {t['text']!r} at "
                         f"({fmt3(t['x'])},{fmt3(t['y'])})")

    # REF_POS: reference-text drift for the kept-on-silk refs
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for ref, (rx, ry, rsize, rang) in getattr(pl, "REF_POS", {}).items():
        fp = by_ref.get(ref)
        if fp is None:
            continue
        r = fp.Reference()
        bx, by = rel_mm(r.GetPosition())
        bsize = round(r.GetTextHeight() / 1e6, 3)
        bang = round(r.GetTextAngleDegrees()) % 360
        if abs(bx - rx) > SILK_EPS or abs(by - ry) > SILK_EPS \
                or bang != rang % 360 or abs(bsize - rsize) > 1e-3:
            lines.append(f"REF_POS[{ref}] drift: ({fmt3(rx)},{fmt3(ry)},"
                         f"{rsize},{rang}) -> ({fmt3(bx)},{fmt3(by)},{bsize},{bang})")
    rep.section("F. silk", lines)


def check_signal_copper(board, padctr, routes, alias, rep):
    if alias is None:
        print("G. signal copper: skipped (out/netlist.net missing)")
        return
    auth = authored_segments(routes, padctr)
    brd = board_segments(board)
    # translate authored circuit net -> exported for signal (GND handled in E)
    auth_by_net = {}
    for net, layer, w, pts in auth:
        if net == "GND":
            continue
        auth_by_net.setdefault(alias.get(net, net), set()).add((layer, w, pts))
    brd_by_net = {}
    for net, layer, w, pts in brd:
        if net == "GND" or not net:
            continue
        brd_by_net.setdefault(net, set()).add((layer, w, pts))

    # vias
    auth_via, brd_via = {}, {}
    for entry in getattr(routes, "VIAS", []):
        net = alias.get(entry[0], entry[0])
        auth_via.setdefault(net, set()).add((round(entry[1], 3), round(entry[2], 3)))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" and t.GetNetname() not in ("GND", ""):
            x, y = rel_mm(t.GetPosition())
            brd_via.setdefault(t.GetNetname(), set()).add((round(x, 3), round(y, 3)))

    lines = []
    for net in sorted(set(auth_by_net) | set(brd_by_net) | set(auth_via) | set(brd_via)):
        a, b = auth_by_net.get(net, set()), brd_by_net.get(net, set())
        av, bv = auth_via.get(net, set()), brd_via.get(net, set())
        add_s, rem_s = len(b - a), len(a - b)
        add_v, rem_v = len(bv - av), len(av - bv)
        if add_s or rem_s or add_v or rem_v:
            parts = []
            if add_s or rem_s:
                parts.append(f"+{add_s}/-{rem_s} seg")
            if add_v or rem_v:
                parts.append(f"+{add_v}/-{rem_v} via")
            lines.append(f"{net}: {', '.join(parts)}")
    if lines:
        lines.append("run: python3 generator/extract_tracks.py BOARD --all "
                     "-o generator/pcb_routes.py")
    rep.section("G. signal copper", lines)


def check_outline(board, rep):
    lines = []
    outlines = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outlines, False):
        lines.append("board outline is not closed")
    else:
        bb = outlines.BBox()
        x0, y0 = bb.GetX() / 1e6 - OX, bb.GetY() / 1e6 - OY
        w, h = bb.GetWidth() / 1e6, bb.GetHeight() / 1e6
        ew, eh = pl.BOARD["size"]
        if abs(x0) > 0.05 or abs(y0) > 0.05:
            lines.append(f"outline origin ({x0:.3f},{y0:.3f}) != board (0,0)")
        if abs(w - ew) > 0.05 or abs(h - eh) > 0.05:
            lines.append(f"outline {w:.3f}x{h:.3f} != BOARD size {ew}x{eh}")
    rep.section("H. outline", lines)


# --- --apply: text surgery on generator/pcb_layout.py ------------------------

def place_tuple_text(nx, ny, nrot, nside):
    parts = [fmt_coord(nx), fmt_coord(ny), str(int(round(nrot)))]
    if nside:
        parts.append('"B"')
    return "(" + ", ".join(parts) + ")"


def apply_edits(rep):
    """Mirror PLACE + STITCH edits into generator/pcb_layout.py. Every changed
    line must match uniquely or nothing is written."""
    text = open(LAYOUT_PY).read()
    errors = []

    for ref, nx, ny, nrot, nside in rep.place_edits:
        pat = re.compile(rf'^(\s*)"{re.escape(ref)}":\s*\([^)]*\)(,)(.*)$', re.M)
        tup = place_tuple_text(nx, ny, nrot, nside)

        def repl(m, _ref=ref, _tup=tup):
            return f'{m.group(1)}"{_ref}": {_tup}{m.group(2)}{m.group(3)}'

        text, n = pat.subn(repl, text)
        if n != 1:
            errors.append(f'PLACE["{ref}"]: {n} matches (need exactly 1)')

    for entry in rep.stitch_del:
        tup = re.escape(tuple_str(entry))
        pat = re.compile(rf'^[ \t]*{tup},[^\n]*\n', re.M)
        text, n = pat.subn("", text)
        if n != 1:
            errors.append(f"STITCH {tuple_str(entry)}: {n} matches (need exactly 1)")

    if rep.stitch_add:
        m = re.search(r'^STITCH = \[', text, re.M)
        if not m:
            errors.append("STITCH list not found")
        else:
            close = text.index("\n]", m.end())
            block = "\n    # hand_diff harvest"
            for x, y, dia, drill in rep.stitch_add:
                sv = getattr(pl, "STITCH_VIA", pl.DEFAULT_VIA)
                if (round(dia, 3), round(drill, 3)) == (round(sv["diameter"], 3),
                                                        round(sv["drill"], 3)):
                    entry = (x, y)
                else:
                    entry = (x, y, dia, drill)
                block += f"\n    {tuple_str(entry)},"
            text = text[:close] + block + text[close:]

    if errors:
        print("hand_diff --apply: REFUSED, no file written:")
        for e in errors:
            print(f"    {e}")
        return False

    tmp = LAYOUT_PY + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, LAYOUT_PY)
    print(f"hand_diff --apply: wrote {len(rep.place_edits)} placement + "
          f"{len(rep.stitch_add)} added / {len(rep.stitch_del)} removed stitch "
          f"edit(s) to generator/pcb_layout.py")
    print("next: python3 generator/pcb.py  (regenerate), then the gate "
          "(make check, drc_summary --gate, check_pcb).")
    print("GND tracks / silk / copper-graphics / signal-sync from the report "
          "above are NOT auto-applied -- harvest them per their hints.")
    return True


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    positional = [a for a in args if not a.startswith("-")]
    board_path = positional[0] if positional else DEFAULT_BOARD

    try:
        import pcb_routes as routes
    except ImportError:
        routes = type("_", (), {"TRACKS": [], "VIAS": []})()

    board = pcbnew.LoadBoard(board_path)
    padctr = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            padctr[(fp.GetReference(), str(pad.GetNumber()))] = pad.GetPosition()
    alias = build_alias()

    print(f"hand_diff: {board_path}")
    rep = Report()
    check_placement(board, rep)
    check_existence(board, rep)
    check_copper_graphics(board, rep)
    check_stitch(board, rep)
    check_gnd_tracks(board, padctr, routes, rep)
    check_silk(board, rep)
    check_signal_copper(board, padctr, routes, alias, rep)
    check_outline(board, rep)

    if apply and (rep.place_edits or rep.stitch_add or rep.stitch_del):
        apply_edits(rep)
    elif apply:
        print("hand_diff --apply: nothing to mirror (placement + stitch clean)")

    if rep.dirty:
        print("hand_diff: unharvested differences")
        sys.exit(1)
    print("hand_diff: OK (fully mirrored)")


if __name__ == "__main__":
    main()
