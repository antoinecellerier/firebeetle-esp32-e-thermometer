#!/usr/bin/env python3
"""JLCPCB CPL (pick-and-place) exporter with rotation corrections + checklist.

Emits the component-placement CSV JLCPCB's assembly service consumes, applying
per-footprint rotation deltas: JLC's zero orientation comes from their own parts
library and often differs from KiCad's footprint zero, so a raw `kicad-cli pcb
export pos` uploads the whole board mis-rotated. FAB_ROTATIONS / the per-ref
overrides below record the corrections and their provenance; the JLC order
preview is the only ground truth, so every correction stays low/medium
confidence until eyeballed against a real preview and marked `verified:`.

Usage (driven by `make fab`):
  python3 generator/fab_cpl.py out/fab/board/thermometer-c6.kicad_pcb \\
      -o out/fab/thermometer-c6-cpl.csv \\
      --checklist out/fab/rotation-checklist.md

The assembled set is defined by circuit.py (LCSC part set, not DNP, has a
footprint) and cross-checked against the board: any assembled ref that is
missing, DNP, excluded-from-position-files, or not on the front is a fatal
error (JLCPCB economy assembly is single-sided, top only). Coordinates match
`kicad-cli pcb export pos --side front` absolute-origin CSV (Mid Y is negated).

FAB_ROTATIONS / REF_ROTATION_OVERRIDES are module-level so a future
verify/check_fab.py can import and re-derive the same corrections.
"""

import argparse
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import circuit  # noqa: E402

# JLC CPL rotation corrections. JLC's zero orientation comes from their parts
# library and often differs from KiCad's footprint zero. Convention here:
# CPL rot = (kicad rot + delta) % 360, CCW-positive (both systems CCW).
# The JLC order-preview is ground truth; each entry records source/confidence
# and gets `verified:` backfilled after eyeballing the first order preview.
FAB_ROTATIONS = [  # (regex vs footprint lib item name, delta_deg) - first match wins
    # JLC model zeros are arbitrary per package — the 2026-07-18 preview walks
    # (two passes, pad-crosshair overlays) established: 3-pin small packages
    # (bare SOT-23, SOT-323/SC-70) and the USB-C need +180; SOT-23-5/-6,
    # TSOT-23-5, SOD-123, D_SMA, JST_PH and everything else need 0. This
    # matches neither community table wholesale (matthewlai right on SOT-23/
    # USB-C, wrong on diodes/JST; KiBot the reverse). Never trust a family
    # inference or a table over an actual order preview.
    (r"^TSOT-23", 0),     # U2 RT9080  legs-on-pads in 2nd preview pass  confidence: verified  verified: 2026-07-18
    (r"^SOT-23$", 180),   # Q1/Q2/Q4/Q5/Q6 bare 3-pin SOT-23: JLC zero differs from the 5/6-pin variants; delta 0 rendered legs in the pad gaps (2nd preview pass, pad-crosshair overlay)  confidence: verified  verified: 2026-07-18
    (r"^SOT-23", 0),      # U3 SOT-23-6 / U4 SOT-23-5  legs-on-pads in 2nd preview pass  confidence: verified  verified: 2026-07-18
    (r"^SOT-323", 180),   # Q3 SC-70: 3-pin like bare SOT-23 — delta 0 rendered 1-leg-N/2-legs-S over 2-pads-N/1-pad-S (user-confirmed crop, 2nd preview pass)  confidence: verified  verified: 2026-07-18
    (r"^USB_C_Receptacle_HRO_TYPE-C-31-M-12", 180),  # J3  the family-inference exception: delta 0 rendered the mouth facing into the board (2nd preview pass 2026-07-18); matthewlai's exact entry stands  confidence: verified  verified: 2026-07-18
    (r"^JST_PH_S", 0),    # J1  source: JLC preview 2026-07-18, tails/pin-1 dot vs pads  confidence: verified  verified: 2026-07-18
    (r"^D_SOD-123", 0),   # D4/D5/D6 MBR0530  source: JLC preview 2026-07-18, cathode bands  confidence: verified  verified: 2026-07-18
    (r"^D_SMA", 0),       # D2 SS14  cathode band WEST in JLC preview  confidence: verified  verified: 2026-07-18
    (r"^LED_0603", 0),    # D1/D3  LED tape polarity varies per LCSC part  confidence: low  verified:
]
REF_ROTATION_OVERRIDES = {  # local-library footprints; override beats pattern
    "U1": 0,   # ESP32-C6-MINI-1  verify antenna end at board WEST edge  confidence: low  verified:
    "J4": 0,   # XUNPU FPC-05FB-24PH20  verify pin1 + latch side  confidence: low  verified:
    "U5": 0,   # Bosch LGA-10 BMP581  rotated LGA invisible after reflow - TOP-PRIORITY preview item  confidence: low  verified:
    "SW1": 0, "SW2": 0,  # local:SW_TS-1187A 4-pad tact switches  confidence: low-med  verified:
}


def no_correction_ok(ref):
    """Refs consciously emitted with no rotation delta: the 2-pad symmetric
    passives (R*/C*), the 2-pad crystal, and the two inductors."""
    return ref in ("Y1", "L1", "L2") or ref[0] in ("R", "C")


# ---------------------------------------------------------------------------


def assembled_refs():
    """circuit.py's assembled set: has an LCSC part, not DNP, has a footprint."""
    return [c["ref"] for c in circuit.COMPONENTS
            if c.get("lcsc") and not c.get("dnp") and c.get("footprint")]


def natural_key(ref):
    """Split a refdes into (prefix, number) so C2 sorts before C10."""
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def lib_item_name(fp):
    """The footprint name without its library nickname (what FAB_ROTATIONS
    patterns match against): 'Package_TO_SOT_SMD:SOT-23' -> 'SOT-23'."""
    return str(fp.GetFPID().GetLibItemName())


def delta_for(ref, name):
    """Rotation delta and its provenance. Override beats pattern; first
    pattern match wins. Returns (delta, kind, key) with kind in
    {'override', 'pattern', 'none'} and key = ref / regex / None."""
    if ref in REF_ROTATION_OVERRIDES:
        return REF_ROTATION_OVERRIDES[ref], "override", ref
    for rx, delta in FAB_ROTATIONS:
        if re.search(rx, name):
            return delta, "pattern", rx
    return 0, "none", None


def copper_pad_numbers(fp):
    """Distinct non-empty pad numbers on a copper layer (mechanical/mask-only
    pads carry no number and are ignored)."""
    nums = set()
    for pad in fp.Pads():
        n = str(pad.GetNumber())
        if n and pad.IsOnCopperLayer():
            nums.add(n)
    return nums


def is_critical(ref, fp):
    """Orientation-critical: a diode/transistor/IC/connector/switch, or any
    part with more than two pads."""
    return (ref[0] in ("D", "Q", "U", "J") or ref.startswith("SW")
            or len(copper_pad_numbers(fp)) > 2)


def fmt_rot(v):
    """Normalize to [0,360) and render with at most one decimal."""
    v = round(v, 1) % 360
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def compass(dx, dy):
    """Board-frame compass of an offset as seen in the top render: north is
    -y (up), south +y, east +x, west -x. A component axis counts only when it
    is at least ~35% of the offset's length, so corner pads read as diagonals
    (SOUTH-WEST) and edge features as cardinals (WEST)."""
    mag = (dx * dx + dy * dy) ** 0.5
    if mag < 1e-6:
        return "CENTER"
    vert = "NORTH" if dy < 0 else "SOUTH"
    horiz = "EAST" if dx > 0 else "WEST"
    parts = []
    if abs(dy) >= 0.35 * mag:
        parts.append(vert)
    if abs(dx) >= 0.35 * mag:
        parts.append(horiz)
    return "-".join(parts) or (vert if abs(dy) >= abs(dx) else horiz)


def ref_pad(fp):
    """The pad whose position anchors the orientation cue: pad '1' (pin 1,
    and cathode for KiCad Diode:*/Device:LED where pin 1 = K), else 'A1'
    (USB-C row A), else the lexicographically first numbered pad."""
    pads = {}
    for pad in fp.Pads():
        n = str(pad.GetNumber())
        if n:
            pads.setdefault(n, pad)
    for name in ("1", "A1"):
        if name in pads:
            return name, pads[name]
    name = sorted(pads)[0]
    return name, pads[name]


def antenna_dir(board, u1_fp):
    """Compass edge of the ESP32 module's antenna keep-out relative to U1."""
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetZoneName() == "antenna":
            bb = z.GetBoundingBox()
            cx = (bb.GetLeft() + bb.GetRight()) / 2
            cy = (bb.GetTop() + bb.GetBottom()) / 2
            fp_pos = u1_fp.GetPosition()
            return compass((cx - fp_pos.x) / 1e6, (cy - fp_pos.y) / 1e6)
    return None


def orientation_cue(ref, fp, board):
    """Human-checkable orientation cue for the JLC 2D preview, derived from the
    reference pad's board-frame position (top view)."""
    name, pad = ref_pad(fp)
    fp_pos = fp.GetPosition()
    dx = (pad.GetPosition().x - fp_pos.x) / 1e6
    dy = (pad.GetPosition().y - fp_pos.y) / 1e6
    where = compass(dx, dy)
    if ref[0] == "D":                       # Diode/LED: pin 1 = cathode
        return f"cathode band {where}"
    if ref[0] == "Q":                       # SOT-23/SOT-323: pin 1 = gate
        return f"pin 1 (G) at {where}"
    if ref == "U1":
        ant = antenna_dir(board, fp)
        return (f"antenna overhang {ant} edge; pin 1 {where}" if ant
                else f"pin 1 {where}")
    return f"pin {name} at {where}"


# --- confidence tags live in this file's comments; surface them in the
#     checklist without disturbing the importable data structures. ---
_CONF_RE = re.compile(r"confidence:\s*(\S+)")


def _confidence_maps():
    """Map FAB_ROTATIONS regex -> confidence and override ref -> confidence by
    scanning this module's own source comments."""
    rot, ovr = {}, {}
    src = open(os.path.abspath(__file__)).read().splitlines()
    in_rot = in_ovr = False
    for line in src:
        if line.startswith("FAB_ROTATIONS"):
            in_rot, in_ovr = True, False
        elif line.startswith("REF_ROTATION_OVERRIDES"):
            in_rot, in_ovr = False, True
        elif line.startswith("]") or line.startswith("}"):
            in_rot = in_ovr = False
        cm = _CONF_RE.search(line)
        conf = cm.group(1) if cm else "?"
        if in_rot:
            m = re.search(r'\(r"([^"]+)",\s*-?\d+\)', line)
            if m:
                rot[m.group(1)] = conf
        elif in_ovr:
            for m in re.finditer(r'"([A-Za-z]+\d+)":\s*-?\d+', line):
                ovr[m.group(1)] = conf
    return rot, ovr


def build_rows(board):
    """One CPL record per assembled ref, with the metadata the invariants and
    the checklist need. Fatal on any assembled ref the board cannot assemble."""
    by_ref = {c["ref"]: c for c in circuit.COMPONENTS}
    fpmap = {fp.GetReference(): fp for fp in board.Footprints()}
    rows = []
    for ref in assembled_refs():
        fp = fpmap.get(ref)
        if fp is None:
            raise SystemExit(f"fab_cpl: {ref} is assembled but missing from the board")
        if fp.IsDNP():
            raise SystemExit(f"fab_cpl: {ref} is assembled in circuit.py but DNP on the board")
        if fp.IsExcludedFromPosFiles():
            raise SystemExit(f"fab_cpl: {ref} is assembled but excluded from position files")
        if fp.GetLayer() != pcbnew.F_Cu:
            raise SystemExit(f"fab_cpl: {ref} is assembled but not on the front (top) side")
        name = lib_item_name(fp)
        delta, kind, key = delta_for(ref, name)
        pos = fp.GetPosition()
        rows.append(dict(
            ref=ref, comp=by_ref[ref], fp=fp, name=name,
            x=pos.x / 1e6, y=-pos.y / 1e6,
            kicad_rot=fp.GetOrientationDegrees(),
            cpl_rot=fmt_rot(fp.GetOrientationDegrees() + delta),
            delta=delta, kind=kind, key=key,
            critical=is_critical(ref, fp)))
    rows.sort(key=lambda r: natural_key(r["ref"]))
    return rows


def check_invariants(rows):
    """Fatal on: unused (dead) rotation rules, an orientation-critical ref with
    no correction/exemption covering it, wrong row count, or any non-Top row."""
    want = set(assembled_refs())
    if len(rows) != len(want):
        raise SystemExit(f"fab_cpl: emitted {len(rows)} rows, expected {len(want)}")

    used_patterns = {r["key"] for r in rows if r["kind"] == "pattern"}
    for rx, _ in FAB_ROTATIONS:
        if rx not in used_patterns:
            raise SystemExit(f"fab_cpl: dead FAB_ROTATIONS rule {rx!r} matched no emitted part")
    used_overrides = {r["key"] for r in rows if r["kind"] == "override"}
    for ref in REF_ROTATION_OVERRIDES:
        if ref not in used_overrides:
            raise SystemExit(f"fab_cpl: dead REF_ROTATION_OVERRIDES key {ref!r} matched no emitted part")

    for r in rows:
        if r["critical"] and r["kind"] == "none" and not no_correction_ok(r["ref"]):
            raise SystemExit(
                f"fab_cpl: orientation-critical {r['ref']} ({r['name']}) has no "
                f"rotation rule, override, or NO_CORRECTION_OK exemption")


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        f.write("Designator,Mid X,Mid Y,Layer,Rotation\n")
        for r in rows:
            f.write(f"{r['ref']},{r['x']:.4f},{r['y']:.4f},Top,{r['cpl_rot']}\n")


CHECKLIST_INTRO = """\
# Rotation verification checklist

One row per orientation-critical part (diodes, transistors, ICs, connectors,
switches). The JLCPCB 2D order preview is the **only** ground truth: after
uploading `thermometer-c6-cpl.csv`, compare each part's rendered orientation
against the "Expected orientation" cue below (a top-view compass bearing of the
part's pin-1 / cathode / antenna feature, board WEST = left).

On a mismatch: fix the part's `delta` in `generator/fab_cpl.py` (adjust the
matching `FAB_ROTATIONS` entry or add a `REF_ROTATION_OVERRIDES` key), mark that
entry `verified:` once it matches, re-run `make fab`, and re-upload the CPL. If
*every* part is rotated by the same amount, or shifted by a uniform X/Y offset,
suspect the origin/whole-board setting rather than per-part deltas.

"""


def write_checklist(rows, board, path):
    conf_rot, conf_ovr = _confidence_maps()

    def confidence(r):
        if r["kind"] == "override":
            return conf_ovr.get(r["key"], "?")
        if r["kind"] == "pattern":
            return conf_rot.get(r["key"], "?")
        return "none"

    cols = ["Ref", "Value", "LCSC", "Footprint", "KiCad rot",
            "Delta (confidence)", "CPL rot",
            "Expected orientation in JLC preview", "preview OK"]
    with open(path, "w") as f:
        f.write(CHECKLIST_INTRO)
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("|" + "|".join(["---"] * len(cols)) + "|\n")
        for r in rows:
            if not r["critical"]:
                continue
            cue = orientation_cue(r["ref"], r["fp"], board)
            f.write("| " + " | ".join([
                r["ref"],
                r["comp"].get("value", ""),
                r["comp"].get("lcsc", ""),
                r["name"],
                fmt_rot(r["kicad_rot"]),
                f"{r['delta']:+d} ({confidence(r)})",
                r["cpl_rot"],
                cue,
                "`[ ]`",
            ]) + " |\n")


def main():
    ap = argparse.ArgumentParser(description="JLCPCB CPL exporter with rotation corrections")
    ap.add_argument("board", help="path to the .kicad_pcb to export")
    ap.add_argument("-o", "--output", required=True, help="CPL CSV output path")
    ap.add_argument("--checklist", help="rotation verification checklist (markdown) output path")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.board)
    rows = build_rows(board)
    check_invariants(rows)
    write_csv(rows, args.output)
    if args.checklist:
        write_checklist(rows, board, args.checklist)

    n_crit = sum(1 for r in rows if r["critical"])
    print(f"fab_cpl: {len(rows)} placements -> {os.path.basename(args.output)} "
          f"({n_crit} orientation-critical" + (", checklist written" if args.checklist else "") + ")")


if __name__ == "__main__":
    main()
