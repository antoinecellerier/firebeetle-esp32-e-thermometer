# Rotation verification checklist

One row per orientation-critical part (diodes, transistors, ICs, connectors,
switches). The JLCPCB 2D order preview is the **only** ground truth: after
uploading `thermometer-c6-cpl.csv`, compare each part's rendered orientation
against the "Expected orientation" cue below (a top-view compass bearing of the
part's pin-1 / cathode / antenna feature, board WEST = left).

On a mismatch: fix the part's `delta` in `generator/fab_cpl.py` (adjust the
matching `FAB_ROTATIONS` entry or add a `REF_ROTATION_OVERRIDES` key), mark that
entry `verified:` once it matches, re-run `make fab`, and re-upload the CPL. If
*every* part is rotated by the same amount, or shifted by a uniform X/Y offset,
suspect the origin/whole-board setting rather than per-part deltas.

| Ref | Value | LCSC | Footprint | KiCad rot | Delta (confidence) | CPL rot | Expected orientation in JLC preview | preview OK |
|---|---|---|---|---|---|---|---|---|
| D1 | CHG red | C2286 | LED_0603_1608Metric | 180 | +0 (low) | 180 | cathode band EAST | `[ ]` |
| D2 | SS14 | C2480 | D_SMA | 0 | +0 (verified) | 0 | cathode band WEST | `[ ]` |
| D3 | STATUS white | C2290 | LED_0603_1608Metric | 180 | +0 (verified) | 180 | cathode band EAST | `[ ]` |
| D4 | MBR0530 | C5204746 | D_SOD-123 | 90 | +0 (verified) | 90 | cathode band SOUTH | `[ ]` |
| D5 | MBR0530 | C5204746 | D_SOD-123 | 90 | +0 (verified) | 90 | cathode band SOUTH | `[ ]` |
| D6 | MBR0530 | C5204746 | D_SOD-123 | 0 | +0 (verified) | 0 | cathode band WEST | `[ ]` |
| J1 | JST-PH-2 BAT | C295747 | JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal | 0 | +0 (verified) | 0 | pin 1 at NORTH | `[ ]` |
| J3 | USB-C | C165948 | USB_C_Receptacle_HRO_TYPE-C-31-M-12 | 180 | +0 (low) | 180 | pin A1 at SOUTH-EAST | `[ ]` |
| J4 | EPD FPC24 0.5mm | C2856831 | XUNPU_FPC-05FB-24PH20 | 90 | +0 (low) | 90 | pin 1 at NORTH | `[ ]` |
| Q1 | AO3401A | C15127 | SOT-23 | 90 | +180 (verified) | 270 | pin 1 (G) at SOUTH-WEST | `[ ]` |
| Q2 | AO3401A | C15127 | SOT-23 | 90 | +180 (verified) | 270 | pin 1 (G) at SOUTH-WEST | `[ ]` |
| Q3 | Si1308EDL | C469327 | SOT-323_SC-70 | 270 | +180 (verified) | 90 | pin 1 (G) at NORTH-EAST | `[ ]` |
| Q4 | AO3401A | C15127 | SOT-23 | 90 | +180 (verified) | 270 | pin 1 (G) at SOUTH-WEST | `[ ]` |
| Q5 | 2N7002 | C8545 | SOT-23 | 90 | +180 (verified) | 270 | pin 1 (G) at SOUTH-WEST | `[ ]` |
| Q6 | AO3401A | C15127 | SOT-23 | 90 | +180 (verified) | 270 | pin 1 (G) at SOUTH-WEST | `[ ]` |
| SW1 | RESET | C318884 | SW_TS-1187A | 0 | +0 (verified) | 0 | pin 1 at NORTH-WEST | `[ ]` |
| SW2 | BOOT | C318884 | SW_TS-1187A | 0 | +0 (verified) | 0 | pin 1 at NORTH-WEST | `[ ]` |
| U1 | ESP32-C6-MINI-1-N4 | C5736265 | ESP32-C6-MINI-1 | 90 | +0 (verified) | 90 | antenna overhang WEST edge; pin 1 SOUTH-WEST | `[ ]` |
| U2 | RT9080-33GJ5 | C841192 | TSOT-23-5 | 0 | +270 (verified) | 270 | pin 1 at NORTH-WEST | `[ ]` |
| U3 | USBLC6-2SC6 | C7519 | SOT-23-6 | 0 | +270 (verified) | 270 | pin 1 at NORTH-WEST | `[ ]` |
| U4 | MCP73831-2 | C424093 | SOT-23-5 | 0 | +270 (verified) | 270 | pin 1 at NORTH-WEST | `[ ]` |
| U5 | BMP581 | C5362283 | Bosch_LGA-10_2x2mm | 90 | +0 (verified) | 90 | pin 1 at SOUTH | `[ ]` |
