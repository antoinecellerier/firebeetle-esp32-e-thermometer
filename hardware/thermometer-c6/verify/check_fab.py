#!/usr/bin/env python3
"""Final gate of the `make fab` pipeline: validate the out/fab/ artifact bundle.

Cross-checks the exported CPL / pos / BOM / gerbers / drill / zip against the
project's own intent (circuit.py assembled set, fab_cpl.py rotation tables,
pcb_layout.BOARD) and the fab stamp, so a mis-stamped, stale, or internally
inconsistent bundle never ships. Collects every failure, prints each with a
clear prefix, exits 1 if any; prints `check_fab: OK (N assertions)` otherwise.

Usage (driven by `make fab`):
  python3 verify/check_fab.py out/fab --stamp "<git-short-hash> <YYYY-MM-DD>"

The stamp is FAB_STAMP: "<7-12 hex git short hash> <YYYY-MM-DD>". The rotation
deltas and the assembled/DNP partition are imported from generator/ (fab_cpl,
circuit, pcb_layout) rather than duplicated, so this gate re-derives what the
exporters claimed instead of restating it.
"""

import csv
import json
import os
import re
import sys
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

import circuit  # noqa: E402
import fab_cpl  # noqa: E402
import pcb_layout as pl  # noqa: E402

sys.path.insert(0, HERE)
import drc_summary  # noqa: E402  (verify/; shares the fab DRC classification)

NAME = "thermometer-c6"
COMMITTED_BOARD = os.path.join(PROJECT, NAME + ".kicad_pcb")
BOM_SRC = os.path.join(PROJECT, "bom", NAME + "-bom.csv")

CPL_HEADER = "Designator,Mid X,Mid Y,Layer,Rotation"

# The 10 gerber files that carry a %TF.FileFunction line, and the substring each
# must contain (Edge_Cuts renders "Profile,NP"; the map renders "Drillmap").
GERBER_FILEFUNCTION = {
    NAME + "-F_Cu.gtl": "Copper,L1,Top",
    NAME + "-B_Cu.gbl": "Copper,L2,Bot",
    NAME + "-F_Mask.gts": "Soldermask,Top",
    NAME + "-B_Mask.gbs": "Soldermask,Bot",
    NAME + "-F_Silkscreen.gto": "Legend,Top",
    NAME + "-B_Silkscreen.gbo": "Legend,Bot",
    NAME + "-F_Paste.gtp": "Paste,Top",
    NAME + "-B_Paste.gbp": "Paste,Bot",
    NAME + "-Edge_Cuts.gm1": "Profile",
    NAME + "-drl_map.gbr": "Drillmap",
}
# Every file the gerber zip must contain: the 10 above + drill + job.
GERBER_FILES = set(GERBER_FILEFUNCTION) | {NAME + ".drl", NAME + "-job.gbrjob"}

STAMP_RE = re.compile(r"^[0-9a-f]{7,12} \d{4}-\d{2}-\d{2}$")

checks = 0
failures = []


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        failures.append(msg)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def read_csv(path):
    """Return (header_list, [row_list, ...]) or (None, []) if missing."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except OSError:
        return None, []
    return (rows[0], rows[1:]) if rows else (None, [])


def ang_close(a, b, tol):
    d = (a - b) % 360.0
    return min(d, 360.0 - d) <= tol


def main():
    argv = sys.argv[1:]
    stamp = None
    fab_dir = None
    i = 0
    while i < len(argv):
        if argv[i] == "--stamp":
            stamp = argv[i + 1]
            i += 2
        else:
            fab_dir = argv[i]
            i += 1
    if fab_dir is None or stamp is None:
        sys.exit("usage: check_fab.py <fab_dir> --stamp '<hash> <YYYY-MM-DD>'")

    fab_board = os.path.join(fab_dir, "board", NAME + ".kicad_pcb")

    assembled = set(fab_cpl.assembled_refs())
    all_refs = {c["ref"] for c in circuit.COMPONENTS}
    not_assembled = all_refs - assembled

    # 1. stamp format + presence on the exported board, absence on the committed
    check(bool(STAMP_RE.match(stamp)),
          f"stamp: {stamp!r} does not match '<7-12 hex> YYYY-MM-DD'")
    needle = f"rev {circuit.REV} {stamp}"
    btext = read_text(fab_board)
    check(btext is not None, f"stamp: exported board {fab_board} missing")
    if btext is not None:
        n = btext.count(needle)
        check(n == 1, f"stamp: exported board carries {needle!r} {n}x (want 1)")
    ctext = read_text(COMMITTED_BOARD)
    check(ctext is not None, f"stamp: committed board {COMMITTED_BOARD} missing")
    if ctext is not None:
        check(needle not in ctext,
              f"stamp: committed board unexpectedly carries {needle!r}")

    # 2. DRC clean by the strict fab gate (REAL=0 AND DEFERRED=0; only scoped-
    #    rule waivers allowed), generated after the stamped board. Same
    #    classification the `make fab` gate (drc_summary --gate-fab) applied.
    drc_path = os.path.join(fab_dir, "drc.json")
    check(os.path.exists(drc_path), "drc: drc.json missing")
    if os.path.exists(drc_path):
        if os.path.exists(fab_board):
            check(os.path.getmtime(drc_path) >= os.path.getmtime(fab_board),
                  "drc: drc.json is older than the stamped board")
        try:
            drc = json.loads(read_text(drc_path))
        except (ValueError, TypeError):
            drc = None
            check(False, "drc: drc.json is not valid JSON")
        if drc is not None:
            buckets = {"REAL": [], "DEFERRED": [], "WAIVED": []}
            for k in drc_summary.CATS:
                for v in drc.get(k, []):
                    buckets[drc_summary.classify(v)].append(v)
            check(not buckets["REAL"],
                  f"drc: REAL violations present: "
                  f"{[v.get('type') for v in buckets['REAL']]}")
            check(not buckets["DEFERRED"],
                  f"drc: DEFERRED (postponed) violations present: "
                  f"{[v.get('type') for v in buckets['DEFERRED']]}")

    # 3. CPL structure vs circuit.py assembled set
    cpl_path = os.path.join(fab_dir, NAME + "-cpl.csv")
    cpl_header, cpl_rows = read_csv(cpl_path)
    check(cpl_header is not None, f"cpl: {cpl_path} missing")
    cpl_refs = [r[0] for r in cpl_rows]
    cpl_set = set(cpl_refs)
    cpl_by_ref = {r[0]: r for r in cpl_rows}
    if cpl_header is not None:
        check(",".join(cpl_header) == CPL_HEADER,
              f"cpl: header {','.join(cpl_header)!r} != {CPL_HEADER!r}")
        check(cpl_set == assembled,
              f"cpl: ref set != circuit assembled set "
              f"(missing={sorted(assembled - cpl_set)}, "
              f"extra={sorted(cpl_set - assembled)})")
        bad_layer = sorted({r[0] for r in cpl_rows if r[3] != "Top"})
        check(not bad_layer, f"cpl: non-Top rows: {bad_layer}")
        bad_prefix = sorted(r for r in cpl_refs
                            if r[:2] in ("TP", "JP") or r[0] == "H")
        check(not bad_prefix, f"cpl: forbidden TP/JP/H refs: {bad_prefix}")
        in_dnp = sorted(cpl_set & not_assembled)
        check(not in_dnp, f"cpl: DNP refs present: {in_dnp}")
        bad_rot = []
        for r in cpl_rows:
            try:
                v = float(r[4])
            except ValueError:
                bad_rot.append(r[0])
                continue
            if not (0.0 <= v < 360.0):
                bad_rot.append(r[0])
        check(not bad_rot, f"cpl: rotation not in [0,360): {sorted(set(bad_rot))}")
        ox, oy = pl.BOARD["origin"]
        w, h = pl.BOARD["size"]
        margin = 1.0  # edge-launch USB pads reach slightly past the centre band
        oob = []
        for r in cpl_rows:
            try:
                x, my = float(r[1]), float(r[2])
            except ValueError:
                oob.append(r[0])
                continue
            y = -my  # CPL Mid Y is negated; (Mid X, -Mid Y) is the board point
            if not (ox - margin <= x <= ox + w + margin
                    and oy - margin <= y <= oy + h + margin):
                oob.append(r[0])
        check(not oob, f"cpl: placements outside board bbox: {sorted(oob)}")

    # 4. CPL <-> pos-raw cross-check (coords, rotation-minus-delta, side, set)
    pos_header, pos_rows = read_csv(os.path.join(fab_dir, "pos-raw.csv"))
    check(pos_header is not None, "pos: pos-raw.csv missing")
    pos = {}
    for r in pos_rows:
        pos[r[0]] = dict(pkg=r[2], x=r[3], y=r[4], rot=r[5], side=r[6])
    pos_set = set(pos)

    board = pcbnew.LoadBoard(fab_board) if os.path.exists(fab_board) else None
    fpmap = {fp.GetReference(): fp for fp in board.Footprints()} if board else {}
    dnp_in_pos = {ref for ref, fp in fpmap.items()
                  if ref in not_assembled and fp.GetLayer() == pcbnew.F_Cu
                  and not fp.IsExcludedFromPosFiles()}
    if pos_header is not None and board is not None:
        expected_pos = cpl_set | dnp_in_pos
        check(pos_set == expected_pos,
              f"xcheck: pos-raw set != CPL union top-side-DNP "
              f"(missing={sorted(expected_pos - pos_set)}, "
              f"extra={sorted(pos_set - expected_pos)})")
        probs = []
        for ref in cpl_refs:
            p = pos.get(ref)
            if p is None:
                probs.append(f"{ref}: absent from pos-raw")
                continue
            crow = cpl_by_ref[ref]
            try:
                cx, cy, crot = float(crow[1]), float(crow[2]), float(crow[4])
                px, py, prot = float(p["x"]), float(p["y"]), float(p["rot"])
            except ValueError:
                probs.append(f"{ref}: non-numeric coord/rotation")
                continue
            if abs(cx - px) > 0.001 or abs(cy - py) > 0.001:
                probs.append(f"{ref}: XY ({cx},{cy}) != pos ({px},{py})")
            fp = fpmap.get(ref)
            name = str(fp.GetFPID().GetLibItemName()) if fp else p["pkg"]
            delta, _, _ = fab_cpl.delta_for(ref, name)
            if not ang_close(crot - delta, prot, 0.01):
                probs.append(f"{ref}: (CPL {crot} - delta {delta}) != pos {prot}")
            if p["side"] != "top":
                probs.append(f"{ref}: side {p['side']!r} != 'top'")
        check(not probs, "xcheck: CPL/pos mismatch:\n    " + "\n    ".join(probs))

    # 5. BOM byte-identical to source + designator union == CPL set
    bom_fab = os.path.join(fab_dir, NAME + "-bom.csv")
    fab_b, src_b = read_bytes(bom_fab), read_bytes(BOM_SRC)
    check(fab_b is not None, f"bom: {bom_fab} missing")
    check(src_b is not None, f"bom: source {BOM_SRC} missing")
    check(fab_b is not None and fab_b == src_b,
          "bom: fab copy not byte-equal to bom/thermometer-c6-bom.csv")
    bom_header, bom_rows = read_csv(bom_fab)
    if bom_header is not None:
        di = bom_header.index("Designator") if "Designator" in bom_header else 1
        desig = set()
        for r in bom_rows:
            for d in r[di].split(","):
                d = d.strip()
                if d:
                    desig.add(d)
        check(desig == cpl_set,
              f"bom: designator union != CPL set "
              f"(missing={sorted(cpl_set - desig)}, "
              f"extra={sorted(desig - cpl_set)})")

    # 6. Gerbers present + non-empty, FileFunction map, drill units/tools
    gdir = os.path.join(fab_dir, "gerbers")
    for fn in sorted(GERBER_FILES):
        p = os.path.join(gdir, fn)
        check(os.path.exists(p) and os.path.getsize(p) > 0,
              f"gerbers: {fn} missing or empty")
    for fn, expected in GERBER_FILEFUNCTION.items():
        txt = read_text(os.path.join(gdir, fn))
        m = re.search(r"%TF\.FileFunction,([^*]*)\*%", txt) if txt else None
        got = m.group(1) if m else None
        check(got is not None and expected in got,
              f"gerbers: {fn} FileFunction {got!r} lacks {expected!r}")
    dtxt = read_text(os.path.join(gdir, NAME + ".drl"))
    check(dtxt is not None and "METRIC" in dtxt, "gerbers: drill lacks METRIC")
    check(bool(dtxt) and re.search(r"^T\d+C0\.300\b", dtxt, re.M),
          "gerbers: drill lacks a C0.300 (via) tool")
    check(bool(dtxt) and re.search(r"^T\d+C2\.200\b", dtxt, re.M),
          "gerbers: drill lacks a C2.200 (NPTH mount) tool")

    # 7. Exactly one gerber zip, exact namelist, stamp encoded in its name
    zips = [f for f in os.listdir(fab_dir)
            if re.fullmatch(re.escape(NAME) + r"-gerbers-.+\.zip", f)]
    check(len(zips) == 1,
          f"zip: expected exactly one {NAME}-gerbers-*.zip, found {sorted(zips)}")
    if len(zips) == 1:
        zname = zips[0]
        with zipfile.ZipFile(os.path.join(fab_dir, zname)) as z:
            names = set(z.namelist())
        check(names == GERBER_FILES,
              f"zip: namelist != the 12 gerber files "
              f"(missing={sorted(GERBER_FILES - names)}, "
              f"extra={sorted(names - GERBER_FILES)})")
        m = re.fullmatch(re.escape(NAME) + r"-gerbers-(.+)\.zip", zname)
        part = m.group(1) if m else ""
        want = stamp.replace(" ", "-")
        check(part == want, f"zip: name stamp {part!r} != {want!r}")

    # 8. Rotation checklist covers every orientation-critical CPL ref
    cl = read_text(os.path.join(fab_dir, "rotation-checklist.md"))
    check(cl is not None, "checklist: rotation-checklist.md missing")
    if cl is not None:
        crit = [r for r in cpl_refs if r[0] in ("D", "Q", "U", "J")
                or r[:2] == "SW"]
        absent = [r for r in crit
                  if not re.search(r"(?<![A-Za-z0-9])" + re.escape(r)
                                   + r"(?![A-Za-z0-9])", cl)]
        check(not absent,
              f"checklist: orientation-critical refs absent: {sorted(absent)}")

    if failures:
        print(f"check_fab: {len(failures)} FAILURES")
        for f_ in failures:
            print(" ", f_)
        sys.exit(1)
    print(f"check_fab: OK ({checks} assertions)")


if __name__ == "__main__":
    main()
