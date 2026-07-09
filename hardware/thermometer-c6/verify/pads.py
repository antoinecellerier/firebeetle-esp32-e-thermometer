#!/usr/bin/env python3
"""Dump pad and courtyard geometry of the generated board, board-relative mm.

Every clearance argument starts here. Note that pcbnew's pad.GetSize() is
PRE-rotation, so margins must come from the bounding box, which is what this
prints.

Usage: python3 verify/pads.py [SELECTOR ...]     (no selector = every pad)
  REF                  every pad of a footprint          e.g. R20
  REF.PAD              one pad                           e.g. Q4.3
  net:NAME             pads on a net (suffix match)      e.g. net:EPD_VCC
  box:x1,y1,x2,y2      pads whose centre is in the box   e.g. box:6,19,18,32
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]


def load():
    board = pcbnew.LoadBoard(os.path.join(PROJECT, "thermometer-c6.kicad_pcb"))
    rows = []
    for fp in board.GetFootprints():
        cy = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
        crtyd = (cy.GetLeft() / 1e6 - OX, cy.GetTop() / 1e6 - OY,
                 cy.GetRight() / 1e6 - OX, cy.GetBottom() / 1e6 - OY)
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            layers = pad.GetLayerSet().Seq()
            d = pad.GetDrillSize()
            rows.append(dict(
                ref=fp.GetReference(), num=str(pad.GetNumber()),
                net=pad.GetNetname(),
                cx=pad.GetPosition().x / 1e6 - OX,
                cy=pad.GetPosition().y / 1e6 - OY,
                x1=bb.GetLeft() / 1e6 - OX, y1=bb.GetTop() / 1e6 - OY,
                x2=bb.GetRight() / 1e6 - OX, y2=bb.GetBottom() / 1e6 - OY,
                drill=max(d.x, d.y) / 1e6, crtyd=crtyd,
                rot=fp.GetOrientationDegrees(),
                F=pcbnew.F_Cu in layers, B=pcbnew.B_Cu in layers))
    return rows


def matches(r, sel):
    if not sel:
        return True
    for s in sel:
        if s.startswith("net:"):
            if r["net"] == s[4:] or r["net"].endswith(s[4:]):
                return True
        elif s.startswith("box:"):
            x1, y1, x2, y2 = (float(v) for v in s[4:].split(","))
            if x1 <= r["cx"] <= x2 and y1 <= r["cy"] <= y2:
                return True
        elif "." in s:
            if f'{r["ref"]}.{r["num"]}' == s:
                return True
        elif r["ref"] == s:
            return True
    return False


def main():
    sel = sys.argv[1:]
    rows = sorted((r for r in load() if matches(r, sel)),
                  key=lambda r: (r["ref"], r["num"]))
    if not rows:
        raise SystemExit("pads: nothing matched " + " ".join(sel))

    print(f"{'pad':10} {'net':16} {'centre':>16} "
          f"{'bbox (x1 y1)-(x2 y2)':>33} {'lyr':4} {'drill':>5}")
    for r in rows:
        lyr = ("F" if r["F"] else "") + ("B" if r["B"] else "") or "-"
        drill = f'{r["drill"]:.2f}' if r["drill"] else "-"
        print(f'{r["ref"] + "." + r["num"]:10} {r["net"][:16]:16} '
              f'({r["cx"]:7.3f},{r["cy"]:7.3f}) '
              f'({r["x1"]:7.3f},{r["y1"]:7.3f})-({r["x2"]:7.3f},{r["y2"]:7.3f}) '
              f'{lyr:4} {drill:>5}')

    print("\ncourtyard (F.CrtYd bbox)          size        rot")
    seen = set()
    for r in rows:
        if r["ref"] in seen:
            continue
        seen.add(r["ref"])
        c = r["crtyd"]
        if c[2] <= c[0]:  # test pads / mounting holes have none
            continue
        print(f'{r["ref"]:6} ({c[0]:7.3f},{c[1]:7.3f})-({c[2]:7.3f},{c[3]:7.3f})'
              f'  {c[2] - c[0]:6.3f} x {c[3] - c[1]:6.3f}  {r["rot"]:.0f}')


if __name__ == "__main__":
    main()
