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
    # R6 (EN pull-up) belongs beside C9 at U1's south row, not in the 2.5mm
    # channel north of U1 where all six EPD signals and both UART lines cross
    "R6": (16.6, 21.5, 0),
    "C9": (14.75, 21.5, 0),
    "SW1": (3.9, 2.9, 0),
    "SW2": (11.6, 2.9, 0),
    "R7": (19.0, 23.4, 90),
    # status LED at the south edge: U1's east flank (x17.9..19.4, y9.4..14.6)
    # is the only F.Cu window for the east column's escapes, and it is the only
    # pocket between U1's and J3's courtyards, so nothing may sit there
    "D3": (14.65, 32.75, 180),
    "R8": (11.85, 32.75, 0),
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
    "TP7": (29.9, 28.35, 0, "B"),
    "TP8": (29.0, 12.6, 0, "B"),
    "TP9": (32.3, 13.5, 0, "B"),
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

TRACKS = [
    # ---- battery entry chain (465mA EPD refresh bursts; 0.6 squeezes the
    # J1/C14 and Q6/JP1 pad windows at 0.2 clearance) ----
    ("~BAT_IN", "F.Cu", 0.5, ["J1.1", (20.95, 26.2), (20.95, 22.9),
                              (25.4, 22.9), (26.5, 21.8), "Q6.3"]),
    ("~VBAT_RAW", "F.Cu", 0.6, ["Q6.2", (28.4, 25.0), (26.94, 25.0),
                                "JP1.1"]),
    ("~VBAT_RAW", "F.Cu", 0.8, ["JP1.1", (26.94, 28.5), "J2.1"]),
    # east leg: JP1.2 -> J2.2, then B.Cu north of the J5 pin rows and up the
    # east margin (x45.75) behind the J4 fanout; the F.Cu corridor stays
    # free for the panel-cap feeds
    ("VBAT", "F.Cu", 0.5, ["JP1.2", (29.2, 26.2), (29.2, 31.3),
                           (28.4, 32.05), "J2.2"]),
    ("VBAT", "B.Cu", 0.5, ["J2.2", (28.6, 31.4), (29.4, 29.75),
                           (44.9, 29.75), (45.75, 28.9), (45.75, 4.6),
                           (44.05, 2.9), (43.0, 2.9), (42.25, 2.15)]),
    # charger output C6-first, tapped off the east B lane
    ("VBAT", "B.Cu", 0.5, [(45.75, 5.8), (39.0, 5.8), (36.6, 5.2),
                           (36.1, 4.75)]),
    ("VBAT", "F.Cu", 0.5, [(36.1, 4.75), (36.9, 5.05), "C6.1"]),
    ("VBAT", "F.Cu", 0.5, ["U4.3", (36.9, 4.4), "C6.1"]),
    # divider feed on B.Cu under the JST (y25.15 clears the C29 pads);
    # the via sits on the JP1.2->J2.2 link
    ("VBAT", "B.Cu", 0.5, [(29.2, 26.2), (28.0, 25.15), (16.45, 25.15),
                           (16.45, 24.9)]),
    ("VBAT", "F.Cu", 0.5, [(16.45, 24.9), (16.45, 25.56), (15.94, 26.11),
                           "Q4.2"]),
    # ... and on to R18's gate pull-up, ending in a via-in-pad. The lane is a
    # B.Cu wall from x9.31 to x29 at y24.70..25.60 (0.5mm minimum width on
    # VBAT): nothing else crosses it, so the divider's own nets stay on F.Cu
    # and VBAT_ADC's two B.Cu spurs stay on their own sides of it.
    ("VBAT", "B.Cu", 0.5, [(16.9, 25.15), (9.75, 25.15), "R18.1"]),

    # ---- VSYS: charger/load-share NE to LDO SW via west-edge B.Cu ----
    # (the y4.15 lane ducks south of the J3 shield-leg back-side pads)
    ("VSYS", "F.Cu", 0.5, ["D2.1", (30.0, 1.85), (30.0, 1.4)]),
    ("VSYS", "B.Cu", 0.5, [(30.0, 1.4), (28.85, 1.4), (28.85, 3.95),
                           (28.65, 4.15), (6.7, 4.15), (6.5, 4.35),
                           (6.5, 25.6), (7.55, 26.4)]),
    # NE corner: B.Cu along y1.4 past Q1, then up to Q1.2 from the east
    # (Q1.3's tall pad blocks any F.Cu lane along the top edge)
    ("VSYS", "B.Cu", 0.5, [(30.0, 1.4), (41.0, 1.4), (41.2, 1.2),
                           (44.35, 1.2), (44.95, 1.8), (44.95, 2.65)]),
    ("VSYS", "F.Cu", 0.5, [(44.95, 2.65), (44.2, 3.4), "Q1.2"]),
    ("VSYS", "F.Cu", 0.5, [(7.55, 26.4), (7.8, 26.9), "U2.1"]),
    # U2 pin 3 (EN) fed on B.Cu — pins 1/3 can't be strapped on F past pin 2
    ("VSYS", "B.Cu", 0.5, [(6.5, 25.6), (6.5, 29.0), (7.46, 29.9),
                           (8.36, 29.9), (8.36, 29.75)]),
    ("VSYS", "F.Cu", 0.5, [(8.36, 29.75), "U2.3"]),
    ("VSYS", "F.Cu", 0.5, ["U2.3", (8.36, 30.4), (8.19, 30.6), "C2.1"]),
    ("VSYS", "F.Cu", 0.5, ["C2.1", (8.19, 32.2), "C1.1"]),

    # ---- VBUS (USB current path; not in the 0.5 min-width class) ----
    # A9 escapes through a via in its own 0.6mm pad and runs B.Cu west of the
    # mounting hole: the 0.9mm window between the A8 pad and that hole cannot
    # carry both VBUS and CC2 on F.Cu, and CC2 has no pad wide enough for a
    # via (see the USB-C fan-out below).
    ("VBUS", "B.Cu", 0.4, [(25.85, 1.2), (25.4, 1.65), (25.4, 2.85),
                           (25.85, 3.3)]),
    ("VBUS", "F.Cu", 0.4, [(25.85, 3.3), (26.8, 4.25), (26.8, 6.9)]),
    # U3.6/C5.2 leave only a 0.7mm gap -> 0.3mm neck up to U3.5
    ("VBUS", "F.Cu", 0.3, [(26.8, 6.9), (26.97, 7.07), (26.97, 10.9),
                           (26.58, 11.34), "U3.5"]),
    ("VBUS", "F.Cu", 0.3, [(26.97, 11.2), (27.6, 11.8), "C5.1"]),
    ("VBUS", "F.Cu", 0.4, [(26.97, 7.9), (28.6, 8.39), "R22.1"]),
    # VBUS_SENSE divider feed loops around R23 (R22.2 sits in the direct path)
    ("VBUS", "F.Cu", 0.4, ["R22.1", (29.9, 9.1), (31.3, 9.1), (31.7, 8.6),
                           (31.7, 6.4), (31.1, 5.79), "R5.1"]),
    # D2 feed hooks around the J3 shield leg's F pad
    ("VBUS", "F.Cu", 0.4, [(26.97, 7.35), (28.5, 7.35), (28.75, 7.1),
                           (28.75, 6.6), (31.5, 6.6), (33.4, 5.7),
                           (33.4, 3.5), "D2.2"]),
    # U4.4/Q1.1 fed around the south of C6 (a straight D2.2->U4.4 lane would
    # cut the U4.3->C6 VBAT link)
    ("VBUS", "F.Cu", 0.4, [(33.4, 5.7), (33.75, 6.35), (39.9, 6.35),
                           (40.5, 5.75), (40.5, 3.62), "Q1.1"]),
    ("VBUS", "F.Cu", 0.4, ["U4.4", (40.28, 3.31), "Q1.1"]),
    # CHG LED resistor feed: via-in-pad at A4 (the A1/B8/NPTH box leaves no
    # F.Cu escape), B.Cu south around the shield-leg pads, back up west of D1
    ("VBUS", "F.Cu", 0.4, ["J3.A4", (20.95, 1.2)]),
    ("VBUS", "B.Cu", 0.4, [(20.95, 1.2), (21.6, 2.5), (21.6, 3.4),
                           (16.4, 3.4), (15.5, 2.2)]),
    ("VBUS", "F.Cu", 0.4, [(15.5, 2.2), (16.1, 1.75), "R4.1"]),

    # ---- USB-C signal fan-out (J3's 0.5mm pitch defeats the autorouter) ----
    # CC2 owns the A8/mounting-hole window now that VBUS is on B.Cu there,
    # then crosses the D pair on B.Cu, passing north of TP5's back-side pad
    ("~USB_CC2", "F.Cu", 0.25, ["J3.B5", (25.2, 1.6), (25.2, 8.5)]),
    ("~USB_CC2", "B.Cu", 0.25, [(25.2, 8.5), (22.4, 8.5), (22.4, 10.69),
                                "R2.1"]),
    # CC1 dives south-west past the mounting hole and runs west of R1: the
    # R1/R2 gap is only 0.55mm, too narrow for a 0.25mm lane
    ("~USB_CC1", "F.Cu", 0.25, ["J3.A5", (22.15, 1.85), (20.15, 3.85),
                                (20.15, 10.6), "R1.1"]),
    # B7/A6/A7/B6 alternate D-/D+/D-/D+, so exactly one pair must cross the
    # other. The lanes first spread from 0.5mm pitch to via pitch; D+ then
    # crosses on B.Cu at y5.5, clear of the VSYS lane at y4.15; D- merges on
    # F.Cu below the via row, where D+ has vacated its lane.
    ("~USB_DM_CONN", "F.Cu", 0.25, ["J3.B7", (22.65, 2.4), (22.0, 3.05),
                                    (22.0, 6.6), (23.65, 6.6)]),
    ("~USB_DM_CONN", "F.Cu", 0.25, ["J3.A7", (23.65, 10.39), "U3.1"]),
    ("~USB_DP_CONN", "F.Cu", 0.25, ["J3.A6", (23.15, 3.2), (22.7, 3.65),
                                    (22.7, 5.5)]),
    ("~USB_DP_CONN", "B.Cu", 0.25, [(22.7, 5.5), (24.5, 5.5)]),
    # B6 continues south through the channel between U3's pad columns
    ("~USB_DP_CONN", "F.Cu", 0.25, ["J3.B6", (24.15, 2.4), (24.5, 2.75),
                                    (24.5, 9.0), (24.79, 9.29),
                                    (24.79, 12.29), "U3.3"]),

    # ---- VBUS_SENSE divider mid-node ----
    # R22.2 -> R23.1 crosses the ladder diagonally; the 0.74mm channel between
    # R22.1 and R23.2 only clears a 0.2mm track, and only off-centre
    ("VBUS_SENSE", "F.Cu", 0.2, ["R22.2", (29.46, 7.25), (30.6, 8.39),
                                 "R23.1"]),

    # ---- EPD booster switch core ----
    # RESE sense/current path: Q3 source -> R14 (default 0.47R leg) through
    # the Q3.1/Q3.3 pad gap with a jog north past R13.2; star point is the
    # Q3.2 pad (J4.3 Kelvin sense taps there, routed with the J4 fan-out)
    ("EPD_RESE", "F.Cu", 0.3, ["Q3.2", (29.99, 15.31), (31.9, 15.31),
                               (32.1, 15.11), (34.3, 15.11), (34.3, 17.01),
                               "R14.1"]),
    # R15/R16 alternates hang off a B.Cu column via via-in-pad (an F column
    # doesn't fit: C20.1's HV clearance vs the R-ladder leaves exactly 0mm)
    ("EPD_RESE", "B.Cu", 0.3, ["R14.1", "R15.1", "R16.1"]),
    # RESE legs to their solder jumpers: short and wide (joint mR vs 0.47R)
    ("~RESE_A", "F.Cu", 0.5, ["R14.2", "JP2.1"]),
    ("~RESE_B", "F.Cu", 0.5, ["R15.2", "JP3.1"]),
    ("~RESE_C", "F.Cu", 0.5, ["R16.2", "JP4.1"]),
    # SW node: Q3 drain exits east around R13, dives south through the
    # JP-column/C22 window at x32.0, feeds both inductor jumpers + C16 + D4
    ("EPD_SW", "F.Cu", 0.4, ["Q3.3", (31.7, 16.2), (31.9, 16.4),
                             (31.9, 17.3), (32.0, 17.4), (32.0, 22.79),
                             "C16.1"]),
    ("EPD_SW", "F.Cu", 0.4, ["JP5.2", (32.0, 22.96)]),
    ("EPD_SW", "F.Cu", 0.4, ["JP6.2", (32.0, 19.36)]),
    ("EPD_SW", "F.Cu", 0.4, [(32.0, 18.1), (38.0, 18.1), "D4.2"]),
    # inductor-to-jumper links; 10U crosses 47U so it ducks onto B.Cu
    ("~SW_10U", "F.Cu", 0.4, ["L1.2", (24.34, 16.6), (25.4, 17.0)]),
    ("~SW_10U", "B.Cu", 0.4, [(25.4, 17.0), (29.5, 21.66)]),
    ("~SW_10U", "F.Cu", 0.4, [(29.5, 21.66), "JP5.1"]),
    ("~SW_47U", "F.Cu", 0.4, ["L2.2", (28.95, 20.49), (29.4, 20.04),
                              (29.4, 18.06), "JP6.1"]),
    # charge pump: C16 low pad -> D6 -> D5
    ("~EPD_PUMP", "F.Cu", 0.4, ["C16.2", (30.86, 27.10), "D6.1"]),
    ("~EPD_PUMP", "F.Cu", 0.4, ["D6.1", (30.87, 27.6), "D5.2"]),
    # rectified rails to their reservoir caps (J4 feeds come with the fan-out)
    ("EPD_PREVGH", "F.Cu", 0.3, ["D4.1", (38.05, 21.55), "C17.1"]),
    ("EPD_PREVGL", "F.Cu", 0.3, ["D6.2", (35.22, 25.55), "C18.1"]),

    # ---- U1 north-row escapes ----
    # Six EPD signals and both UART lines have to cross the 2.5mm band north of
    # U1 (SW2's pads above, the 0.8mm-pitch north row below), and each F.Cu
    # approach fences the next pad. Drop straight through the pad instead: the
    # module's paddle is nine F.Cu pads, so B.Cu under the body is untouched.
    # The lanes fan out east at 0.6mm pitch and surface in the flank.
    # (each lane drops clear of its neighbour's via before turning east:
    # a 45-degree exit straight off the pad grazes it by 0.06mm)
    ("EPD_CS", "B.Cu", 0.25, ["U1.26", (15.0, 8.45), (17.55, 8.8)]),
    ("EPD_DC", "B.Cu", 0.25, ["U1.27", (14.2, 9.05), (17.55, 9.4)]),
    ("EPD_BUSY", "B.Cu", 0.25, ["U1.29", (12.6, 9.65), (17.55, 10.0)]),

    # ---- +3V3 trunk: LDO/U1 -> Q2 source (the only 465mA stretch) ----
    # Pinned, not autorouted: left to itself the router reaches Q2.2 from the
    # south-east and lays a 0.5mm B.Cu diagonal across the whole south of the
    # board, walling off every J5-bound signal. The trunk belongs under L1.
    ("+3V3", "B.Cu", 0.5, [(9.45, 19.55), (19.0, 19.55), (20.5, 18.05)]),
    ("+3V3", "F.Cu", 0.5, [(20.5, 18.05), (22.3, 18.05), (23.25, 17.1),
                           (23.25, 14.45)]),
    ("+3V3", "B.Cu", 0.5, [(23.25, 14.45), (24.5, 15.7), (27.1, 15.7)]),
    ("+3V3", "F.Cu", 0.5, [(27.1, 15.7), "Q2.2"]),
    # gate-row south pads: the +3V3 pair links along the row and drops to the
    # trunk through a via in C28.1 (the row's only escape -- ~SW_47U owns the
    # F.Cu corridor at y20.49 and the L2 pad walls the west)
    ("+3V3", "F.Cu", 0.25, ["R12.1", (27.36, 18.93), "C28.1"]),
    ("+3V3", "B.Cu", 0.25, [(28.4, 18.93), (27.1, 17.63), (27.1, 15.7)]),

    # ---- Q2 gate network: bus along the north row, stub up to Q2.1 ----
    ("~EPD_GATE", "F.Cu", 0.25, ["R24.1", "R12.2"]),
    ("~EPD_GATE", "F.Cu", 0.25, ["R12.2", "C28.2"]),
    ("~EPD_GATE", "F.Cu", 0.25, [(26.3, 17.96), (26.3, 16.6), "Q2.1"]),

    # ---- battery divider block ----
    # VBAT_ADC is a 50k Thevenin node: kept on F.Cu between the two ladder
    # pads and up U1's ADC pin through the 0.85mm C7/C3 pad channel (the only
    # F.Cu gap; no via fits in it). The bench pad and the filter cap hang off
    # short B.Cu spurs, one either side of the VBAT lane.
    ("VBAT_ADC", "F.Cu", 0.25, ["R20.2", "R21.1"]),
    ("VBAT_ADC", "F.Cu", 0.25, ["R20.2", (10.47, 24.23), (10.47, 21.0),
                                (11.0, 20.47), "U1.5"]),
    ("VBAT_ADC", "B.Cu", 0.25, [(10.87, 20.6), "TP11.1"]),
    ("VBAT_ADC", "B.Cu", 0.25, [(10.89, 26.0), (10.89, 27.0), (12.6, 27.0),
                                "C29.1"]),
    # ladder top: R20's east pad straight into Q4's drain
    ("~VDIV_TOP", "F.Cu", 0.25, ["R20.1", "Q4.3"]),
    # gate node: south lane under the ladder (0.27mm to R21's pads, 0.25mm to
    # U2's), then east under Q4's body to Q5's drain
    ("~VDIV_PGATE", "F.Cu", 0.25, ["R18.2", (9.31, 26.72), (13.0, 26.72),
                                   "Q4.1"]),
    ("~VDIV_PGATE", "F.Cu", 0.25, ["Q4.1", (13.6, 26.2), (14.25, 26.2),
                                   "Q5.3"]),

    # ---- EPD_VCC panel feed to J4.15/16 ----
    # 0.3mm stubs while inside the fpc-fanout area (a 0.5mm stub cannot clear
    # the neighbouring 0.5mm-pitch pads; see the power-track-width-fanout DRU
    # rule), widening to 0.5 once clear, then B.Cu to R17's via-in-pad — the
    # anchor the autorouted EPD_VCC tree grows from.
    # It ducks under the digital fan-out rather than crossing it on F.Cu: pins
    # 9..14 escape west at 0.5mm pitch, where the only legal track centre is a
    # 0.05mm-wide slot, and they cannot spread to via pitch before x44.
    ("EPD_VCC", "F.Cu", 0.3, ["J4.16", (45.7, 18.45), (45.7, 18.1), "J4.15"]),
    ("EPD_VCC", "F.Cu", 0.3, [(45.7, 18.3), (44.85, 18.3)]),
    ("EPD_VCC", "B.Cu", 0.4, [(44.85, 18.3), (41.0, 14.45), (41.0, 14.2)]),
    ("EPD_VCC", "F.Cu", 0.5, [(41.0, 14.2), (40.0, 13.2), (40.0, 8.3)]),
    ("EPD_VCC", "B.Cu", 0.5, [(40.0, 8.3), (37.35, 8.3), (34.2, 5.15)]),
    ("EPD_VCC", "F.Cu", 0.5, ["R17.1", (34.2, 5.15)]),
]

VIAS = [
    # via-in-pad on U1's north row (0.4mm-wide pads; the 0.6mm via overhangs
    # 0.1mm each side and still clears the 0.8mm-pitch neighbours by 0.3mm)
    ("EPD_CS", 15.0, 8.05),
    ("EPD_DC", 14.2, 8.05),
    ("EPD_BUSY", 12.6, 8.05),
    ("VBAT", 42.25, 2.15),  # via-in-pad Q1.3
    ("VBAT", 36.1, 4.75),
    ("VBAT", 29.2, 26.2),
    ("VBAT", 16.45, 24.9),
    ("VBAT", 9.31, 24.99),  # via-in-pad R18.1
    ("VSYS", 30.0, 1.4),
    ("VSYS", 44.95, 2.65),
    ("VSYS", 7.55, 26.4),
    ("VSYS", 8.36, 29.75),
    ("VBUS", 20.95, 1.2),
    ("VBUS", 15.5, 2.2),
    ("VBUS", 25.85, 1.2),  # via-in-pad J3.A9
    ("VBUS", 25.85, 3.3),
    ("~USB_DP_CONN", 22.7, 5.5),   # D+ crosses the D- pair on B.Cu
    ("~USB_DP_CONN", 24.5, 5.5),
    ("~USB_CC2", 25.2, 8.5),       # CC2 crosses both pairs on B.Cu
    ("~USB_CC2", 22.01, 11.08),    # via-in-pad R2.1
    # RESE alternates B column: via-in-pad on all three resistor sense legs
    ("EPD_RESE", 35.45, 17.01),
    ("EPD_RESE", 35.45, 13.41),
    ("EPD_RESE", 35.45, 9.81),
    # ~SW_10U B-hop under ~SW_47U
    ("~SW_10U", 25.4, 17.0),
    ("~SW_10U", 29.5, 21.66),
    # EPD_VCC J4 feed: under the digital fan-out, F->B mid-run, via-in-pad R17.1
    ("EPD_VCC", 44.85, 18.3),
    ("EPD_VCC", 41.0, 14.2),
    ("EPD_VCC", 40.0, 8.3),
    ("EPD_VCC", 34.2, 5.15),
    # divider: the north spur's via sits on the 45-degree leg into U1.5 (no via
    # fits in the C7/C3 channel); the south one is a via-in-pad on R21.1
    ("VBAT_ADC", 10.87, 20.6),
    ("VBAT_ADC", 10.89, 26.0),
    # +3V3 trunk hops; (9.45,19.55) is a via-in-pad on U1.3, (28.4,18.93) on C28.1
    ("+3V3", 9.45, 19.55),
    ("+3V3", 20.5, 18.05),
    ("+3V3", 23.25, 14.45),
    ("+3V3", 27.1, 15.7),
    ("+3V3", 28.4, 18.93),
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

# Autorouted tracks (generator/route.py -> pcb_routes.py, checked in).
# `make route` regenerates; hand-tweaks there are fine (same data format).
import os as _os
if not _os.environ.get("PCB_NO_ROUTES"):
    try:
        import pcb_routes as _routes
        TRACKS = TRACKS + _routes.TRACKS
        VIAS = VIAS + _routes.VIAS
    except ImportError:
        pass
