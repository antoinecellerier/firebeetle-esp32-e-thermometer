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

## Phase 0 — before any power (per board)

- [ ] Visual pass against the JLC renders / placement-verification table:
      J4 0.5mm-pitch row for bridges, U1 module fillets, U5 seated (vent
      pinhole NW, pin 1 SW), **U6 pads empty**, every diode band per the
      table (D1/D3 cathode E, D2 W, D4/D5 S, D6 W).
- [ ] Jumper state as shipped: JP1 bridged (copper), JP2+JP5 bridged
      (0.47Ω RESE + 10µH — universal default), JP3/JP4/JP6 open.
- [ ] DNP provisions empty: D7 (TVS), R9 (10M 32k bias), U6; J2/J5 headers
      unstuffed; TPs bare. C29 (10nF ADC reservoir) IS populated.
- [ ] DMM resistance to GND, no dead short: VBAT, VSYS (J2.2), 3V3 (TP4),
      EPD_VCC, PREVGH, PREVGL, VCOM.
- [ ] Diode-mode sanity: D2 drop VSYS→VBUS only; Q6 body-diode direction at
      the JST; LP I2C pull-ups read ~4.7k from GPIO6/7 pads to 3V3.
- [ ] J4↔panel adapter pin-1 continuity (mouth EAST, pin 1 at the NORTH end
      of the row) — the respun footprint's first physical verification.
- [ ] **JST pigtail polarity vs the `+` silk before first battery plug**
      (JST vs Adafruit pigtail convention differs — README open item 5).

## Phase 1 — first power (battery + panel absent)

- [ ] Power via PPK2 source mode: J2 pin 2 + GND, JST empty, JP1 wicked open
      (or a current-limited supply, 4.0V / 50mA limit, at the same point).
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
      settle is ample (τ = 0.5ms).
- [ ] Charging self-heat: quantify how far BMP581 reads high while charging
      (README notes it; get a number for logging).

Afterwards: update the shutdown thresholds in Thermometer.cpp if re-derived,
append the floor/refresh numbers to the docs/notes.md power logbook, and file
any part swaps (D2, crystal variant) as rev B candidates.
