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
SILK:   [(text, x, y, size_mm, rot[, layer[, hjust[, vjust]]])]  silk text,
        thickness 0.15*size; optional layer "F.SilkS" (default) or "B.SilkS"
        (mirrored so it reads correctly through the board). hjust in
        {"L","C","R"} (default "C"), vjust in {"T","C","B"} (default "C"):
        multi-line \\n blocks anchor at a corner (e.g. "R"/"T" = top-right) so
        their lines align toward one board edge; single-line labels stay centred
SILK_SHAPES: [("rect"|"line", x1, y1, x2, y2[, layer[, width]])]  silk GRAPHIC
        outlines rendered by pcb.py add_silk_shapes as pcbnew.PCB_SHAPE. "rect"
        = one unfilled rectangle (opposite corners), "line" = one straight
        segment; layer defaults "F.SilkS", width defaults 0.15mm

Floorplan (48x35; pouch-adjacent target relaxed for the antenna keep-out,
booster HV clearances and the routable-density limit):
  west      U1 MINI-1, antenna section at the edge under a both-layer keep-out
  north     EN/BOOT buttons + CHG LED, USB-C (J3), charger block NE
  east      J4 FPC (cable exits east), storage-cap columns + south row before it
  centre    channel col + crystal, L1/L2, gate, booster jumpers/RESE/pump
  south     sensors SW corner (keep-outs), LDO, divider, JST + Q6/JP1/J2, J5
  bottom    bench test pads; back DNP/hand-solder parts D7/R9
            (C9/C14/C15 populated; C29 now front/populated)
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
    "TP1": (15.2, 26.1075, 0, "B"),
    "TP2": (21.2, 27.4, 0, "B"),
    "TP3": (23.9, 27.4, 0, "B"),
    "U2": (9.5, 28.35, 0),
    "C1": (8.93, 33.17, 0),
    "C2": (9.14, 31.22, 0),
    "C3": (11.37, 22.52, 90),
    "C4": (8.11, 23.95, 90),
    "TP4": (11.37, 23.295, 0, "B"),
    "J3": (23.4, 1.745, 180),
    "R1": (21.98, 10.63, 270),
    "R2": (20.79, 10.63, 270),
    "U3": (24.79, 11.34, 0),
    "C5": (28.12, 11.34, 90),
    "U4": (38.2, 2.25, 0),
    "R3": (29.41, 5.28, 270),
    "C6": (37.85, 5.13, 0),
    "R4": (33.9, 6.5, 180),
    "D1": (34.4875, 5.1, 180),
    "D2": (32.45, 2.29, 0),
    # Q1 sits SW of H1's mount (45.8, 2.2): pushed west+south so its SOT-23
    # courtyard clears H1's keep-out, with its VSYS/VBUS load-share copper
    # rerouted to follow (harvested from the GUI working copy).
    "Q1": (41.6, 5.0375, 90),
    "R5": (30.61, 5.28, 90),
    # VBUS_SENSE divider south of the moved Q1, on the load-share VBUS lane:
    # the mid-node exits east on F into the east-edge margin (its old central
    # spot walled it in on every side). R22 rot 0 lays VBUS (west) / VBUS_SENSE
    # (east) along Q1's south feed; R23 rot 90 drops VBUS_SENSE onto GND, its
    # ground pad landing on the (44.0, 6.6) stitch.
    "R22": (41.2, 7.6, 0),
    "R23": (44.0, 7.11, 90),
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
    "TP5": (21.34, 21.8, 0, "B"),
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
    "TP6": (38.45, 21.95, 0, "B"),
    # TP7 (EPD_PREVGL bench pad) lives between C16 and D6 on the bottom face:
    # its 2.1mm HV B.Cu wall sits out of the south corridor's east-running band
    # (y26.5..29.2) and out of the pinch band x28.7..31.1, next to the copper
    # it senses (D6.2/C18.1), leaving B.Cu descent slots either side.
    "TP7": (35.45, 25.55, 0, "B"),
    "TP8": (31.29, 14.4225, 0, "B"),
    # TP9 (EPD_RESE bench pad) kisses its own net's B.Cu sense column at
    # x35.45 (same net, zero-length hookup): at its old (32.3, 13.5) spot it
    # walled the only free north-south B.Cu seam east of the booster, which
    # DBG_IO8's descent and ~EPD_VGH's C20-to-J4.5 hook both need.
    "TP9": (35.45, 9.8125, 0, "B"),
    "J4": (43.075, 16.8, 90),
    "C19": (30.8, 11.3, 90),
    "C20": (33.27, 12.0, 90),
    "C21": (40.6, 27.3, 270),
    "C22": (33.27, 20.14, 90),
    "C23": (43.6, 27.3, 270),
    "C24": (46.6, 27.3, 270),
    "C25": (38.28, 24.6, 90),
    "R17": (31.8, 5.28, 90),
    "TP10": (38.28, 25.55, 0, "B"),
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
    "C29": (12.6, 27.7, 0),
    "TP11": (12.12, 27.7, 0, "B"),
    "J5": (33.9, 33.6, 90),
    # Diagonal M2 mount points, placed for manufacturability: center >=2.1mm
    # from every board edge (wall->edge >=1.0mm; the JLC hole-to-edge floor is
    # ~0.5mm) and clear of non-pour copper. H1 is the squeeze (east edge + the
    # VBAT/VSYS/EPD_SCK traces at x~43.2 to its west): at x45.8 the east wall
    # and the copper clearance balance at ~1.1mm. H2 is H1's 180-degree mirror
    # about the board center (24, 17.5) so the two mounts are symmetric.
    "H1": (45.8, 2.2, 0),
    "H2": (2.2, 32.8, 0),
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
    ('GND', 'F.Cu', 0.5, [(38.025, 26.85), (37.875, 27.0), (37.2, 27.0), (37.375, 26.825), (39.025, 26.825), (40.45, 28.25), (40.6, 28.25)]),
    ('GND', 'F.Cu', 0.5, [(8.425, 21.625), (8.503, 21.703), (9.543, 21.703), (9.8, 21.446), (9.8, 20.9)]),
    ('GND', 'F.Cu', 0.5, [(33.27, 19.19), (35.55, 19.65)]),
    ('GND', 'F.Cu', 0.5, [(30.5, 33.4), (30.87, 32.4)]),
    ('GND', 'F.Cu', 0.5, [(14.6, 4.775), (18.98, 4.775), (19.08, 4.875)]),
    ('GND', 'F.Cu', 0.5, [(13.02, 22.49), (11.37, 21.745)]),
    ('GND', 'F.Cu', 0.25, [(26.65, 5.79), (29.59, 5.79), (30.61, 4.77)]),
    ('GND', 'F.Cu', 0.25, [(19.4, 22.7), (18.75, 22.05), (18.65, 22.05), (16.75, 20.15), (16.75, 19.9), (16.7, 19.85), (15.8, 19.85), (15.8, 17.6), (16.7, 17.15), (19.58, 17.15), (20.315, 16.415), (20.315, 12.335), (20.535, 12.115), (20.8, 12.115), (20.79, 12.105), (20.79, 11.14), (21.98, 11.14)]),
    ('GND', 'F.Cu', 0.25, [(5.12, 21.5), (5.12, 21.38), (6.6, 19.9), (6.72, 19.9)]),
    ('GND', 'F.Cu', 0.25, [(30.8, 10.35), (33.27, 11.05), (33.57, 10.75), (36.75, 10.75), (37.95, 9.55)]),
    ('GND', 'F.Cu', 0.25, [(32.7, 16.81), (34.239, 17.765), (34.474, 18.0), (36.7, 18.0), (37.95, 16.75), (39.6, 18.4), (40.25, 19.05), (41.45, 19.05)]),
    ('GND', 'F.Cu', 0.25, [(15.025, 24.375), (15.025, 23.425), (14.65, 23.05), (14.214, 23.05), (13.02, 22.49)]),
    ('GND', 'F.Cu', 0.25, [(38.3, 0.5), (38.3, 1.401), (37.451, 2.25), (37.062, 2.25), (37.717, 2.258), (38.342, 2.883), (38.35, 4.68), (38.8, 5.13)]),
    ('GND', 'F.Cu', 0.25, [(11.91, 26.0), (11.91, 26.213), (13.08, 27.383), (13.08, 27.7)]),
    ('GND', 'F.Cu', 0.25, [(16.75, 8.0), (17.0, 8.25), (17.884, 8.25), (19.08, 7.054), (19.08, 4.875)]),
    ('GND', 'F.Cu', 0.25, [(29.925, 28.45), (29.925, 31.455), (30.87, 32.4)]),
    ('GND', 'F.Cu', 0.25, [(10.125, 26.125), (9.955, 24.33), (9.875, 24.25), (9.25, 24.25), (8.11, 23.47)]),
    ('GND', 'F.Cu', 0.25, [(31.9, 24.4), (32.0, 24.3), (29.1, 24.8), (29.3, 24.8)]),
    ('GND', 'F.Cu', 0.25, [(1.838, 22.4), (1.1, 22.4), (0.8, 22.7)]),
    ('GND', 'F.Cu', 0.25, [(21.98, 12.75), (21.98, 12.739), (21.356, 12.115), (20.8, 12.115)]),
    ('GND', 'F.Cu', 0.25, [(8.362, 28.35), (9.5, 28.7), (9.5, 30.63), (10.09, 31.22)]),
    ('GND', 'F.Cu', 0.25, [(15.8, 19.85), (15.8, 20.5), (15.23, 21.5)]),
    ('GND', 'F.Cu', 0.45, [(29.375, 13.775), (29.375, 10.455), (29.48, 10.35), (30.8, 10.35)]),
    ('GND', 'F.Cu', 0.45, [(29.375, 10.455), (29.31, 10.39), (28.12, 10.39)]),
    ('GND', 'F.Cu', 0.3, [(0.8, 21.9), (1.84, 21.9), (1.84, 22.4)]),
    ('GND', 'F.Cu', 0.3, [(4.35, 22.95), (3.412, 22.95), (3.362, 22.9)]),
    ('GND', 'F.Cu', 0.2, [(41.45, 14.55), (41.5, 14.6), (42.7, 14.6)]),
    ('GND', 'F.Cu', 0.4, [(4.4, 22.9), (4.35, 22.95), (4.25, 22.85)]),
    ('GND', 'B.Cu', 0.25, [(29.1, 24.8), (27.582, 24.8), (26.5, 23.718)]),
    ('GND', 'B.Cu', 0.25, [(14.925, 24.475), (15.025, 24.375), (15.0, 24.4), (10.025, 24.4), (9.875, 24.25)]),
    ('GND', 'B.Cu', 0.25, [(13.02, 22.49), (13.0, 22.51), (13.0, 24.4), (12.988, 24.412)]),
    ('GND', 'B.Cu', 0.5, [(2.7, 25.375), (2.7, 24.6)]),
    ('GND', 'B.Cu', 0.2, [(23.652, 11.34), (23.952, 11.04), (27.47, 11.04), (28.12, 10.39)]),
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
    (9.543, 21.703, 0.6, 0.3),
    (9.875, 24.25),
    (10.125, 26.125),
    (11.37, 21.7, 0.6, 0.3),
    (11.8, 12.0, 0.6, 0.3),
    (11.8, 15.9, 0.6, 0.3),
    (15.025, 24.375),
    (15.225, 21.55),
    (16.5, 23.366, 0.6, 0.3),
    (17.51, 30.34, 0.6, 0.3),
    (18.36, 30.34, 0.6, 0.3),
    (19.35, 22.05, 0.6, 0.3),
    # (four GND stitch vias near y5.8-6.9 pruned: J3's mouth-north respin moved
    # the USB-C pad row onto them — they fell inside VBUS/CC2/D+/D- pads.)
    (25.51, 28.13, 0.6, 0.3),
    (25.77, 28.94, 0.6, 0.3),
    (29.375, 13.775),
    (29.925, 28.45),
    (30.5, 33.4, 0.6, 0.3),
    (32.7, 16.81, 0.6, 0.3),
    (38.8, 5.13, 0.6, 0.3),
    (44.0, 6.6, 0.6, 0.3),
    # hand_diff harvest
    (9.8, 20.9),
    (23.775, 24.0),
    (26.5, 23.718),
    (29.1, 24.8, 0.6, 0.3),
    (32.0, 24.3, 0.6, 0.3),
    (33.27, 11.05, 0.6, 0.3),
    (35.45, 23.65, 0.6, 0.3),
    (39.3, 9.9, 0.6, 0.3),
    # hand_diff harvest
    (11.91, 26.0, 0.6, 0.3),
    (13.02, 22.49, 0.6, 0.3),
    (19.4, 22.7, 0.6, 0.3),
    (37.2, 27.0, 0.6, 0.3),
    (37.95, 13.15, 0.6, 0.3),
    (38.28, 23.65, 0.6, 0.3),
    # hand_diff harvest
    (0.9, 4.775, 0.6, 0.3),
    (6.9, 4.775, 0.6, 0.3),
    (8.6, 4.775, 0.6, 0.3),
    (10.4, 10.0, 0.6, 0.3),
    (11.3, 10.0, 0.6, 0.3),
    (14.0, 18.3, 0.6, 0.3),
    (14.6, 4.775, 0.6, 0.3),
    (15.0, 18.3, 0.6, 0.3),
    (20.15, 5.79, 0.6, 0.3),
    (20.9, 33.2, 0.6, 0.3),
    (23.652, 11.34, 0.6, 0.3),
    (26.65, 5.79, 0.6, 0.3),
    (28.12, 10.39, 0.6, 0.3),
    (37.95, 16.75, 0.6, 0.3),
    (43.6, 28.25, 0.6, 0.3),
    (46.6, 28.25, 0.6, 0.3),
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
         rect=(37.5, 10.0, 43.5, 23.5),
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
    # DRC-only marker (no restrictions) on F.SilkS: scopes a negative
    # silk_clearance (see pcb.py .kicad_dru rule 'silk-merge') so the JP1<->IBAT
    # link line in SILK_SHAPES may run its ends into JP1's/J2's silk boxes for
    # the intended connected look without tripping silk_overlap. Sits in the
    # pad-free gap between JP1's pads (bottom mask ~27.09) and J2's (top mask
    # ~28.70) so the marker's own F.SilkS outline clears every mask aperture
    # (no silk_over_copper); the line only has to thread the marker, not fill
    # it, for A.insideArea to match. Rule areas are DRC constructs -- not
    # plotted to the silk gerber. silk-merge intentionally not in check_pcb.py's
    # "nothing inside" list (silk, not copper); tracks/vias False keep route.py,
    # straighten.py and widen.py from ever treating it as a copper keep-out.
    dict(name="silk-merge", layers=["F.SilkS"], rect=(26.5, 27.4, 27.3, 28.1),
         tracks=False, vias=False, fills=False, pads=False),
]

# Reference-designator overrides for the refs kept on F.SilkS (J1/J5/U5/U6
# per add_footprints' KEEP_SILK_REFS). Every kept refdes must clear its part's
# body and neighbours at the >=0.8mm/0.15mm legibility floor. Tuple is
# (x, y, size_mm, angle_deg), board-relative like PLACE. (J3's refdes is not
# kept: its footprint default sits off the board outline, so it goes to F.Fab.)
REF_POS = {
    "J1": (18.5, 22.7, 0.8, 0),     # north pocket, clear of J1 body / BAT+ / C14
    "J5": (35.15, 28.6, 0.8, 0),    # grouped immediately left of the DBG marker
    #                                 (DBG nudged E to 37.5 to clear D6's silk)
    "U5": (4.7, 22.9, 0.8, 180),    # SE of U5's body, clear of C12/the keep-out
    # U6 refdes SOUTH of U6's body (clear of the sensor keep-out, y28.5): its
    # old spot between U5 and U6 could be misread as U5's. Now unambiguously U6.
    "U6": (2.7, 29.1, 0.8, 0),
}

# Footprint F.SilkS graphic items relocated to F.Fab so authored labels can sit
# where the outline used to be (and to clear residual footprint-graphic DRC).
# "all" = every F.SilkS graphic; "poly" = only filled SHAPE_T_POLY items.
# J5 (DNP debug header) carries its DBG label + kept refdes over its own
# footprint area; U1's pin-1 triangle (a POLY) overlaps C8's pad while the
# module outline rectangle stays on silk. The jumpers (JP1-JP6) keep their
# stock outline on silk — their value labels sit clear of the footprint.
SILK_TO_FAB = {"J5": "all", "U1": "poly"}

# 3D models for the footprints kicad-packages3d can't render: the six local
# footprints ship no (model) at all, and the two stock KiCad footprints (J1
# JST, J3 USB-C) reference STEP files absent from the installed 3D library.
# pcb.py attaches these after FootprintLoad. Keyed by footprint id so one entry
# covers every instance (SW1/SW2, U5/U6). STEP files live in local.3dmodels/
# (gitignored; regenerate with ./fetch-3dmodels.sh, which pulls them from the
# BOM's LCSC ids via easyeda2kicad) and resolve through ${KIPRJMOD}.
#
# The EasyEDA models are each authored against their own EasyEDA footprint, whose
# origin is not our footprint's origin, so the four larger parts need an offset
# to land their body on our F.Fab outline. Values were measured by rendering each
# part ALONE (no neighbours) and comparing the model silhouette bbox against the
# F.Fab rect; see the offset->board mapping below, which depends on the
# footprint's board rotation:
#   rot   0 : board displacement = (+ox, -oy)
#   rot +90: board displacement = (-oy, -ox)
#   rot -90: board displacement = (+oy, +ox)
# U1/J4 are rotated on this board, which is why their offsets look transposed.
# U5/U6/SW1/SW2 are symmetric about their origin and need nothing.
#
# Verify any change by rendering the part in isolation and checking its body
# against the F.Fab outline. Do NOT use model-silhouette-vs-pad-centroid
# metrics: neighbouring models bleed into the measurement window, and a pad
# bbox is not the body centre for castellated/asymmetric parts.
# value = (step_filename, offset_mm(x,y,z), rotate_deg(x,y,z), scale(x,y,z))
MODELS_3D = {
    "local:ESP32-C6-MINI-1":
        ("ESP32-C6-MINI-1.step", (0, 2.70, 0), (0, 0, 0), (1, 1, 1)),
    "local:Bosch_LGA-10_2x2mm":
        ("Bosch_LGA-10_2x2mm_BMP581.step", (0, 0, 0), (0, 0, 0), (1, 1, 1)),
    "local:Bosch_LGA-9_3.25x3.25mm":
        ("Bosch_LGA-9_3.25x3.25mm_BMP585.step", (0, 0, 0), (0, 0, 0), (1, 1, 1)),
    "local:XUNPU_FPC-05FB-24PH20":
        # The model renders the physical truth: SMT tails at the REAR
        # (actuator) face, mouth/cable-entry slot on the far side. Numeric
        # STEP proof (2026-07-19, out/j4-proof/): gold-contact feet 0.5mm
        # inside the rear wall, mouth lips 6.55mm away. J4 is placed pads-west
        # / mouth-east (rot 90), so the model seats with the mouth at the east
        # board edge, matching the panel-cable approach.
        ("XUNPU_FPC-05FB-24PH20.step", (0, 1.35, 0), (0, 0, 0), (1, 1, 1)),
    "local:SW_TS-1187A":
        ("SW_TS-1187A.step", (0, 0, 0), (0, 0, 0), (1, 1, 1)),
    "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal":
        ("JST_PH_S2B-PH-SM4-TB_Horizontal.step", (0.98, -3.25, 0), (0, 0, 0), (1, 1, 1)),
    "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12":
        # The JLC/EasyEDA STEP has its gold SMT tails at model +y and its origin
        # at the front-shell reference, ~2.3mm south of the land-pattern centroid
        # -- so the z-rot-180 that faces the mouth north pivots the body about
        # that off-centre origin and needs a y offset re-derived in the rotated
        # frame, not the un-rotated value. rotate (0,0,180) seats the mouth over
        # the north board edge and the gold tails on the south pad row; offset
        # (0,-0.94,0) lands the 4 shell legs in their plated slots and the 2
        # plastic posts in the NPTH holes (numeric STEP proof 2026-07-20,
        # out/j3-proof/: shell pegs <=0.11mm, NPTH <=0.14mm, tail row 0.11mm; x
        # exact; model front->rear leg span 4.175mm vs land 4.180mm).
        ("USB_C_Receptacle_HRO_TYPE-C-31-M-12.step", (0, -0.94, 0), (0, 0, 180), (1, 1, 1)),
}

# Functional silkscreen (M7c, LEGIBILITY-FIRST). Every authored label is
# >=0.8mm text / >=0.15mm stroke (JLCPCB reliable-silk minimum, DRC-enforced via
# min_text_height/min_text_thickness) and sits on EXPOSED silk beside its part,
# never under a chip/connector body (each label's bbox is courtyard-clear on its
# own board side).
# No "*" default markers — the ships-bridged/open state is obvious from the
# jumper pads and a printed "*" would go stale if the selection changes.
# POSITION-SPECIFIC labels stay beside their part on that part's side; general
# position-independent notes go to B.SilkS (mirrored) to free top room.
# Ω/µ/° render in KiCad's Newstroke stroke font.
SILK = [
    # === TOP (F.SilkS) — position-specific, beside the part it labels ===
    # buttons / LEDs
    ("RST", 3.9, 6.5, 0.8, 0),          # S of SW1
    ("BOOT", 11.6, 6.5, 0.8, 0),        # S of SW2
    ("CHG", 16.5, 6.5, 0.8, 0),         # S of D1 (charge LED)
    ("STATUS", 14.5, 34.2, 0.8, 0),     # S of D3 (status LED), nudged W of J1.MP
    # battery connector J1: BAT + polarity in the clear pocket N of J1's body
    ("BAT", 18.0, 24.2, 0.8, 0),
    ("+", 20.0, 24.2, 0.9, 0),          # directly above J1.1 (the + pad, x=20)
    # battery-current series-measurement break at J2 (in J2's south edge strip);
    # wick JP1 and insert an ammeter (e.g. PPK2) across J2. Label device-neutral.
    ("IBAT", 27.8, 34.48, 0.8, 0),
    # RESE sense jumpers: value beside each JP, vertical in the JP<->J4 corridor
    ("3Ω", 39.8, 8.9, 0.8, 90),         # JP4
    ("2.2Ω", 39.8, 12.5, 0.8, 90),      # JP3
    ("0.47Ω", 39.8, 16.1, 0.8, 90),     # JP2
    # inductor jumpers: value beside each JP. 10µH beside JP5 (south pocket,
    # centred to clear Q6 W / C16 E bodies); 47µH in the pocket W of JP6 between
    # C28 (W) and JP6 (E) — spot found in the GUI working copy and harvested.
    ("10µH", 30.8, 24.6, 0.8, 0),
    ("47µH", 27.8, 20.0, 0.8, 0),
    # debug header J5: per-pin legend won't fit at >=0.8mm on the crowded top;
    # DBG marker only here, with J5's kept refdes grouped immediately to its
    # left (REF_POS["J5"]) so the pair reads as one label. The full 10-pin pinout
    # is a B.SilkS legend on the BACK, north of the header (see the J5 back legend
    # below) — the pins are through-hole and land on the back, so the mirrored
    # legend aligns with them.
    ("DBG", 37.5, 28.6, 0.8, 0),
    # EPD FPC J4 (24-pin): the contact-tail pad column is WEST (x41.45) and the
    # mouth/cable entry faces EAST to the board edge. Pin 1 (north end) is
    # marked by the footprint's own pin-1 silk dot at (40.48, 11.05), just W of
    # pad 1 — the ~1.4mm corridor between JP2/3/4's silk and the pad column has
    # no room for a second >=0.8mm glyph beside the dot. "2/4" marks the south
    # (pin-24) end where the corridor is jumper-free.
    ("2\n4", 40.4, 22.6, 0.8, 0),       # W of J4 pin 24 (south end)

    # === BACK (B.SilkS, mirrored) — bench test points, label beside each pad ===
    # TP1 VBAT / TP3 GND north of their pads; TP2's GND sits SOUTH of its pad so
    # the two GND labels don't read as one row.
    ("VBAT", 18.5, 25.7, 0.8, 0, "B.SilkS"),
    ("GND", 21.2, 29.2, 0.8, 0, "B.SilkS"),
    ("GND", 23.9, 25.7, 0.8, 0, "B.SilkS"),
    # TP4 is the 3V3 rail probe-ONLY pad (RT9080 forbids back-drive); the
    # "probe-only" warning rides on TP4's own label.
    ("3V3 probe-only", 11.6, 32.3, 0.8, 0, "B.SilkS"),
    ("EPD_VCC", 24.0, 11.9, 0.8, 0, "B.SilkS"),
    # PREVGH/PREVGL/VCOM sit NORTH of their pads (smaller y) so they don't
    # crowd the J5 pinout legend that occupies the strip to their south.
    ("PREVGH", 38.4, 22.0, 0.8, 0, "B.SilkS"),
    ("PREVGL", 33.4, 22.8, 0.8, 0, "B.SilkS"),
    ("GDR", 29.0, 14.4, 0.8, 0, "B.SilkS"),
    ("RESE", 36.35, 12.3, 0.8, 0, "B.SilkS"),
    ("VCOM", 44.4, 24.0, 0.8, 0, "B.SilkS"),
    ("VBAT_ADC", 13.2, 21.5, 0.8, 0, "B.SilkS"),   # tracks TP11 (moved +0.2 in x)

    # Optional DNP hand-solder BACK parts: refdes + value beside each pad so the
    # assembler knows what fits there (both bottom-side, populated only if the
    # respective ring/startup issue proves real).
    ("D7 SMF5.0A", 30.5, 10.0, 0.8, 0, "B.SilkS"),  # VBUS surge clamp, S of D7
    # R9 10M (crystal bias) moved E of R9, clear of the VBAT_ADC TP label to its
    # west (VBAT_ADC right edge x15.98; this label left edge x19.55).
    ("R9 10M", 22.0, 20.5, 0.8, 0, "B.SilkS"),

    # JLCPCB order-number placement token (JLC's "specify a location" option):
    # JLC swaps this 12-char string for the board's order number (~same 8.5mm
    # footprint). Rotated 90 and stood vertically just E of the antenna keep-out
    # outline (rect E edge x5.3), centered on the rect's y-center (13.95) so it
    # runs parallel to the outline. ~0.7mm gap W to the rect, and it stays
    # OUTSIDE the keep-clear zone; the tall clear back band E of the antenna has
    # no back pads here, so it reads cleanly.
    ("JLCJLCJLCJLC", 6.5, 13.95, 0.8, 90, "B.SilkS"),

    # battery type by J1: J1 is a front SMD JST whose north pocket (BAT/+) has no
    # >=0.8mm exposed FRONT-silk gap (Q4 W, C14 E, caps N, J1 pads S), so the LiPo
    # spec goes on the BACK, south of J1's body — exposed there (J1 has no THT pads).
    ("3.7V LiPo", 21.0, 33.9, 0.8, 0, "B.SilkS"),

    # === BACK (B.SilkS, mirrored) — general notes, two multi-line corner blocks.
    # Each is ONE native \n text object anchored at a top corner and justified
    # toward its own board edge, so KiCad aligns the lines automatically (stored
    # justify is verbatim: SetMirrored does not flip it, so "R"/top reads
    # left-aligned from the west edge on the back, "L"/top reads right-aligned to
    # the east edge). ===
    # NW-corner block, TOP-LEFT anchored at (1.0, 0.6): project URL, the full
    # product name, "rev A" (holds the check_pcb "rev " token) and the indoor
    # charge range as one contiguous phrase. A blank line separates the URL from
    # the name. Sits in the bare NW back corner (pour-free, no back parts), north
    # of J3's front footprint; DRC-clean silk clearance.
    ("github.com/antoinecellerier\n\nLow Power ePaper Thermometer\nrev A\n"
     "CHARGE INDOORS 0-45°C", 1.0, 0.6, 0.8, 0, "B.SilkS", "R", "T"),
    # populate-ONE legend (bridge/fit exactly one per group), as ONE TOP-RIGHT
    # anchored block in the clean NE back corner (right edge x44.0), north of the
    # charger and clear of the WEST antenna keep-out and H1. Keyed off component
    # VALUES — the JP refdes aren't printed on the board. Holds the check_pcb
    # literals "bridge one" / "fit one"; the "EPD:"/"Sensor:" heads name each group.
    ("EPD: bridge one only\nRESE 0.47/2.2/3Ω\nIND 10/47µH\n"
     "Sensor: fit one only\nU5 BMP581/U6 BMP585", 44.0, 0.6, 0.8, 0,
     "B.SilkS", "L", "T"),

    # === BACK (B.SilkS) — antenna keep-out reminder ===
    # Enclosure/mounting note (keep metal/ground/battery clear of the antenna
    # region). On the BACK: the FRONT antenna area is entirely under the U1
    # module (invisible once assembled), while the back over the keep-out is
    # bare (pour excluded) and has no parts, so the note + SILK_SHAPES outline
    # read here. Rotated 90 as two columns to fit the tall/narrow keep-out box.
    ("ANTENNA", 2.0, 13.95, 0.8, 90, "B.SilkS"),
    ("KEEP CLEAR", 3.6, 13.95, 0.8, 90, "B.SilkS"),

    # === BACK (B.SilkS, mirrored) — J5 debug-header pinout legend ===
    # J5 is a 2x5 through-hole header (pads land on the back), mounted on the
    # TOP. The full 10-pin legend didn't fit at >=0.8mm on the crowded top, so it
    # lives here on the back, north of the header, column-aligned over the
    # through-hole pin pairs: each x-column is a pin pair, upper text row = the
    # NORTH (even) pin, lower text row = the SOUTH (odd) pin. Looser 1.25mm pitch,
    # bounded south by the pad tops (y30.21) and north by TP6 — MOUNT TOP moves up
    # to open the rows. Pad columns x = 33.90/36.44/38.98/41.52/44.06. Pins 9&10
    # are BOTH GND -> one centred label. MOUNT TOP: header solders to the TOP.
    ("MOUNT TOP", 39.0, 26.9, 0.8, 0, "B.SilkS"),   # solder-side cue
    ("J5", 46.7, 32.325, 0.8, 0, "B.SilkS"),        # legend tag, SE corner
    # even pins 2/4/6/8 (NORTH row) — upper text row
    ("+3V3", 33.90, 28.15, 0.8, 0, "B.SilkS"),      # pin 2
    ("TX",   36.44, 28.15, 0.8, 0, "B.SilkS"),      # pin 4
    ("IO4",  38.98, 28.15, 0.8, 0, "B.SilkS"),      # pin 6
    ("IO8",  41.52, 28.15, 0.8, 0, "B.SilkS"),      # pin 8
    # odd pins 1/3/5/7 (SOUTH row) — lower text row
    ("GND",  33.90, 29.4, 0.8, 0, "B.SilkS"),       # pin 1
    ("EN",   36.44, 29.4, 0.8, 0, "B.SilkS"),       # pin 3
    ("RX",   38.98, 29.4, 0.8, 0, "B.SilkS"),       # pin 5
    ("IO5",  41.52, 29.4, 0.8, 0, "B.SilkS"),       # pin 7
    # pins 9 (S) & 10 (N): both GND -> single centred label for the column
    ("GND",  44.06, 28.775, 0.8, 0, "B.SilkS"),     # pins 9 & 10
]

# Silk GRAPHIC outlines (non-text), rendered by pcb.py add_silk_shapes. See the
# module docstring for the entry format.
SILK_SHAPES = [
    # Antenna keep-out reminder outline on the BACK: trace the KEEPOUTS["antenna"]
    # rect (0, 7.25, 5.3, 20.65) with the west edge inset to x0.5 for
    # silk_edge_clearance; N/S/E follow the true keep-out. Back side because the
    # FRONT keep-out is under the U1 module (invisible assembled) whereas the back
    # over it is bare (pour excluded) — and B.SilkS carries no module outline to
    # double. Silk is non-conductive -> RF-safe, and allowed in the copper-only
    # keep-out. Pairs with the "ANTENNA"/"KEEP CLEAR" B.SilkS note inside it.
    ("rect", 0.5, 7.25, 5.3, 20.65, "B.SilkS", 0.15),
    # JP1<->IBAT link cue on the FRONT: a short vertical line under JP1.1 (the
    # Net-(J2-Pin_1) jumper pad, x26.94), materialising the series-measurement
    # break — wick JP1, insert an ammeter across J2. Its ends deliberately merge
    # into JP1's silk box (bottom edge y27.35, incl. an arc) and J2's silk box
    # (top edge y28.16) for the connected look; the 'silk-merge' rule area
    # (KEEPOUTS) + .kicad_dru rule (pcb.py) scope a negative silk_clearance so
    # those intended overlaps don't trip silk_overlap while clashes elsewhere
    # still gate.
    ("line", 26.89, 27.29, 26.89, 28.2, "F.SilkS", 0.1),
]

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
