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
    "R3": (29.41, 5.28, 90),
    "C6": (37.85, 5.13, 0),
    "R4": (16.5, 1.1, 90),
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
    "R10": (6.62, 22.07, 90),
    "R11": (6.62, 24.27, 90),
    "C12": (4.75, 21.45, 0),
    "C13": (1.3, 29.9, 0),
    "U6": (2.7, 26.6, 90),
    "C26": (6.1, 28.5, 90),
    "C27": (6.61, 26.45, 90),
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
    "R13": (32.7, 16.3, 90),
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
    "C21": (36.6, 27.42, 0),
    "C22": (33.27, 20.14, 90),
    "C23": (40.1, 27.42, 0),
    "C24": (43.6, 27.42, 0),
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
    "R19": (13.02, 21.98, 90),
    "R20": (11.4, 24.65, 180),
    "R21": (11.4, 26.0, 0),
    "C29": (14.2, 26.0, 0, "B"),
    "TP11": (13.0, 23.4, 0, "B"),
    "J5": (33.9, 33.6, 90),
    "H1": (46.6, 2.1, 0),
    "H2": (2.4, 33.2, 0),
}

# ---------------------------------------------------------------------------

# M6 GND stitching (generated by the stitch router, then exact-clearance
# verified). TRACKS below are 0.15mm GND spurs/jumpers that tie pour islands
# and pocketed GND pads to the main plane where a single stitch via cannot
# reach (the two pours share only ~5 F/B overlap regions, so most GND groups
# need a short routed hop). STITCH (below) are 0.5mm/0.3mm GND through-vias.
# Every element clears other-net copper by >=0.2mm (0.3mm vs HV, 0.18mm inside
# fpc-fanout), hole-to-hole >=0.25mm. Residual unconnected GND (sensor grounds
# under the U5/U6 keep-out, the charger's U4/R3/R5 pads, parts of the FPC-east
# region) is walled off by the existing signal hand-routing and unreachable
# without a signal reroute or keep-out change.
TRACKS = [
    ("GND", "F.Cu", 0.15, [(12.175, 25.775), (12.475, 25.475), (12.525, 25.475), (12.875, 25.125), (12.900, 25.125), (12.925, 25.100), (12.975, 25.100), (13.000, 25.075), (13.675, 25.075), (13.800, 25.200), (13.800, 25.225), (13.850, 25.275), (13.850, 25.300), (13.875, 25.325), (13.875, 25.350), (13.900, 25.375), (13.900, 25.875), (14.425, 26.400)]),
    ("GND", "B.Cu", 0.15, [(14.425, 26.400), (14.450, 26.400)]),
    ("GND", "F.Cu", 0.15, [(46.825, 19.025), (47.225, 19.025)]),
    ("GND", "F.Cu", 0.15, [(6.925, 25.825), (7.225, 25.525), (7.600, 25.525), (7.625, 25.500), (8.000, 25.500), (8.675, 24.825), (8.675, 24.800), (8.700, 24.775), (8.700, 24.675), (8.725, 24.675), (8.725, 24.600), (8.850, 24.475), (8.875, 24.475), (8.900, 24.450), (8.950, 24.450), (8.975, 24.425), (9.100, 24.425), (9.125, 24.400), (9.200, 24.400), (9.225, 24.375), (9.650, 24.375), (9.900, 24.625), (9.900, 24.700), (9.925, 24.725), (9.925, 25.925), (10.125, 26.125)]),
    ("GND", "B.Cu", 0.15, [(10.125, 26.125), (10.450, 26.450), (10.475, 26.450), (10.525, 26.500), (10.550, 26.500), (10.600, 26.550), (10.625, 26.550), (10.650, 26.575), (10.700, 26.575), (10.725, 26.600), (11.100, 26.600), (11.250, 26.750)]),
    ("GND", "F.Cu", 0.15, [(30.025, 29.925), (30.025, 29.575), (29.975, 29.525), (29.975, 29.150), (29.950, 29.125), (29.950, 28.475), (29.925, 28.450)]),
    ("GND", "F.Cu", 0.15, [(8.375, 23.700), (8.675, 24.000), (8.675, 24.075), (8.700, 24.100), (8.700, 24.150), (8.725, 24.175), (8.725, 24.275), (8.850, 24.400)]),
    ("GND", "B.Cu", 0.15, [(20.300, 21.200), (21.800, 21.200), (21.950, 21.350), (21.950, 21.375), (22.000, 21.425), (22.000, 21.450), (22.050, 21.500), (22.050, 21.525), (22.075, 21.550), (22.075, 21.625), (22.100, 21.650), (22.100, 21.925), (22.125, 21.950), (22.125, 22.025), (22.150, 22.050), (22.150, 22.125), (22.175, 22.150), (22.175, 22.225), (22.200, 22.250), (22.200, 22.350), (22.225, 22.375), (22.225, 22.450), (22.250, 22.475), (22.250, 22.500), (23.375, 23.625)]),
    ("GND", "B.Cu", 0.15, [(15.225, 21.550), (15.375, 21.700), (15.600, 21.700), (16.850, 22.950), (16.900, 22.950), (16.925, 22.975), (16.950, 22.975), (16.975, 23.000), (18.300, 23.000), (18.350, 23.050), (18.375, 23.050), (18.425, 23.100), (18.450, 23.100), (18.500, 23.150), (18.525, 23.150), (18.550, 23.175), (18.625, 23.175), (18.650, 23.200), (19.100, 23.200), (19.250, 23.050), (19.250, 23.025), (19.300, 22.975), (19.300, 22.950), (19.350, 22.900), (19.350, 22.875), (19.375, 22.850), (19.375, 22.775), (19.400, 22.750), (19.400, 22.100), (20.250, 21.250)]),
    ("GND", "B.Cu", 0.15, [(13.200, 21.750), (13.350, 21.900), (13.350, 22.225), (13.825, 22.700), (13.825, 22.725), (13.875, 22.775), (13.875, 22.800), (13.925, 22.850), (13.925, 22.875), (13.950, 22.900), (13.950, 22.925), (13.975, 22.950), (13.975, 23.000), (14.000, 23.025), (14.000, 23.075), (14.025, 23.100), (14.025, 23.150), (14.050, 23.175), (14.050, 23.350), (14.775, 24.075), (14.775, 24.125), (15.025, 24.375)]),
    ("GND", "F.Cu", 0.15, [(15.025, 24.375), (15.025, 24.875), (14.750, 25.150), (14.725, 25.150), (14.675, 25.200), (14.650, 25.200), (14.600, 25.250), (14.550, 25.250), (14.525, 25.275), (14.000, 25.275), (13.950, 25.325)]),
    ("GND", "F.Cu", 0.15, [(11.375, 22.200), (11.375, 22.275)]),
    ("GND", "B.Cu", 0.15, [(11.375, 22.275), (11.450, 22.350), (11.450, 22.450), (11.550, 22.550), (11.550, 22.575), (11.600, 22.625), (11.600, 22.650), (11.650, 22.700), (11.650, 22.725), (11.675, 22.750), (11.675, 22.825), (11.700, 22.850), (11.700, 23.300), (11.550, 23.450), (11.525, 23.450), (11.475, 23.500), (11.450, 23.500), (11.400, 23.550), (11.375, 23.550), (11.350, 23.575), (11.275, 23.575), (11.250, 23.600), (10.525, 23.600), (9.875, 24.250)]),
    ("GND", "F.Cu", 0.15, [(9.875, 24.250), (9.750, 24.375)]),
    ("GND", "F.Cu", 0.15, [(16.000, 20.200), (16.900, 20.200), (17.950, 21.250), (17.975, 21.250), (18.000, 21.275), (18.025, 21.275), (18.050, 21.300), (18.150, 21.300), (18.175, 21.325), (18.625, 21.325), (19.350, 22.050)]),
    ("GND", "F.Cu", 0.15, [(16.300, 17.350), (16.250, 17.400), (16.225, 17.400), (16.200, 17.425), (16.175, 17.425), (16.025, 17.575), (16.025, 17.600), (16.000, 17.625), (16.000, 20.150)]),
    ("GND", "F.Cu", 0.15, [(19.950, 1.675), (19.650, 1.975), (19.650, 2.350), (19.625, 2.375), (19.625, 2.625), (17.100, 5.150), (17.050, 5.150), (16.975, 5.225), (16.875, 5.225), (16.850, 5.250), (14.575, 5.250), (14.100, 5.725)]),
    ("GND", "B.Cu", 0.15, [(14.100, 5.725), (13.200, 6.625), (13.200, 6.650), (13.175, 6.675), (13.175, 6.725), (13.150, 6.750), (13.150, 6.775), (13.125, 6.800), (13.125, 6.925), (13.100, 6.950), (13.100, 7.850), (14.625, 9.375), (14.625, 10.025), (14.950, 10.350)]),
    ("GND", "F.Cu", 0.15, [(14.950, 10.350), (11.525, 10.350), (11.475, 10.300)]),
    ("GND", "B.Cu", 0.15, [(11.475, 10.300), (11.475, 13.775), (15.575, 17.875)]),
    ("GND", "F.Cu", 0.15, [(15.575, 17.875), (15.950, 17.875)]),
    ("GND", "F.Cu", 0.15, [(22.175, 12.450), (22.475, 12.150), (22.475, 11.775), (22.500, 11.750), (22.500, 11.550), (22.575, 11.475), (22.575, 11.450), (22.600, 11.425), (22.600, 11.375), (22.625, 11.350), (22.625, 7.075), (21.550, 6.000)]),
    ("GND", "B.Cu", 0.15, [(21.550, 6.000), (20.000, 6.000), (19.500, 5.500)]),
    ("GND", "F.Cu", 0.15, [(19.500, 5.500), (18.175, 4.175)]),
    ("GND", "F.Cu", 0.15, [(23.000, 11.125), (22.675, 11.125)]),
    ("GND", "F.Cu", 0.15, [(16.525, 7.650), (16.525, 7.450), (16.050, 6.975)]),
    ("GND", "B.Cu", 0.15, [(16.050, 6.975), (16.050, 5.500)]),
    ("GND", "F.Cu", 0.15, [(16.050, 5.500), (16.050, 5.300)]),
    ("GND", "B.Cu", 0.15, [(9.850, 22.175), (11.275, 22.175), (11.325, 22.225)]),
    ("GND", "F.Cu", 0.15, [(8.425, 21.625), (8.725, 21.925), (9.100, 21.925), (9.125, 21.950), (9.625, 21.950), (9.800, 22.125)]),
    ("GND", "F.Cu", 0.15, [(5.475, 21.175), (5.825, 20.825)]),
    ("GND", "F.Cu", 0.15, [(45.625, 14.525), (42.350, 14.525)]),
    ("GND", "B.Cu", 0.15, [(42.350, 14.525), (40.025, 14.525)]),
    ("GND", "F.Cu", 0.15, [(40.025, 14.525), (38.125, 14.525), (36.300, 12.700), (36.250, 12.700), (36.175, 12.625), (36.150, 12.625), (36.125, 12.600), (36.000, 12.600), (35.975, 12.575), (34.850, 12.575), (34.275, 12.000), (33.550, 12.000), (32.675, 11.125)]),
    ("GND", "F.Cu", 0.15, [(38.025, 26.850), (38.050, 26.825)]),
    ("GND", "B.Cu", 0.15, [(38.050, 26.825), (38.175, 26.700), (38.775, 26.700), (43.125, 22.350), (43.125, 22.325), (43.150, 22.300), (43.150, 22.250), (43.175, 22.225), (43.175, 22.200), (43.200, 22.175), (43.200, 19.650), (43.850, 19.000), (43.850, 18.975), (43.900, 18.925), (43.900, 18.900), (43.950, 18.850), (43.950, 18.825), (43.975, 18.800), (43.975, 18.725), (44.000, 18.700), (44.000, 14.450)]),
    ("GND", "F.Cu", 0.15, [(44.000, 14.450), (44.000, 14.475)]),
    ("GND", "B.Cu", 0.15, [(41.750, 22.000), (41.900, 21.850), (41.900, 21.825), (42.250, 21.475), (42.275, 21.475), (42.300, 21.450), (42.350, 21.450), (42.375, 21.425), (42.400, 21.425), (42.425, 21.400), (43.150, 21.400)]),
    ("GND", "F.Cu", 0.15, [(32.375, 15.925), (32.000, 15.925)]),
    ("GND", "B.Cu", 0.15, [(32.000, 15.925), (31.525, 15.925), (29.375, 13.775)]),
    ("GND", "F.Cu", 0.15, [(29.375, 13.775), (29.375, 11.250), (29.425, 11.200)]),
    ("GND", "B.Cu", 0.15, [(36.025, 24.125), (36.175, 24.275), (36.900, 24.275), (37.275, 24.650)]),
    ("GND", "F.Cu", 0.15, [(37.275, 24.650), (37.275, 24.875), (37.200, 24.950), (37.200, 25.000), (37.150, 25.050), (37.150, 25.150), (37.125, 25.175), (37.125, 26.100), (37.375, 26.350), (37.400, 26.350), (37.450, 26.400), (37.475, 26.400), (37.500, 26.425), (37.550, 26.425), (37.575, 26.450), (37.625, 26.450), (37.975, 26.800)]),
    ("GND", "F.Cu", 0.15, [(33.675, 19.700), (33.675, 19.900)]),
    ("GND", "B.Cu", 0.15, [(33.675, 19.900), (33.675, 22.725), (34.050, 23.100), (34.075, 23.100), (34.125, 23.150), (34.150, 23.150), (34.200, 23.200), (34.225, 23.200), (34.250, 23.225), (34.325, 23.225), (34.350, 23.250), (34.850, 23.250), (34.875, 23.275), (34.925, 23.275), (34.950, 23.300), (34.975, 23.300), (35.000, 23.325), (35.050, 23.325), (35.075, 23.350), (35.125, 23.350), (35.150, 23.375), (35.175, 23.375), (35.200, 23.400), (35.250, 23.400), (35.275, 23.425), (35.325, 23.425), (35.975, 24.075)]),
    ("GND", "F.Cu", 0.15, [(34.825, 19.650), (33.725, 19.650)]),
    ("GND", "F.Cu", 0.15, [(14.600, 4.780), (14.580, 5.250)]),
    ("GND", "F.Cu", 0.15, [(1.840, 21.900), (1.840, 22.400)]),
    # U5.8/9 escape: west across the clear F.Cu gap to a stitch via into the
    # B.Cu west-edge plane (via at 0.70,21.90, below the antenna keep-out).
    ("GND", "F.Cu", 0.15, [(1.840, 21.900), (0.700, 21.900)]),
]

VIAS = []

# GND through-vias (0.5mm/0.3mm, see STITCH_VIA): plane-merge vias at F/B pour
# overlaps + the spur layer-transition vias, sorted by y. Each sits inside GND
# fill on both layers with >=0.28mm inward margin (auto-clears other-net copper
# to spec) and >=0.55mm centre-to-centre from every other hole.
STITCH = [
    (0.700, 21.900),
    (26.650, 1.575),
    (7.290, 3.040),
    (16.050, 5.500),
    (19.500, 5.500),
    (14.100, 5.725),
    (21.030, 5.780),
    (21.550, 6.000),
    (46.740, 6.340),
    (16.050, 6.975),
    (11.475, 10.300),
    (14.950, 10.350),
    (32.620, 11.070),
    (29.480, 11.150),
    (11.425, 11.550),
    (29.375, 13.775),
    (40.025, 14.525),
    (42.350, 14.525),
    (44.000, 14.450),
    (32.000, 15.925),
    (15.575, 17.875),
    (33.675, 19.900),
    (20.300, 21.200),
    (15.225, 21.550),
    (13.200, 21.750),
    (41.750, 22.000),
    (19.350, 22.050),
    (9.850, 22.175),
    (11.375, 22.275),
    (23.375, 23.625),
    (36.025, 24.125),
    (9.875, 24.250),
    (15.025, 24.375),
    (37.275, 24.650),
    (10.125, 26.125),
    (14.425, 26.400),
    (38.050, 26.825),
    (25.510, 28.130),
    (29.925, 28.450),
    (17.510, 30.340),
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
