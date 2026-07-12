#!/usr/bin/env python3
"""Extract tracks/vias from a .kicad_pcb into pcb_layout TRACKS/VIAS lines.

Escape hatch for manual routing: route interactively in KiCad on a COPY of
the board (never the generated one), then either

    python3 generator/extract_tracks.py /path/to/copy.kicad_pcb NET [NET...]

and paste the printed entries into generator/pcb_layout.py, or harvest the
whole board (every net with copper except GND) as a complete pcb_routes.py:

    python3 generator/extract_tracks.py /path/to/copy.kicad_pcb --all \\
        > generator/pcb_routes.py

Coordinates come out board-relative, matching BOARD["origin"]. In per-net
mode net names are the exported KiCad names (rename anonymous nets to their
circuit.py "~" names by hand); --all renames them automatically via pcb.py's
netlist alias map (needs out/netlist.net, i.e. run `make netlist` first).
"""
import sys
from collections import defaultdict

import pcbnew

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]

HAND_HEADER = '''\
"""Hand-routed copper, harvested wholesale from the KiCad GUI working copy.
Regenerate ONLY with `extract_tracks.py BOARD --all > pcb_routes.py` after a
GUI editing pass (HAND-ROUTING.md). `make route` refuses to overwrite this
file while HAND_ROUTED is set (FORCE_REROUTE=1 overrides and DESTROYS it)."""

HAND_ROUTED = True
'''


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    board = pcbnew.LoadBoard(sys.argv[1])
    layer_name = {pcbnew.F_Cu: "F.Cu", pcbnew.B_Cu: "B.Cu"}

    # --all: every net with copper except GND (the M6 pour owns GND), printed
    # as a complete pcb_routes.py module; anonymous nets are renamed from
    # their exported KiCad names back to circuit.py's "~" names.
    wholesale = sys.argv[2] == "--all"
    if wholesale:
        import pcb
        rename = {exp: name for name, exp in pcb.build_net_maps()[2].items()}
        wanted = {t.GetNetname() for t in board.GetTracks()} - {"GND", ""}
        unknown = wanted - set(rename)
        if unknown:
            raise SystemExit(f"extract_tracks: nets not in the netlist "
                             f"(stale board?): {sorted(unknown)}")
        print(HAND_HEADER)
    else:
        wanted = set(sys.argv[2:])
        rename = {}

    tracks = defaultdict(list)   # (net, layer, width) -> [segments]
    vias = []
    for t in board.GetTracks():
        net = t.GetNetname()
        if net not in wanted:
            continue
        net = rename.get(net, net)
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

    if wholesale:
        print("TRACKS = [")
    # chain segments into polylines where endpoints meet
    items = sorted(tracks.items()) if wholesale else list(tracks.items())
    for (net, layer, width), segs in items:
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
    if wholesale:
        print("]\n\nVIAS = [")
        for net, x, y in sorted(vias):
            print(f"    ({net!r}, {x}, {y}),")
        print("]")
    else:
        for net, x, y in vias:
            print(f"    ({net!r}, {x}, {y}),  # via")


if __name__ == "__main__":
    main()
