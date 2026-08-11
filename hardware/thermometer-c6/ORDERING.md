# Ordering — thermometer-c6 at JLCPCB

Order checklist for the `make fab` bundle. The fab pipeline (render → DRC →
gerbers/drill → CPL/BOM → zip → `verify/check_fab.py`) is the mechanism;
this file is the human procedure around it. Settled fab decisions live in
[`CLAUDE.md`](CLAUDE.md) ("Settled decisions — don't re-ask").

## 1. Generate & upload

- [ ] Check out the ordering commit on a **clean tree** and run `make fab`.
      A dirty tree is refused so the `rev A <hash> <date>` silk stamp names the
      exact committed source (`FAB_FORCE=1` overrides but makes the stamp a lie
      — don't ship one).
- [ ] Upload `out/fab/thermometer-c6-gerbers-<hash>-<date>.zip` (12 files:
      9 gerbers + drill + drill-map + job) to the JLCPCB quote page.

## 2. Board fabrication options

- [ ] Dimensions **48×35mm**, **2 layers**, **1.6mm**, outer copper **1oz**,
      qty **≥5**, solder mask **white** with black silk (deliberate,
      2026-07-20), TG **≥135**.
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

## 2b. Confirmations raised for the 2026-07-20 order — all resolved
##     (drafted 2026-07-18; the order was paid 2026-07-20 and the boards landed
##     2026-07-29. Dispositions actually taken: `archive/README.md`, "Known
##     items carried into the order")

- [x] **JLCJLCJLCJLC token under "Remove Mark" — RESOLVED 2026-07-20, token
      DELETED.** Support's answer was that the order-number-at-a-specified-
      position service "is already unavailable", i.e. the token could never do
      its job — leaving it risked only the literal string printing on back
      silk. The `SILK` entry was removed from `generator/pcb_layout.py`; the
      board now ships with no order mark. Nothing left to confirm.
- [x] **J4 GEOMETRY + ROUTING DONE (respin
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
      REAL=0 DEFERRED=0 WAIVED=0 at full severity. JLC's preview model showed
      the true orientation all along (tails with actuator); the land pattern was
      the error.
      **Resolved:** the CPL rotation delta stayed `0`/`confidence: low` and was
      covered by Confirm Parts Placement + the DFM gate rather than a preview
      re-walk (`archive/README.md`). J4 pin-1 and mouth-east are now
      hardware-verified on board 1 by continuity (`BRINGUP.md` Phase 0).
- [x] **J3 DATUM + LAND + ROUTING DONE
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
      **Preview walked 2026-07-20 — placement CONFIRMED, the render is a JLC
      model artifact, and JLC support confirmed it.** Their 3D preview draws
      the whole J3 model — housing, solder tails AND shell legs together —
      about 1.3mm off the land pattern, so the tails miss the pads and the
      legs miss the holes. That is a rigid-body displacement of the model,
      which is exactly the (0, −1.050, 0) correction `pcb_layout.MODELS_3D`
      already applies to seat this EasyEDA STEP (its origin is the
      front-shell reference, not the land centroid); JLC's viewer applies no
      such correction. Cross-checked by parsing the shipped gerber+drill zip
      directly: front shell slot 2.110 from the edge (HRO 2.1078), rear 6.290
      (6.2794), NPTH 5.760 — and the intended mouth overhang is **0.490** =
      HRO's own 2.600 − 2.110. `check_pcb.py` §9b(b) pins the front slot
      absolutely at 2.110 ±0.05, so a datum error of this size would fail the
      gate by ~25×; it passes.
      **JLC chat 2026-07-20 (agent Oscar), verbatim:** *"you can proceed to
      order … sometimes our system's 3d model have issue causing the part
      misalign … our engineer will manually correct it for you"*, and *"if
      there is any issue our engineer will inform you via email"*. Asked
      whether misalignment has to be flagged explicitly or is caught anyway:
      *"yes it will be pause if issue were found … our engineer will review
      for you first … if there is any issue it will pause and send you email
      … **it will not proceed without your confirmation**"*. So DFM review is
      a hard gate on their side, not an opt-in. That closes the residual
      pick-and-place-origin question as far as a frontline answer can.
      Keep the J3 clause in the PCBA Remark (§3) and Confirm Parts Placement
      = Yes anyway — they cost nothing and leave a paper trail, and the
      remark explicitly asks them NOT to silently adjust the placement.
      **Resolved:** the rotation delta stayed `0`/`confidence: low`, covered by
      Confirm Parts Placement + the DFM gate (`archive/README.md`). The
      X-rays show J3's 0.5mm row resolving individually with no bridging, and
      board 1 enumerates over USB.
- [x] **D1 CPL DELTA RESET (respin 2026-07-20).** The mouth-north J3 USB
      reroute re-placed D1 (**CHG** LED) rot 90 → 180, voiding its 2026-07-18
      LED_0603 preview verification; its CPL delta was reset to 0 (unverified)
      via a `REF_ROTATION_OVERRIDES["D1"]` entry.
      **Resolved without a re-walk:** its `0` was directly preview-verified
      2026-07-18 (cathode cue S), and a rotation delta corrects a
      footprint↔library convention offset, so it is independent of the
      placement change that voided the annotation (`archive/README.md`).
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
- [ ] **PCBA Remark** — NOT free: filling it in adds an Advanced Options line
      `PCBA remark: "Quote after review"`, excluded from the displayed total
      and charged after their engineer reads it (observed 2026-07-20). Worth
      it for the U5 no-wash instruction. Paste:
      "U5 (BMP581) is a vented barometric pressure sensor — do not wash the
      board, no coating/ink over U5; standard reflow per Bosch guidelines is
      fine. Bake Y1/MSD parts at your discretion if floor life requires.
      J4 (C2856831 FPC-05FB-24PH20): mount with the contact-tail/cable-entry
      side toward the board edge. **Pin 1 is the filled silk dot beside the
      north end of the pad row** — there is no '1' glyph (the footprint marks
      it with an `fp_circle` at local (5.75, −2.6), directly beside pad 1 at
      local x +5.75).
      J3 (C165948 USB-C): please place J3 to the LAND PATTERN, not to the
      model body. In your placement preview the J3 model — body, solder tails
      and shell legs together — renders about 1.3mm off the pads and holes.
      J3 is an edge-launch part, so I do intend a small housing overhang past
      the north board edge; I make it 0.49mm, with every pad and shell slot
      still on the board, and I make the front shell slot 2.110mm from that
      edge per the HRO TYPE-C-31-M-12 drawing. If your DFM check reads any of
      that differently, please tell me before assembly rather than adjusting
      it."
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
      (In stock 2026-07-23: 6,563 pcs on JLC assembly, $2.35–3.03.)

Cost-reduction checks from the 2026-07-22 research (see README "Rev B
candidates → Cost reduction"; tiers/stock re-verified 2026-07-23 against
JLC's part API — the BOM dialog is still ground truth at order time):

- [ ] **Try matching D4–D6 MBR0530 → B5819W C8598** in the BOM dialog —
      confirmed Basic 2026-07-23 (621k stock, $0.029, SOD-123, Vf
      600mV@1A). One Extended feeder line saved *if* feeders are billed
      per Extended line (see below). Leakage/Vf deltas are fine for the
      gated booster.
- [x] **Tiers verified 2026-07-23 (JLC part API)**: C98192, C5204746,
      C469327 (stock 6,445 — thin), C2856831 all **Extended**. No Basic
      4.7µF ≥50V 0805 exists (the only Basic 4.7µF 0805 is 25V — too
      marginal for the ~22V EPD rails); nearest Basic alternative is
      **C440198** 10µF 50V X5R 0805 (2.4M stock) — a candidate line-kill
      needing booster re-validation, see README.
- [ ] **Check the feeder-fee model on the next itemised quote**: JLC's
      live assembly-price page (updated 2025-09-01) documents Standard
      PCBA at **$1.50 per unique line, Basic included** (Economic: $3 per
      Extended line, Basic free) — yet the 2026-07-20 quote billed
      17 × €2.75, which matches the $3/Extended model, not the documented
      one. The "2025-12-19 rate cut" turned out to be a third-party page
      edit, not a JLC announcement. Which model actually bills decides
      whether Basic swaps save feeder money at all — ask support which 17
      parts were counted.
- [ ] **Quote POFV at qty 5/10/20** once, to learn whether the €44.07 is
      flat per order (amortises with volume) or scales — this decides how
      urgent the POFV-free rev B re-route is. Not documented anywhere
      public (2026-07-23: JLC's extra-charges article omits POFV; only
      documented fact is POFV is free on 6–20-layer, paid on 2/4-layer),
      so the quote calculator is the only oracle.
- [x] **X-Ray fee decoded 2026-07-23**: tiered per inspected piece
      ($1.57/pc at 1–10, $0.79 at 11–50, …), identical Economic/Standard;
      €11.46 ≈ 2 parts (U1 shield + U5 LGA) × 4 boards × $1.57. Mandatory
      for LGA/QFN/shield packages — not removable, but it scales with
      quantity rather than being a flat order fee.

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
- [ ] Append a provenance entry to [`archive/README.md`](archive/README.md):
      commit hash, stamp, JLC order number, and the options chosen (ENIG /
      POFV / order-number position).
- [ ] Commit.

## 8. Quote history

Record every itemised quote here — earlier rounds were only ever remembered as
a bare total (~€205), which made "did that change?" unanswerable.

### 2026-07-20, bundle `87f5d93` — €204.94, qty 5 PCB / 4 assembled

| line | € | note |
|---|---|---|
| **PCB** | **64.49** | |
| — Via Covering (POFV) | 44.07 | the single largest cost on the board |
| — Surface Finish (ENIG) | 14.84 | |
| — Via Plating Method | 2.92 | |
| — Special Offer | 1.75 | |
| — Confirm Production file | 0.91 | |
| **Standard PCBA** | **140.46** | |
| — Components (35 items) | 49.62 | 37 BOM lines, 35 unique parts — see below |
| — Feeders Loading | 46.75 | **= 17 × €2.75 exactly** — the open feeder question |
| — Setup Fee | 22.32 | |
| — X-Ray Inspection | 11.46 | mandatory (U1 shield + U5 LGA); tiered per piece ≈ 2 × 4 × $1.57 |
| — Stencil | 7.17 | |
| — SMT Assembly | 2.32 | |
| — Packaging | 0.43 | |
| — Confirm Parts Placement | 0.39 | wanted — see §3 |
| — Panel / Large Size | 0.00 | |
| **Advanced** | | |
| — Depanel + edge rail | 2.58 | opt-in; advanced options add a build day |
| Build time | 0.00 | PCB 3d, assembly 3–4d (2–3d would be +€43.01) |

Coupon €17.46 applied → €198.94. Weight 527.10g (5 boards + edge rails; JLC
grows the panel to 70×71mm because Standard PCBA needs ≥70mm a side).

**Shipping: the quoted estimate is a lie for this order.** The quote and cart
pages advertise "Global Standard Direct Line" (€1.31 / €9.72), but at
checkout that line is restricted to orders **under $150** — this order is
~€199, so it is not selectable and the real carrier costs more. Budget for
the actual checkout options, not the estimate. Splitting the order to get
under the cap is not worth it: the €22.32 PCBA setup fee is per-order.

**The 35-vs-37 gap is benign — resolved 2026-07-20 in the BOM tab.** JLC
reported "37 parts detected / 37 parts confirmed"; it bills 35 because two
pairs of BOM lines share one LCSC part and get merged: R18/R19/R22/R23/R5
with R20/R21 (both **C25741**), and SW1 with SW2 (both **C318884**). The ⚠
icons on those rows are merge notices, not problems. Checked the one that
would have mattered: R20/R21 are the VBAT_ADC divider and are spec'd 1% —
C25741 is `0402WGF1003TCE`, whose `F` code IS ±1%, so the merge does not
quietly downgrade battery-sense accuracy.

Deltas worth watching next round: the feeder count (17 billed vs 15 Extended
lines counted in the BOM tab 2026-07-20), and whether X-Ray and depanel are
optional.

Settled deliberately 2026-07-20, do not "correct" these: **white** solder
mask (not green) and **lead-free / high-temp** solder paste.

### Import charges — budget them, they are not on JLC's invoice

JLC invoice (2026-07-27): merchandise €209.27 (bare PCB €13.25 + 4×
assembled €49.01) + shipping €20.12 (DHL Express Worldwide, CPT) − coupon
€17.46 = **€211.93 paid**. DHL door bill: **€62.00** = €42.00 TVA (20% of
the €211.93 invoice total — checks exactly) + €20.00 clearance fee ("frais
additionnels de dédouanement", €16.67 + its own TVA). Actual customs duty:
€0 — EU tariff on populated PCBs is zero, so the entire door charge is VAT
plus the courier's fixed fee. **Landed: €273.93 ≈ €68.50 per assembled
board.**

Rule for future orders: anything over €150 gets import VAT collected by the
courier (20% of goods + shipping) plus a ~€15–20 disbursement fee — add
~22–25% to the checkout total to get the landed cost. Sub-€150 orders with
IOSS (LCSC/DigiKey style) prepay VAT at checkout and owe nothing at the
door, which is why small part orders never showed this. Splitting an order
under €150 to dodge the fee still loses: the €22.32 PCBA setup fee is
per-order (see shipping note above).
