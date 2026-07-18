# Ordering — thermometer-c6 at JLCPCB

Order checklist for the `make fab` bundle. The fab pipeline (render → DRC →
gerbers/drill → CPL/BOM → zip → `verify/check_fab.py`) is the mechanism;
this file is the human procedure around it. Settled fab decisions live in
`CLAUDE.md` ("Settled decisions — don't re-ask").

## 1. Generate & upload

- [ ] Check out the ordering commit on a **clean tree** and run `make fab`.
      A dirty tree is refused so the `rev A <hash> <date>` silk stamp names the
      exact committed source (`FAB_FORCE=1` overrides but makes the stamp a lie
      — don't ship one).
- [ ] Upload `out/fab/thermometer-c6-gerbers-<hash>-<date>.zip` (12 files:
      9 gerbers + drill + drill-map + job) to the JLCPCB quote page.

## 2. Board fabrication options

- [ ] Dimensions **48×35mm**, **2 layers**, **1.6mm**, outer copper **1oz**,
      qty **≥5**, solder mask green, TG **≥135**.
- [ ] **Surface finish: ENIG.** Chosen for flat pads under the 0.5mm-pitch
      LGA-10 sensor and the 0.5mm FPC — the board sits at JLC's 0.20mm HASL
      clearance floor, so HASL bumps are a risk there.
- [ ] **Via Covering: "Epoxy Filled & Capped" (POFV) — REQUIRED.** The
      via-in-pad escapes depend on it; the 0.3mm via drills are within JLC's
      fill limit.
- [ ] **Mark on PCB: keep "Remove Mark"** (2026 UI: a strict two-way choice
      vs "2D barcode (Serial Number)"; removal is now free and the default —
      the legacy "Order Number (Specify Position)" flow no longer exists).
      Leave the 2D-barcode serial option unset (it needs a reserved 2×10mm
      solid silk square this board doesn't have). The `JLCJLCJLCJLC` token on
      back silk at (6.5, 13.95) is a legacy no-op under Remove Mark — JLC's
      CAM scrubs its own magic string; residual worst case is the literal
      text printing on back silk (cosmetic). Confirm scrubbing via chat if
      that matters for the run.

## 2b. Open confirmations with JLCPCB support — ASK BEFORE PAYING
##     (drafted 2026-07-18 for the first order; resolve via chat, then tick)

- [ ] **JLCJLCJLCJLC token under "Remove Mark":** confirm the back-silk token
      text is scrubbed (not printed literally). If they won't confirm, cut a
      token-less silk revision (delete the SILK entry in
      `generator/pcb_layout.py`, `make fab`, re-upload) before ordering.
- [ ] **J4 PLACEMENT ERROR — RESPIN REQUIRED BEFORE ORDERING (found
      2026-07-19).** Numeric STEP analysis (scratch proof pack + the
      manufacturer drawing `datasheets/XUNPU_FPC-05FB-NPH20.pdf`) proves the
      FPC-05FB's SMT tails are at the REAR (actuator) face, ~6.6mm from the
      mouth. With tails on the east pad column the mouth faces WEST into the
      board — the panel cable cannot mate. Fix: rotate J4 180° in place
      (contact pads west, anchors/mouth east), re-derive pin-1/cable mapping
      vs the DESPI-C02 reference (pin 1 lands SOUTH after rotation — the
      2026-07-08 numbering resolution must be redone for the new geometry),
      re-route the FPC fanout, re-run all gates, re-export, re-upload.
      JLC's preview model showed this correctly all along (tails with
      actuator); the land pattern was the error.
- [ ] **Feeder count:** Feeders Loading fee bills 17 × ~€2.75 while the BOM
      has 16 Extended lines — ask which parts are counted (≈€2.75 delta).

## 3. Assembly options

- [ ] **Standard PCBA, top side only.** Economy is impossible for this board:
      ENIG and POFV each disable it, and U1 (ESP32-C6-MINI-1) + U5 (BMP581)
      are Standard-only parts (verified against a live quote 2026-07-18).
      All assembled parts are on F.Cu by construction (TPs/jumpers are
      copper-only, headers are DNP).
- [ ] Upload `out/fab/thermometer-c6-bom.csv` + `out/fab/thermometer-c6-cpl.csv`.
      **75 placements / 37 BOM lines.**
- [ ] **Confirm Parts Placement: Yes** (first order with this CPL — their
      engineer sends placement imagery for approval before assembly; ~+1 day).
- [ ] **PCBA Remark** (free), paste:
      "U5 (BMP581) is a vented barometric pressure sensor — do not wash the
      board, no coating/ink over U5; standard reflow per Bosch guidelines is
      fine. Bake Y1/MSD parts at your discretion if floor life requires.
      J4 (C2856831 FPC-05FB-24PH20): mount with the contact-tail/cable-entry
      side toward the board edge, pin 1 at the '1' silk marker — your
      placement preview renders this model displaced from its pads; please
      confirm orientation against the land pattern at DFM."
- [ ] Expect one feeder-loading fee (~€2.75) per Extended BOM line — 16 lines
      as of 2026-07-18; only D3 (white C2290) and the 10k (C25744) have Basic
      same-footprint options, the rest have none (audited 2026-07-18). If JLC
      auto-substitutes the 10k with an Extended part (stock), re-match in the
      BOM review page to any in-stock **Basic** 10k 0402 — candidates
      C25744 (1%) / C60490 (1%) / C25531 (±5%; tolerance fine for all seven
      positions — pull-ups, gate series/bleed, and MCP73831 PROG where ±5%
      = 95–105mA). 2026-07-18: all three were out of JLC assembly stock at
      once and every in-stock 10k 0402 was Extended — in that case just
      accept the auto-substitute (e.g. C174175) and eat the ~€2.75 feeder
      fee. Third-party part browsers show LCSC retail stock, not JLC
      assembly stock — trust only the BOM dialog.

## 4. Stock re-verification (before quoting)

Re-check LCSC/JLC stock — several parts run thin:

- [ ] U1 ESP32-C6-MINI-1-N4 **C5736265**
- [ ] Q3 Si1308EDL **C469327** (thin — fallback Si1304BDL clone **C7419947**)
- [ ] 10k **C25744** (alt **C60490**, then **C25531** ±5% Basic — see §3)
- [ ] **U5 BMP581 C5362283 — if out of stock, populate U6 BMP585 instead:**
      in `generator/circuit.py` set U5 `dnp=True` and U6/C26/C27 `dnp=False`
      (populate-exactly-one — both strap I2C 0x47), `make check`, commit, then
      re-run `make fab`. The BOM/CPL pick up the swap automatically.

## 5. FPC connector warning

- [ ] J4 must be **C2856831 (XUNPU FPC-05FB-24PH20, DUAL contact)**. The
      bottom-contact sibling **C2856805** looks identical in search results and
      does **NOT** work with the panel cable — never substitute.

## 6. Rotation/polarity verification (MANDATORY)

- [ ] In JLC's component-placement preview, walk `out/fab/rotation-checklist.md`
      row by row (22 orientation-critical parts). **The preview is ground
      truth** — the correction table in `generator/fab_cpl.py` is a first guess,
      and the SOT-23 family carries a known community-table conflict.
- [ ] On a mismatch: adjust the part's delta in `fab_cpl.py`, mark the entry
      `verified:`, re-run `make fab`, re-upload the CPL. If **all** parts are
      uniformly rotated or offset, suspect origin handling, not per-part deltas.
- [ ] Top-priority rows: **U5** (rotated LGA is invisible after reflow), **J4**
      pin 1, **U1** antenna WEST, and all FETs.
- [ ] Answer any JLC engineer polarity-confirmation email against the same
      checklist.

## 7. Archive after submitting

- [ ] Copy the exact uploaded zip + CPL + BOM + the ticked
      `rotation-checklist.md` into `archive/order-<YYYY-MM-DD>/`.
- [ ] Append a provenance entry to `archive/README.md`: commit hash, stamp,
      JLC order number, and the options chosen (ENIG / POFV / order-number
      position).
- [ ] Commit.
