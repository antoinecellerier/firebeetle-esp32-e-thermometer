#!/usr/bin/env python3
"""Render what route.py's A* actually sees, as a PNG.

Drives route.py's own Bitmap/build_bitmaps, so the picture is the obstacle set
the router searched -- not an approximation of it. Corridors that look open on
the board renders are routinely 0.05mm wide here, and vice versa.

  red    F.Cu blocked, B.Cu free      blue   B.Cu blocked, F.Cu free
  black  both blocked                 white  free on both
  green  1mm grid, brighter every 5mm

The routed net's own copper reads as free (clearance is waived against it), so
render for the net you are about to author.

  PCB_NO_ROUTES=1  authored copper only -- what the router starts from
  (unset)          authored + checked-in pcb_routes -- what is on the board now

Usage: python3 verify/occupancy.py NET WIDTH OUT.png [x1 y1 x2 y2] [--via]

`--via` renders the via-placement bitmap instead of the track one: it also
carries the net-agnostic hole keep-outs, so it is the map to read when a via
has nowhere to land.
"""

import os
import sys

NOROUTES = bool(os.environ.get("PCB_NO_ROUTES"))

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

# pcb_layout must be imported BEFORE route, which forces PCB_NO_ROUTES=1 for
# its own use. The cached module then keeps whatever routes the env asked for.
import pcb_layout as pl  # noqa: F401,E402
import route as rt  # noqa: E402
from PIL import Image  # noqa: E402

SCALE = 4  # px per 0.05mm cell -> 80 px/mm


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__.strip().splitlines()[-4])
    net, width, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    rest = [a for a in sys.argv[4:] if not a.startswith("--")]
    kind = "via" if "--via" in sys.argv else "trk"
    bw, bh = pl.BOARD["size"]
    crop = tuple(float(v) for v in rest[:4]) if len(rest) >= 4 else (0, 0, bw, bh)

    pads = rt.load_pads()
    alias = rt.net_alias(pads)
    segs, vias = rt.authored_copper(pads)
    exp = alias.get(net, net)
    maps = rt.build_bitmaps(pads, segs, vias, exp, width, alias)

    cx1, cy1 = rt.cell(crop[0], crop[1])
    cx2, cy2 = rt.cell(crop[2], crop[3])
    img = Image.new("RGB", ((cx2 - cx1) * SCALE, (cy2 - cy1) * SCALE),
                    (255, 255, 255))
    px = img.load()
    for iy in range(cy1, cy2):
        for ix in range(cx1, cx2):
            f = rt.blocked(maps, kind, "F.Cu", ix, iy)
            b = rt.blocked(maps, kind, "B.Cu", ix, iy)
            if f and b:
                c = (40, 40, 40)
            elif f:
                c = (235, 120, 120)
            elif b:
                c = (120, 150, 235)
            else:
                continue
            for dy in range(SCALE):
                for dx in range(SCALE):
                    px[(ix - cx1) * SCALE + dx, (iy - cy1) * SCALE + dy] = c

    for mx in range(int(crop[0]), int(crop[2]) + 1):
        ix = (rt.cell(mx, 0)[0] - cx1) * SCALE
        if 0 <= ix < img.width:
            col = (0, 190, 0) if mx % 5 == 0 else (190, 235, 190)
            for y in range(img.height):
                px[ix, y] = col
    for my in range(int(crop[1]), int(crop[3]) + 1):
        iy = (rt.cell(0, my)[1] - cy1) * SCALE
        if 0 <= iy < img.height:
            col = (0, 190, 0) if my % 5 == 0 else (190, 235, 190)
            for x in range(img.width):
                px[x, iy] = col

    img.save(out)
    src = "authored only" if NOROUTES else "authored + routed"
    print(f"occupancy: {out}  net={net} (exported {exp}) width={width} "
          f"kind={kind} crop={crop}\n  {src}, {len(segs)} segments, "
          f"{len(vias)} vias; {img.width}x{img.height}px at {SCALE * 20}px/mm")


if __name__ == "__main__":
    main()
