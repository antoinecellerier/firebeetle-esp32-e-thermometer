# BRINGUP.md — rev A first-article checklist

Consolidates the bring-up items from README (Bench procedures, open items),
REVIEW-KICAD-HAPPY.md (○ OPEN rows), SCHEMATIC-VERIFICATION.md (first-article
adds), and the placement verification in
`archive/order-2026-07-20/jlc-production-files/`. Run Phases 0–2 in order on
the first board; Phase 3 measurements once; then a quick Phase 0–1 pass on the
remaining boards. Bench ground rules (README): **never back-feed TP4 (3V3)** —
RT9080 forbids VOUT > VIN + 0.3V and EN=0 active-discharges at ~80Ω; inject
bench power only at the J2/JP1 battery-side break.

Test points (back side): VBAT, VBAT_ADC, 3V3 (probe-only), EPD_VCC, PREVGH,
PREVGL, VCOM, GDR, RESE, GND ×2. VSYS is reachable at J2 pin 2.

## 2026-07-27 — JLC first-article X-rays (pre-arrival; boards ETA 2026-07-30)

Four frames in `archive/order-2026-07-20/xray/`, one per assembled board —
distinct solder micro-features per frame prove they are not re-shots, but the
frame↔board mapping is unknowable. Per-part identification is proven, not
eyeballed: `xray/annotated/` overlays every top-side footprint's bbox
projected from the board file (transform + per-part verdict table in
`xray/README.md`; `xray/annotate.py` regenerates). Findings, consistent
across all four:

- U5 (BMP581 LGA-10): all 10 joints wetted and uniform, package centered,
  no bridging.
- U1 (MINI-1): castellations evenly wetted, no bridges, module centered.
  Center GND pads unreadable through the module's internal layers — fine,
  no thermal load. The 45°-rotated QFN is the C6 die inside the module.
- J3 (USB-C): 0.5mm pin row resolves individually, no bridging; shell
  through-legs filled. **J4 is off-frame in all four images** (frames cover
  x≲38mm of the 48mm board; J4's row sits at x≈41.5) — the X-rays say
  nothing about it, so the Phase 0 optical bridge check on J4 is the only
  inspection it gets.
- Satellite solder micro-balls (~50–100µm) near U5 on 2–3 frames — see the
  Phase 0 item below. The fuzzy round blob top-right in two frames is off
  the board at (x≈−6.1, y≈−2.8)mm — on the panel rail/carrier, and too
  faint to be solder at its ~0.9mm diameter.

X-ray confirms geometry only (no bridges, nothing missing or shifted); it
proves neither electrical contact on the LGA nor passive values — Phases 0–2
remain the gate.

## Phase 0 — before any power (per board)

Board numbering (2026-07-29, boards in hand): the four assembled boards are
hand-marked 1–4 on the back below the USB port — the fab put no serials on
them, so the numbers map to neither JLC's internal count nor the X-ray
frames. The lone unassembled board carries a factory 0005 datamatrix and is
board 5. Board 1 is the first-article board for Phases 0–2.

- [x] Visual pass against the JLC renders / placement-verification table:
      J4 0.5mm-pitch row for bridges, U1 module fillets, U5 seated (vent
      pinhole NW, pin 1 SW), **U6 pads empty**, every diode band per the
      table (D1/D3 cathode E, D2 W, D4/D5 S, D6 W).
      2026-07-29: pass on all four assembled boards. Board 4's U5 sits
      slightly skewed (rotation). The X-rays showed all four packages
      centered, but the frame↔board mapping is unknowable, so they can't
      clear board 4 specifically; slight LGA skew is normally benign
      (reflow self-alignment). Arbitrate at the Phase 2 BMP581 detect —
      run board 4 through that check early.
- [x] Loupe + brush pass around U5: the X-rays show satellite solder
      micro-balls near the package on 2–3 boards — dislodge anything loose
      (vent-port neighborhood; harmless once confirmed not mobile).
      2026-07-29: nothing visible under the loupe on any board; finish
      very clean. Treating the micro-balls as under-package/immobile.
- [x] Jumper state as shipped: JP1 bridged (copper), JP2+JP5 bridged
      (0.47Ω RESE + 10µH — universal default), JP3/JP4/JP6 open.
      2026-07-29: confirmed on all boards. Bridges are factory copper
      (must be cut before first use as NO), matching the KiCad model.
- [x] DNP provisions empty: D7 (TVS), R9 (10M 32k bias), U6; J2/J5 headers
      unstuffed; TPs bare. C29 (10nF ADC reservoir) IS populated.
      2026-07-29: confirmed. (R9 is an 0402 across the Y1 pads — bench-
      stuff only if the 32k cold-start item bites.)
- [x] DMM resistance to GND, no dead short: VBAT, VSYS (J2.2), 3V3 (TP4),
      EPD_VCC, PREVGH, PREVGL, VCOM.
      2026-07-29: boards 1 and 5 clear on all seven rails. The RESE TP is
      *not* in this list and must not be added: TP9 sits on EPD_RESE,
      which is R14 (0.47Ω) through bridged JP2 straight to GND — board
      1's 0.60Ω there is the sense resistor plus jumper/probe resistance,
      by design. Board 5 reads open at RESE only because the bare board
      has no R14. Boards 2–4 get this pass in the remaining-boards sweep.
- [x] Diode-mode sanity (red probe = +):
      - D2 conducts **VBUS→VSYS** — anode is the east pad, cathode band
        west on VSYS (an earlier revision of this line said "VSYS→VBUS";
        that was backwards). Red on the anode pad, black on the band:
        expect a 0.2–0.35V Schottky drop.
        2026-07-29 board 1: **0.2142V forward — pass.** (The 1.96V first
        measured red-on-VSYS was the blocked direction reading through
        peripheral paths.)
      - Q6 body diode: red on J1 pin 1 (the `+` pad), black on the VBAT
        TP (bridged JP1 makes it the same node): expect ~0.4–0.7V —
        AO3401A D→S body diode, BAT_IN→VBAT_RAW. Swapped: no drop.
        2026-07-29 board 1: **0.4259V — pass** (low end is normal at a
        DMM's ~0.3mA test current; datasheet Vf figures are at 1A).
      - LP I2C pull-ups: Ω mode straight across R10 and R11 (or from
        U6's empty SDA/SCL pads to the 3V3 TP): ~4.7k each.
        2026-07-29 board 1: **4.67kΩ both — pass** (nominal −0.6%,
        within the 1% tolerance). Consistent with the earlier matched
        1.4849V diode-mode readings (≈316µA test current × 4.7k).
- [x] J4↔panel adapter pin-1 continuity (mouth EAST, pin 1 at the NORTH end
      of the row) — the respun footprint's first physical verification.
      Method: J4's nets are probeable at back TPs (GDR→2, RESE→3,
      EPD_VCC→15/16, PREVGH→21, PREVGL→23, VCOM→24, GND→8/17) or at
      front-side component pads on the same nets. Seat the rig's 24-pin
      FFC in J4 with the panel NOT attached at the far end, then beep
      each net against the adapter's matching pin. RESE (pin 3, north
      end) plus VCOM (pin 24, south end) is an asymmetric pair that
      catches a flipped row immediately.
      2026-07-29 board 1: **all continuous and on the right adapter
      pins** — RESE, GDR, GND ×2, EPD_VCC ×2, PREVGH, PREVGL, VCOM.
      The respun footprint (pin 1 north, mouth east) is verified on
      hardware. Bench note: back TPs are impractical when the reference
      is on the front face (FFC seated topside) — coordinating probes on
      both faces mid-air doesn't work; front component pads on the same
      nets were used instead. TPs remain fine for single-face probing
      (powered floor/scope work with the board face-down or on edge).
- [x] **JST pigtail polarity vs the `+` silk before first battery plug**
      (JST vs Adafruit pigtail convention differs — README open item 5).
      2026-07-29: confirmed by DMM on the loose plug — the red wire /
      + contact mates with J1's `+`-marked pad. Shell orientation also
      matches the existing devices' pigtails.

**Phase 0 complete on board 1 (2026-07-29).** Boards 2–4 still owe the
quick per-board pass after first-article Phases 0–2.

## Phase 1 — first power (battery + panel absent)

- [ ] Power via PPK2 source mode: J2 pin 2 + GND, JST empty, JP1 cut open
      (factory copper bridge, per Phase 0 — knife cut, re-close with
      solder afterwards; "wick" doesn't apply the first time). Or a
      current-limited supply, 4.0V / 50mA limit, at the same point.
- [ ] 3V3 = 3.30V at TP4 (probe only).
- [ ] EPD_VCC = 0V (gate held off by the 10k pull-up).
- [ ] Quiescent draw plausible (unflashed module executes ROM console — mA
      range is normal; the µA floor is checked in Phase 2 after flashing).
- [ ] USB attach, battery absent: USB-Serial-JTAG enumerates; VSYS ≈ VBUS
      minus the D2 drop (load-share path). Expect the CHG LED to
      float-cycle with no battery — brief check only, then unplug (the
      product rule is: don't leave USB attached without a battery).
- [ ] Battery attach (JP1 re-bridged or J2 shorted): charge current ≈100mA
      (R3 10k → 0.25C for a 400–500mAh pouch); CHG LED solid while charging.
      Charging is indoor-only, 0–45°C (no TS pin on MCP73831).

## Phase 2 — firmware smoke test (`pio run -e thermometer_c6_debug`)

- [ ] Flash over USB; serial monitor up.
- [ ] Boot log has **no 32k-XTAL fallback warning** → RTC slow clock is the
      FC-135 (CONFIG_RTC_CLK_SRC_EXT_CRYS). If it falls back: that's the
      32k cold-start item in Phase 3; R9 10M is the bench-stuff mitigation.
- [ ] BMP581 detected at 0x47 on LP I2C (GPIO6/7); temperature plausible.
- [ ] Logged battery mV ≈ DMM VBAT ±50mV (divider ×2 + curve-fitting cali);
      VDIV_EN measured 0V outside the read window.
- [ ] vbus_present(): true on USB, false unplugged.
- [ ] Status LED on GPIO15 works (needs DISABLE_LEDS commented out in
      local-secrets.h for the test).
- [ ] Panel attached (power off first): full refresh renders; BUSY
      light-sleep path works; EPD_VCC returns to 0V after hibernate and the
      floated control pins don't back-light the panel rail (probe EPD_VCC).
- [ ] Deep-sleep floor on PPK2 (reference: XIAO C6 rig ~15.8µA; the LDO tree
      will differ — record the number in docs/notes.md power logbook).
- [ ] LP core survives sleep cycles: lp counter increments, no echo boots,
      no `uN`/PANIC forensics indicators on screen.

## Phase 3 — first-article measurements (one board, PPK2 + scope)

- [ ] **VGH/VGL reach spec during refresh with JP2+JP5** (0.47Ω/10µH
      universal config). GDEH0576T81's datasheet config is 2.2Ω/47µH =
      JP3+JP6 — that's the on-board fallback if VGH sags.
      [REVIEW-KICAD-HAPPY ○]
- [ ] EPD_VCC ramp with the R24/C28 soft-start on a scope (no brownout at
      gate-on). [README PPK2 items]
- [ ] **3V3 sag during the ~465mA refresh peak at VBAT = 3.7V** (bench
      supply at J2). Worst-case RT9080 dropout sits right at the cutoff.
      Then decide: keep 3800/3700mV thresholds (Thermometer.cpp) or
      re-derive to ~3.4–3.5V — the LDO tree degrades gracefully where the
      XIAO buck cliffed. [SCHEMATIC-VERIFICATION]
- [ ] Boost transient current vs the Si1308EDL 610mA ILIM at refresh start.
      [SCHEMATIC-VERIFICATION]
- [ ] 32k crystal **cold start**: power-on from fridge-cold (ESR rises when
      cold; FC-135's 70kΩ spec sits at Espressif's max). Mitigations in
      order: R9 10M bench-stuff, 7pF FC-135 variant. [REVIEW-KICAD-HAPPY ○]
- [ ] **Warm sleep floor** (~40°C): D2 SS14 reverse leakage lands on the
      floor via the 66k VBUS pulldowns; PMEG6010-class is the fallback (no
      SMA drop-in — board change for rev B if needed). [REVIEW-KICAD-HAPPY ○]
- [ ] VBAT_ADC accuracy across 3.5–4.2V vs DMM; confirm the 5ms divider
      settle is ample (τ = 0.5ms). While looking at this trace, also check
      whether the settle wait shows as a visible chunk of a non-refresh
      wake. Analysis 2026-07-22 (deferred pending these numbers): the read
      runs only on CPU wakes, so the blocking 5ms costs ~0.075mC (5ms ×
      ~15mA) against a multi-mC wake — <1%, an 8× smaller target than the
      already-declined 40ms EPD-reset light-sleep. If it ever matters, the
      known fixes are (a) hoist the VDIV_EN enable to setup() entry with an
      elapsed-time remainder guard in read_battery_level() (logging hides
      the settle only in debug builds), or (b) trim 5ms→3ms (6τ, ~10mV
      battery-scale error) for a zero-complexity 60% cut.
- [ ] Charging self-heat: quantify how far BMP581 reads high while charging
      (README notes it; get a number for logging).

Afterwards: update the shutdown thresholds in Thermometer.cpp if re-derived,
append the floor/refresh numbers to the docs/notes.md power logbook, and file
any part swaps (D2, crystal variant) as rev B candidates.
