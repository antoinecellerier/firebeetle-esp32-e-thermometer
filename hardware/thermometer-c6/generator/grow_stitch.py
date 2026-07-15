#!/usr/bin/env python3
"""Grow GND stitch vias 0.5/0.3 -> 0.6/0.3 where DRC still passes.

A 0.6mm pad over a 0.3mm drill leaves a 0.15mm annular ring (vs 0.1mm at
0.5mm) -- better fab yield and a lower-inductance plane tie. Each pcb_layout
STITCH via is tried at 0.6/0.3; the ones whose growth keeps the board
DRC-clean are recorded as (x, y, 0.6, 0.3) overrides (pcb.py renders the
override, else STITCH_VIA). Vias too tight to clear a neighbour stay 0.5.

    python3 generator/grow_stitch.py [--dry-run] [--sep MM]

Gate (reject on any of): pcb.py failure; a DRC violation not in
starved_thermal/silk_*; any unconnected item; schematic-parity break;
verify/check_pcb.py failure -- identical to widen.py's gate. Geographically
separated vias (> --sep apart) are grown as a batch and bisected on failure to
isolate the offenders, keeping the render/DRC count down.
"""
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from widen import gate  # noqa: E402  (same render+DRC+check_pcb gate)

LAYOUT = os.path.join(HERE, "pcb_layout.py")
GROW_DIA = 0.6
GROW_DRILL = 0.3
SEP = 2.0
BATCH_CAP = 24


def load_stitch():
    import importlib
    prev = os.environ.get("PCB_NO_ROUTES")
    os.environ["PCB_NO_ROUTES"] = "1"
    try:
        import pcb_layout
        importlib.reload(pcb_layout)
        return [tuple(e) for e in pcb_layout.STITCH]
    finally:
        if prev is None:
            del os.environ["PCB_NO_ROUTES"]
        else:
            os.environ["PCB_NO_ROUTES"] = prev


def write_stitch(entries):
    """Rewrite the STITCH = [...] block; 2-tuples and 4-tuples both round-trip
    in the checked-in one-per-line style."""
    src = open(LAYOUT).read()
    body = "\n".join("    ({}),".format(", ".join(repr(v) for v in e))
                     for e in entries)
    m = re.search(r"STITCH = \[\n.*?\n\]", src, re.DOTALL)
    if not m:
        raise SystemExit("grow_stitch: STITCH block not found")
    src = src[:m.start()] + "STITCH = [\n" + body + "\n]" + src[m.end():]
    tmp = LAYOUT + ".tmp"
    open(tmp, "w").write(src)
    os.replace(tmp, LAYOUT)


def rendered(base, grow):
    """entries with indices in `grow` set to 0.6/0.3, the rest at their
    original size."""
    g = set(grow)
    out = []
    for i, e in enumerate(base):
        if i in g:
            out.append((e[0], e[1], GROW_DIA, GROW_DRILL))
        else:
            out.append((e[0], e[1]) if len(e) < 4 else e)
    return out


def commit_and_gate(base, grow):
    write_stitch(rendered(base, grow))
    return gate()


def sift(base, accepted, batch, stats):
    """Subset of `batch` (indices) that grows cleanly on top of the fixed
    `accepted` set. A failing batch bisects; the right half is tested against
    accepted plus the left survivors so near-neighbour interactions are seen."""
    ok, _ = commit_and_gate(base, accepted | set(batch))
    stats["gates"] += 1
    if ok:
        return set(batch)
    if len(batch) == 1:
        return set()
    mid = len(batch) // 2
    left = sift(base, accepted, batch[:mid], stats)
    right = sift(base, accepted | left, batch[mid:], stats)
    return left | right


def build_batch(cands, pts):
    batch = []
    for i in cands:
        if all(math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) > SEP
               for j in batch):
            batch.append(i)
            if len(batch) >= BATCH_CAP:
                break
    return batch


def main():
    args = sys.argv[1:]
    global SEP
    if "--sep" in args:
        SEP = float(args[args.index("--sep") + 1])
    base = load_stitch()
    pts = [(e[0], e[1]) for e in base]
    already = sum(1 for e in base if len(e) >= 4)
    todo = [i for i, e in enumerate(base) if len(e) < 4]
    print(f"grow_stitch: {len(base)} stitch vias ({already} already grown), "
          f"trying {len(todo)} at {GROW_DIA}/{GROW_DRILL}")

    if "--dry-run" in args:
        print("  (dry run: nothing written, no DRC)")
        return

    stats = {"gates": 0}
    grown = set(i for i, e in enumerate(base) if len(e) >= 4)
    pending = list(todo)
    it = 0
    while pending:
        batch = build_batch(pending, pts)
        it += 1
        add = sift(base, grown, batch, stats)
        grown |= add
        for i in batch:
            pending.remove(i)
        print(f"iter {it:3d}: batch {len(batch):2d}  grown {len(add):2d}  "
              f"(total {len(grown)}, gates {stats['gates']})", flush=True)

    write_stitch(rendered(base, grown))
    ok, reason = gate()
    print("\n=== grow_stitch summary ===")
    print(f"stitch vias grown 0.5->0.6: {len(grown)} / {len(base)}   "
          f"(left at 0.5: {len(base) - len(grown)})")
    print(f"gate cycles: {stats['gates'] + 1}   final gate: {reason}")
    if not ok:
        print("WARNING: final gate not clean")
        sys.exit(1)


if __name__ == "__main__":
    main()
