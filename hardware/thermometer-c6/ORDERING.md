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
      solid silk square this board doesn't have). The board carries **no
      order-mark token**: JLC support confirmed 2026-07-20 that the
      specify-position service "is already unavailable", so the
      `JLCJLCJLCJLC` back-silk string was deleted from
      `generator/pcb_layout.py` rather than shipped as a stale artifact whose
      only two outcomes were "silently scrubbed" or "printed literally".

## 2b. Open confirmations with JLCPCB support — ASK BEFORE PAYING
##     (drafted 2026-07-18 for the first order; resolve via chat, then tick)

- [x] **JLCJLCJLCJLC token under "Remove Mark" — RESOLVED 2026-07-20, token
      DELETED.** Support's answer was that the order-number-at-a-specified-
      position service "is already unavailable", i.e. the token could never do
      its job — leaving it risked only the literal string printing on back
      silk. The `SILK` entry was removed from `generator/pcb_layout.py`; the
      board now ships with no order mark. Nothing left to confirm.
- [ ] **J4 GEOMETRY + ROUTING DONE — PREVIEW RE-WALK STILL OPEN (respin
      2026-07-19, depth corrected 2026-07-20).** Numeric STEP analysis
      (`out/j4-proof/` + the manufacturer drawing
      `datasheets/XUNPU_FPC-05FB-NPH20.pdf`) proved the FPC-05FB's SMT tails
      are at the REAR (actuator) face; the old placement (tails on the east pad
      column) pointed the mouth WEST into the board so the panel cable could
      not mate. J4 is re-placed mouth-EAST, contact-tail/pad column WEST
      (x41.45), footprint pads renumbered so pad 1 = panel circuit 1 stays at
      the NORTH end (circuit.py and the README FPC pin table unchanged).
      Body depth is **5.40** and the mouth sits **4.95mm** east of the pad row
      at x46.40 — 1.60mm inboard of the edge, not flush. (The earlier 6.55/6.6
      figures came from bounding-boxing raw CARTESIAN_POINTs, which include
      LINE/AXIS2_PLACEMENT_3D entities owning no geometry; VERTEX_POINT-only
      gives 5.40, matching the XUNPU drawing exactly — `out/j3-land/` §7.)
      The 24-pin fanout is **re-routed and complete**: 0 unconnected, DRC
      REAL=0 DEFERRED=0 WAIVED=0 at full severity. **Still to do before
      paying:** the J4 CPL rotation delta was reset to 0 (unverified), so
      re-walk the JLC preview for J4. JLC's preview model showed the true
      orientation all along (tails with actuator); the land pattern was the
      error.
- [ ] **J3 DATUM + LAND + ROUTING DONE — PREVIEW RE-WALK STILL OPEN
      (respins 2026-07-19 + 2026-07-20).** The 2026-07-19 pass (`out/j3-proof/`)
      fixed the ORIENTATION: the old rot-0 placement sat the HRO USB-C mouth
      facing SOUTH into the board with the solder tails at the north edge — an
      unpluggable connector, masked by a 3D model mis-registered 180°. J3 was
      re-placed mouth-NORTH (rot 180). The 2026-07-20 pass fixed the DATUM and
      the LAND, and both were wrong:
      * **Datum** (`out/j3-datum/`, datasheet content-stream parse + 1200dpi
        raster + STEP, three methods agreeing to ≤0.005mm). HRO's `5.79` is
        measured **PCB EDGE → ⌀0.60 NPTH post CENTRELINE**, not to the pad row,
        and `4.18` is **shell-slot centre to shell-slot centre**. The front
        shell slot therefore belongs **2.11mm** from the edge, not 0.695 — J3
        was **1.415mm too far north**. Fixed: `PLACE["J3"]` y 1.745 → 3.160.
      * **Land** (`out/j3-land/`, solder foot isolated from the STEP by
        colour + planarity + z=0, measured 0.850mm). The stock KiCad land left
        only **+0.080mm heel** protrusion (below IPC-7351B *Least* 0.25, and
        negative under the tolerance stack) while spending +0.520 on toe. The
        footprint is now a project fork,
        `local:USB_C_Receptacle_HRO_TYPE-C-31-M-12`, with the SMT row shifted
        0.170mm toward the mouth and the NPTH posts 0.65 → 0.60mm (HRO's own
        value — it is what makes the shift legal at the 0.25mm `hole_clearance`
        rule). Result: heel **+0.250** / toe **+0.350**, 100% of the 0.200mm
        heel-fillet zone covered.
      The `edge-clearance-usb-c` DRU rule and its `drc_summary` waiver are
      **DELETED**. They existed only to waive 2 `copper_edge_clearance` errors
      caused by the front shell pad hanging 0.105mm OFF the board edge — a
      symptom of the placement error, not a property of an edge-launch part.
      The edge web is now 1.510mm and full-severity DRC is REAL=0 **WAIVED=0**
      with no J3 exception. `check_pcb.py` §9b now asserts the whole datasheet
      chain (front slot 2.110 from the edge, 4.180 slot span, 3.650 to the NPTH,
      4.925 to the pad row) plus "no shell pad overhangs the edge", so a datum
      regression fails the gate instead of being waived.
      The cut copper is **re-routed and complete** — VBUS, D+ and D− to the
      y7.035 pad row, plus EPD_BUSY, EPD_RST and the VSYS north crossing the
      datum-correct body sits on. Board-wide: 0 unconnected, 0 dangling, DRC
      REAL=0 DEFERRED=0 WAIVED=0 at full severity, schematic parity 0.
      **Preview walked 2026-07-20 — placement CONFIRMED, body render is an
      artifact.** JLC's 3D preview draws the J3 housing ~2.7mm past the north
      edge while the pads render correctly on their land. Pads and body are
      rigidly linked in one footprint, so copper-right/body-wrong can only be
      model seating in their viewer, not a placement error. Cross-checked by
      parsing the shipped gerber+drill zip directly: front shell slot 2.110
      from the edge (HRO 2.1078), rear 6.290 (6.2794), NPTH 5.760 — and the
      intended mouth overhang is **0.490** = HRO's own 2.600 − 2.110.
      `check_pcb.py` §9b(b) pins the front slot absolutely at 2.110 ±0.05, so
      a 2.7mm datum error would fail the gate by 50×; it passes.
      Residual risk carried into the order: **it is unknown whether JLC's
      pick-and-place origin matches their renderer's origin.** Mitigated by
      Confirm Parts Placement = Yes plus a J3 clause in the PCBA Remark (§3)
      telling them to place to the land pattern, not the model body.
      **Still to do before paying:** the J3 CPL *rotation* delta is 0 and
      still **unverified** — confirm mouth-north/pin-1 in the preview.
- [ ] **D1 CPL DELTA RESET (respin 2026-07-20).** The mouth-north J3 USB
      reroute re-placed D1 (status LED) rot 90 → 180, voiding its 2026-07-18
      LED_0603 preview verification; its CPL delta was reset to 0 (unverified)
      via a `REF_ROTATION_OVERRIDES["D1"]` entry. Re-walk the JLC preview for
      D1 alongside J3 and J4 before paying.
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
      confirm orientation against the land pattern at DFM.
      J3 (C165948 USB-C): this is an edge-launch part — the housing is MEANT
      to overhang the north board edge by 0.49mm (HRO's own recommended
      layout), while every pad and shell slot stays on the board. Your
      placement preview renders the J3 body ~2.7mm past the edge, i.e. ~2.2mm
      further out than the land pattern; the pads render correctly. Please
      place J3 to the LAND PATTERN, not to the model body, and confirm at DFM
      that the front shell slot sits 2.110mm from the board edge."
- [ ] Expect one feeder-loading fee (~€2.75) per Extended BOM line — 16 lines
      as of 2026-07-18; only D3 (white C2290) and the 10k (C25744) have Basic
      same-footprint options, the rest have none (audited 2026-07-18). If JLC
      auto-substitutes the 10k with an Extended part (stock), re-match in the
      BOM review page to any in-stock **Basic** 10k 0402 — candidates
      C25744 (1%) / C60490 (1%) / C25531 (±5%; tolerance fine for all seven
      positions — pull-ups, gate series/bleed, and MCP73831 PROG where ±5%
      = 95–105mA). 2026-07-18 all three were out of JLC assembly stock at once
      and every in-stock 10k 0402 was Extended; **2026-07-20 C25744 is back in
      stock**, so the BOM's own part should go through as Basic and this
      contingency likely never fires. If it is gone again by order time, accept
      the auto-substitute (e.g. C174175) and eat the ~€2.75 feeder fee.
      Third-party part browsers show LCSC retail stock, not JLC assembly stock
      — **confirm C25744 in the BOM dialog itself**, which is the only view
      that reflects assembly availability.

## 4. Stock re-verification (before quoting)

Re-check LCSC/JLC stock — several parts run thin:

- [ ] U1 ESP32-C6-MINI-1-N4 **C5736265**
- [ ] Q3 Si1308EDL **C469327** (thin — fallback Si1304BDL clone **C7419947**)
- [ ] 10k **C25744** — back in stock 2026-07-20; re-confirm in the BOM dialog
      (alt **C60490**, then **C25531** ±5% Basic — see §3)
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
