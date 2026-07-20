#!/usr/bin/env python3
"""Compact text digest of out/drc.json (kicad-cli pcb drc --format json).

Usage: python3 verify/drc_summary.py [out/drc.json] [--top N] [--gate|--gate-fab]

Default: one summary line + up to N items per non-empty category (type,
description, mm coords). Exits 1 if any item exists, 0 if clean.

--gate: classify by type into REAL / DEFERRED / WAIVED and exit 0 iff REAL == 0.
This is the M5 copper-legality signal: WAIVED = M6 pours (starved_thermal) and
M7 silk; DEFERRED = dangling copper / unconnected nets that vanish once every
net routes and the GND pour lands; REAL = actual clearance/width/hole/short
violations -- the only ones that gate PathFinder's go/no-go. Reading this
instead of the raw drc.json (or DRC PNGs) keeps the routing loop cheap.

--gate-fab: the STRICT ship gate for `make fab`. Same classification, but a
finished board may not merely postpone anything, so it exits 0 iff REAL == 0
AND DEFERRED == 0 -- every remaining violation must be explicitly waived by a
scoped rule. It prints the WAIVED list with a reason per entry so the fab log
records exactly what shipped and why. (The J3 edge-launch copper_edge_clearance
waiver is GONE as of the 2026-07-20 datum respin: it waived a placement error,
not a design intent. WAIVED is expected to be empty.)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DEFAULT = os.path.join(PROJECT, "out", "drc.json")

CATS = ("violations", "unconnected_items", "schematic_parity")

# M6 (GND pours) and M7 (silk) are later milestones -- never a copper gate.
WAIVED = {"starved_thermal", "silk_edge_clearance", "silk_overlap",
          "silk_over_copper"}
# Expected while nets are still unrouted / the GND pour is absent; they clear
# once M5 hits zero stragglers and M6 lands. Reported, but don't fail the gate.
DEFERRED = {"track_dangling", "via_dangling", "unconnected_items"}


def classify(v):
    vtype = v.get("type")
    if vtype in WAIVED:
        return "WAIVED"
    # NOTE: copper_edge_clearance is REAL for every footprint including J3.
    # The old J3-scoped waiver covered the front shell pad hanging 0.105mm off
    # the north edge, which out/j3-datum/ proved was a 1.415mm placement error
    # (HRO's "5.79" is edge -> NPTH post centreline). Post-respin the edge web
    # is 1.510mm and nothing is waived. A J3 edge violation now means the
    # placement regressed -- fix the placement, do not re-add this branch.
    if vtype in DEFERRED:
        return "DEFERRED"
    return "REAL"


def pos_str(item):
    p = item.get("pos") or {}
    if isinstance(p, dict) and "x" in p and "y" in p:
        return f"({p['x']:.2f},{p['y']:.2f})"
    return ""


def fmt_violation(v):
    items = v.get("items", [])
    coords = " ".join(s for s in (pos_str(it) for it in items) if s)
    desc = v.get("description") or v.get("type", "?")
    return (f"{v.get('severity', '?')} {v.get('type', '?')}: "
            f"{desc} {coords}").rstrip()


def waive_reason(v):
    """Why a WAIVED violation is accepted -- named in the fab log."""
    return "later-milestone waiver (M6 GND pour / M7 silk)"


def main():
    args = list(sys.argv[1:])
    top = 5
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i:i + 2]
    gate_fab = "--gate-fab" in args
    if gate_fab:
        args.remove("--gate-fab")
    gate = "--gate" in args
    if gate:
        args.remove("--gate")
    path = args[0] if args else DEFAULT
    try:
        with open(path) as f:
            d = json.load(f)
    except OSError as e:
        print(f"DRC: no report ({e})")
        return 2

    if gate or gate_fab:
        import collections
        buckets = {"REAL": [], "DEFERRED": [], "WAIVED": []}
        for c in CATS:
            for v in d.get(c, []):
                buckets[classify(v)].append(v)
        label = "FAB GATE" if gate_fab else "GATE"
        print(f"{label}: REAL={len(buckets['REAL'])} "
              f"DEFERRED={len(buckets['DEFERRED'])} "
              f"WAIVED={len(buckets['WAIVED'])}")
        # The strict fab gate accepts only explicitly-waived violations, so it
        # names every one it let through -- the fab log records what shipped.
        if gate_fab and buckets["WAIVED"]:
            print(f"  WAIVED ({len(buckets['WAIVED'])}):")
            for v in buckets["WAIVED"]:
                print(f"    {fmt_violation(v)}  <- {waive_reason(v)}")
        # REAL always detailed; DEFERRED detailed too under the fab gate, where
        # it is a hard failure rather than an expected mid-route state.
        for bucket in ("REAL", "DEFERRED"):
            vs = buckets[bucket]
            if not vs:
                continue
            hist = collections.Counter(v.get("type") for v in vs)
            print(f"  {bucket}: {dict(hist)}")
            if bucket == "REAL" or gate_fab:
                for v in vs[:top]:
                    print(f"    {fmt_violation(v)}")
                if len(vs) > top:
                    print(f"    ... +{len(vs) - top} more")
        if gate_fab:
            return 1 if (buckets["REAL"] or buckets["DEFERRED"]) else 0
        return 1 if buckets["REAL"] else 0

    counts = {c: len(d.get(c, [])) for c in CATS}
    total = sum(counts.values())
    print(f"DRC: {total} items "
          f"({counts['violations']} viol, "
          f"{counts['unconnected_items']} unconnected, "
          f"{counts['schematic_parity']} parity)")
    for c in CATS:
        vs = d.get(c, [])
        if not vs:
            continue
        print(f"  [{c}] {len(vs)}:")
        for v in vs[:top]:
            print(f"    {fmt_violation(v)}")
        if len(vs) > top:
            print(f"    ... +{len(vs) - top} more")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
