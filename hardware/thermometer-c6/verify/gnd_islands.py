#!/usr/bin/env python3
"""GND connectivity + single-point-of-failure audit of the generated board.

Confirms the GND net is one connected copper system, then finds the ties whose
loss would strand a region from the main plane -- the "thin / single via" spots.

The truth source is pcbnew's own (island-aware) connectivity: after refilling
zones, GetUnconnectedCount(False)==0 means fully joined (this is what kicad-cli
DRC reports as unconnected_items). Geometry alone can't reproduce it -- the pour
is the connective tissue and most GND tracks reach it through endpoints, not
overlap; and GetConnectedItems() flattens every zone island into one node, which
hides both the F<->B split and per-island isolation. So articulation is probed
the only reliable way: physically remove one via/track, rebuild connectivity,
and see whether the unconnected count rises. A rise => that item is the SOLE tie
for whatever it strands. Nested (series-chain) cuts are folded to the maximal
(outermost) region. Redundant-via spots are search + oracle-validated: a 0.5/0.3
stitch is only reported if, once added, the original via stops being critical
AND it sits inside GND copper on both layers, clear of holes and the antenna
keep-out. Where the feeding tie is a sub-via-width neck, no stitch fits and the
fix is to widen it.

Usage: python3 verify/gnd_islands.py [BOARD.kicad_pcb] [--png OUT.png]
  default board: thermometer-c6.kicad_pcb   (pass out/hand/... to audit a copy)
"""

import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))
import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]
FCU, BCU = pcbnew.F_Cu, pcbnew.B_Cu
GNDN = "GND"
STITCH = pl.STITCH_VIA  # 0.5mm pad / 0.3mm drill
# antenna keep-outs forbid vias; sensor keep-outs allow them but are too tight
# to double; the fpc-fanout area runs relaxed HV clearance (0.18mm) that the
# pour-coverage test can't see -- so a stitch is never auto-placed in any of
# these rects (all minor 1-pad ties anyway).
NO_VIA = [k["rect"] for k in pl.KEEPOUTS
          if k["name"] in ("antenna", "antenna-margin", "U5-sensor",
                           "U6-sensor", "fpc-fanout")]


def rel(p):
    return (p.x / 1e6 - OX, p.y / 1e6 - OY)


def vi(x, y):
    return pcbnew.VECTOR2I(int(round((x + OX) * 1e6)), int(round((y + OY) * 1e6)))


def pname(pad):
    return pad.GetParentFootprint().GetReference() + "." + pad.GetNumber()


def load(path):
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.BuildConnectivity()
    gnd = b.GetNetsByName()[GNDN].GetNetCode()
    return b, b.GetConnectivity(), gnd


def gnd_pads(b, gnd):
    return [p for fp in b.GetFootprints() for p in fp.Pads()
            if p.GetNetCode() == gnd]


def isolated(conn, pads):
    """Pads not in the largest cluster, keyed by min-UUID signature of each
    pad's connected set (authoritative, reflects the current board state)."""
    groups = {}
    for p in pads:
        sig = min([x.m_Uuid.AsString() for x in conn.GetConnectedItems(p)]
                  + [p.m_Uuid.AsString()])
        groups.setdefault(sig, []).append(p)
    if not groups:
        return frozenset()
    main = max(groups.values(), key=len)
    keep = {id(x) for x in main}
    return frozenset(pname(p) for p in pads if id(p) not in keep)


def maximal(cuts):
    """Keep cuts whose stranded pad-set is not a proper subset of another's --
    folds a series via/track chain down to its outermost (widest) tie."""
    sets = [c["iso"] for c in cuts]
    return [c for c in cuts if not any(c["iso"] < s for s in sets)]


def via_pass(b, conn, base, pads, gnd):
    out = []
    for v in [t for t in b.GetTracks()
              if t.GetNetCode() == gnd and t.GetClass() == "PCB_VIA"]:
        pos = rel(v.GetPosition())
        b.Remove(v)
        b.BuildConnectivity()
        rise = conn.GetUnconnectedCount(False) > base
        if rise:
            iso = isolated(conn, pads)
        b.Add(v)
        b.BuildConnectivity()
        if rise:
            out.append(dict(pos=pos, iso=iso))
    return out


def track_pass(b, conn, base, pads, gnd):
    out = []
    for t in [t for t in b.GetTracks()
              if t.GetNetCode() == gnd and t.GetClass() == "PCB_TRACK"]:
        w, a, e, ly = (t.GetWidth() / 1e6, rel(t.GetStart()),
                       rel(t.GetEnd()), t.GetLayer())
        b.Remove(t)
        b.BuildConnectivity()
        rise = conn.GetUnconnectedCount(False) > base
        if rise:
            iso = isolated(conn, pads)
        b.Add(t)
        b.BuildConnectivity()
        # a lone pad reached by one track is a normal stub; a *region* (>=2 pads)
        # behind one track is a return-path neck.
        if rise and len(iso) >= 2:
            out.append(dict(w=w, a=a, e=e, layer=ly, iso=iso))
    return out


# ---- redundant-via placement (search + oracle validation) -------------------

def copper_index(b, gnd):
    shp = {FCU: [], BCU: []}
    holes = []

    def add(sh, layer):
        bb = sh.BBox()
        shp[layer].append((sh, (bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY,
                                bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY)))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            holes.append((*rel(t.GetPosition()), t.GetDrillValue() / 2e6))
            if t.GetNetCode() == gnd:
                for l in (FCU, BCU):
                    add(t.GetEffectiveShape(l), l)
        elif t.GetNetCode() == gnd:
            add(t.GetEffectiveShape(t.GetLayer()), t.GetLayer())
    for fp in b.GetFootprints():
        for p in fp.Pads():
            d = p.GetDrillSize().x / 1e6
            if d:
                holes.append((*rel(p.GetPosition()), d / 2))
            if p.GetNetCode() == gnd:
                for l in (FCU, BCU):
                    if p.IsOnLayer(l):
                        add(p.GetEffectiveShape(l), l)
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.GetNetCode() == gnd:
            for l in z.GetLayerSet().Seq():
                add(z.GetFilledPolysList(l), l)
    return shp, holes


def covered(shp, x, y, layer, m):
    """A 0.5mm stitch pad (radius ~m) at (x,y) sits wholly on GND copper on
    `layer` -> it inherits the pour's clearance to every other net."""
    for dx, dy in ((0, 0), (m, 0), (-m, 0), (0, m), (0, -m), (m * .7, m * .7),
                   (-m * .7, m * .7), (m * .7, -m * .7), (-m * .7, -m * .7)):
        px, py, pt, ok = x + dx, y + dy, vi(x + dx, y + dy), False
        for sh, bb in shp[layer]:
            if bb[0] - .01 <= px <= bb[2] + .01 and bb[1] - .01 <= py <= bb[3] + .01 \
                    and sh.Collide(pt, 0):
                ok = True
                break
        if not ok:
            return False
    return True


def legal(x, y, holes, exclude):
    if any(r[0] - .3 <= x <= r[2] + .3 and r[1] - .3 <= y <= r[3] + .3
           for r in NO_VIA):
        return False
    for hx, hy, hr in holes:
        d = math.hypot(x - hx, y - hy)
        if d < 1e-4:
            continue
        if abs(hx - exclude[0]) < 1e-4 and abs(hy - exclude[1]) < 1e-4:
            if d < 0.8:            # copper via-to-via for a 0.5 vs 0.6mm pad
                return False
        elif d < hr + 0.15 + 0.25:  # hole-to-hole: this drill/2 + clr
            return False
    return True


def find_redundant(b, conn, base, gnd, pos, shp, holes):
    """Closest 0.5/0.3 GND stitch that is DRC-legal AND, once added, makes the
    via at `pos` non-critical (a genuine parallel path). None => no stitch fits
    (the feeding tie is a neck); widen it instead."""
    orig = next((t for t in b.GetTracks()
                 if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd
                 and math.hypot(*(a - c for a, c in zip(rel(t.GetPosition()), pos))) < 1e-3), None)
    if orig is None:
        return None
    tried, r = 0, 0.75
    while r <= 3.0 and tried < 90:
        for ang in range(0, 360, 8):
            x = round(pos[0] + r * math.cos(math.radians(ang)), 2)
            y = round(pos[1] + r * math.sin(math.radians(ang)), 2)
            if not legal(x, y, holes, pos):
                continue
            if not (covered(shp, x, y, FCU, 0.25) and covered(shp, x, y, BCU, 0.25)):
                continue
            tried += 1
            nv = pcbnew.PCB_VIA(b)
            nv.SetPosition(vi(x, y))
            nv.SetDrill(pcbnew.FromMM(STITCH["drill"]))
            nv.SetWidth(pcbnew.FromMM(STITCH["diameter"]))
            nv.SetNetCode(gnd)
            b.Add(nv)
            b.Remove(orig)
            b.BuildConnectivity()
            fixed = conn.GetUnconnectedCount(False) <= base
            b.Add(orig)
            b.Remove(nv)
            b.BuildConnectivity()
            if fixed:
                return (x, y, round(r, 2))
        r += 0.1
    return None


# ---- reporting --------------------------------------------------------------

def report(b, conn, gnd, png):
    pads = gnd_pads(b, gnd)
    base = conn.GetUnconnectedCount(False)
    nvia = len([t for t in b.GetTracks()
                if t.GetNetCode() == gnd and t.GetClass() == "PCB_VIA"])
    print(f"GND audit: {len(pads)} GND pads, {nvia} GND vias")
    print("\n(a) CONNECTIVITY")
    if base == 0:
        print("  GND is FULLY CONNECTED (0 unconnected, 1 copper system).")
    else:
        iso = sorted(isolated(conn, pads))
        print(f"  GND NOT fully connected: {base} unconnected (ratsnest gaps).")
        print(f"  stranded pads (best effort): {iso}")

    vc = via_pass(b, conn, base, pads, gnd)
    tc = track_pass(b, conn, base, pads, gnd)
    shp, holes = copper_index(b, gnd)
    vmax = {id(c) for c in maximal(vc)}
    for c in vc:  # each critical via: does a redundant stitch fix it, and where?
        c["spot"] = (find_redundant(b, conn, base, gnd, c["pos"], shp, holes)
                     if c["iso"] else None)
    vc = sorted((c for c in vc if c["iso"]), key=lambda c: -len(c["iso"]))
    tmax = sorted(maximal(tc), key=lambda c: -len(c["iso"]))

    print(f"\n(b) SINGLE-VIA TIES  ({len(vc)} vias each the SOLE ground path for "
          "a region; worst first. [outer] = not nested behind a bigger via tie)")
    for c in vc:
        p, n = c["pos"], len(c["iso"])
        tag = "[outer]" if id(c) in vmax else "[nested]"
        if c["spot"]:
            fix = f"stitch redundant 0.5/0.3 GND via at ({c['spot'][0]},{c['spot'][1]})"
        else:
            fix = ("no legal stitch spot nearby (thin neck / congestion / keep-out)"
                   " -- widen the feeding trace or re-route")
        print(f"  {tag} via@({p[0]:.2f},{p[1]:.2f}) SOLE tie for {n:2d} pads: "
              f"{sorted(c['iso'])[:12]}{' ...' if n > 12 else ''}")
        print(f"          -> {fix}")

    print(f"\n(c) NARROW-NECK TIES ({len(tc)} region-bearing single tracks -> "
          f"{len(tmax)} maximal; worst first)")
    for c in tmax:
        a, e = c["a"], c["e"]
        flag = "  <== BOTTLENECK (sub-0.25mm)" if c["w"] < 0.25 else ""
        ly = pcbnew.BOARD.GetStandardLayerName(c["layer"])
        print(f"  {c['w']:.2f}mm {ly} ({a[0]:.2f},{a[1]:.2f})->({e[0]:.2f},"
              f"{e[1]:.2f}) SOLE tie for {len(c['iso'])} pads{flag}")
        print(f"      -> widen to {STITCH['diameter']:.1f}mm+ / add a via pair "
              "tying the region to the B plane")

    fixable = sum(1 for c in vc if c["spot"])
    print("\nSUMMARY")
    print(f"  GND connected: {base == 0}.  {len(vc)} single-via SPOF ties "
          f"({fixable} stitch-fixable now), {len(tmax)} narrow-neck SPOF(s).")
    if tmax:
        print("  Priority: the sub-0.25mm neck(s) in (c) gate the largest "
              "regions and take no stitch -- widen those first.")

    if png:
        render(b, gnd, [c for c in vc if id(c) in vmax], tmax, png)
    return base


def render(b, gnd, vmax, tmax, out):
    from PIL import Image, ImageDraw
    S, M = 26, 2
    W, H = pl.BOARD["size"]
    img = Image.new("RGB", (int((W + 2 * M) * S), int((H + 2 * M) * S)), (12, 12, 16))
    d = ImageDraw.Draw(img, "RGBA")

    def X(x):
        return int((x + M) * S)

    def Y(y):
        return int((y + M) * S)
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() != gnd:
            continue
        for l in z.GetLayerSet().Seq():
            col = (60, 90, 140, 90) if l == BCU else (150, 90, 60, 90)
            ps = z.GetFilledPolysList(l)
            for i in range(ps.OutlineCount()):
                o = ps.Outline(i)
                pts = [(X(o.CPoint(k).x / 1e6 - OX), Y(o.CPoint(k).y / 1e6 - OY))
                       for k in range(o.PointCount())]
                if len(pts) > 2:
                    d.polygon(pts, fill=col)
    for c in tmax:
        d.line([X(c["a"][0]), Y(c["a"][1]), X(c["e"][0]), Y(c["e"][1])],
               fill=(255, 170, 0, 255), width=max(2, int(c["w"] * S)))
    for c in vmax:
        x, y = X(c["pos"][0]), Y(c["pos"][1])
        d.line([x - 6, y - 6, x + 6, y + 6], fill=(255, 40, 40), width=3)
        d.line([x - 6, y + 6, x + 6, y - 6], fill=(255, 40, 40), width=3)
    img.save(out)
    print(f"\nwrote {out} (blue=B pour, red=F pour, red X=SOLE-tie via, "
          "orange=narrow neck)")


def main():
    args = sys.argv[1:]
    png = None
    if "--png" in args:
        i = args.index("--png")
        png = args[i + 1]
        del args[i:i + 2]
    path = args[0] if args else os.path.join(PROJECT, "thermometer-c6.kicad_pcb")
    b, conn, gnd = load(path)
    print(f"board: {path}")
    base = report(b, conn, gnd, png)
    sys.exit(1 if base else 0)


if __name__ == "__main__":
    main()
