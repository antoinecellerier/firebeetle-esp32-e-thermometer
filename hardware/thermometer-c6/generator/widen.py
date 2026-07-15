#!/usr/bin/env python3
"""Board-wide track widener for the two authored copper lists.

Grows every track toward a per-class width cap, keeping the widest value that a
render + DRC + check_pcb cycle still passes -- so nothing that breaks clearance,
shorts a net or drops a connection survives. Widths only ever increase; the gate
is the sole authority for what is kept.

    python3 generator/widen.py [--layout] [--dry-run] [--sep MM] [--step MM]

Default target is pcb_routes.py's signal TRACKS (which also carry the power
nets); --layout widens pcb_layout.py's GND lacing instead. Same gate either way
(pcb.py renders both files). A real run rewrites the target file in place with
the extract_tracks.py formatting (only the changed widths differ) and leaves
thermometer-c6.kicad_pcb rendered from the result; --dry-run reports the plan
without rendering or writing.

Per-class caps (a track already wider than its cap is left untouched -- widths
never shrink):
  * signal (SPI/I2C/UART/USB/GPIO/HV escapes): cap 0.30mm, floor raise to 0.25+
    where it fits.
  * GND: cap 0.50mm. The thin sub-0.25 necks that verify/gnd_islands.py flags as
    the ground BOTTLENECK are widened first (thinnest-first ordering), clearing
    them past 0.25 before the rest fatten.
  * power / burst (EPD_VCC, +3V3, VBAT, VSYS, VBUS, ~VBAT_RAW, ~BAT_IN): cap
    0.70mm. Only the burst-carrying segments (>= 0.4mm today) are grown; the thin
    fanout-relaxation / pull-up stubs (< 0.4mm, incl. EPD_VCC's 0.25/0.3 J4
    escapes) are left as-is so the tight fpc-fanout pitch stays routable. Every
    kept width stays >= any DRU min-width rule because it only grows.

Algorithm (mirrors straighten.py's gated-batch/bisect scaffold): each track
climbs a --step ladder one rung per iteration. A geometric pre-screen drops a
rung that clearly cannot clear its neighbours (clearance 0.2mm, 0.3mm HV outside
the fpc-fanout, pad bboxes, keep-outs, board edge) so hopeless rungs never reach
the gate; the survivors -- greedily chosen so batched tracks' bboxes stay > --sep
apart, hence non-interacting -- are gated together and bisected to isolate any
offender. A gate rejection freezes that track (widths are monotone: if +step
fails DRC, wider fails too). Runs to an internal fixpoint; re-run fresh until it
widens nothing (the greedy order can leave a straggler that a settled neighbour
now permits).
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

# "routes" = pcb_routes.py TRACKS (signal + power copper); "layout" =
# pcb_layout.py TRACKS (GND lacing). Set from --layout in main().
TARGET = "routes"

# DRC violation types that never gate copper edits: M6 pours + M7 silk.
WAIVED = {"starved_thermal", "silk_edge_clearance", "silk_overlap",
          "silk_over_copper"}

# --- net classes + caps ----------------------------------------------------
POWER_NETS = {"EPD_VCC", "+3V3", "VBAT", "VSYS", "VBUS", "~VBAT_RAW", "~BAT_IN"}
CAP = {"signal": 0.30, "gnd": 0.50, "power": 0.70}
# only the burst-carrying power segments (>= this today) are grown; thinner ones
# are stubs / fanout escapes that must stay narrow.
POWER_MIN_WIDEN = 0.40

SEP = 2.0          # min mm bbox gap between two tracks batched together
STEP = 0.05        # width ladder increment
BATCH_CAP = 24     # max candidates per batch (bounds bisection depth)
INDIV_THRESH = 6   # bisect down to this size, then test members one by one
SLACK = 1e-4       # don't reject a rung sitting exactly at the DRC limit
VIA_DEF_R = 0.3    # DEFAULT_VIA 0.6 / 2


def klass(net):
    if net == "GND":
        return "gnd"
    if net in POWER_NETS:
        return "power"
    return "signal"


def d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_sep(A, B, sep):
    """True if bboxes A and B are more than `sep` apart (cannot interact)."""
    return (A[2] + sep < B[0] or B[2] + sep < A[0]
            or A[3] + sep < B[1] or B[3] + sep < A[1])


# --- geometry (shared with straighten.py) ----------------------------------

def seg_pt_dist(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    ll = dx * dx + dy * dy
    if ll == 0:
        return d(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll))
    return d(p, (ax + t * dx, ay + t * dy))


def seg_seg_dist(a, b, c, e):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2 = orient(a, b, c), orient(a, b, e)
    o3, o4 = orient(c, e, a), orient(c, e, b)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)):
        return 0.0
    return min(seg_pt_dist(c, a, b), seg_pt_dist(e, a, b),
               seg_pt_dist(a, c, e), seg_pt_dist(b, c, e))


def seg_rect_dist(a, b, rect):
    x1, y1, x2, y2 = rect
    inside = (x1 <= a[0] <= x2 and y1 <= a[1] <= y2) or \
             (x1 <= b[0] <= x2 and y1 <= b[1] <= y2)
    if inside:
        return 0.0
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return min(seg_seg_dist(a, b, corners[i], corners[(i + 1) % 4])
               for i in range(4))


# --- model I/O -------------------------------------------------------------

def target_file():
    return LAYOUT if TARGET == "layout" else ROUTES


def load():
    """Fresh import of the target module -> (tracks, vias). tracks are mutable
    [net, layer, width, [(x,y),...]]. vias are passed through write() unchanged
    (widen never touches vias)."""
    import importlib
    if TARGET == "layout":
        prev = os.environ.get("PCB_NO_ROUTES")
        os.environ["PCB_NO_ROUTES"] = "1"
        try:
            import pcb_layout
            importlib.reload(pcb_layout)
            tracks = [[n, l, w, [tuple(p) for p in pts]]
                      for n, l, w, pts in pcb_layout.TRACKS]
        finally:
            if prev is None:
                del os.environ["PCB_NO_ROUTES"]
            else:
                os.environ["PCB_NO_ROUTES"] = prev
        return tracks, None
    import pcb_routes
    importlib.reload(pcb_routes)
    tracks = [[n, l, w, [tuple(p) for p in pts]]
              for n, l, w, pts in pcb_routes.TRACKS]
    return tracks, list(pcb_routes.VIAS)


def write(tracks, vias):
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
    src = open(LAYOUT).read()
    body = "\n".join(
        '    ("{}", "{}", {}, [{}]),'.format(
            net, layer, width,
            ", ".join(f"({x}, {y})" for x, y in pts))
        for net, layer, width, pts in tracks)
    m = re.search(r"TRACKS = \[\n.*?\n\]\nVIAS = \[\]", src, re.DOTALL)
    if not m:
        raise SystemExit("widen: pcb_layout TRACKS/VIAS block not found")
    src = src[:m.start()] + "TRACKS = [\n" + body + "\n]\nVIAS = []" + src[m.end():]
    tmp = LAYOUT + ".tmp"
    open(tmp, "w").write(src)
    os.replace(tmp, LAYOUT)


# --- gate ------------------------------------------------------------------

def _run(cmd):
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
    if r.returncode not in (0, 5):
        return False, "drc-cli:" + r.stderr.strip()[:80]
    dd = json.load(open(DRC_JSON))
    real = [v for v in dd.get("violations", []) if v.get("type") not in WAIVED]
    if real:
        h = {}
        for v in real:
            h[v["type"]] = h.get(v["type"], 0) + 1
        return False, "viol:" + ",".join(f"{k}x{n}" for k, n in h.items())
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


# --- pre-screen obstacle context -------------------------------------------

def load_obstacles():
    """Static context: pad bboxes from the rendered board (mapped to circuit
    net names), HV nets, fanout + keep-out rects, board size. Loaded once."""
    import pcbnew
    import pcb as pcbgen
    import pcb_layout as pl
    if not os.path.exists(BOARD):
        r = _run([sys.executable, os.path.join(HERE, "pcb.py")])
        if r.returncode != 0:
            raise SystemExit("widen: cannot render board for pad extraction")
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


def load_ext():
    """Copper on the OTHER file (static obstacles): (ext_tracks, ext_vias).
    ext_tracks = [(net, layer, width, pts)]; ext_vias = [(net, x, y, radius)]."""
    import importlib
    import pcb_routes
    importlib.reload(pcb_routes)
    routes_tracks = [(n, l, w, [tuple(p) for p in pts])
                     for n, l, w, pts in pcb_routes.TRACKS]
    routes_vias = [(n, x, y, VIA_DEF_R) for n, x, y in pcb_routes.VIAS]

    prev = os.environ.get("PCB_NO_ROUTES")
    os.environ["PCB_NO_ROUTES"] = "1"
    try:
        import pcb_layout
        importlib.reload(pcb_layout)
        gnd_tracks = [(n, l, w, [tuple(p) for p in pts])
                      for n, l, w, pts in pcb_layout.TRACKS]
        sr = pcb_layout.STITCH_VIA["diameter"] / 2
        stitch = [("GND", e[0], e[1], (e[2] / 2 if len(e) > 3 else sr))
                  for e in pcb_layout.STITCH]
    finally:
        if prev is None:
            del os.environ["PCB_NO_ROUTES"]
        else:
            os.environ["PCB_NO_ROUTES"] = prev

    if TARGET == "layout":            # target GND -> ext is the routed copper
        return routes_tracks, routes_vias
    # target routes -> ext is the GND lace + every via (routed + stitch)
    return gnd_tracks, routes_vias + stitch


def build_ctx(tracks):
    ctx = load_obstacles()
    ext_tracks, ext_vias = load_ext()
    ctx["ext_tracks"] = ext_tracks
    ctx["ext_bbox"] = [(bbox(pts), t) for t in ext_tracks for pts in (t[3],)]
    ctx["ext_vias"] = ext_vias
    return ctx


def clr(net1, net2, ctx, a, b):
    """DRC clearance for a segment a-b between nets: 0.3 for HV pairs, except
    fully inside the fpc-fanout area (rule 0.18; 0.2 used = conservative)."""
    if net1 in ctx["hv"] or net2 in ctx["hv"]:
        x1, y1, x2, y2 = ctx["fanout"]
        if not (x1 <= min(a[0], b[0]) and max(a[0], b[0]) <= x2
                and y1 <= min(a[1], b[1]) and max(a[1], b[1]) <= y2):
            return 0.30
    return 0.20


def track_fits(tracks, ctx, ti, w):
    """Cheap geometric screen: can track ti carry width w without breaking
    clearance to any other-net copper / keep-out / board edge? Conservative in
    the reject direction (pad bboxes); the gate is the source of truth."""
    net, layer, _, pts = tracks[ti]
    half = w / 2
    bw, bh = ctx["size"]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        sx1, sy1 = min(a[0], b[0]) - 2.0, min(a[1], b[1]) - 2.0
        sx2, sy2 = max(a[0], b[0]) + 2.0, max(a[1], b[1]) + 2.0
        # same-file other-net tracks (live widths)
        for tj, (n2, l2, w2, p2) in enumerate(tracks):
            if tj == ti or n2 == net or l2 != layer:
                continue
            need = half + w2 / 2 + clr(net, n2, ctx, a, b) - SLACK
            for k in range(len(p2) - 1):
                q1, q2 = p2[k], p2[k + 1]
                if max(q1[0], q2[0]) < sx1 or min(q1[0], q2[0]) > sx2 \
                        or max(q1[1], q2[1]) < sy1 or min(q1[1], q2[1]) > sy2:
                    continue
                if seg_seg_dist(a, b, q1, q2) < need:
                    return False
        # other-file tracks (static)
        for bb, (n2, l2, w2, p2) in ctx["ext_bbox"]:
            if n2 == net or l2 != layer:
                continue
            if bb[2] < sx1 or bb[0] > sx2 or bb[3] < sy1 or bb[1] > sy2:
                continue
            need = half + w2 / 2 + clr(net, n2, ctx, a, b) - SLACK
            for k in range(len(p2) - 1):
                if seg_seg_dist(a, b, p2[k], p2[k + 1]) < need:
                    return False
        # vias (both layers)
        for n2, x, y, r in ctx["ext_vias"]:
            if n2 == net or not (sx1 <= x <= sx2 and sy1 <= y <= sy2):
                continue
            if seg_pt_dist((x, y), a, b) < half + r + clr(net, n2, ctx, a, b) - SLACK:
                return False
        # pads
        for n2, on_f, on_b, rect in ctx["pads"]:
            if n2 == net or not (on_f if layer == "F.Cu" else on_b):
                continue
            if rect[2] < sx1 or rect[0] > sx2 or rect[3] < sy1 or rect[1] > sy2:
                continue
            if seg_rect_dist(a, b, rect) < half + clr(net, n2, ctx, a, b) - SLACK:
                return False
        # track-forbidding keep-outs
        for rect in ctx["keepouts"]:
            if seg_rect_dist(a, b, rect) < half - SLACK:
                return False
        # board edge (copper-edge-clearance 0.2)
        edge = min(a[0], b[0], a[1], b[1], bw - a[0], bw - b[0],
                   bh - a[1], bh - b[1])
        if edge < half + 0.2 - SLACK:
            return False
    return True


# --- candidate width ladder ------------------------------------------------

def inside_fanout(pts, ctx):
    fx1, fy1, fx2, fy2 = ctx["fanout"]
    bx = bbox(pts)
    return fx1 <= bx[0] and bx[2] <= fx2 and fy1 <= bx[1] and bx[3] <= fy2


def next_width(net, w, pts, ctx):
    """Next ladder rung for a track (net, width w), or None if ineligible /
    at cap."""
    k = klass(net)
    cap = CAP[k]
    if k == "power":
        if w < POWER_MIN_WIDEN:      # thin stub / fanout escape: leave narrow
            return None
        if inside_fanout(pts, ctx):
            return None
    nxt = round(w + STEP, 3)
    if nxt > cap + 1e-9:
        return None
    return nxt


# --- batch gate + bisect (mirrors straighten.py) ---------------------------

def apply_widths(tracks, picks):
    setw = {ti: w for _, ti, w in picks}
    return [[n, l, setw.get(ti, w), list(pts)]
            for ti, (n, l, w, pts) in enumerate(tracks)]


def commit_and_gate(base, picks, vias):
    write(apply_widths(base, picks), vias)
    return gate()


def _sift(base, batch, vias, stats):
    ok, reason = commit_and_gate(base, batch, vias)
    stats["gates"] += 1
    if ok:
        return list(batch)
    if len(batch) == 1:
        stats["rejected"].append((base[batch[0][1]][0], batch[0][2], reason))
        return []
    if len(batch) <= INDIV_THRESH:
        keep = []
        for c in batch:
            ok, reason = commit_and_gate(base, [c], vias)
            stats["gates"] += 1
            if ok:
                keep.append(c)
            else:
                stats["rejected"].append((base[c[1]][0], c[2], reason))
        return keep
    mid = len(batch) // 2
    return (_sift(base, batch[:mid], vias, stats)
            + _sift(base, batch[mid:], vias, stats))


def resolve(base, batch, vias, stats):
    keep = _sift(base, batch, vias, stats)
    if len(keep) == len(batch) or len(keep) < 2:
        return keep
    ok, _ = commit_and_gate(base, keep, vias)
    stats["gates"] += 1
    if ok:
        return keep
    acc = []
    for c in keep:
        ok, _ = commit_and_gate(base, acc + [c], vias)
        stats["gates"] += 1
        if ok:
            acc.append(c)
    return acc


def build_batch(cands, boxes):
    batch = []
    for cand in cands:
        ti = cand[1]
        if all(bbox_sep(boxes[ti], boxes[c[1]], SEP) for c in batch):
            batch.append(cand)
            if len(batch) >= BATCH_CAP:
                break
    return batch


# --- reporting -------------------------------------------------------------

def length(pts):
    return sum(d(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def dist(tracks):
    """class -> {width: count} distribution."""
    out = {}
    for net, _, w, _ in tracks:
        out.setdefault(klass(net), {})
        out[klass(net)][w] = out[klass(net)].get(w, 0) + 1
    return out


def copper_area(tracks):
    return sum(w * length(pts) for _, _, w, pts in tracks)


def fmt_dist(dd):
    return "  ".join(f"{k}:{{" + ", ".join(f"{w}:{n}" for w, n in
                     sorted(dd[k].items())) + "}" for k in sorted(dd))


# --- main ------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    global SEP, STEP, TARGET
    if "--layout" in args:
        TARGET = "layout"
    if "--sep" in args:
        SEP = float(args[args.index("--sep") + 1])
    if "--step" in args:
        STEP = float(args[args.index("--step") + 1])

    tracks, vias = load()
    ctx = build_ctx(tracks)
    boxes = {ti: bbox(t[3]) for ti, t in enumerate(tracks)}
    d0 = dist(tracks)
    a0 = copper_area(tracks)

    if dry:
        elig = [ti for ti, (n, _, w, pts) in enumerate(tracks)
                if next_width(n, w, pts, ctx) is not None]
        fits = sum(1 for ti in elig
                   if track_fits(tracks, ctx, ti, next_width(
                       tracks[ti][0], tracks[ti][2], tracks[ti][3], ctx)))
        print(f"widen --dry-run  target={TARGET} sep={SEP} step={STEP}")
        print(f"  tracks: {len(tracks)}   copper-area: {a0:.1f} mm.mm")
        print(f"  width distribution: {fmt_dist(d0)}")
        print(f"  eligible to grow +1 rung: {len(elig)}   pass pre-screen now: "
              f"{fits}")
        print("  (dry run: nothing written, no DRC)")
        return

    stats = {"gates": 0, "rejected": []}
    frozen = set()
    advanced = 0
    it = 0
    while True:
        cands = []
        for ti, (net, layer, w, pts) in enumerate(tracks):
            if ti in frozen:
                continue
            nxt = next_width(net, w, pts, ctx)
            if nxt is None:
                frozen.add(ti)
                continue
            if not track_fits(tracks, ctx, ti, nxt):
                frozen.add(ti)
                continue
            cands.append((w, ti, nxt))     # (current width -> thinnest first)
        if not cands:
            break
        cands.sort()
        batch = build_batch(cands, boxes)
        it += 1
        keep = resolve(tracks, batch, vias, stats)
        keepset = {ti for _, ti, _ in keep}
        for _, ti, nxt in batch:
            if ti in keepset:
                tracks[ti][2] = nxt
                advanced += 1
            else:
                frozen.add(ti)
        print(f"iter {it:3d}: batch {len(batch):2d}  advanced {len(keepset):2d}  "
              f"(rungs {advanced}, frozen {len(frozen)}, gates {stats['gates']})",
              flush=True)

    write(tracks, vias)
    ok, reason = gate()
    d1 = dist(tracks)
    a1 = copper_area(tracks)
    print("\n=== widen summary ===")
    print(f"target:       {TARGET}")
    print(f"width dist before: {fmt_dist(d0)}")
    print(f"width dist after:  {fmt_dist(d1)}")
    print(f"copper-area:  {a0:.1f} -> {a1:.1f} mm.mm  (+{a1 - a0:.1f})")
    print(f"rungs climbed: {advanced}   iterations: {it}   "
          f"gate cycles: {stats['gates'] + 1}")
    if stats["rejected"]:
        from collections import Counter
        rc = Counter(r[2].split(":")[0] for r in stats["rejected"])
        print(f"rung rejections: {len(stats['rejected'])}  {dict(rc)}")
    print(f"final gate: {reason}")
    if not ok:
        print("WARNING: final gate not clean")
        sys.exit(1)


if __name__ == "__main__":
    main()
