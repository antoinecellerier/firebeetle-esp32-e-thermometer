"""Authored PCB layout: board outline, placement, tracks, vias, zones, silk.

Coordinates are board-relative millimetres (origin = board top-left corner);
pcb.py adds BOARD["origin"] to everything. Rotations are KiCad footprint
orientations in degrees (CCW positive; with y down, +90 maps (x,y)->(y,-x)).

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

Floorplan (48x35; pouch-adjacent target relaxed for the antenna keep-out,
booster HV clearances and the routable-density limit):
  west      U1 MINI-1, antenna section at the edge under a both-layer keep-out
  north     EN/BOOT buttons + CHG LED, USB-C (J3), charger block NE
  east      J4 FPC (cable exits east), storage-cap columns + south row before it
  centre    channel col + crystal, L1/L2, gate, booster jumpers/RESE/pump
  south     sensors SW corner (keep-outs), LDO, divider, JST + Q6/JP1/J2, J5
  bottom    bench test pads, DNP/hand-solder small parts (C9/C14/C15/C29/D7/R9)
  MINI-1 rot 90 pad sides: EAST col s->n: 12 IO0, 13 IO1, 14 GND, 15 SDA,
  16 SCL, 17 D-, 18 D+, 19 GATE, 20 LED, 21 NC, 22 IO8, 23 BOOT, 24 MOSI;
  NORTH row w->e: 31 TXD0, 30 RXD0, 29 BUSY, 28 RST, 27 DC, 26 CS, 25 SCK;
  SOUTH row w->e: 1 GND, 2 GND, 3 3V3, 4 NC, 5 ADC, 6 VDIV_EN, 7 NC, 8 EN,
  9 VBUS_SENSE, 10 IO5, 11 GND.
"""

BOARD = dict(origin=(100.0, 100.0), size=(48.0, 35.0))

DEFAULT_VIA = dict(diameter=0.6, drill=0.3)

PLACE = {
    "J1": (21.0, 30.0, 0),
    "Q6": (27.45, 22.78, 90),
    "JP1": (27.59, 26.29, 0),
    "J2": (27.8, 29.6, 0),
    "TP1": (18.5, 27.4, 0, "B"),
    "TP2": (21.2, 27.4, 0, "B"),
    "TP3": (23.9, 27.4, 0, "B"),
    "U2": (9.5, 28.35, 0),
    "C1": (8.93, 33.17, 0),
    "C2": (9.14, 31.22, 0),
    "C3": (11.37, 22.52, 90),
    "C4": (8.11, 23.95, 90),
    "TP4": (11.6, 30.6, 0, "B"),
    "J3": (23.4, 5.0, 0),
    "R1": (20.82, 10.57, 90),
    "R2": (22.01, 10.57, 90),
    "U3": (24.79, 11.34, 0),
    "C5": (28.12, 11.34, 90),
    "U4": (38.2, 2.25, 0),
    "R3": (29.41, 5.28, 90),
    "C6": (37.85, 5.13, 0),
    "R4": (16.5, 1.1, 90),
    "D1": (16.5, 3.7, 90),
    "D2": (32.45, 2.29, 0),
    "Q1": (42.25, 2.48, 90),
    "R5": (30.61, 5.28, 90),
    "R22": (29.46, 7.88, 90),
    "R23": (30.66, 7.88, 90),
    "D7": (30.5, 8.2, 0, "B"),
    "U1": (11.8, 13.95, 90),
    "C7": (9.57, 22.52, 90),
    "C8": (8.11, 21.95, 90),
    "R6": (15.4, 6.3, 0),
    "C9": (14.75, 21.5, 0),
    "SW1": (3.9, 2.9, 0),
    "SW2": (11.6, 2.9, 0),
    "R7": (19.0, 23.4, 90),
    "D3": (18.67, 13.12, 90),
    "R8": (18.41, 10.38, 90),
    "Y1": (19.09, 16.84, 90),
    "C10": (18.85, 20.7, 0),
    "C11": (18.85, 19.5, 0),
    "R9": (18.5, 20.5, 0, "B"),
    "U5": (2.6, 22.4, 0),
    "R10": (6.62, 22.07, 90),
    "R11": (6.62, 24.27, 90),
    "C12": (5.41, 22.05, 90),
    "C13": (5.41, 24.05, 90),
    "U6": (2.7, 26.6, 0),
    "C26": (5.41, 26.05, 90),
    "C27": (6.61, 26.45, 90),
    "Q2": (27.25, 15.27, 90),
    "R12": (26.02, 18.47, 90),
    "R24": (27.21, 18.47, 90),
    "C28": (28.4, 18.45, 90),
    "C14": (21.5, 23.75, 0),
    "C15": (21.5, 12.75, 0),
    "TP5": (24.0, 10.0, 0, "B"),
    "L1": (22.84, 15.7, 0),
    "L2": (22.84, 20.49, 0),
    "JP5": (30.8, 11.29, 90),
    "JP6": (30.8, 14.89, 90),
    "Q3": (30.64, 18.29, 90),
    "R13": (30.02, 20.97, 90),
    "R14": (35.45, 16.53, 90),
    "R15": (35.45, 20.12, 90),
    "R16": (35.45, 23.72, 90),
    "JP2": (37.95, 16.5, 90),
    "JP3": (37.95, 20.09, 90),
    "JP4": (37.95, 23.69, 90),
    "D4": (34.65, 8.2, 0),
    "D5": (34.65, 10.79, 0),
    "D6": (34.65, 13.39, 0),
    "C16": (38.28, 8.75, 90),
    "C17": (38.28, 12.34, 90),
    "C18": (33.27, 16.55, 90),
    "TP6": (41.6, 12.6, 0, "B"),
    "TP7": (42.03, 15.28, 0, "B"),
    "TP8": (29.0, 12.6, 0, "B"),
    "TP9": (32.3, 13.5, 0, "B"),
    "J4": (44.6, 16.8, 270),
    "C19": (35.05, 27.42, 0),
    "C20": (38.65, 27.42, 0),
    "C21": (33.04, 5.33, 0),
    "C22": (33.27, 20.14, 90),
    "C23": (42.25, 27.42, 0),
    "C24": (31.45, 27.42, 0),
    "C25": (33.27, 23.74, 90),
    "R17": (44.62, 27.38, 90),
    "TP10": (41.26, 9.88, 0, "B"),
    "Q4": (14.25, 25.17, 90),
    "Q5": (14.25, 29.37, 90),
    "R18": (9.31, 25.17, 90),
    "R19": (13.02, 21.98, 90),
    "R20": (10.51, 25.17, 90),
    "R21": (11.71, 25.17, 90),
    "C29": (14.2, 26.0, 0, "B"),
    "TP11": (13.0, 23.4, 0, "B"),
    "J5": (33.8, 33.6, 90),
    "H1": (46.6, 2.1, 0),
    "H2": (2.4, 33.2, 0),
}

# ---------------------------------------------------------------------------

TRACKS = [
    # ---- battery entry chain (0.8mm; 465mA EPD refresh bursts) ----
    ("~BAT_IN", "F.Cu", 0.8, ["J1.1", (20.0, 26.0), (25.4, 26.0)]),
    ("~BAT_IN", "F.Cu", 0.6, [(25.4, 26.0), (27.45, 23.95), "Q6.3"]),
    ("~VBAT_RAW", "F.Cu", 0.8, ["Q6.2", (28.4, 24.6), (26.94, 25.6), "JP1.1"]),
    ("~VBAT_RAW", "F.Cu", 0.8, ["JP1.1", (26.94, 28.5), "J2.1"]),
    ("VBAT", "F.Cu", 0.8, ["JP1.2", (29.2, 26.0), (38.8, 26.0), (40.0, 24.8),
                           (40.0, 6.2), (44.3, 6.2), (44.3, 2.4), "Q1.3"]),
    ("VBAT", "F.Cu", 0.5, [(40.0, 4.0), (38.2, 4.0), "U4.3"]),
    ("VBAT", "F.Cu", 0.5, ["U4.3", (36.9, 4.4), "C6.1"]),
    ("VBAT", "F.Cu", 0.8, ["JP1.2", (28.24, 25.5), (27.6, 24.9), (16.3, 24.9),
                           (16.3, 26.11), "Q4.2"]),
    # divider top R18 feed hops B.Cu under the ADC resistor row
    ("VBAT", "F.Cu", 0.5, [(16.3, 24.9), (16.6, 24.6)]),
    ("VBAT", "B.Cu", 0.5, [(16.6, 24.6), (9.31, 26.3)]),
    ("VBAT", "F.Cu", 0.5, [(9.31, 26.3), "R18.1"]),
    ("VBAT", "F.Cu", 0.5, ["J2.2", (27.8, 32.14)]),

    # ---- VSYS: charger/load-share NE to LDO SW via west-edge B.Cu ----
    ("VSYS", "F.Cu", 0.5, ["D2.1", (30.45, 4.14), (29.9, 4.14)]),
    ("VSYS", "F.Cu", 0.5, [(30.45, 4.14), (40.3, 4.14), (41.8, 5.2),
                           (43.2, 5.2), "Q1.2"]),
    ("VSYS", "F.Cu", 0.5, ["D2.1", (30.0, 1.85), (30.0, 1.4)]),
    ("VSYS", "B.Cu", 0.5, [(30.0, 1.4), (16.8, 1.4), (16.8, 3.0), (6.5, 3.0),
                           (6.5, 26.1), (7.0, 26.6)]),
    ("VSYS", "F.Cu", 0.5, [(7.0, 26.6), (7.8, 27.0), "U2.1"]),
    ("VSYS", "F.Cu", 0.5, ["U2.1", "U2.3"]),
    ("VSYS", "F.Cu", 0.5, ["U2.3", (8.36, 30.4), (8.19, 30.6), "C2.1"]),
    ("VSYS", "F.Cu", 0.5, ["C2.1", (8.19, 32.2), "C1.1"]),

    # ---- VBUS (USB current path; not in the 0.5 min-width class) ----
    ("VBUS", "F.Cu", 0.4, ["J3.A9", (25.85, 2.2), (26.8, 3.2), (26.8, 6.9),
                           (27.1, 7.2), (27.1, 10.8), (26.58, 11.34), "U3.5"]),
    ("VBUS", "F.Cu", 0.4, [(27.1, 11.9), (27.72, 12.29), "C5.1"]),
    ("VBUS", "F.Cu", 0.4, [(27.1, 7.9), (28.6, 8.39), "R22.1"]),
    ("VBUS", "F.Cu", 0.4, ["R22.1", (29.9, 7.6), (30.61, 6.3), "R5.1"]),
    ("VBUS", "F.Cu", 0.4, [(27.7, 6.6), (31.5, 6.6), (33.4, 5.7), (33.4, 3.5),
                           "D2.2"]),
    ("VBUS", "F.Cu", 0.4, [(27.1, 7.2), (27.7, 6.6)]),
    ("VBUS", "F.Cu", 0.4, ["D2.2", (34.45, 3.6), (35.9, 4.0), (38.9, 4.0),
                           (39.34, 3.7), "U4.4"]),
    ("VBUS", "F.Cu", 0.4, ["U4.4", (39.6, 4.0), (40.9, 4.0), (41.3, 3.62),
                           "Q1.1"]),
    # CHG LED resistor feed (B.Cu hop past the USB shield pads)
    ("VBUS", "F.Cu", 0.4, ["J3.A4", (20.95, 2.1)]),
    ("VBUS", "B.Cu", 0.4, [(20.95, 2.1), (17.4, 1.7), (16.5, 2.2)]),
    ("VBUS", "F.Cu", 0.4, [(16.5, 2.2), "R4.1"]),
]

VIAS = [
    ("VBAT", 16.6, 24.6),
    ("VBAT", 9.31, 26.3),
    ("VSYS", 30.0, 1.4),
    ("VSYS", 7.0, 26.6),
    ("VBUS", 20.95, 2.1),
    ("VBUS", 16.5, 2.2),
]

STITCH = []

# B.Cu ground pour over the full board (the antenna keep-out excludes it
# from the antenna region); F.Cu pour added with the routing passes.
COPPER_ZONES = [
    ("GND", "B.Cu", [(0, 0), (48.0, 0), (48.0, 35.0), (0, 35.0)]),
]

KEEPOUTS = [
    # marker area (no restrictions): HV clearance relaxes to 0.18mm here so
    # the 0.5mm-pitch FPC escape routing is legal (see pcb.py .kicad_dru)
    dict(name="fpc-fanout", layers=["F.Cu", "B.Cu"], rect=(39.5, 8.0, 48.0, 25.5),
         tracks=False, vias=False, fills=False, pads=False),
    # MINI-1 antenna section (module x 0.5..5.2 at rot 90) to the board
    # edge, all copper kept out on both layers per Espressif HDG
    dict(name="antenna", layers=["F.Cu", "B.Cu"], rect=(0, 7.25, 5.3, 20.65),
         tracks=True, vias=True, fills=True, pads=False),
    # no copper/vias/pour under either pressure sensor (Bosch handling +
    # thermal-fidelity guidance)
    # sensors: no vias/pour under the body; the LGA's own escape traces are
    # unavoidable (Bosch reference layouts route them), so tracks stay legal
    dict(name="U5-sensor", layers=["F.Cu", "B.Cu"], rect=(1.3, 21.1, 3.9, 23.7),
         tracks=False, vias=True, fills=True, pads=False),
    dict(name="U6-sensor", layers=["F.Cu", "B.Cu"], rect=(0.8, 24.7, 4.6, 28.5),
         tracks=False, vias=True, fills=True, pads=False),
]

SILK = []
