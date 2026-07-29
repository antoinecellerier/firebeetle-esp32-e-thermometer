# JLC first-article X-rays — 2026-07-27

`1.png`–`4.png` as received from JLC (order SMT026072062920). Four frames =
four distinct assembled boards (unique satellite-ball positions and placement
jitter per frame; frame↔board mapping unknowable).
[`annotated/`](annotated/) overlays every
top-side footprint's bounding box, projected from the board file — the
evidence for each part identification. `annotate.py` regenerates them.

## Frame↔board transform (measured, not eyeballed)

Footprint bboxes come from `thermometer-c6.kicad_pcb` via pcbnew (KiCad abs
minus the (100,100) origin). Frames map board-west to image-top:

    col = 1301 − 41.5·y + dx      row = 41.5·x + 307 + dy      [px, mm]

Scale 41.5 px/mm fitted on U5/J3/U1 anchors in `4.png`, then validated by all
~35 in-frame footprints landing on their blobs in all four overlays. Per-frame
offsets (dx,dy) vs `4.png` by normalized cross-correlation on two landmark
templates (crystal + U5 regions; agreement ≤3 px, NCC 0.88–0.98):
`3.png` (+290,+6), `2.png` (−90,+10), `1.png` (+279,−40). Frames pair into
two framings: {4,2} and {3,1} (H2 + the J2 rings enter frame only in {3,1}).

## Findings (all four boards)

| Part | Verdict |
|---|---|
| U5 BMP581 LGA-10 | 10/10 joints wetted, uniform, centered; no bridging |
| U1 MINI-1 | castellations evenly wetted all sides, no bridges, centered; center GND pads unreadable through module internals (fine — no thermal load); the 45°-rotated QFN is the C6 die inside the module |
| J3 USB-C | 12-pin 0.5mm row resolves pin-by-pin, no bridging; 4 shell through-legs filled |
| J1 JST-PH | pins + SM4 tabs wetted |
| SW1/SW2, Y1, L1/L2, U2–U4, Q*, D* | present, on-pad, nothing anomalous |
| U6 / J2 DNP | pads verifiably EMPTY in every frame |
| **J4 FPC-24** | **off-frame in all four images** — nearest edge (x=40.3mm) projects ≥400 px below the frame. The X-rays say nothing about J4; the Phase 0 optical bridge check is its only inspection |

Incidental observations:

- Satellite solder micro-balls (~50–100µm) near U5 on 2–3 boards, at a
  different spot each time → BRINGUP.md Phase 0 loupe item.
- The faint ~0.9mm round blob top-right in `4.png`/`2.png` is NOT on a board:
  it sits at board-relative (x≈−6.1, y≈−2.8)mm — off the NW corner, on the
  panel rail/carrier — and tracks the board across the two framings exactly
  (absent from {3,1} where that spot leaves the frame). Too faint to be
  solder at that diameter.

A correction the overlay pass caught: the clean 0.5mm row first attributed to
J4 is J3's (USB-C also has a 12-pin 0.5mm row; the shell through-legs and
tongue cutouts are the discriminators). X-ray confirms geometry only — it
proves neither LGA electrical contact nor passive values; BRINGUP.md Phases
0–2 remain the acceptance gate.
