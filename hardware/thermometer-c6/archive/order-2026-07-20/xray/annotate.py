#!/usr/bin/env python3
"""Overlay board-file footprint bboxes onto the JLC X-ray frames.

Run from this directory: python3 annotate.py
Regenerates annotated/<n>-annotated.png. Transform derivation: README.md.
"""
import os
import pcbnew
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "../../..", "thermometer-c6.kicad_pcb")
S, A, B = 41.5, 1301.0, 307.0            # board mm -> 4.png px: col = A - S*y, row = S*x + B
SHIFTS = {"4.png": (0, 0), "3.png": (290, 6), "2.png": (-90, 10), "1.png": (279, -40)}
DNP = {"U6", "D7", "R9", "J2", "J5"}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

board = pcbnew.LoadBoard(BOARD)
bb = {}
for fp in board.GetFootprints():
    if fp.IsFlipped():
        continue
    r = fp.GetBoundingBox(False)
    bb[fp.GetReference()] = (r.GetLeft()/1e6-100, r.GetTop()/1e6-100,
                             r.GetRight()/1e6-100, r.GetBottom()/1e6-100)

font, sfont = ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 18)
os.makedirs(os.path.join(HERE, "annotated"), exist_ok=True)
for name, (dx, dy) in SHIFTS.items():
    im = Image.open(os.path.join(HERE, name)).convert("RGB")
    dr = ImageDraw.Draw(im)
    W, H = im.size
    for ref, (x0, y0, x1, y1) in bb.items():
        big = max(x1-x0, y1-y0) >= 2.4
        c0, c1 = A - S*y1 + dx, A - S*y0 + dx
        r0, r1 = S*x0 + B + dy, S*x1 + B + dy
        off = c0 < -5 or c1 > W+5 or r0 < -5 or r1 > H+5
        c0c, r0c, c1c, r1c = max(c0, 1), max(r0, 1), min(c1, W-2), min(r1, H-2)
        if c1c - c0c < 4 or r1c - r0c < 4:
            continue
        color = (255, 140, 0) if ref in DNP else ((255, 40, 40) if ref == "J4" else (0, 200, 60))
        dr.rectangle([c0c, r0c, c1c, r1c], outline=color, width=3 if big else 2)
        if big or ref in DNP:
            label = ref + (" DNP" if ref in DNP else "") + (" (cut)" if off else "")
            f = font if big else sfont
            tx, ty = max(c0c+3, 2), max(r0c-30, 2)
            tb = dr.textbbox((tx, ty), label, font=f)
            dr.rectangle([tb[0]-2, tb[1]-1, tb[2]+2, tb[3]+1], fill=(255, 255, 255))
            dr.text((tx, ty), label, fill=color, font=f)
    x0, y0, x1, y1 = bb["J4"]
    c0, c1 = A - S*y1 + dx, A - S*y0 + dx
    r0 = S*x0 + B + dy
    if r0 > H:
        cm = (c0 + c1) / 2
        dr.polygon([(cm-25, H-70), (cm+25, H-70), (cm, H-15)], fill=(255, 40, 40))
        lbl = f"J4 {int(r0-H)}px below frame"
        tb = dr.textbbox((cm-160, H-115), lbl, font=font)
        dr.rectangle([tb[0]-2, tb[1]-1, tb[2]+2, tb[3]+1], fill=(255, 255, 255))
        dr.text((cm-160, H-115), lbl, fill=(255, 40, 40), font=font)
    out = os.path.join(HERE, "annotated", f"{name[0]}-annotated.png")
    im.save(out)
    print("wrote", out)
