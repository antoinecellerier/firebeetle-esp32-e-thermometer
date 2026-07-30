# BRINGUP.md — rev A first-article checklist

Consolidates the bring-up items from README (Bench procedures, open items),
REVIEW-KICAD-HAPPY.md (○ OPEN rows), SCHEMATIC-VERIFICATION.md (first-article
adds), and the placement verification in
[`archive/order-2026-07-20/jlc-production-files/`](archive/order-2026-07-20/jlc-production-files/).
Run Phases 0–2 in order on the first board; Phase 3 measurements once; then a
quick Phase 0–1 pass on the remaining boards. Bench ground rules (README): **never back-feed TP4 (3V3)** —
RT9080 forbids VOUT > VIN + 0.3V and EN=0 active-discharges at ~80Ω; inject
bench power only at the J2/JP1 battery-side break.

Test points (back side): VBAT, VBAT_ADC, 3V3 (probe-only), EPD_VCC, PREVGH,
PREVGL, VCOM, GDR, RESE, GND ×2. J2 (the `IBAT` header) spans the JP1
break: pin 1 = battery side (VBAT_RAW), pin 2 = system side (VBAT — the
charger output node, *not* VSYS). VSYS has no TP or header — probe D2's
cathode (band/west) pad, Q1's source, or C1/C2.

## 2026-07-27 — JLC first-article X-rays (pre-arrival; boards ETA 2026-07-30)

Four frames in [`archive/order-2026-07-20/xray/`](archive/order-2026-07-20/xray/),
one per assembled board — distinct solder micro-features per frame prove they
are not re-shots, but the frame↔board mapping is unknowable. Per-part
identification is proven, not eyeballed:
[`xray/annotated/`](archive/order-2026-07-20/xray/annotated/) overlays every
top-side footprint's bbox projected from the board file (transform +
per-part verdict table in
[`xray/README.md`](archive/order-2026-07-20/xray/README.md);
`xray/annotate.py` regenerates). Findings, consistent across all four:

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

- [x] Power via PPK2 source mode, 4.0V. Injection point options:
      (a) J2 pin 2 + GND with JP1 cut open (factory copper bridge, per
      Phase 0 — knife cut, re-close with solder afterwards; "wick"
      doesn't apply the first time) — excludes Q6 and the charger;
      (b) **chosen for board 1: J1 via a Dupont-into-JST harness, JP1
      untouched** — the real battery path, so Q6 reverse-protects a
      mis-wired lead and all measurements are true battery-terminal
      figures. Includes Q6's Rds(on) (negligible at these currents) and
      the MCP73831 VBAT-pin leakage (sub-µA to low-µA, datasheet,
      unmeasured) — the Phase 2 floor read here is the deployment
      number, marginally above what (a) would show.
      A current-limited bench supply (4.0V / 50mA) at either point is
      the no-PPK2 fallback.
      2026-07-29 board 1: **first power clean** via (b). Inrush 0.67A
      for ~1–2ms (cap bank through Q6 + harness), ~10ms near zero (POR
      hold-off), then steady ROM draw — no brownout looping.
- [x] 3V3 = 3.30V at TP4 (probe only).
      2026-07-29 board 1: **3.299V — pass.**
- [x] EPD_VCC ≈ 0V (gate held off by the 10k pull-up). The node floats
      behind the off PFET — no bleed path — so a 10MΩ DMM reads the
      leakage equilibrium, not a hard 0V: a few hundred mV is a pass
      (tens of nA); ~3.3V would mean the gate is on.
      2026-07-29 board 1: **0.22V — pass** (~22nA into the DMM).
- [x] Quiescent draw plausible (unflashed module executes ROM console — mA
      range is normal; the µA floor is checked in Phase 2 after flashing).
      2026-07-29 board 1: **~22mA steady** (sel. avg 22.22mA, max
      24.38mA over 2.4s) — pass.
- [x] USB attach, battery absent: USB-Serial-JTAG enumerates; VSYS ≈ VBUS
      minus the D2 drop (load-share path). Expect the CHG LED to
      float-cycle with no battery — brief check only, then unplug (the
      product rule is: don't leave USB attached without a battery).
      2026-07-29 board 1: **all pass.** Enumerates as Espressif USB JTAG
      serial debug unit, MAC 98:88:E0:75:47:9C (board 1's identity);
      ROM banner clean over devserial (`boot:0x38` normal straps,
      `invalid header: 0xffffffff` = factory-blank flash). VSYS 4.788V
      at D2's cathode pad (≈ VBUS − 0.21V). CHG blinked once then quiet:
      VBAT (J2.2) float-holds at 4.296V — the charger topped the
      unloaded cap bank past termination (mild overshoot; Q1 blocks both
      ways with VBUS on its gate, divider gated off, so nothing bleeds
      the node back below the recharge threshold). Charger provisionally
      working; real verdict at the battery-attach step.
- [x] Battery attach (JP1 re-bridged or J2 shorted): charge current ≈100mA
      (R3 10k → 0.25C for a 400–500mAh pouch); CHG LED solid while charging.
      Charging is indoor-only, 0–45°C (no TS pin on MCP73831).
      2026-07-29 board 1 (JP1 never cut; PPK2 ampere meter in series on
      the battery + lead — charge current flows board→battery, so VIN
      faces J1): **102.97mA CC for the first ~7s — PROG confirmed.**
      Then start/stop cycling (~10↔100mA comb, aliased at 100S/s,
      envelope declining): series resistance offsets the voltage the
      charger sees, so CV/termination and recharge cycle early. Two
      co-suspects, same signature: the measurement harness (PPK2 burden
      + Dupont crimps) and the test pack's own internal resistance (a
      pouch idle for ~2 years; the other packs live in running
      prototypes). Not a charger-fault signature either way — PROG and
      the CC plateau are the checks, and they passed. Confirm with a
      known-good pack, meterless: CHG solid → terminates. Don't charge
      the aged pack unattended.

## Phase 2 — firmware smoke test (`pio run -e thermometer_c6_debug`)

First smoke build 2026-07-29: `thermometer_c6_debug`, hash `3b42d3a`, no
extra flags, `USE_BMP58x` + `DISABLE_DISPLAY` + LEDs enabled (no panel on
the board yet). Bring-up panel is the **GDEM0154I61** (`USE_154_GDEY`) —
the as-shipped JP2 0.47Ω + JP5 10µH are its correct config per the README
jumper table; the T81 stays on the soak rig for now. Flash log in
docs/history-store-validation.md.

- [x] Flash over USB; serial monitor up.
      2026-07-29 board 1: flashed at 3b42d3a; boot log captured via
      devserial. Full boot→sense→persist→sleep on first power: base
      snapshot seq 1 (erase 4ms / program 12ms / verify 4ms), LP core
      started at 5s poll, deep sleep entered (port drops — normal).
- [x] Boot log has **no 32k-XTAL fallback warning** → RTC slow clock is the
      FC-135 (CONFIG_RTC_CLK_SRC_EXT_CRYS). If it falls back: that's the
      32k cold-start item in Phase 3; R9 10M is the bench-stuff mitigation.
      2026-07-29 board 1: **no fallback warning — FC-135 running.**
      (W-level logs demonstrably reach this console: wifi W lines print.)
- [x] BMP581 detected at 0x47 on LP I2C (GPIO6/7); temperature plausible.
      2026-07-29 board 1: **chip ID 0x50 detected, 29.79°C** — plausible
      for a warm July room + board self-heat.
- [x] Logged battery mV ≈ DMM VBAT ±50mV (divider ×2 + curve-fitting cali);
      VDIV_EN measured 0V outside the read window.
      2026-07-29 board 1: **panel 4178mV vs 4200mV PPK2-sourced at J1 =
      −22mV — pass** (through Q6 + harness). VDIV gating proven by the
      18.7µA sleep floor rather than a pin probe: an ungated divider
      would add ~5µA. (Earlier USB-only reading of 4196mV was the
      charger's float-held node, also consistent.)
- [ ] vbus_present(): true on USB, false unplugged.
      2026-07-29: false-case demonstrated behaviorally — full render
      cycles on battery-path power, no spurious shutdown. Remaining
      direct check (optional): DMM J5 pin 6 (VBUS_SENSE divider) — a
      clean DC level with USB in, 0V without.
- [x] Status LED on GPIO15 works (needs DISABLE_LEDS commented out in
      local-secrets.h for the test).
      2026-07-29 board 1: observed lighting on a wake.
- [ ] Panel attached (power off first): full refresh renders; BUSY
      light-sleep path works; EPD_VCC returns to 0V after hibernate and the
      floated control pins don't back-light the panel rail (probe EPD_VCC).
      2026-07-29 board 1, GDEM0154I61: **first render PASS** — 33.9°C /
      16:01 CEST / 4204mV / `! DEBUG 5s` / footer `#3 r3 lp2 0d w:ULP
      mx4.2V 91bd4d8`. `w:ULP` = the frame came from an LP delta wake;
      `#3 r3` = archive continuity across the reflash; the refresh
      itself proves the boost chain (GDR/RESE/pump/PREVGH/PREVGL) on
      the as-shipped 0.47Ω/10µH. Temp read high then decayed toward
      the 27°C room — handling + USB self-heat (Phase 3 quantifies).
      Still open here: EPD_VCC probe after hibernate (expect the
      floating few-hundred-mV, not 3.3V).
- [x] Deep-sleep floor on PPK2 (reference: XIAO C6 rig ~15.8µA; the LDO tree
      will differ — record the number in docs/notes.md power logbook).
      2026-07-29 board 1: **18.3µA @ 4.2V** through the J1 deployment path,
      flat across a 2397s quiet window ≈ the ~46min field interval
      (docs/notes.md 2026-07-29; the first capture's 18.6–18.8µA was the
      board still shedding USB-era heat).
- [x] LP core survives sleep cycles: lp counter increments, no echo boots,
      no `uN`/PANIC forensics indicators on screen.
      2026-07-29 board 1: `w:ULP` frames on both builds (debug 5s and
      release 60s), `lp2` alive, **no `uN`, no `! PANIC`** across the
      release capture's sleep cycles. Delta wakes rendered frames at
      exactly the LP cadence while the board cooled.

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
      The regime map half is automated: `ppk2.py sweep --rail reva-j1`
      (fresh boot + classification per 100mV step 4.2→3.0V, then a 10mV
      bisect of the edge — `tools/ppk2.py` docstring has the flow). Flash
      `PLATFORMIO_BUILD_FLAGS="-DBATTERY_SHUTDOWN_DISABLED -DDISABLE_WIFI"
      pio run -e thermometer_c6_debug -t upload` first, detach serial, USB
      out; closeout = revive on USB, reflash release (gets the shutdown
      latch back), append report.md to the notes.md power logbook. The
      sweep sees input current only — the scope-on-3V3 dropout check stays
      manual, aimed at the edge the sweep finds.
      **Sweep DONE 2026-07-30** (notes.md): fresh-boot cliff **3317–3320mV**,
      ≤1–2mV wide; render never failed down to 3.31V, the sleep is what
      breaks (~104µA / ~55Hz oscillation below the edge); floor rises
      19→30µA over 3.38→3.32V. Candidate thresholds **3550/3450mV** — apply
      only after the scope-at-3.45V and cold checks above.
- [ ] Boost transient current vs the Si1308EDL 610mA ILIM at refresh start.
      [SCHEMATIC-VERIFICATION]
- [ ] 32k crystal **cold start**: power-on from fridge-cold (ESR rises when
      cold; FC-135's 70kΩ spec sits at Espressif's max). Mitigations in
      order: R9 10M bench-stuff, 7pF FC-135 variant. [REVIEW-KICAD-HAPPY ○]
- [ ] **Warm sleep floor** (~40°C): D2 SS14 reverse leakage lands on the
      floor via the 66k VBUS pulldowns; PMEG6010-class is the fallback (no
      SMA drop-in — board change for rev B if needed). [REVIEW-KICAD-HAPPY ○]
- [ ] VBAT_ADC accuracy across 3.5–4.2V vs DMM; confirm the 5ms divider
      settle is ample (τ = 0.5ms). Protocol (2026-07-29): PPK2 source at
      J1, USB OUT (the charger fights the source for VBAT); the panel
      only shows fresh mV on a rendered frame, so press RST per step to
      force one. 4.2→3.8V in 100mV steps, then below deliberately —
      ≤3.8V exercises the low-battery behavior and ≤3.7V the shutdown
      path (first hardware test of the threshold logic; revive on USB).
      First datapoint 2026-07-29: −22mV at 4.2V. Boards 2–4 get a
      single-point check (~4.0V) during their sweep — the curve fit is
      shared but the 1% divider stack is per-board (±40mV worst case). While looking at this trace, also check
      whether the settle wait shows as a visible chunk of a non-refresh
      wake. Analysis 2026-07-22 (deferred pending these numbers): the read
      runs only on CPU wakes, so the blocking 5ms costs ~0.075mC (5ms ×
      ~15mA) against a multi-mC wake — <1%, an 8× smaller target than the
      already-declined 40ms EPD-reset light-sleep. If it ever matters, the
      known fixes are (a) hoist the VDIV_EN enable to setup() entry with an
      elapsed-time remainder guard in read_battery_level() (logging hides
      the settle only in debug builds), or (b) trim 5ms→3ms (6τ, ~10mV
      battery-scale error) for a zero-complexity 60% cut.
- [ ] **Self-heat, separated by source.** There is no usable number yet: board
      1's 33.9°C against 29.8°C an hour earlier mixes bench sun, USB self-heat
      and the operator's fingers on the board (it decayed afterwards), so it
      bounds nothing. Take **equilibrium** deltas against a reference
      thermometer, one mode at a time, lid off and hands off:
      (a) battery only, sleeping — expect no measurable rise (calculated
          single-digit mW average);
      (b) USB parked in the service window, no pack — isolates U1+U2, the
          ~150mW continuous case;
      (c) USB with a pack charging — adds U4's ~130mW, which is 37mm away and
          so should present as whole-board warming rather than a local
          gradient. If (c) ≫ (b), the charger dominates and no sensor
          placement fixes it (README rev B candidate); if (b) ≈ (c), the local
          sources do.
      Then decide whether readings taken while charging should be suppressed or
      flagged rather than filed into the hourly ring.
      Cheap A/B for the U1-proximity term without a respin: build one of boards
      2–4 with U6 BMP585 instead of U5 and repeat (b).
- [ ] **USB flash-service window** (`fc9e72c`, untested on hardware). Plug a
      host into a sleeping board: expect a near-instant GPIO4 wake (measure
      plug→boot), `w:USB` in the footer, `! USB` on the panel, and the by-id
      port appearing **and staying**. Then `pio run -e thermometer_c6_debug -t
      upload` with nothing touched, twice back to back — the second proves the
      cycle converges rather than needing a button again.
      - [ ] Dumb 5V charger (no host): no rewake loop (the GPIO wake is armed
            only on VBUS-low), and the ~3s host probe appears on the PPK2 once
            per USB_WINDOW_PROBE_SKIP_WAKES wakes, not on every one. Note the
            docked cadence is deliberately the sleep interval, not the 1h
            safety net, so a docked board wakes far more often than a deployed
            one — that is what keeps the port reachable.
      - [ ] Unplug mid-window: exit inside ~300ms, one badge-clearing refresh,
            then deep sleep; replug wakes instantly again.
      - [ ] **Sleep floor with GPIO4 armed** vs the 18.7µA baseline. Expected
            unchanged (R23 holds the pad at 0V, and the internal pulldown is
            disabled by `CONFIG_ESP_SLEEP_GPIO_ENABLE_INTERNAL_RESISTORS=n`),
            but this measurement is the proof, not the reasoning.
      - [ ] Force a refresh while the window is open: the port must survive it
            (plain busy-wait instead of light sleep). Confirm a later
            battery refresh still shows the light-sleep slices.
      - [ ] `-DUSB_WINDOW_OBSERVE_CYCLES=2`: exactly two real sleep cycles
            (port drops each time), then the port comes back and stays. Reflash
            and confirm it repeats without touching the cable.
      - [ ] ≥2h parked on a host: hourly ring keeps filling, NTP resyncs on
            schedule, no TWDT. Watch for one benign extra wake on the first
            real sleep after a long window (a latched LP wake request); log it
            either way.

Afterwards: update the shutdown thresholds in Thermometer.cpp if re-derived,
append the floor/refresh numbers to the docs/notes.md power logbook, and file
any part swaps (D2, crystal variant) as rev B candidates.
