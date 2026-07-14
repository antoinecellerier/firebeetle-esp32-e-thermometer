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

BOARD = dict(origin=(100.0, 100.0), size=(49.0, 36.0))

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
    "C13": (1.3, 29.9, 0),
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
    ("GND", "F.Cu", 0.15, [(8.85, 24.475), (8.875, 24.475), (8.9, 24.45), (8.95, 24.45), (8.975, 24.425), (9.1, 24.425), (9.125, 24.4), (9.2, 24.4), (9.225, 24.375), (9.65, 24.375), (9.9, 24.625), (9.9, 24.7), (9.925, 24.725), (9.925, 25.925), (10.125, 26.125)]),
    ("GND", "F.Cu", 0.15, [(37.275, 24.65), (37.275, 24.875), (37.2, 24.95), (37.2, 25.0), (37.15, 25.05), (37.15, 25.15), (37.125, 25.175), (37.125, 26.1), (37.375, 26.35), (37.4, 26.35), (37.45, 26.4), (37.475, 26.4), (37.5, 26.425), (37.55, 26.425), (37.575, 26.45), (37.625, 26.45), (37.975, 26.8)]),
    ("GND", "F.Cu", 0.15, [(8.375, 23.7), (8.675, 24.0), (8.675, 24.075), (8.7, 24.1), (8.7, 24.15), (8.725, 24.175), (8.725, 24.275), (8.85, 24.4)]),
    ("GND", "F.Cu", 0.15, [(30.025, 29.925), (30.025, 29.575), (29.975, 29.525), (29.975, 29.15), (29.95, 29.125), (29.95, 28.475), (29.925, 28.45)]),
    ("GND", "F.Cu", 0.15, [(22.175, 12.45), (22.475, 12.15), (22.475, 11.775), (22.5, 11.75), (22.5, 11.55), (22.575, 11.475), (22.575, 11.45), (22.6, 11.425), (22.6, 11.375), (22.625, 11.35), (22.625, 7.075), (21.55, 6.0)]),
    ("GND", "F.Cu", 0.15, [(9.875, 24.25), (9.75, 24.375)]),
    ("GND", "F.Cu", 0.15, [(16.0, 20.2), (16.9, 20.2), (17.95, 21.25), (17.975, 21.25), (18.0, 21.275), (18.025, 21.275), (18.05, 21.3), (18.15, 21.3), (18.175, 21.325), (18.625, 21.325), (19.35, 22.05)]),
    ("GND", "F.Cu", 0.15, [(1.84, 22.4), (1.84, 21.9), (0.7, 21.9)]),
    ("GND", "F.Cu", 0.15, [(15.025, 24.375), (15.025, 24.875), (14.75, 25.15), (14.725, 25.15), (14.675, 25.2), (14.65, 25.2), (14.6, 25.25), (14.55, 25.25), (14.525, 25.275), (14.0, 25.275), (13.95, 25.325)]),
    ("GND", "F.Cu", 0.15, [(16.3, 17.35), (16.25, 17.4), (16.225, 17.4), (16.2, 17.425), (16.175, 17.425), (16.025, 17.575), (16.025, 17.6), (16.0, 17.625), (16.0, 20.15)]),
    ("GND", "F.Cu", 0.15, [(12.175, 25.775), (12.475, 25.475), (12.525, 25.475), (12.875, 25.125), (12.9, 25.125), (12.925, 25.1), (12.975, 25.1), (13.0, 25.075), (13.675, 25.075), (13.8, 25.2), (13.8, 25.225), (13.85, 25.275), (13.85, 25.3), (13.875, 25.325), (13.875, 25.35), (13.9, 25.375), (13.9, 25.875), (14.425, 26.4)]),
    ("GND", "F.Cu", 0.15, [(16.05, 5.5), (16.05, 5.3)]),
    ("GND", "F.Cu", 0.15, [(11.375, 22.2), (11.375, 22.275)]),
    ("GND", "F.Cu", 0.15, [(45.625, 14.525), (45.575, 14.475), (45.35, 14.475), (45.35, 14.25), (44.68, 13.58), (43.295, 13.58), (42.35, 14.525)]),
    ("GND", "F.Cu", 0.15, [(8.425, 21.625), (8.725, 21.925), (9.1, 21.925), (9.125, 21.95), (9.625, 21.95), (9.8, 22.125)]),
    ("GND", "F.Cu", 0.15, [(19.95, 1.675), (19.65, 1.975), (19.65, 2.35), (19.625, 2.375), (19.625, 2.625), (17.1, 5.15), (17.05, 5.15), (16.975, 5.225), (16.875, 5.225), (16.85, 5.25), (14.58, 5.25), (14.6, 4.78)]),
    ("GND", "F.Cu", 0.15, [(40.025, 14.525), (38.125, 14.525), (36.3, 12.7), (36.25, 12.7), (36.175, 12.625), (36.15, 12.625), (36.125, 12.6), (36.0, 12.6), (35.975, 12.575), (34.85, 12.575), (34.275, 12.0), (33.55, 12.0), (32.675, 11.125)]),
    ("GND", "F.Cu", 0.15, [(19.5, 5.5), (18.175, 4.175)]),
    ("GND", "F.Cu", 0.15, [(16.525, 7.65), (16.525, 7.45), (16.05, 6.975)]),
    ("GND", "F.Cu", 0.15, [(46.825, 19.025), (47.225, 19.025)]),
    ("GND", "F.Cu", 0.15, [(14.58, 5.25), (14.575, 5.25), (14.1, 5.725)]),
    ("GND", "F.Cu", 0.15, [(33.675, 19.9), (33.675, 19.595), (33.27, 19.19)]),
    ("GND", "F.Cu", 0.15, [(14.95, 10.35), (11.525, 10.35), (11.475, 10.3)]),
    ("GND", "F.Cu", 0.15, [(23.0, 11.125), (22.675, 11.125)]),
    ("GND", "F.Cu", 0.15, [(15.575, 17.875), (15.95, 17.875)]),
    ("GND", "F.Cu", 0.15, [(29.375, 13.775), (29.375, 11.25), (29.425, 11.2)]),
    ("GND", "F.Cu", 0.15, [(38.025, 26.85), (38.05, 26.825)]),
    ("GND", "F.Cu", 0.2, [(32.7, 16.81), (33.353, 17.463), (34.403, 17.463), (34.765, 17.825), (36.875, 17.825), (37.95, 16.75), (39.35, 18.15), (39.35, 19.15), (38.85, 19.65), (35.55, 19.65), (35.09, 19.19), (33.27, 19.19)]),
    ("GND", "F.Cu", 0.2, [(13.02, 22.49), (12.115, 22.49), (11.37, 21.745)]),
    ("GND", "F.Cu", 0.2, [(3.362, 22.9), (3.463, 23.0), (4.2, 23.0), (4.3, 23.0)]),
    ("GND", "F.Cu", 0.2, [(46.225, 19.05), (44.55, 19.05), (44.5, 19.0)]),
    ("GND", "F.Cu", 0.2, [(37.062, 2.25), (37.725, 2.25), (38.3, 2.825), (38.3, 4.63), (38.8, 5.13)]),
    ("GND", "F.Cu", 0.2, [(27.72, 6.05), (27.98, 5.79), (29.41, 5.79), (29.59, 5.79), (30.61, 4.77)]),
    ("GND", "F.Cu", 0.2, [(2.7, 25.375), (2.7, 25.3)]),
    ("GND", "B.Cu", 0.15, [(15.225, 21.55), (15.375, 21.7), (15.6, 21.7), (16.85, 22.95), (16.9, 22.95), (16.925, 22.975), (16.95, 22.975), (16.975, 23.0), (18.3, 23.0), (18.35, 23.05), (18.375, 23.05), (18.425, 23.1), (18.45, 23.1), (18.5, 23.15), (18.525, 23.15), (18.55, 23.175), (18.625, 23.175), (18.65, 23.2), (19.1, 23.2), (19.25, 23.05), (19.25, 23.025), (19.3, 22.975), (19.3, 22.95), (19.35, 22.9), (19.35, 22.875), (19.375, 22.85), (19.375, 22.775), (19.4, 22.75), (19.4, 22.1), (20.25, 21.25)]),
    ("GND", "B.Cu", 0.15, [(11.375, 22.275), (11.45, 22.35), (11.45, 22.45), (11.55, 22.55), (11.55, 22.575), (11.6, 22.625), (11.6, 22.65), (11.65, 22.7), (11.65, 22.725), (11.675, 22.75), (11.675, 22.825), (11.7, 22.85), (11.7, 23.3), (11.55, 23.45), (11.525, 23.45), (11.475, 23.5), (11.45, 23.5), (11.4, 23.55), (11.375, 23.55), (11.35, 23.575), (11.275, 23.575), (11.25, 23.6), (10.525, 23.6), (9.875, 24.25)]),
    ("GND", "B.Cu", 0.15, [(20.3, 21.2), (21.8, 21.2), (21.95, 21.35), (21.95, 21.375), (22.0, 21.425), (22.0, 21.45), (22.05, 21.5), (22.05, 21.525), (22.075, 21.55), (22.075, 21.625), (22.1, 21.65), (22.1, 21.925), (22.125, 21.95), (22.125, 22.025), (22.15, 22.05), (22.15, 22.125), (22.175, 22.15), (22.175, 22.225), (22.2, 22.25), (22.2, 22.35), (22.225, 22.375), (22.225, 22.45), (22.25, 22.475), (22.25, 22.5), (23.375, 23.625)]),
    ("GND", "B.Cu", 0.15, [(33.675, 19.9), (33.675, 22.725), (34.05, 23.1), (34.075, 23.1), (34.125, 23.15), (34.15, 23.15), (34.2, 23.2), (34.225, 23.2), (34.25, 23.225), (34.325, 23.225), (34.35, 23.25), (34.85, 23.25), (34.875, 23.275), (34.925, 23.275), (34.95, 23.3), (34.975, 23.3), (35.0, 23.325), (35.05, 23.325), (35.075, 23.35), (35.125, 23.35), (35.15, 23.375), (35.175, 23.375), (35.2, 23.4), (35.25, 23.4), (35.275, 23.425), (35.325, 23.425), (35.975, 24.075)]),
    ("GND", "B.Cu", 0.15, [(14.425, 26.4), (14.45, 26.4)]),
    ("GND", "B.Cu", 0.15, [(14.1, 5.725), (13.2, 6.625), (13.2, 6.65), (13.175, 6.675), (13.175, 6.725), (13.15, 6.75), (13.15, 6.775), (13.125, 6.8), (13.125, 6.925), (13.1, 6.95), (13.1, 7.85), (14.625, 9.375), (14.625, 10.025), (14.95, 10.35)]),
    ("GND", "B.Cu", 0.15, [(10.125, 26.125), (10.45, 26.45), (10.475, 26.45), (10.525, 26.5), (10.55, 26.5), (10.6, 26.55), (10.625, 26.55), (10.65, 26.575), (10.7, 26.575), (10.725, 26.6), (11.1, 26.6), (11.25, 26.75)]),
    ("GND", "B.Cu", 0.15, [(11.475, 10.3), (11.475, 13.775), (15.575, 17.875)]),
    ("GND", "B.Cu", 0.15, [(36.025, 24.125), (36.175, 24.275), (36.9, 24.275), (37.275, 24.65)]),
    ("GND", "B.Cu", 0.15, [(13.2, 21.75), (13.35, 21.9), (13.35, 22.225), (13.825, 22.7), (13.825, 22.725), (13.875, 22.775), (13.875, 22.8), (13.925, 22.85), (13.925, 22.875), (13.95, 22.9), (13.95, 22.925), (13.975, 22.95), (13.975, 23.0), (14.0, 23.025), (14.0, 23.075), (14.025, 23.1), (14.025, 23.15), (14.05, 23.175), (14.05, 23.35), (14.775, 24.075), (14.775, 24.125), (15.025, 24.375)]),
    ("GND", "B.Cu", 0.15, [(38.05, 26.825), (38.175, 26.7)]),
    ("GND", "B.Cu", 0.15, [(21.55, 6.0), (20.0, 6.0), (19.5, 5.5)]),
    ("GND", "B.Cu", 0.15, [(9.85, 22.175), (11.275, 22.175), (11.325, 22.225)]),
    ("GND", "B.Cu", 0.15, [(42.35, 14.525), (40.025, 14.525)]),
    ("GND", "B.Cu", 0.15, [(16.05, 6.975), (16.05, 5.5)]),
    ("GND", "B.Cu", 0.2, [(44.5, 19.0), (44.5, 19.2), (44.2, 19.5)]),
    ("GND", "B.Cu", 0.2, [(38.8, 5.13), (40.27, 6.6), (40.9, 6.6)]),
    ("GND", "B.Cu", 0.2, [(4.2, 23.0), (4.2, 22.0)]),
    ("GND", "B.Cu", 0.2, [(27.72, 1.87), (29.63, 1.87), (31.0, 0.5)]),
    ("GND", "B.Cu", 0.2, [(2.7, 25.3), (2.7, 24.6)]),
]
VIAS = []

# GND through-vias (0.5mm/0.3mm, see STITCH_VIA), harvested from the hand board:
# plane-merge vias at F/B pour overlaps + spur layer-transition vias, incl. one
# under sensor U6 (vias are allowed under the sensor keep-outs; only the pour is
# barred). Rendered as STITCH_VIA positions by pcb.py.
STITCH = [
    (17.51, 30.34),
    (36.025, 24.125),
    (21.55, 6.0),
    (9.875, 24.25),
    (11.425, 11.55),
    (9.85, 22.175),
    (26.65, 1.575),
    (37.275, 24.65),
    (15.025, 24.375),
    (40.9, 6.6),
    (41.75, 22.0),
    (19.35, 22.05),
    (14.425, 26.4),
    (2.7, 25.3),
    (29.375, 13.775),
    (15.225, 21.55),
    (11.475, 10.3),
    (15.575, 17.875),
    (42.35, 14.525),
    (16.05, 5.5),
    (29.48, 11.15),
    (23.375, 23.625),
    (25.51, 28.13),
    (14.95, 10.35),
    (7.29, 3.04),
    (33.675, 19.9),
    (20.3, 21.2),
    (29.925, 28.45),
    (46.74, 6.34),
    (38.05, 26.825),
    (11.375, 22.275),
    (40.025, 14.525),
    (32.62, 11.07),
    (16.05, 6.975),
    (19.5, 5.5),
    (14.1, 5.725),
    (21.03, 5.78),
    (32.7, 16.81),
    (0.7, 21.9),
    (4.2, 23.0),
    (10.125, 26.125),
    (44.5, 19.0),
    (38.8, 5.13),
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
