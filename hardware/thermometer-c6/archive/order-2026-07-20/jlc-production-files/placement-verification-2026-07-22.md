# Independent placement verification — JLC order SMT026072062920 (2026-07-22)

Performed by an Opus 4.8 subagent against
`jlc-placement-confirm-top-hires.png` (JLC's engineer-adjusted "Confirm
Parts Placement" 2D view), cross-checked against the CPL, the KiCad
board's actual pad geometry (`verify/pads.py`), the rotation checklist,
and the JLC BOM listing screenshots. Verdict: **no stop-the-order
findings** across all 75 placements.

## Pixel↔mm mapping

Board outline in screenshot pixels: west x=752, east x=3219, north
y=251, south y=2043 → ≈51.3 px/mm (board 48×35mm). `rel_x = CPL_X −
100`, `rel_y = −CPL_Y − 100`; `X_px = 752 + 51.40·rel_x`, `Y_px = 251 +
51.20·rel_y`. Validated on all four edge-cut lines and on J3/J4 centers;
all 75 predicted centers landed on rendered parts; no board part is
occluded by page chrome.

Polarized parts were verified against the KiCad board's pad geometry,
not prose cues. Note: this board's SOT-23s (Q1/Q2/Q4/Q5/Q6) place pins
1&2 on the SOUTH face and the single drain NORTH (pin-1 gate SW); Q3
(SC-70) is flipped: 2 legs NORTH, single leg SOUTH.

## Placement walk — all 75 designators

Verdict key: OK = render matches design intent. rel = board-relative (x from west, y from north), mm.

| Desig | Expected (rel x,y / pkg / orient cue) | Render shows | Verdict |
|---|---|---|---|
| C1 | 8.93,33.17 / 0603 | 0603 cap "C1", horiz | OK |
| C2 | 9.14,31.22 / 0805 (22µF bulk) | large 0805 "C2" | OK |
| C3 | 11.37,22.52 / 0603 | 0603 "C3" vert | OK |
| C4 | 8.11,23.95 / 0402 | 0402 "C4" | OK |
| C5 | 28.12,11.34 / 0805 | 0805 "C5" | OK |
| C6 | 37.85,5.13 / 0805 | 0805 "C6" | OK |
| C7 | 9.57,22.52 / 0603 | 0603 "C7" | OK |
| C8 | 8.11,21.95 / 0402 | 0402 "C8" | OK |
| C9 | 14.75,21.5 / 0402 | 0402 "C9" | OK |
| C10 | 18.85,20.7 / 0402 (20pF) | 0402 "C10" | OK |
| C11 | 18.85,19.5 / 0402 (20pF) | 0402 "C11" | OK |
| C12 | 5.6,21.5 / 0402 | 0402 "C12" | OK |
| C13 | 5.6,30.6 / 0402 | 0402 "C13" | OK |
| C14 | 24.0,24.1 / 0603 | 0603 "C14" | OK |
| C15 | 21.5,12.75 / 0402 | 0402 "C15" | OK |
| C16 | 33.27,23.74 / 0805 | 0805 "C16" | OK |
| C17 | 35.55,20.6 / 0805 | 0805 "C17" | OK |
| C18 | 35.45,24.6 / 0805 | 0805 "C18" | OK |
| C19 | 30.8,11.3 / 0805 | 0805 "C19" | OK |
| C20 | 33.27,12.0 / 0805 | 0805 "C20" | OK |
| C21 | 40.6,27.3 / 0805 | 0805 "C21" | OK |
| C22 | 33.27,20.14 / 0805 | 0805 "C22" | OK |
| C23 | 43.1,27.3 / 0805 | 0805 "C23" | OK |
| C24 | 45.6,27.3 / 0805 | 0805 "C24" | OK |
| C25 | 38.28,24.6 / 0805 | 0805 "C25" | OK |
| C28 | 28.4,18.45 / 0402 (10nF) | 0402 "C28" | OK |
| C29 | 12.6,27.7 / 0402 (10nF) | 0402 "C29" | OK |
| D1 | 34.49,5.1 / 0603 LED / cathode EAST | LED "D1", green cathode mark EAST, "−" east; identical to D3 | OK |
| D2 | 32.45,2.29 / SMA / cathode band WEST | SMA "D2", light cathode band WEST | OK |
| D3 | 14.65,32.75 / 0603 LED / cathode EAST | LED "D3", green cathode mark EAST; identical to D1 | OK |
| D4 | 38.45,20.3 / SOD-123 / cathode SOUTH | vert body, white cathode band SOUTH | OK |
| D5 | 30.87,30.75 / SOD-123 / cathode SOUTH | vert body, cathode band SOUTH | OK |
| D6 | 32.02,27.1 / SOD-123 / cathode WEST | horiz body, cathode band WEST | OK |
| J1 | 21.0,30.0 / JST-PH-2 / pin1 NORTH | JST, contact posts NORTH, body/mount SOUTH | OK |
| J3 | 23.4,3.16 / USB-C / shell overhangs NORTH, A1 SE, 12 tails S | shell mouth overhangs north edge; 12 SMT tails south; both shell tabs present | OK |
| J4 | 43.08,16.8 / FPC-24 / mouth EAST, actuator+pads WEST, pin1 N | contact-pad column + dark actuator WEST, body/mouth toward EAST edge, pin1 (N end) | OK |
| L1 | 22.84,15.7 / 4×4 (10µH) | large inductor "L1" | OK |
| L2 | 22.84,20.49 / 4×4 (47µH) | inductor "L2", silk "47µH" | OK |
| Q1 | 41.6,5.04 / SOT-23 / pin1 G SW; 2-leg S, drain N | 2 legs SOUTH, 1 leg NORTH = board | OK |
| Q2 | 27.25,15.27 / SOT-23 / pin1 G SW | 2 legs SOUTH, 1 leg NORTH | OK |
| Q3 | 30.64,15.31 / SC-70 / pin1 NE; 2-leg N, single S (flipped) | 2 legs NORTH, 1 leg SOUTH-center | OK |
| Q4 | 14.25,25.17 / SOT-23 / pin1 G SW | 2 legs SOUTH, 1 leg NORTH | OK |
| Q5 | 14.25,29.37 / SOT-23 / pin1 G SW | 2 legs SOUTH, 1 leg NORTH, silk "2N7002" | OK |
| Q6 | 27.45,22.78 / SOT-23 / pin1 G SW | 2 legs SOUTH, 1 leg NORTH | OK |
| R1 | 21.98,10.63 / 0402 (5.1k) | 0402 "R1" | OK |
| R2 | 20.79,10.63 / 0402 (5.1k) | 0402 "R2" (JLC-revised, symmetric) | OK |
| R3 | 29.41,5.28 / 0402 (10k) | 0402 "R3" (revised) | OK |
| R4 | 33.9,6.5 / 0402 (1k) | 0402 "R4" (revised) | OK |
| R5 | 30.61,5.28 / 0402 (100k) | 0402 "R5" (revised) | OK |
| R6 | 16.6,21.5 / 0402 (10k) | 0402 "R6" (revised) | OK |
| R7 | 11.1,6.4 / 0402 (10k) | 0402 "R7" between RST/BOOT | OK |
| R8 | 11.85,32.75 / 0402 (1k) | 0402 "R8" | OK |
| R10 | 5.6,25.3 / 0402 (4.7k) | 0402 "R10" | OK |
| R11 | 5.6,26.3 / 0402 (4.7k) | 0402 "R11" | OK |
| R12 | 27.21,18.47 / 0402 (10k) | 0402 "R12" (revised) | OK |
| R13 | 32.7,16.3 / 0402 (10k) | 0402 "R13" | OK |
| R14 | 35.45,16.1 / 0805 (0.47Ω) | 0805 "R14", silk "0.47Ω" | OK |
| R15 | 35.45,12.5 / 0805 (2.2Ω) | 0805 "R15", silk "2.2Ω" | OK |
| R16 | 35.45,8.9 / 0805 (3.0Ω) | 0805 "R16", silk "3Ω" | OK |
| R17 | 31.8,5.28 / 0402 (10k) | 0402 "R17" | OK |
| R18 | 9.31,25.5 / 0402 (100k) | 0402 "R18" | OK |
| R19 | 13.02,21.98 / 0402 (100k) | 0402 "R19" (revised) | OK |
| R20 | 11.4,24.65 / 0402 (100k) | 0402 "R20" (revised) | OK |
| R21 | 11.4,26.0 / 0402 (100k) | 0402 "R21" | OK |
| R22 | 41.2,7.6 / 0402 (100k) | 0402 "R22" (revised) | OK |
| R23 | 44.0,7.11 / 0402 (100k) | 0402 "R23" | OK |
| R24 | 26.02,18.47 / 0402 (10k) | 0402 "R24" | OK |
| SW1 | 6.2,2.9 / SMD-4P switch / pin1 NW | tactile switch "SW1" (RST), pads N/S | OK |
| SW2 | 13.9,2.9 / SMD-4P switch / pin1 NW | tactile switch "SW2" (BOOT), pads N/S | OK |
| U1 | 11.8,13.95 / ESP32-C6-MINI / antenna WEST, pin1 SW | large module, magenta antenna keepout WEST, pads S/E | OK |
| U2 | 9.5,28.35 / TSOT-23-5 / 3-leg WEST, 2-leg EAST, pin1 NW | 3 legs WEST, 2 legs EAST, pin-1 dot + silk triangle at N | OK |
| U3 | 24.79,11.34 / SOT-23-6 / symmetric 3+3, pin1 NW (needs dot) | 3+3 legs; body pin-1 dot + silk triangle both at NW | OK |
| U4 | 38.2,2.25 / SOT-23-5 / 3-leg WEST, 2-leg EAST, pin1 NW | 3 legs WEST, 2 legs EAST, dot at N | OK |
| U5 | 2.6,22.4 / LGA-10 (BMP581) / FITTED, pin1 S | white LGA body present (fitted), index consistent with pin1 S; U6 pads bare | OK |
| Y1 | 19.09,16.84 / 3215 crystal | 2-pad crystal "Y1" | OK |

U6 (not in CPL/BOM): bare LGA pads + "U6" silk, no body → unpopulated.
Exactly one of the U5/U6 pair fitted (U5). No FLAG / INDETERMINATE /
OCCLUDED rows.

## BOM listing cross-check — all 75 match

JLC header: Assembled (75), Unassembled (0). Merged listing pages 1–3:
every designator maps to exactly the LCSC part number in
`thermometer-c6-bom.csv`, footprints plausible, MPN decodes consistent
(0402WGF1001=1k, 1002=10k, 1003=100k, 4701=4.7k, 5101=5.1k;
CL05B104=100nF, CL10A106=10µF, CL21A475=4.7µF, CL21B105=1µF,
CL21A226=22µF). Count by class: 27 C + 6 D + 3 J + 2 L + 6 Q + 23 R +
2 SW + 5 U + 1 Y = 75.

JLC "Revised Items" = 9 designators (R2, R3, R4, R5, R6, R12, R19, R20,
R22) — all symmetric 0402 resistors, part numbers unchanged, rendered
positions match our CPL. Placement normalizations, no functional impact;
no polarized part was revised.

## Resistor value decode — confirmed, no 10× error

| Ref | LCSC | MPN | Confirmed value | Source |
|---|---|---|---|---|
| R14 | C2930220 | FOJAN FRL0805FR470TS | 0.47Ω ±1% 0805 | JLCPCB part page |
| R15 | C17521 | UNI-ROYAL 0805W8F220KT5E | 2.2Ω ±1% 0805 | JLCPCB part page |
| R16 | C17660 | UNI-ROYAL 0805W8F300KT5E | 3.0Ω ±1% 0805 | LCSC part page |

In the UNI-ROYAL `0805W8F####` scheme the trailing letter K is a
low-value multiplier (×0.01), not ×1000 — `220K`=2.2Ω, `300K`=3.0Ω
(family siblings: `2201`=2.2kΩ, `2700`=270Ω, `3001`=3.0kΩ,
`3300`=330Ω). FOJAN `FR470` = 0.47Ω.

## Residual notes (not blockers)

- U5 (LGA-10) orientation cannot be strongly discriminated from a top
  render (pads underneath); fitment and position are definitive and the
  pin-1 index is consistent with pin1-SOUTH.
- SW1/SW2 are 2-net tactile switches, near-symmetric; position/package
  correct and the pin row is on the correct side.
