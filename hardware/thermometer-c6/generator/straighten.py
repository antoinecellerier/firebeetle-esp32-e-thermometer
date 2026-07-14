#!/usr/bin/env python3
"""Board-wide squiggle straightener for generator/pcb_routes.py.

Simplifies hand-routed polylines by (1) merging exactly-collinear runs and
(2) deleting interior vertices whose removal shortens the copper, gated by a
render + DRC + check_pcb cycle so nothing that breaks clearance or
connectivity survives. Endpoints never move (they anchor to pads/vias/other
tracks); interior vertices that coincide with a same-net vertex or a via are
load-bearing junctions and are left alone.

    python3 generator/straighten.py [--layout] [--dry-run] [--sep MM] [--min-save MM]

--layout straightens pcb_layout.py's GND TRACKS instead of pcb_routes.py's
signal TRACKS (same gate; the GND lacing polylines take the identical
interior-vertex-delete + collinear-merge treatment).

--dry-run reports what the collinear pass and shortcut candidates would do
without rendering or touching pcb_routes.py. A real run rewrites pcb_routes.py
in place (same net order + float formatting, so the diff is only the changed
polylines) and leaves thermometer-c6.kicad_pcb rendered from the result.

Gate (a candidate/batch is rejected on any of): pcb.py failure; a DRC
violation whose type is not starved_thermal/silk_*; a non-GND unconnected
item; or verify/check_pcb.py failure. Geographically separated candidates
(> --sep apart) are batch-tested together and bisected on failure to isolate
the offenders, keeping the render/DRC count down.

A render+DRC cycle costs ~10s, so candidates are pre-screened geometrically
first: the shortcut chord must keep DRC clearance (0.2mm, 0.3mm for HV nets
outside the fpc-fanout area) to every other-net segment/via/pad (pad bboxes
read once from the rendered board) and stay out of the tracks-forbidden
keep-outs; and every same-net tee endpoint / via touching the replaced
segments mid-span must still lie on the chord. The screen is conservative
(pad bboxes, no J4-pad relaxation), which only costs missed candidates --
the DRC gate stays the source of truth for everything that passes.
"""
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

ROUTES = os.path.join(HERE, "pcb_routes.py")
LAYOUT = os.path.join(HERE, "pcb_layout.py")
BOARD = os.path.join(PROJECT, "thermometer-c6.kicad_pcb")
DRC_JSON = os.path.join(PROJECT, "out", "drc.json")

# Which polyline list to straighten: "routes" = pcb_routes.py TRACKS (signal
# copper), "layout" = pcb_layout.py TRACKS (the GND lacing). The gate is
# identical either way (pcb.py renders both files); only the load/write ends
# differ. Set from --layout in main().
TARGET = "routes"


def target_file():
    return LAYOUT if TARGET == "layout" else ROUTES

# DRC violation types that never gate copper edits: M6 pours + M7 silk.
WAIVED = {"starved_thermal", "silk_edge_clearance", "silk_overlap",
          "silk_over_copper"}

SEP = 5.0          # min mm between two candidates batched together
MIN_SAVE = 0.05    # skip shortcuts saving less than this
COLLINEAR_TOL = 1e-3   # mm perpendicular offset counted as collinear
BATCH_CAP = 32     # max candidates per batch (bounds bisection depth)
INDIV_THRESH = 6   # bisect down to this size, then test members one by one


def d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def r3(p):
    return (round(p[0], 3), round(p[1], 3))


def seg_pt_dist(p, a, b):
    """Distance from point p to segment a-b."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    ll = dx * dx + dy * dy
    if ll == 0:
        return d(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll))
    return d(p, (ax + t * dx, ay + t * dy))


def seg_seg_dist(a, b, c, e):
    """Distance between segments a-b and c-e (0 if they intersect)."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2 = orient(a, b, c), orient(a, b, e)
    o3, o4 = orient(c, e, a), orient(c, e, b)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)):
        return 0.0
    return min(seg_pt_dist(c, a, b), seg_pt_dist(e, a, b),
               seg_pt_dist(a, c, e), seg_pt_dist(b, c, e))


def seg_rect_dist(a, b, rect):
    """Distance from segment a-b to rectangle (x1,y1,x2,y2) (0 if touching)."""
    x1, y1, x2, y2 = rect
    inside = (x1 <= a[0] <= x2 and y1 <= a[1] <= y2) or \
             (x1 <= b[0] <= x2 and y1 <= b[1] <= y2)
    if inside:
        return 0.0
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return min(seg_seg_dist(a, b, corners[i], corners[(i + 1) % 4])
               for i in range(4))


# --- model I/O -------------------------------------------------------------

def load():
    """Fresh import of the target module -> (tracks, vias). tracks are mutable:
    [net, layer, width, [(x, y), ...]]. For the layout (GND) target the STITCH
    vias stand in for `vias` so GND vertices sitting on a stitch via are treated
    as load-bearing junctions."""
    import importlib
    if TARGET == "layout":
        # pcb_layout appends pcb_routes.TRACKS unless PCB_NO_ROUTES is set, so
        # reload with it set to get the GND-only list, then restore the env so
        # the subprocess renders (which own connectivity) still see full copper.
        prev = os.environ.get("PCB_NO_ROUTES")
        os.environ["PCB_NO_ROUTES"] = "1"
        try:
            import pcb_layout
            importlib.reload(pcb_layout)
            tracks = [[n, l, w, [tuple(p) for p in pts]]
                      for n, l, w, pts in pcb_layout.TRACKS]
            vias = [("GND", x, y) for (x, y) in pcb_layout.STITCH]
        finally:
            if prev is None:
                del os.environ["PCB_NO_ROUTES"]
            else:
                os.environ["PCB_NO_ROUTES"] = prev
        return tracks, vias
    import pcb_routes
    importlib.reload(pcb_routes)
    tracks = [[n, l, w, [tuple(p) for p in pts]]
              for n, l, w, pts in pcb_routes.TRACKS]
    return tracks, list(pcb_routes.VIAS)


def write(tracks, vias):
    """Rewrite the target file's TRACKS, preserving everything else and the
    extract_tracks.py formatting so unchanged entries stay byte-identical."""
    if TARGET == "layout":
        write_layout(tracks)
        return
    orig = open(ROUTES).read()
    head = orig[:orig.index("\nTRACKS = [\n") + 1]
    lines = [head + "TRACKS = ["]
    for net, layer, width, pts in tracks:
        body = ", ".join(f"({x}, {y})" for x, y in pts)
        lines.append(f"    ({net!r}, {layer!r}, {width}, [{body}]),")
    lines.append("]\n\nVIAS = [")
    for net, x, y in vias:
        lines.append(f"    ({net!r}, {x}, {y}),")
    lines.append("]")
    tmp = ROUTES + ".tmp"
    open(tmp, "w").write("\n".join(lines) + "\n")
    os.replace(tmp, ROUTES)


def write_layout(tracks):
    """Splice the GND TRACKS block back into pcb_layout.py in place, leaving
    VIAS/STITCH/PLACE/zones untouched. Double-quoted strings match the checked-in
    style so unchanged rows stay byte-identical."""
    src = open(LAYOUT).read()
    body = "\n".join(
        '    ("{}", "{}", {}, [{}]),'.format(
            net, layer, width,
            ", ".join(f"({x}, {y})" for x, y in pts))
        for net, layer, width, pts in tracks)
    m = re.search(r"TRACKS = \[\n.*?\n\]\nVIAS = \[\]", src, re.DOTALL)
    if not m:
        raise SystemExit("straighten: pcb_layout TRACKS/VIAS block not found")
    src = src[:m.start()] + "TRACKS = [\n" + body + "\n]\nVIAS = []" + src[m.end():]
    tmp = LAYOUT + ".tmp"
    open(tmp, "w").write(src)
    os.replace(tmp, LAYOUT)


def nverts(tracks):
    return sum(len(t[3]) for t in tracks)


def length(tracks):
    return sum(d(pts[i], pts[i + 1])
               for _, _, _, pts in tracks for i in range(len(pts) - 1))


# --- gate ------------------------------------------------------------------

def _run(cmd):
    # PYTHONDONTWRITEBYTECODE: this tool rewrites pcb_routes.py many times a
    # minute; a same-second same-size rewrite makes a stale __pycache__ entry
    # look valid and pcb.py then renders copper that is not on disk (phantom
    # DRC shorts). Disable bytecode caching for every child.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True,
                          env=env)


def gate():
    """Render + DRC + check_pcb. Returns (ok, reason)."""
    r = _run([sys.executable, os.path.join(HERE, "pcb.py")])
    if r.returncode != 0:
        return False, "pcb.py:" + (r.stderr.strip().splitlines() or ["?"])[-1]
    r = _run(["kicad-cli", "pcb", "drc", "--severity-all",
              "--schematic-parity", "--refill-zones", "--format", "json",
              "-o", DRC_JSON, BOARD])
    if r.returncode not in (0, 5):   # 5 = violations found (we judge from json)
        return False, "drc-cli:" + r.stderr.strip()[:80]
    dd = json.load(open(DRC_JSON))
    real = [v for v in dd.get("violations", []) if v.get("type") not in WAIVED]
    if real:
        h = {}
        for v in real:
            h[v["type"]] = h.get(v["type"], 0) + 1
        return False, "viol:" + ",".join(f"{k}x{n}" for k, n in h.items())
    # This tool straightens a FINISHED board (0 unconnected baseline), so any
    # new unconnected is a regression -- including GND. Waiving GND here (a
    # routing-era habit, where the pour reconnects it later) is unsafe: a GND
    # pad under a fills=False sensor keep-out has no pour to fall back on, so a
    # deleted vertex that was its only spur silently disconnects it.
    nunc = len(dd.get("unconnected_items", []))
    if nunc:
        return False, f"unconnected:{nunc}"
    if dd.get("schematic_parity"):
        return False, f"parity:{len(dd['schematic_parity'])}"
    r = _run([sys.executable, os.path.join(PROJECT, "verify", "check_pcb.py")])
    if r.returncode != 0:
        tail = (r.stdout.strip().splitlines() or ["?"])[-1]
        return False, "check_pcb:" + tail[:80]
    return True, "ok"


# --- passes ----------------------------------------------------------------

def collinear_pass(tracks):
    """Remove interior vertices that lie on the straight line between their
    neighbours (or duplicate a neighbour). Copper is unchanged to within
    COLLINEAR_TOL, so this needs no per-step gate."""
    removed = 0
    for t in tracks:
        pts = t[3]
        i = 1
        while i < len(pts) - 1:
            a, c, b = pts[i - 1], pts[i], pts[i + 1]
            drop = False
            if a == c or c == b:
                drop = True
            else:
                ab = d(a, b)
                if ab > 0:
                    cross = abs((b[0] - a[0]) * (c[1] - a[1])
                                - (b[1] - a[1]) * (c[0] - a[0]))
                    proj = ((c[0] - a[0]) * (b[0] - a[0])
                            + (c[1] - a[1]) * (b[1] - a[1])) / (ab * ab)
                    if cross / ab < COLLINEAR_TOL and 0 < proj < 1:
                        drop = True
            if drop:
                del pts[i]
                removed += 1
            else:
                i += 1
    return removed


def protected_coords(tracks, vias):
    """coord -> True for vertices that must not be deleted: a via, or a
    coordinate shared by >=2 same-net vertices (a junction/tee)."""
    from collections import Counter
    per_net = {}
    for net, _, _, pts in tracks:
        c = per_net.setdefault(net, Counter())
        for p in pts:
            c[r3(p)] += 1
    vset = {r3((x, y)) for _, x, y in vias}
    return per_net, vset


VIA_R = 0.3   # DEFAULT_VIA diameter 0.6 / 2
EPS = 1e-3    # geometric contact tolerance
SLACK = 1e-4  # do not reject chords sitting exactly at the DRC limit


def load_obstacles():
    """Static pre-screen context: pad bboxes from the rendered board (net
    names mapped back to circuit.py names), HV nets, fanout + keep-out rects.
    Pads/keep-outs never move during the sweep, so this loads once."""
    import pcbnew
    import pcb as pcbgen        # HV_NETS + exported-name alias map
    import pcb_layout as pl
    if not os.path.exists(BOARD):
        r = _run([sys.executable, os.path.join(HERE, "pcb.py")])
        if r.returncode != 0:
            raise SystemExit("straighten: cannot render board for pad extraction")
    rev = {e: c for c, e in pcbgen.build_net_maps()[2].items()}
    ox, oy = pl.BOARD["origin"]
    board = pcbnew.LoadBoard(BOARD)
    pads = []
    for fp in board.Footprints():
        for pad in fp.Pads():
            on_f = pad.IsOnLayer(pcbnew.F_Cu)
            on_b = pad.IsOnLayer(pcbnew.B_Cu)
            if not (on_f or on_b):
                continue
            bb = pad.GetBoundingBox()
            pads.append((rev.get(pad.GetNetname(), pad.GetNetname()),
                         on_f, on_b,
                         (bb.GetLeft() / 1e6 - ox, bb.GetTop() / 1e6 - oy,
                          bb.GetRight() / 1e6 - ox, bb.GetBottom() / 1e6 - oy)))
    return dict(
        pads=pads, hv=set(pcbgen.HV_NETS),
        fanout=next(k["rect"] for k in pl.KEEPOUTS if k["name"] == "fpc-fanout"),
        keepouts=[k["rect"] for k in pl.KEEPOUTS if k.get("tracks", True)],
        size=pl.BOARD["size"])


def _clr(net1, net2, obst, a, b):
    """DRC clearance between nets for a chord a-b: 0.3 for HV pairs, except
    inside the fpc-fanout area (actual rule 0.18; 0.2 used = conservative)."""
    if net1 in obst["hv"] or net2 in obst["hv"]:
        x1, y1, x2, y2 = obst["fanout"]
        if not (x1 <= min(a[0], b[0]) and max(a[0], b[0]) <= x2
                and y1 <= min(a[1], b[1]) and max(a[1], b[1]) <= y2):
            return 0.30
    return 0.20


def prescreen(tracks, vias, obst, ti, vi):
    """Cheap geometric screen for deleting vertex vi of track ti. Returns
    (ok, why). Conservative in the reject direction only for pads (bbox)."""
    net, layer, w, pts = tracks[ti]
    a, c, b = pts[vi - 1], pts[vi], pts[vi + 1]
    # same-net copper touching the replaced segments mid-span (a tee created
    # by pcb.py's split_tees, or a via) must still touch the chord
    for tj, (n2, _l2, _w2, p2) in enumerate(tracks):
        if n2 != net or tj == ti:
            continue
        for p in (p2[0], p2[-1]):
            if min(seg_pt_dist(p, a, c), seg_pt_dist(p, c, b)) < EPS \
                    and seg_pt_dist(p, a, b) >= EPS:
                return False, "tee"
    for n2, x, y in vias:
        if n2 == net and min(seg_pt_dist((x, y), a, c),
                             seg_pt_dist((x, y), c, b)) < EPS \
                and seg_pt_dist((x, y), a, b) >= EPS:
            return False, "via-tee"
    # clearance: chord vs other-net copper / keep-outs / board edge
    half = w / 2
    bx1, by1 = min(a[0], b[0]) - 2.0, min(a[1], b[1]) - 2.0
    bx2, by2 = max(a[0], b[0]) + 2.0, max(a[1], b[1]) + 2.0
    for n2, l2, w2, p2 in tracks:
        if n2 == net or l2 != layer:
            continue
        need = half + w2 / 2 + _clr(net, n2, obst, a, b) - SLACK
        for i in range(len(p2) - 1):
            q1, q2 = p2[i], p2[i + 1]
            if max(q1[0], q2[0]) < bx1 or min(q1[0], q2[0]) > bx2 \
                    or max(q1[1], q2[1]) < by1 or min(q1[1], q2[1]) > by2:
                continue
            if seg_seg_dist(a, b, q1, q2) < need:
                return False, f"trk:{n2}"
    for n2, x, y in vias:
        if n2 == net or not (bx1 <= x <= bx2 and by1 <= y <= by2):
            continue
        if seg_pt_dist((x, y), a, b) < half + VIA_R \
                + _clr(net, n2, obst, a, b) - SLACK:
            return False, f"via:{n2}"
    for n2, on_f, on_b, rect in obst["pads"]:
        if n2 == net or not (on_f if layer == "F.Cu" else on_b):
            continue
        if rect[2] < bx1 or rect[0] > bx2 or rect[3] < by1 or rect[1] > by2:
            continue
        if seg_rect_dist(a, b, rect) < half + _clr(net, n2, obst, a, b) - SLACK:
            return False, f"pad:{n2}"
    for rect in obst["keepouts"]:
        if seg_rect_dist(a, b, rect) < half - SLACK:
            return False, "keepout"
    bw, bh = obst["size"]
    edge = min(a[0], b[0], a[1], b[1], bw - a[0], bw - b[0],
               bh - a[1], bh - b[1])
    if edge < half + 0.2 - SLACK:
        return False, "edge"
    return True, ""


def candidates(tracks, vias, blacklist, min_save, obst, screened=None):
    """List of (saved, ti, vi, coord) for every deletable interior vertex
    that survives the geometric pre-screen."""
    per_net, vset = protected_coords(tracks, vias)
    out = []
    for ti, (net, _, _, pts) in enumerate(tracks):
        for vi in range(1, len(pts) - 1):
            a, c, b = pts[vi - 1], pts[vi], pts[vi + 1]
            cc = r3(c)
            if per_net[net][cc] >= 2 or cc in vset:
                continue
            if (net, cc) in blacklist:
                continue
            saved = d(a, c) + d(c, b) - d(a, b)
            if saved < min_save:
                continue
            ok, why = prescreen(tracks, vias, obst, ti, vi)
            if not ok:
                if screened is not None:
                    screened[why.split(":")[0]] = \
                        screened.get(why.split(":")[0], 0) + 1
                continue
            out.append((saved, ti, vi, c))
    out.sort(reverse=True)
    return out


def apply_removals(tracks, picks):
    """Return a deep-ish copy of tracks with the picked (ti, vi) vertices
    removed. picks vertices on the same track are non-adjacent by construction
    so index-set removal is well defined."""
    drop = {}
    for _, ti, vi, _ in picks:
        drop.setdefault(ti, set()).add(vi)
    new = []
    for ti, (net, layer, width, pts) in enumerate(tracks):
        if ti in drop:
            pts = [p for j, p in enumerate(pts) if j not in drop[ti]]
        new.append([net, layer, width, list(pts)])
    return new


def commit_and_gate(base, picks, vias):
    """Write base+picks, render, gate. Returns (ok, reason)."""
    write(apply_removals(base, picks), vias)
    return gate()


def _reject(base, cand, reason, stats):
    s, ti, _vi, coord = cand
    stats["rejected"].append((base[ti][0], coord, s, reason))


def _sift(base, batch, vias, stats):
    """Bisect to isolate offenders; below INDIV_THRESH test members one by
    one. Returns candidates that each passed in a gated group (a whole-passing
    sub-batch or a passing singleton). No cross-group guarantee -- resolve()
    adds the single top-level union confirm."""
    ok, reason = commit_and_gate(base, batch, vias)
    stats["gates"] += 1
    if ok:
        return list(batch)
    if len(batch) == 1:
        _reject(base, batch[0], reason, stats)
        return []
    if len(batch) <= INDIV_THRESH:
        keep = []
        for c in batch:
            ok, reason = commit_and_gate(base, [c], vias)
            stats["gates"] += 1
            if ok:
                keep.append(c)
            else:
                _reject(base, c, reason, stats)
        return keep
    mid = len(batch) // 2
    return (_sift(base, batch[:mid], vias, stats)
            + _sift(base, batch[mid:], vias, stats))


def resolve(base, batch, vias, stats):
    """Subset of `batch` guaranteed to pass the gate as a whole."""
    keep = _sift(base, batch, vias, stats)
    if len(keep) == len(batch) or len(keep) < 2:
        return keep  # whole batch passed, or 0/1 survivor: already validated
    ok, _ = commit_and_gate(base, keep, vias)
    stats["gates"] += 1
    if ok:
        return keep
    # rare cross-candidate interaction: rebuild greedily (batch is saved-sorted)
    acc = []
    for c in keep:
        ok, _ = commit_and_gate(base, acc + [c], vias)
        stats["gates"] += 1
        if ok:
            acc.append(c)
    return acc


def build_batch(cands):
    """Greedy max batch of mutually compatible candidates: > SEP apart, and
    non-adjacent when on the same track."""
    batch = []
    for cand in cands:
        _, ti, vi, coord = cand
        ok = True
        for _, tj, vj, cj in batch:
            if d(coord, cj) <= SEP or (ti == tj and abs(vi - vj) < 2):
                ok = False
                break
        if ok:
            batch.append(cand)
            if len(batch) >= BATCH_CAP:
                break
    return batch


# --- main ------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    global SEP, MIN_SAVE, TARGET
    if "--layout" in args:
        TARGET = "layout"
    if "--sep" in args:
        SEP = float(args[args.index("--sep") + 1])
    if "--min-save" in args:
        MIN_SAVE = float(args[args.index("--min-save") + 1])

    tracks, vias = load()
    v0, l0 = nverts(tracks), length(tracks)

    coll = collinear_pass(tracks)
    obst = load_obstacles()
    screened = {}
    cands = candidates(tracks, vias, set(), MIN_SAVE, obst, screened)

    if dry:
        print(f"straighten --dry-run  (sep={SEP} min-save={MIN_SAVE})")
        print(f"  vertices: {v0}  track length: {l0:.1f}mm")
        print(f"  collinear merges available: {coll}")
        print(f"  shortcut candidates: {len(cands)}  "
              f"potential save (single pass) ~"
              f"{sum(c[0] for c in cands):.2f}mm")
        print(f"  pre-screened out: {sum(screened.values())}  {screened}")
        print(f"  projected vertices after collinear pass: {nverts(tracks)}")
        print("  (dry run: nothing written, no DRC)")
        return

    # collinear pass is free but still validated by the first gate.
    baseline = open(target_file()).read()
    write(tracks, vias)
    ok, reason = gate()
    if not ok:
        # restore the pre-run file and re-render -- never leave the tree
        # in a failed intermediate state
        open(target_file(), "w").write(baseline)
        _run([sys.executable, os.path.join(HERE, "pcb.py")])
        print(f"straighten: collinear pass failed the gate ({reason}); "
              f"aborted and restored")
        sys.exit(1)
    print(f"collinear pass: removed {coll} vertices, gate ok "
          f"({nverts(tracks)} verts, {length(tracks):.1f}mm)", flush=True)

    stats = {"gates": 1, "rejected": []}
    blacklist = set()
    accepted = 0
    it = 0
    while True:
        cands = candidates(tracks, vias, blacklist, MIN_SAVE, obst)
        if not cands:
            break
        batch = build_batch(cands)
        it += 1
        keep = resolve(tracks, batch, vias, stats)
        for _, ti, vi, coord in batch:
            if all((ti, vi) != (kt, kv) for _, kt, kv, _ in keep):
                blacklist.add((tracks[ti][0], r3(coord)))
        tracks = apply_removals(tracks, keep)
        accepted += len(keep)
        print(f"iter {it:3d}: batch {len(batch):2d}  accepted {len(keep):2d}  "
              f"(total {accepted}, rejected {len(stats['rejected'])}, "
              f"gates {stats['gates']}, verts {nverts(tracks)})", flush=True)

    write(tracks, vias)
    ok, reason = gate()
    v1, l1 = nverts(tracks), length(tracks)
    tried = accepted + len(stats["rejected"])
    print("\n=== straighten summary ===")
    print(f"vertices:     {v0} -> {v1}  ({v0 - v1} removed; "
          f"{coll} collinear + {accepted} shortcut)")
    print(f"track length: {l0:.2f} -> {l1:.2f} mm  (-{l0 - l1:.2f})")
    print(f"candidates:   tried {tried}, accepted {accepted}, "
          f"rejected {len(stats['rejected'])}")
    print(f"gate cycles:  {stats['gates']};  final gate: {reason}")
    if stats["rejected"]:
        print("rejections (net @ coord, saved, reason):")
        for net, coord, s, why in sorted(stats["rejected"],
                                         key=lambda x: -x[2])[:15]:
            print(f"  {net:14} @({coord[0]},{coord[1]})  "
                  f"{s:.2f}mm  {why}")
        if len(stats["rejected"]) > 15:
            print(f"  ... +{len(stats['rejected']) - 15} more")
    if not ok:
        print("WARNING: final gate not clean")
        sys.exit(1)


if __name__ == "__main__":
    main()
