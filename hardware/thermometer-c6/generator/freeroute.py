#!/usr/bin/env python3
"""Freerouting DSN round-trip: render a variant board, export Specctra DSN,
post-process it (net classes + fixed authored copper), run the Freerouting
jar, import the .ses and save a routed board copy for review/harvest.

Variants:
  a   full board (authored + pcb_routes): authored copper is marked
      (type fix), the 35 settled free nets stay rippable -- Freerouting
      negotiates the 12 stragglers against them.
  b   authored copper only (PCB_NO_ROUTES=1): Freerouting routes every free
      net from scratch; authored copper fixed.

DSN post-processing (KiCad's exporter emits a single flat class):
  - global/default width 200um -> 250um (signal track width)
  - class `power` (pcb.POWER_NETS): width 500um
  - class `hv`   (pcb.HV_NETS):    clearance 300um
    The 0.18mm fpc-fanout relaxation cannot be expressed in DSN -- the
    authored fanout copper is fixed instead, so Freerouting never has to
    recreate it. Final legality is judged by `make drc` after harvest,
    never by Freerouting's own rules.
  - with --fix, authored wires/vias -> (type fix): matched by segment
    coverage against the authored-only board's DSN export (deterministic
    coordinates). CAVEAT: Freerouting 1.9's batch autorouter SKIPS every
    net that contains a fixed wire (verified empirically 2026-07-11:
    identical DSNs with/without fix marking; the fixed-copper nets are
    absent from the .ses with it, routed without it). So --fix protects
    authored copper at the cost of excluding its nets from routing --
    default is no fix marking, everything rippable.

Output (out/freerouting/): <v>-base.kicad_pcb, <v>.dsn, <v>.ses,
routed-<v>.kicad_pcb (+ .kicad_dru copy so kicad-cli drc applies the real
rules). Prints Freerouting's incomplete count and a DRC summary.

Run under KiCad python (needs pcbnew), from the project root or anywhere:
  python3 generator/freeroute.py --variant a --jar out/freerouting/freerouting-1.9.0.jar
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402

import pcb  # noqa: E402  (POWER_NETS/HV_NETS/build_net_maps; no side effects)

OUTDIR = os.path.join(PROJECT, "out", "freerouting")
DRU = os.path.join(PROJECT, "thermometer-c6.kicad_dru")


# ---------------------------------------------------------------- rendering

def render_variant(tag, no_routes):
    """Render the board via pcb.py into out/freerouting/<tag>.kicad_pcb
    without touching the checked-in board file."""
    path = os.path.join(OUTDIR, tag + ".kicad_pcb")
    env = dict(os.environ)
    env.pop("PCB_NO_ROUTES", None)
    if no_routes:
        env["PCB_NO_ROUTES"] = "1"
    code = ("import sys; sys.path.insert(0, %r); import pcb; "
            "pcb.BOARD_PATH = %r; pcb.main()" % (HERE, path))
    subprocess.run([sys.executable, "-c", code], env=env, check=True,
                   cwd=PROJECT, stdout=subprocess.DEVNULL)
    return path


def export_dsn(board_path, dsn_path):
    board = pcbnew.LoadBoard(board_path)
    if not pcbnew.ExportSpecctraDSN(board, dsn_path):
        raise SystemExit(f"freeroute: DSN export failed for {board_path}")
    return dsn_path


# ------------------------------------------------------- DSN post-processing

WIRE_RE = re.compile(
    r'\(wire \(path (?P<layer>\S+) (?P<width>\d+)(?P<pts>(?:\s+-?\d+)+)\)'
    r'\(net (?P<net>"[^"]*"|\S+?)\)\(type route\)\)')
VIA_RE = re.compile(
    r'\(via "[^"]+"\s+(?P<x>-?\d+) (?P<y>-?\d+) '
    r'\(net (?P<net>"[^"]*"|\S+?)\)\(type route\)\)')


def wire_segments(m):
    nums = [int(t) for t in m.group("pts").split()]
    pts = list(zip(nums[0::2], nums[1::2]))
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def on_seg(p, a, b):
    """p on closed segment ab (integer coords)."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    ex, ey = px - ax, py - ay
    if dx * ey - dy * ex != 0:
        return False
    dot = ex * dx + ey * dy
    return 0 <= dot <= dx * dx + dy * dy


def covered(seg, authored_segs):
    p, q = seg
    return any(on_seg(p, a, b) and on_seg(q, a, b) for a, b in authored_segs)


def authored_geometry(dsn_text):
    """(net, layer, width) -> [segments], and set of via (net, x, y)."""
    segs = {}
    for m in WIRE_RE.finditer(dsn_text):
        key = (m.group("net"), m.group("layer"), m.group("width"))
        segs.setdefault(key, []).extend(wire_segments(m))
    vias = {(m.group("net"), int(m.group("x")), int(m.group("y")))
            for m in VIA_RE.finditer(dsn_text)}
    return segs, vias


def fix_authored(dsn_text, authored_segs, authored_vias):
    """Mark wires/vias covered by authored copper as (type fix)."""
    counts = [0, 0]

    def fix_wire(m):
        key = (m.group("net"), m.group("layer"), m.group("width"))
        auth = authored_segs.get(key)
        if auth and all(covered(s, auth) for s in wire_segments(m)):
            counts[0] += 1
            return m.group(0).replace("(type route)", "(type fix)")
        return m.group(0)

    def fix_via(m):
        if (m.group("net"), int(m.group("x")), int(m.group("y"))) in authored_vias:
            counts[1] += 1
            return m.group(0).replace("(type route)", "(type fix)")
        return m.group(0)

    dsn_text = WIRE_RE.sub(fix_wire, dsn_text)
    dsn_text = VIA_RE.sub(fix_via, dsn_text)
    return dsn_text, counts


def dsn_name(net):
    """Quote a net name the way the DSN expects (KiCad quotes anything with
    characters outside [A-Za-z0-9_+])."""
    return net if re.fullmatch(r"[A-Za-z0-9_+]+", net) else '"%s"' % net


def find_block(text, start):
    """Span of the balanced s-expression starting at text[start] == '('."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise SystemExit("freeroute: unbalanced DSN")


def tokenize(s):
    return re.findall(r'"[^"]*"|\S+', s)


def add_classes(dsn_text, alias):
    """Widths/clearances: default 250um; power nets 500um; HV nets 300um
    clearance. Nets move out of kicad_default into new classes."""
    power = {dsn_name(alias[n]) for n in pcb.POWER_NETS}
    hv = {dsn_name(alias[n]) for n in pcb.HV_NETS}

    start = dsn_text.index("(class kicad_default")
    s, e = find_block(dsn_text, start)
    block = dsn_text[s:e]
    head_end = block.index("(circuit")
    tokens = tokenize(block[len("(class kicad_default"):head_end])
    kept = [t for t in tokens if t not in power and t not in hv]
    missing = (power | hv) - set(tokens)
    if missing:
        raise SystemExit(f"freeroute: nets not in kicad_default class: {missing}")
    new_default = ("(class kicad_default " + " ".join(kept) + "\n      "
                   + block[head_end:])

    def cls(name, nets, width, clearance):
        return ("\n    (class %s %s\n"
                "      (circuit\n        (use_via \"Via[0-1]_600:300_um\")\n      )\n"
                "      (rule\n        (width %d)\n        (clearance %d)\n      )\n"
                "    )" % (name, " ".join(sorted(nets)), width, clearance))

    extra = cls("power", power, 500, 200) + cls("hv", hv, 250, 300)
    dsn_text = dsn_text[:s] + new_default + extra + dsn_text[e:]
    return dsn_text.replace("(width 200)", "(width 250)")


# ------------------------------------------------------------ run + import

def run_freerouting(jar, dsn, ses, passes, timeout):
    cmd = ["java", "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(passes)]
    print("freeroute: running", " ".join(os.path.basename(c) for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log = ses.replace(".ses", "-freerouting.log")
    open(log, "w").write(r.stdout + r.stderr)
    tail = [ln for ln in (r.stdout + r.stderr).splitlines()
            if re.search(r"incomplete|completed|score|ERROR|not found|unrouted",
                         ln, re.I)]
    for ln in tail[-15:]:
        print("  " + ln.strip())
    if not os.path.exists(ses):
        raise SystemExit(f"freeroute: no .ses produced (exit {r.returncode})")


def import_ses(base_board, authored_board, ses, routed_path):
    board = pcbnew.LoadBoard(base_board)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("freeroute: SES import failed")
    if authored_board is None:
        pcbnew.SaveBoard(routed_path, board)
        shutil.copy(DRU, routed_path.replace(".kicad_pcb", ".kicad_dru"))
        return routed_path
    # Freerouting omits (type fix) wires from the session and KiCad's SES
    # import drops every pre-existing track -- re-inject the authored copper.
    authored = pcbnew.LoadBoard(authored_board)
    n = 0
    for t in authored.GetTracks():
        net = board.FindNet(t.GetNetname())
        if net is None:
            raise SystemExit(f"freeroute: net {t.GetNetname()} missing in routed board")
        if t.GetClass() == "PCB_VIA":
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(t.GetPosition())
            v.SetDrill(t.GetDrill())
            v.SetWidth(t.GetWidth(pcbnew.F_Cu))  # vias need a layer arg in v10
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNet(net)
            board.Add(v)
        else:
            s = pcbnew.PCB_TRACK(board)
            s.SetStart(t.GetStart())
            s.SetEnd(t.GetEnd())
            s.SetWidth(t.GetWidth())
            s.SetLayer(t.GetLayer())
            s.SetNet(net)
            board.Add(s)
        n += 1
    print(f"freeroute: re-injected {n} authored tracks/vias")
    pcbnew.SaveBoard(routed_path, board)
    # matching .kicad_dru so kicad-cli drc applies the real custom rules
    shutil.copy(DRU, routed_path.replace(".kicad_pcb", ".kicad_dru"))
    return routed_path


def drc_summary(routed_path):
    out = routed_path.replace(".kicad_pcb", "-drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all",
                    "--refill-zones", "--format", "json", "-o", out,
                    routed_path], check=False, capture_output=True)
    d = json.load(open(out))
    by_type = {}
    for v in d.get("violations", []):
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1
    unconn = d.get("unconnected_items", [])
    nets = {}
    for v in unconn:
        names = {m.group(1) for i in v.get("items", [])
                 for m in [re.search(r"\[([^\]]*)\]", i.get("description", ""))] if m}
        key = ",".join(sorted(names)) or "?"
        nets[key] = nets.get(key, 0) + 1
    print(f"freeroute: DRC violations by type: {by_type or 'none'}")
    print(f"freeroute: unconnected items: {len(unconn)} by net: "
          + " ".join(f"{k}:{n}" for k, n in
                     sorted(nets.items(), key=lambda kv: -kv[1])))
    return by_type, unconn


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variant", choices=["a", "b"], default="a")
    ap.add_argument("--jar", default=os.path.join(OUTDIR, "freerouting-1.9.0.jar"))
    ap.add_argument("--mp", type=int, default=100, help="max passes")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds")
    ap.add_argument("--fix", action="store_true",
                    help="mark authored copper (type fix); see module doc "
                         "for the 1.9 net-skipping caveat")
    ap.add_argument("--dsn-only", action="store_true",
                    help="produce the post-processed DSN and stop")
    args = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    tag = args.variant
    base = render_variant(f"{tag}-base", no_routes=(tag == "b"))
    authored = render_variant("authored", no_routes=True)

    raw = export_dsn(base, os.path.join(OUTDIR, f"{tag}-raw.dsn"))
    auth_dsn = export_dsn(authored, os.path.join(OUTDIR, "authored.dsn"))

    _, _, alias = pcb.build_net_maps()
    text = open(raw).read()
    if args.fix:
        asegs, avias = authored_geometry(open(auth_dsn).read())
        text, (nw, nv) = fix_authored(text, asegs, avias)
        print(f"freeroute: fixed {nw} authored wires, {nv} authored vias")
    text = add_classes(text, alias)
    dsn = os.path.join(OUTDIR, f"{tag}.dsn")
    open(dsn, "w").write(text)
    if args.dsn_only:
        print("freeroute: wrote", dsn)
        return

    ses = os.path.join(OUTDIR, f"{tag}.ses")
    if os.path.exists(ses):
        os.remove(ses)
    run_freerouting(args.jar, dsn, ses, args.mp, args.timeout)

    # Freerouting omits fixed wires from the .ses, so re-inject authored
    # copper only when it was fix-marked; unfixed runs return everything.
    routed = import_ses(base, authored if args.fix else None, ses,
                        os.path.join(OUTDIR, f"routed-{tag}.kicad_pcb"))
    print("freeroute: routed board ->", routed)
    drc_summary(routed)


if __name__ == "__main__":
    main()
