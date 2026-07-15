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
STITCH: [(x, y) | (x, y, dia, drill)]          GND stitching vias (STITCH_VIA
                                               size, or per-via override)
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
# GND stitch/spur vias use the 0.5mm/0.3mm board minimum: the dense pockets
# cannot clear a 0.6mm annulus, so 0.6mm leaves many GND groups unroutable.
STITCH_VIA = dict(diameter=0.5, drill=0.3)

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
    "R3": (29.41, 5.28, 270),
    "C6": (37.85, 5.13, 0),
    "R4": (16.5, 1.1, 270),
    "D1": (16.5, 3.7, 90),
    "D2": (32.45, 2.29, 0),
    "Q1": (42.25, 2.48, 90),
    "R5": (30.61, 5.28, 90),
    # VBUS_SENSE divider east of Q1, on the load-share VBUS lane: at its old
    # (29.46/30.66, 7.88) spot the mid-node was walled in on every side (VBUS
    # fanout on F; D7 + EPD_VCC's rigid Q2.3 channel on B) and unroutable.
    # Here the node exits east on F straight into the east-edge margin.
    # R22 rot 270 puts its VBUS pad north, beside the Q1.1 feed lane.
    "R22": (42.3, 6.3, 270),
    "R23": (43.5, 6.3, 90),
    "D7": (30.5, 8.2, 0, "B"),
    "U1": (11.8, 13.95, 90),
    "C7": (9.57, 22.52, 90),
    "C8": (8.11, 21.95, 90),
    # R6 (EN pull-up) belongs beside C9 at U1's south row, not in the 2.5mm
    # channel north of U1 where all six EPD signals and both UART lines cross
    "R6": (16.6, 21.5, 0),
    "C9": (14.75, 21.5, 0),
    "SW1": (3.9, 2.9, 0),
    "SW2": (11.6, 2.9, 0),
    # R7 (BOOT pull-up) lies in the pocket between SW2's and U1's courtyards:
    # BOOT taps R7.2 right in its U1.23->SW2 crossing zone, and R7.1's +3V3
    # branch reaches the trunk over the module paddle on F.Cu. At its old
    # (19.0, 23.4) spot it halved the x17.1..19.15 F.Cu column -- the south
    # corridor's only crossing of the VBAT wall -- and sat 13mm from U1.23
    # with the crystal block and the +3V3 trunk in between.
    "R7": (9.0, 6.4, 0),
    # status LED at the south edge: U1's east flank (x17.9..19.4, y9.4..14.6)
    # is the only F.Cu window for the east column's escapes, and it is the only
    # pocket between U1's and J3's courtyards, so nothing may sit there
    "D3": (14.65, 32.75, 180),
    "R8": (11.85, 32.75, 0),
    "Y1": (19.09, 16.84, 90),
    "C10": (18.85, 20.7, 0),
    "C11": (18.85, 19.5, 0),
    "R9": (18.5, 20.5, 0, "B"),
    # Sensor corner, redesigned as a unit: both sensors rot 90 put SCL/SDA on
    # the south/east faces, C12/C13/C26 leave the x5.41 picket strip (C12
    # east of U5 below the antenna keep-out, C13 to the SW corner, C26 south
    # of C27), and the I2C bus enters from the west F.Cu column and the south
    # band instead of threading the old double fence.
    "U5": (2.6, 22.4, 90),
    "R10": (5.6, 25.3, 0),
    "R11": (5.6, 26.3, 0),
    "C12": (5.6, 21.5, 180),
    "C13": (5.6, 30.6, 0),
    "U6": (2.7, 26.6, 90),
    "C26": (5.6, 28.9, 0),
    "C27": (5.6, 27.6, 0),
    "Q2": (27.25, 15.27, 90),
    # gate row: R24 flipped so all three gate pads share the north row (a bus
    # straight up to Q2.1), leaving EPD_PWR_EN and the two +3V3 pads on the
    # south row with the +3V3 pair adjacent. Nothing has to thread a pad gap.
    "R24": (26.02, 18.47, 270),
    "R12": (27.21, 18.47, 90),
    "C28": (28.4, 18.45, 90),
    "C14": (23.0, 24.0, 0),
    "C15": (21.5, 12.75, 0),
    "TP5": (24.0, 10.0, 0, "B"),
    "L1": (22.84, 15.7, 0),
    "L2": (22.84, 20.49, 0),
    "JP5": (30.8, 22.31, 270),
    "JP6": (30.8, 18.71, 270),
    "Q3": (30.64, 15.31, 270),
    "R13": (32.7, 16.3, 270),
    "R14": (35.45, 16.1, 90),
    "R15": (35.45, 12.5, 90),
    "R16": (35.45, 8.9, 90),
    "JP2": (37.95, 16.1, 270),
    "JP3": (37.95, 12.5, 270),
    "JP4": (37.95, 8.9, 270),
    "D4": (38.45, 20.3, 90),
    "D5": (30.87, 30.75, 90),
    "D6": (32.02, 27.1, 0),
    "C16": (33.27, 23.74, 270),
    "C17": (35.55, 20.6, 90),
    "C18": (35.45, 24.6, 90),
    "TP6": (38.4, 23.9, 0, "B"),
    # TP7 (EPD_PREVGL bench pad) lives between C16 and D6 on the bottom face:
    # its 2.1mm HV B.Cu wall sits out of the south corridor's east-running band
    # (y26.5..29.2) and out of the pinch band x28.7..31.1, next to the copper
    # it senses (D6.2/C18.1), leaving B.Cu descent slots either side.
    "TP7": (33.4, 24.7, 0, "B"),
    "TP8": (29.0, 12.6, 0, "B"),
    # TP9 (EPD_RESE bench pad) kisses its own net's B.Cu sense column at
    # x35.45 (same net, zero-length hookup): at its old (32.3, 13.5) spot it
    # walled the only free north-south B.Cu seam east of the booster, which
    # DBG_IO8's descent and ~EPD_VGH's C20-to-J4.5 hook both need.
    "TP9": (36.35, 10.5, 0, "B"),
    "J4": (44.6, 16.8, 270),
    "C19": (30.8, 11.3, 90),
    "C20": (33.27, 12.0, 90),
    "C21": (40.6, 27.3, 270),
    "C22": (33.27, 20.14, 90),
    "C23": (43.6, 27.3, 270),
    "C24": (46.6, 27.3, 270),
    "C25": (38.28, 24.6, 90),
    "R17": (34.9, 5.33, 0),
    "TP10": (44.4, 25.9, 0, "B"),
    "Q4": (14.25, 25.17, 90),
    "Q5": (14.25, 29.37, 90),
    # divider ladder: R20/R21 stacked horizontally so the VBAT_ADC tap is a
    # 0.71mm vertical link between adjacent pads, R20's ~VDIV_TOP pad faces
    # Q4.3 across a clear 1.77mm, and R18 (rot 270) drops ~VDIV_PGATE onto the
    # south lane that runs under the ladder to Q4's gate. The old single row at
    # y25.17 put every shared node diagonally across itself and jammed against
    # C3/C7's pads (0.645mm, and a 0.25 lane needs 0.65).
    "R18": (9.31, 25.5, 270),
    "R19": (13.02, 21.98, 270),
    "R20": (11.4, 24.65, 180),
    "R21": (11.4, 26.0, 0),
    "C29": (14.2, 26.0, 0, "B"),
    "TP11": (13.0, 23.4, 0, "B"),
    "J5": (33.9, 33.6, 90),
    "H1": (46.6, 2.1, 0),
    "H2": (2.4, 33.2, 0),
}

# ---------------------------------------------------------------------------

# GND copper, harvested wholesale from the KiCad GUI working copy
# (out/hand/thermometer-c6.kicad_pcb) alongside the signal harvest in
# pcb_routes.py. These are the GND spurs/jumpers (0.15mm, a few 0.2mm) that tie
# pour islands and pocketed GND pads to the main plane where a single stitch via
# cannot reach. STITCH (below) are the 0.5mm/0.3mm GND through-vias. The hand
# board DRC's copper-clean; regenerate both blocks by harvesting GND from the
# hand board (extract_tracks.py GND) after a GUI GND editing pass.
TRACKS = [
    ("GND", "B.Cu", 0.25, [(10.125, 26.125), (10.9, 26.9), (11.8, 26.9)]),
    ("GND", "B.Cu", 0.45, [(19.08, 6.05), (21.5, 6.05), (21.55, 6.0)]),
    ("GND", "B.Cu", 0.5, [(11.375, 22.275), (11.37, 22.27)]),
    ("GND", "B.Cu", 0.5, [(2.7, 25.375), (2.7, 24.6)]),
    ("GND", "B.Cu", 0.5, [(15.225, 21.55), (15.375, 21.7)]),
    ("GND", "B.Cu", 0.5, [(26.9, 1.7), (26.6, 1.075), (26.65, 1.025), (27.495, 1.87)]),
    ("GND", "F.Cu", 0.25, [(27.72, 6.05), (29.59, 5.79), (30.61, 4.77)]),
    ("GND", "F.Cu", 0.25, [(22.01, 10.06), (22.665, 10.715), (22.665, 10.741), (23.264, 11.34), (23.08, 11.34), (21.98, 12.75)]),
    ("GND", "F.Cu", 0.25, [(32.7, 16.81), (34.239, 17.765), (34.474, 18.0), (36.7, 18.0), (37.95, 16.75), (39.375, 18.175), (39.375, 19.109), (38.834, 19.65), (33.27, 19.19)]),
    ("GND", "F.Cu", 0.25, [(46.825, 19.025), (47.225, 19.025)]),
    ("GND", "F.Cu", 0.3, [(46.225, 19.05), (44.55, 19.05), (44.5, 19.0), (41.2, 19.0)]),
    ("GND", "F.Cu", 0.3, [(14.7, 7.0), (16.3, 7.0), (16.75, 8.0)]),
    ("GND", "F.Cu", 0.3, [(4.35, 22.95), (3.412, 22.95), (3.362, 22.9)]),
    ("GND", "F.Cu", 0.3, [(0.8, 21.9), (1.84, 21.9), (1.84, 22.4)]),
    ("GND", "F.Cu", 0.4, [(4.4, 22.9), (4.35, 22.95), (4.25, 22.85)]),
    ("GND", "F.Cu", 0.45, [(29.375, 13.775), (29.375, 11.25), (29.425, 11.2)]),
    ("GND", "F.Cu", 0.45, [(17.06, 5.79), (14.165, 5.79), (14.1, 5.725), (13.3, 5.43)]),
    ("GND", "F.Cu", 0.5, [(8.425, 21.625), (9.1, 21.925), (9.125, 21.95), (9.8, 22.125)]),
    ("GND", "F.Cu", 0.5, [(11.375, 22.2), (11.375, 22.275)]),
    ("GND", "F.Cu", 0.5, [(13.02, 22.49), (11.37, 21.745)]),
    ("GND", "F.Cu", 0.5, [(11.0, 9.8), (13.4, 9.8), (13.5, 9.7)]),
    ("GND", "F.Cu", 0.5, [(30.5, 33.4), (30.87, 32.4)]),
    ("GND", "F.Cu", 0.5, [(14.95, 10.35), (11.525, 10.35), (11.475, 10.3)]),
    ("GND", "F.Cu", 0.5, [(38.025, 26.85), (38.05, 26.825)]),
    ("GND", "F.Cu", 0.5, [(33.675, 19.9), (33.27, 19.19)]),
    ("GND", "B.Cu", 0.25, [(27.72, 6.05), (23.25, 6.05), (22.425, 6.875)]),
    ("GND", "B.Cu", 0.25, [(11.5, 24.412), (11.8, 22.7), (11.375, 22.275)]),
    ("GND", "B.Cu", 0.25, [(9.875, 24.25), (10.037, 24.412), (12.491, 24.412), (12.555, 24.475), (13.445, 24.475), (13.509, 24.412), (14.988, 24.412)]),
    ("GND", "B.Cu", 0.45, [(12.495, 26.905), (14.057, 26.905), (14.45, 26.512), (14.45, 26.4)]),
    ("GND", "F.Cu", 0.25, [(8.362, 28.35), (9.5, 28.7), (9.5, 30.63), (10.09, 31.22)]),
    ("GND", "F.Cu", 0.25, [(46.225, 14.55), (45.342, 14.55), (45.232, 14.5), (44.832, 14.1), (42.8, 14.1), (41.9, 15.0)]),
    ("GND", "F.Cu", 0.25, [(15.025, 24.375), (15.025, 23.425), (14.65, 23.05), (14.214, 23.05), (13.02, 22.49)]),
    ("GND", "F.Cu", 0.25, [(10.125, 26.125), (9.955, 24.33), (9.875, 24.25), (9.25, 24.25), (8.11, 23.47)]),
    ("GND", "F.Cu", 0.25, [(19.35, 22.05), (18.65, 22.05), (16.75, 20.15), (16.75, 19.9), (16.7, 19.85), (15.8, 19.85), (15.8, 17.6), (16.7, 17.15)]),
    ("GND", "F.Cu", 0.25, [(15.23, 21.5), (15.8, 20.5), (15.8, 19.85)]),
    ("GND", "F.Cu", 0.25, [(27.72, 1.87), (28.435, 1.87), (28.435, 1.835), (29.205, 1.065), (35.74, 1.065), (36.075, 1.4), (36.075, 1.651), (36.674, 2.25), (37.062, 2.25)]),
    ("GND", "F.Cu", 0.25, [(33.27, 11.05), (34.72, 12.5), (36.4, 12.5), (37.95, 13.15)]),
    ("GND", "F.Cu", 0.25, [(5.12, 21.5), (5.12, 21.38), (6.6, 19.9), (6.72, 19.9)]),
    ("GND", "F.Cu", 0.25, [(29.925, 28.45), (29.925, 31.455), (30.87, 32.4)]),
    ("GND", "F.Cu", 0.45, [(12.495, 26.905), (11.91, 26.0)]),
    ("GND", "F.Cu", 0.5, [(14.6, 4.775), (15.361, 4.775), (15.961, 5.375), (17.039, 5.375), (17.425, 4.989), (18.375, 3.438), (19.08, 1.87), (19.08, 3.158)]),
    ("GND", "F.Cu", 0.5, [(19.08, 1.87), (19.995, 0.955)]),
    ("GND", "F.Cu", 0.5, [(14.6, 4.78), (14.58, 5.25), (14.575, 5.25), (14.1, 5.725), (16.242, 5.725), (16.3, 5.783), (14.158, 5.783), (14.1, 5.725)]),
    ("GND", "F.Cu", 0.5, [(16.283, 5.783), (16.3, 5.783)]),
]
VIAS = []

# GND through-vias (0.5mm/0.3mm, see STITCH_VIA), harvested from the hand board:
# plane-merge vias at F/B pour overlaps + spur layer-transition vias, incl. one
# under sensor U6 (vias are allowed under the sensor keep-outs; only the pour is
# barred). Rendered as STITCH_VIA positions by pcb.py.
STITCH = [
    (0.8, 21.9, 0.6, 0.3),
    (0.8, 22.7, 0.6, 0.3),
    (2.7, 25.375, 0.6, 0.3),
    (4.35, 22.95, 0.6, 0.3),
    (7.29, 3.04, 0.6, 0.3),
    (9.543, 21.703, 0.6, 0.3),
    (9.85, 22.175),
    (9.875, 24.25),
    (10.125, 26.125),
    (11.0, 9.8, 0.6, 0.3),
    (11.37, 21.7),
    (11.375, 22.275),
    (11.425, 11.55, 0.6, 0.3),
    (11.475, 10.3),
    (12.08, 12.1, 0.6, 0.3),
    (13.3, 5.43, 0.6, 0.3),
    (13.4, 2.5, 0.6, 0.3),
    (13.5, 9.7, 0.6, 0.3),
    (14.1, 5.725),
    (14.7, 7.0, 0.6, 0.3),
    (14.9, 18.5, 0.6, 0.3),
    (14.95, 10.35),
    (15.025, 24.375),
    (15.225, 21.55),
    (15.5, 7.0, 0.6, 0.3),
    (15.575, 17.875),
    (16.3, 5.783),
    (17.06, 5.79, 0.6, 0.3),
    (17.51, 30.34, 0.6, 0.3),
    (18.36, 30.34, 0.6, 0.3),
    (19.35, 22.05),
    (20.0, 34.5, 0.6, 0.3),
    (20.3, 21.2),
    (21.03, 5.78, 0.6, 0.3),
    (21.55, 6.0),
    (22.425, 6.875, 0.6, 0.3),
    (23.0, 6.5, 0.6, 0.3),
    (23.375, 23.625),
    (25.51, 28.13, 0.6, 0.3),
    (25.77, 28.94, 0.6, 0.3),
    (26.0, 23.3),
    (26.65, 1.025),
    (26.9, 1.7, 0.6, 0.3),
    (29.375, 13.775),
    (29.48, 11.15, 0.6, 0.3),
    (29.925, 28.45),
    (30.5, 33.4, 0.6, 0.3),
    (32.62, 11.07, 0.6, 0.3),
    (32.7, 16.81, 0.6, 0.3),
    (32.8, 19.8, 0.6, 0.3),
    (33.675, 19.9),
    (36.025, 24.125, 0.6, 0.3),
    (37.275, 24.65),
    (38.05, 26.825, 0.6, 0.3),
    (38.8, 5.13, 0.6, 0.3),
    (39.65, 5.13, 0.6, 0.3),
    (40.025, 14.525, 0.6, 0.3),
    (40.635, 6.535),
    (40.9, 13.9, 0.6, 0.3),
    (41.3, 6.5),
    (41.75, 22.0),
    (41.9, 15.0, 0.6, 0.3),
    (42.35, 14.525),
    (44.5, 19.0),
    (44.7, 6.4, 0.6, 0.3),
    (46.6, 5.7, 0.6, 0.3),
    (46.6, 6.7, 0.6, 0.3),
    (12.495, 26.905),
]

# B.Cu ground pour over the full board (the antenna keep-out excludes it
# from the antenna region); F.Cu pour added with the routing passes.
COPPER_ZONES = [
    ("GND", "B.Cu", [(0, 0), (BOARD["size"][0], 0),
                     BOARD["size"], (0, BOARD["size"][1])]),
    # F.Cu GND pour (M6): picks up the 77 top-only GND pads (U1's ground
    # array above all) and doubles as the antenna counterpoise in the
    # antenna-margin area; excluded from the antenna + sensor keep-outs
    # like the B pour. Priorities don't interact across layers.
    ("GND", "F.Cu", [(0, 0), (BOARD["size"][0], 0),
                     BOARD["size"], (0, BOARD["size"][1])]),
]

KEEPOUTS = [
    # marker area (no restrictions): HV clearance relaxes to 0.18mm here so
    # the 0.5mm-pitch FPC escape routing is legal (see pcb.py .kicad_dru)
    dict(name="fpc-fanout", layers=["F.Cu", "B.Cu"],
         rect=(39.5, 8.0, BOARD["size"][0], 25.5),
         tracks=False, vias=False, fills=False, pads=False),
    # MINI-1 antenna section (module x 0.5..5.2 at rot 90) to the board
    # edge, all copper kept out on both layers per Espressif HDG
    dict(name="antenna", layers=["F.Cu", "B.Cu"], rect=(0, 7.25, 5.3, 20.65),
         tracks=True, vias=True, fills=True, pads=False),
    # extra RF margin east of the antenna keep-out (out/topo/REPORT.md
    # audit): the hand-routing cleared this strip of tracks/vias -- lock
    # that in so later passes can't regress it. GND pour stays allowed
    # (adjacent ground is the antenna's counterpoise per the module HDG).
    dict(name="antenna-margin", layers=["F.Cu", "B.Cu"],
         rect=(5.3, 8.5, 7.0, 18.0),
         tracks=True, vias=True, fills=False, pads=False),
    # No copper POUR under either pressure sensor (Bosch thermal-fidelity
    # guidance -- a large-area pour would thermally couple the temp die to the
    # board). Tracks AND vias stay legal: the LGA's escape traces are
    # unavoidable, and a single GND via is a comparable thermal path while
    # buying a low-inductance B-plane ground for the sensor's GND pad. Only
    # `fills` (pour) is barred; keep the sensor GND vias off the die pad
    # itself (via-in-pad wicks solder on an assembled LGA).
    dict(name="U5-sensor", layers=["F.Cu", "B.Cu"], rect=(1.3, 21.1, 3.9, 23.7),
         tracks=False, vias=False, fills=True, pads=False),
    dict(name="U6-sensor", layers=["F.Cu", "B.Cu"], rect=(0.8, 24.7, 4.6, 28.5),
         tracks=False, vias=False, fills=True, pads=False),
]

SILK = []

# Routed copper (generator/pcb_routes.py, checked in). Since the M5 GUI
# hand-routing, pcb_routes.py IS the board's copper (HAND_ROUTED sentinel:
# harvested verbatim, no dogleg expansion in pcb.py; route.py refuses to
# overwrite it). Hand-tweaks there are fine (same data format).
import os as _os
HAND_ROUTED = False
if not _os.environ.get("PCB_NO_ROUTES"):
    try:
        import pcb_routes as _routes
        TRACKS = TRACKS + _routes.TRACKS
        VIAS = VIAS + _routes.VIAS
        HAND_ROUTED = getattr(_routes, "HAND_ROUTED", False)
    except ImportError:
        pass
