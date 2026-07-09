#!/usr/bin/env python3
"""Extract tracks/vias from a .kicad_pcb into pcb_layout TRACKS/VIAS lines.

Escape hatch for manual routing: route a net interactively in KiCad, save a
COPY of the board (never the generated one), then run

    python3 generator/extract_tracks.py /path/to/copy.kicad_pcb NET [NET...]

and paste the printed entries into generator/pcb_routes.py (or pcb_layout.py
for hand-authored copper). Coordinates come out board-relative, matching
BOARD["origin"]. Net names are the exported KiCad names; anonymous nets can
be given as the circuit.py "~" name via the pin-set mapping in pcb.py, so
paste the name the board file uses and rename by hand if needed.
"""
import sys
from collections import defaultdict

import pcbnew

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    board = pcbnew.LoadBoard(sys.argv[1])
    wanted = set(sys.argv[2:])
    layer_name = {pcbnew.F_Cu: "F.Cu", pcbnew.B_Cu: "B.Cu"}

    tracks = defaultdict(list)   # (net, layer, width) -> [segments]
    vias = []
    for t in board.GetTracks():
        net = t.GetNetname()
        if net not in wanted:
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            vias.append((net, round(p.x / 1e6 - OX, 3),
                         round(p.y / 1e6 - OY, 3)))
        else:
            s, e = t.GetStart(), t.GetEnd()
            key = (net, layer_name.get(t.GetLayer(), "?"),
                   round(t.GetWidth() / 1e6, 3))
            tracks[key].append(
                ((round(s.x / 1e6 - OX, 3), round(s.y / 1e6 - OY, 3)),
                 (round(e.x / 1e6 - OX, 3), round(e.y / 1e6 - OY, 3))))

    # chain segments into polylines where endpoints meet
    for (net, layer, width), segs in tracks.items():
        segs = segs[:]
        while segs:
            chain = list(segs.pop(0))
            grew = True
            while grew:
                grew = False
                for i, (a, b) in enumerate(segs):
                    if a == chain[-1]:
                        chain.append(b)
                    elif b == chain[-1]:
                        chain.append(a)
                    elif a == chain[0]:
                        chain.insert(0, b)
                    elif b == chain[0]:
                        chain.insert(0, a)
                    else:
                        continue
                    segs.pop(i)
                    grew = True
                    break
            pts = ", ".join(f"({x}, {y})" for x, y in chain)
            print(f"    ({net!r}, {layer!r}, {width}, [{pts}]),")
    for net, x, y in vias:
        print(f"    ({net!r}, {x}, {y}),  # via")


if __name__ == "__main__":
    main()
