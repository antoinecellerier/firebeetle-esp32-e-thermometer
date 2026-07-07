"""Authored PCB layout: board outline, placement, tracks, vias, zones, silk.

Coordinates are board-relative millimetres (origin = board top-left corner);
pcb.py adds BOARD["origin"] to everything. Rotations are KiCad footprint
orientations in degrees (CCW positive).

PLACE:  {ref: (x, y, rot)}                     all footprints top side
TRACKS: [(net, layer, width_mm, [nodes...])]   node = "REF.PAD" | (x, y);
        unaligned consecutive nodes get one auto 45-degree dogleg
        (diagonal leg first). net is the circuit.py name ("~" names allowed —
        pcb.py resolves them to the exported KiCad net); every REF.PAD node
        must belong to that net (build error otherwise).
VIAS:   [(net, x, y)]                          through via, DEFAULT_VIA sizes
STITCH: [(x, y)]                               GND stitching vias
COPPER_ZONES: [(net, layer, [(x, y) corners])] filled polygons, lowest priority
KEEPOUTS: [dict(name=, layers=[...], rect=(x1, y1, x2, y2),
                tracks=, vias=, fills=, pads=)] rule areas
SILK:   [(text, x, y, size_mm, rot)]           F.SilkS text, thickness 0.15*size
"""

# Board outline: 45x35mm, top-left at sheet (100,100). West short edge carries
# the MINI-1 with its antenna section at the edge (keep-out under it, both
# layers). East short edge: FPC + jumpers. North long edge: USB-C.
BOARD = dict(origin=(100.0, 100.0), size=(45.0, 35.0))

DEFAULT_VIA = dict(diameter=0.6, drill=0.3)

# ---------------------------------------------------------------------------
# Placement. PROVISIONAL parking grid for the pcb.py bring-up (M2): components
# grouped in rough block positions per LAYOUT-PLAN section 2. Refined
# per-component in M3 against ratsnest + renders.
# ---------------------------------------------------------------------------

PLACE = {
    # D: MCU module — antenna section toward the west (x-) board edge
    "U1": (10.0, 17.5, 90),
}

_ZONE_PARKS = {
    # zone key -> (x0, y0, cols, pitch)
    "A: Battery + PPK2 break": (4.0, 31.0, 8, 3.0),
    "B: 3V3 LDO": (22.0, 27.0, 6, 3.0),
    "C: USB-C + charger": (22.0, 3.0, 8, 3.0),
    "D: ESP32-C6": (16.0, 8.0, 4, 3.0),          # U1 support parts (U1 itself above)
    "E: BMP581": (24.0, 31.0, 8, 3.0),
    "F: EPD power gate": (30.0, 14.0, 5, 3.0),
    "G: EPD booster": (30.0, 20.0, 8, 3.0),
    "H: EPD FPC": (36.0, 6.0, 6, 3.0),
    "I: Battery sense": (22.0, 14.0, 5, 3.0),
    "J: Debug": (10.0, 33.0, 10, 3.0),
}


def _provisional_place():
    import circuit
    counters = {}
    for c in circuit.COMPONENTS:
        ref = c["ref"]
        if ref in PLACE:
            continue
        x0, y0, cols, pitch = _ZONE_PARKS[c["zone"]]
        i = counters.get(c["zone"], 0)
        counters[c["zone"]] = i + 1
        PLACE[ref] = (x0 + (i % cols) * pitch, y0 + (i // cols) * pitch, 0)


_provisional_place()

# ---------------------------------------------------------------------------

TRACKS = []

VIAS = []

STITCH = []

# B.Cu ground pour over the full board (the antenna keep-out rule area
# excludes it from the antenna region).
COPPER_ZONES = [
    ("GND", "B.Cu", [(0, 0), (45.0, 0), (45.0, 35.0), (0, 35.0)]),
]

KEEPOUTS = []

SILK = []
