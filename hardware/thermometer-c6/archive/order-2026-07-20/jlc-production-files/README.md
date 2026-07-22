# JLCPCB production files — order SMT026072062920 / PO 13106315A_Y9

Downloaded from the JLCPCB order page after CAM processing (2026-07-22),
for the rev A `3ed40fe` bundle uploaded 2026-07-20.

- `thermometer-c6-gerbers-3ed40fe-2026-07-20_Y9.zip` — JLC's production
  bundle: their CAM-processed layer files (`ok/` — panelized, Protel-style
  short names), the ODB++ job (`ok/*.tgz`), the order parameter dump
  (`YG/4te.json`, GBK-encoded), and two nested copies of the customer
  upload (`YG/*.zip`) which are **byte-identical** to
  `../thermometer-c6-gerbers-3ed40fe-2026-07-20.zip` (verified per file).
- `smt-preview-*.png` — JLC's panelized 2D assembly renders (top/bottom,
  with and without designator overlay). Render color is JLC's generic
  green; the ordered finish is white mask / black silk (deliberate, see
  ORDERING.md).

Pre-confirmation verification (2026-07-22): upload byte-identity; order
params vs settled decisions (2L FR-4 1.6mm 1oz, ENIG, resin-plugged vias,
white/black, no customer code, SMT QR codes on the breakaway rails only;
panel auto-extended to 70×71mm with 2mm board-to-rail gap — clears the
1.9mm J3 USB overhang); the 9 "Revised" designators (R2-R6, R12, R19,
R20, R22) are engineer placement nudges — part numbers and values match
our BOM exactly, all non-polarized 0402; placement walk of the three
unverified rotation-checklist entries: J3 mouth north over the edge,
J4 mouth flush east / pin 1 north, D1 cathode east (render polarity mark
matches the previously verified D3). Remaining checklist entries carry
their `verified` status from the 2026-07-18 three-pass preview walk
(unchanged CPL deltas).
