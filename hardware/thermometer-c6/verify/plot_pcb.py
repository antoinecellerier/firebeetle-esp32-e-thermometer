#!/usr/bin/env python3
"""Render a readable placement/routing map of the generated board.

Draws board outline, courtyards, pads (F.Cu red / B.Cu blue), tracks, vias,
keep-out rule areas, reference labels, and a per-net MST ratsnest of the
still-unrouted connections. Output: out/pcb-map.png (and a zoomed crop when
--crop x1 y1 x2 y2 in board-mm is given).

Usage: python3 verify/plot_pcb.py [--crop x1 y1 x2 y2] [-o out.png]
"""

import os
import sys

import pcbnew
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

import pcb_layout as pl  # noqa: E402

SCALE = 50  # px/mm
OX, OY = pl.BOARD["origin"]
W, H = pl.BOARD["size"]
MARGIN = 3.0


def to_px(x_mm, y_mm):
    return ((x_mm - OX + MARGIN) * SCALE, (y_mm - OY + MARGIN) * SCALE)


def nm_to_px(pos):
    return to_px(pos.x / 1e6, pos.y / 1e6)


def bbox_px(bb):
    x1, y1 = to_px(bb.GetLeft() / 1e6, bb.GetTop() / 1e6)
    x2, y2 = to_px(bb.GetRight() / 1e6, bb.GetBottom() / 1e6)
    return [x1, y1, x2, y2]


def mst_edges(points):
    """Prim's MST over a point list; returns index pairs."""
    n = len(points)
    if n < 2:
        return []
    in_tree = [False] * n
    dist = [float("inf")] * n
    parent = [-1] * n
    dist[0] = 0
    edges = []
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: dist[i])
        in_tree[u] = True
        if parent[u] >= 0:
            edges.append((parent[u], u))
        ux, uy = points[u]
        for v in range(n):
            if not in_tree[v]:
                d = (points[v][0] - ux) ** 2 + (points[v][1] - uy) ** 2
                if d < dist[v]:
                    dist[v] = d
                    parent[v] = u
    return edges


def main():
    args = sys.argv[1:]
    out = os.path.join(PROJECT, "out", "pcb-map.png")
    crop = None
    if "-o" in args:
        i = args.index("-o")
        out = args[i + 1]
        del args[i:i + 2]
    if "--crop" in args:
        i = args.index("--crop")
        crop = [float(v) for v in args[i + 1:i + 5]]

    board = pcbnew.LoadBoard(os.path.join(PROJECT, "thermometer-c6.kicad_pcb"))
    img = Image.new("RGB", (int((W + 2 * MARGIN) * SCALE), int((H + 2 * MARGIN) * SCALE)),
                    "white")
    d = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except OSError:
        font = font_s = ImageFont.load_default()

    # board outline
    d.rectangle([*to_px(OX, OY), *to_px(OX + W, OY + H)], outline="black", width=3)

    # keep-out rule areas
    for z in board.Zones():
        if z.GetIsRuleArea():
            d.rectangle(bbox_px(z.GetBoundingBox()), fill=(255, 200, 120, 70),
                        outline=(200, 120, 0), width=2)

    # copper zone outlines (authored extents, not fills)
    for z in board.Zones():
        if not z.GetIsRuleArea():
            d.rectangle(bbox_px(z.GetBoundingBox()), outline=(0, 0, 255, 40), width=1)

    # courtyards + refs + pads
    unrouted_pts = {}
    for fp in board.Footprints():
        crt = fp.GetCourtyard(pcbnew.F_CrtYd)
        if crt.OutlineCount():
            d.rectangle(bbox_px(crt.BBox()), outline=(150, 150, 150), width=1)
        for pad in fp.Pads():
            layers = pad.GetLayerSet()
            on_f = layers.Contains(pcbnew.F_Cu)
            color = (200, 30, 30, 180) if on_f else (30, 30, 200, 180)
            d.rectangle(bbox_px(pad.GetBoundingBox()), fill=color)
            if pad.GetNetCode() > 0:
                unrouted_pts.setdefault(pad.GetNetname(), []).append(
                    nm_to_px(pad.GetPosition()))
        pos = nm_to_px(fp.GetPosition())
        ref = fp.GetReference()
        d.text((pos[0] + 2, pos[1] - 16), ref, fill="black",
               font=font if ref in ("U1", "J3", "J4", "J1", "J5") else font_s)

    # tracks + vias
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = nm_to_px(t.GetPosition())
            r = t.GetWidth() / 2e6 * SCALE
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r],
                      outline=(0, 120, 0), width=2)
        else:
            a, b_ = nm_to_px(t.GetStart()), nm_to_px(t.GetEnd())
            col = (200, 30, 30, 200) if t.GetLayer() == pcbnew.F_Cu else (30, 30, 200, 200)
            d.line([a, b_], fill=col, width=max(2, int(t.GetWidth() / 1e6 * SCALE)))
            for p in (nm_to_px(t.GetStart()), nm_to_px(t.GetEnd())):
                unrouted_pts.setdefault(t.GetNetname(), []).append(p)

    # ratsnest: MST per net over pads+track-endpoints (rough but readable)
    total_mm = 0.0
    for net, pts in sorted(unrouted_pts.items()):
        for i, j in mst_edges(pts):
            d.line([pts[i], pts[j]], fill=(0, 160, 220, 90), width=1)
            total_mm += (((pts[i][0] - pts[j][0]) ** 2 +
                          (pts[i][1] - pts[j][1]) ** 2) ** 0.5) / SCALE

    d.text((10, 5), f"ratsnest MST ~{total_mm:.0f}mm", fill="black", font=font)

    if crop:
        x1, y1 = to_px(OX + crop[0], OY + crop[1])
        x2, y2 = to_px(OX + crop[2], OY + crop[3])
        img = img.crop((int(x1), int(y1), int(x2), int(y2)))
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print(f"plot: {out} (ratsnest ~{total_mm:.0f}mm)")


if __name__ == "__main__":
    main()
