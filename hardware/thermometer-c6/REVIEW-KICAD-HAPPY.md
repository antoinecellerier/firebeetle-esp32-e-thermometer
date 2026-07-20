# thermometer-c6 Design Review (kicad-happy)

> Newest review first. **Run 2 (2026-07-20)** re-ran the full suite at commit
> `e567982` after the J3/J4 respin. The original pre-order review (**Run 1**,
> 2026-07-17) is preserved unchanged below.

---

# Run 2 — Incremental Respin Review (2026-07-20)

**Commit:** `e567982` (clean tree, verified) · **Tool:** kicad-happy @ `f765dc0`
(identical to Run 1 — not updated, so results are directly comparable) · **Run
dir:** `out/kicad-happy/2026-07-20_0355` (gitignored) · **Prior run diffed
against:** `2026-07-17_1727` (d609762/7b587b7).

**What changed since Run 1** (per the task brief and confirmed from git):
J4 FPC re-placed 180° mouth-east + 24-pin fanout rerouted (77c3ebd, d17b6bb);
J3 USB-C re-placed 180° mouth-north at the edge + USB/collateral rerouted
(e22be63, 26cebbc, c8009ec); 9 testpoints + D1/R4/R17/R1/R2 moved, GND
re-stitched, 12 silk labels relocated; scoped waivers `edge-clearance-usb-c`
(J3) and `footer-silk-j3` in `.kicad_dru`. Also folded in are the Run-1
post-review fixes, now committed to source (were applied at e6828d8 *after*
Run 1's analyzed sources): 9× 4.7µF caps 25V→50V (C1779→**C98192**), D7
`D_TVS`→`D_Zener` (unidirectional), D3 green→**white C2290** (basic part).

## Analyzers re-run (fresh at e567982)

Full suite, same invocation style as Run 1. Gerbers were exported straight from
the committed board (`kicad-cli pcb export gerbers/drill`, JLC layer set) because
`make fab` is currently blocked (see Process finding) — extents/layers reflect
e567982.

| Analyzer | Result | Δ vs Run 1 |
|---|---|---|
| analyze_schematic.py | 63 findings, 0 error* | PD-DET 2→1, VD-004 2→3 (both from the D7/cap value swaps) |
| analyze_pcb.py --full | 182 findings | KO-001 27→22, VP-001 46→67, CP-003 8→10, PM-002 13→12, TB-001 22→21 |
| analyze_gerbers.py | 1 finding (GR-004) | unchanged; board 48.1×35.1mm unchanged |
| cross_analysis.py | 3 findings | PS-002 4→3 |
| analyze_emc.py | 42 findings, 8 error | ES-002 error→info, RP-001 err 2→3, GP-001 err net CC1→CC2 (total errors still 8) |
| analyze_thermal.py | 0 findings | unchanged |
| simulate_subcircuits.py (200 MC + parasitics) | 13 subcircuits: 11 pass / 1 warn / 1 skip | 14→13 (D7 protection-device sim dropped — D7 is now a Zener) |
| lifecycle_audit.py | 0 (LCSC-only, no MPN) | unchanged |

\* `SS-001` (MPN coverage) is reported error-severity but overridden in Run 1
(LCSC codes are the JLC sourcing identity). Structural parity holds: 101
footprints / 76 nets both runs (vias 194→158 — fewer after the fanout +
testpoint simplification).

## Independent gate cross-checks (project's own tooling)

- **Raw kicad-cli DRC on the committed board:** 2 violations, both
  `copper_edge_clearance` on J3 SH shell pads; 0 unconnected, 0 schematic
  parity. `verify/drc_summary.py --gate` → **REAL=0 DEFERRED=0 WAIVED=2** (pass).
- **`verify/gnd_islands.py`:** GND connected = **True** (6 single-via + 3
  narrow-neck SPOF ties — pre-existing reliability characteristics of a dense
  2-layer board, not disconnections).
- **J3/J4 edge geometry measured directly (pcbnew):** J4 pads sit **2.45mm
  inside** the east edge — only its courtyard clearance ring laps 0.245mm
  (this is the new PM-002 "error"). J3's SH shell pads lap the north edge by
  **0.055mm** — the known WAIVED edge-launch USB-C case. No pad/copper of either
  connector sits off-board beyond the waived J3 shell.

## Findings & dispositions (Run 2)

Every finding maps to a Run-1 disposition or is a direct, expected consequence
of a previously-recommended fix. **No new REAL board defect.**

| Finding | Location | Sev | Disposition |
|---|---|---|---|
| PM-002 J4 courtyard overhangs edge 0.245mm (was warning, now error) | J4 east edge | error | **Cosmetic/by-design** — pads 2.45mm inside edge; only courtyard ring laps. Edge-launch FPC mouth faces off-board east, same class as J5/SW1/SW2/J1 (Run-1 accepted) |
| KO-001 D4/JP2/JP3/TP6 (+others) "inside fpc-fanout" (27→22) | fpc-fanout marker | error | **False positive** (Run-1) — tool ignores KiCad per-type allow flags; marker allows everything; DRC clean |
| VP-001 untented via-in-pad 46→67 | J3/J4 reroute + GND stitch | warning | **Waived** (Run-1) — POFV selected at order time |
| EMC RP-001 EPD_SCK now error-tier (32k nets still error) | EPD_SCK layer transition | error | **Accepted** (Run-1 2-layer EMC bucket) — write-only SPI clock, active only during infrequent EPD refresh; 8 total EMC errors unchanged |
| EMC GP-001 significant plane gap moved J3-CC1→J3-CC2 | J3 CC line | error | **False positive** (Run-1) — CC is a DC config line (5.1k Rd), no return current |
| cross PS-002 plane-split island churn (GND 8 / VBAT 4 / VBUS_SENSE 3) | pours | warning | **Watch item** (Run-1) — routing-channel islands; DRC connectivity + gnd_islands pass |
| CP-003 touch-pad "0.0mm GND clearance" +TP4/TP11 (now all 11 TPs) | testpoints | info | **False positive** — heuristic measures to zone *outline*, not the DRC clearance carve-out; DRC clean, no short (incl. TP4=+3V3, TP11=VBAT_ADC) |
| schematic VD-004 "C5 4.7µF/50V over-designed for VBUS" | C5 | info | **Cosmetic/expected** — direct result of the Run-1-recommended 25V→50V upgrade (one BOM line C98192) |
| GR-004 bottom paste 2%; CK-003 EPD_SCK near J3/J4; SP-WARN C29 | — | warn/info | **Unchanged** Run-1 dispositions (DNP provisions / accepted / C29 is an ADC sampling cap misclassified) |

## Deltas vs Run 1

**Fixed / improved**
- **PM-002 R4 edge violation (error) GONE** — R4 moved off the edge; Run-1's
  residual "V-cut/tab stress on R4" risk is resolved. TB-001 R4 tombstoning
  also dropped.
- **EMC ES-002 U3 "no ground via near ESD device" error → info** ("single
  ground via near U3") — the GND re-stitch added a GND via by U3, effectively
  addressing Run-1's "spare via next to U3.2 nice-to-have."
- **Run-1 post-review schematic fixes now in committed source** (50V caps, D7
  unidirectional Zener, D3 white basic) — the PD-DET 2→1, VD-004 +1 (C5),
  and SPICE 14→13 (D7 no longer a protection-device sim) deltas are all
  direct, expected consequences of these approved changes, not regressions.

**New (all triaged non-blocking)** — PM-002 J4 courtyard overhang (error,
by-design), VP-001 +21 (POFV waived), KO-001 recomposition (FP), RP-001 EPD_SCK
error-tier (accepted 2-layer), GP-001 CC1→CC2 (FP), PS-002 island churn (watch),
CP-003 +TP4/TP11 (FP), VD-004 C5 (expected). See table.

**Unchanged** — GR-004, CK-003, SS-001 override, SP-WARN C29, and the entire
Run-1 datasheet/pinout Deep Review layer (not re-executed — `datasheets/` is
gitignored and vendor-PDF-gated; it remains valid because netlist connectivity
is unchanged at 101/76 parity and the only source changes are the three
Run-1-recommended value swaps).

## Process / tooling finding (not a board defect)

**`make fab` is blocked at e567982.** Its `drc` prerequisite runs raw
`kicad-cli pcb drc` (no J3 waiver) and halts on the 2 J3 `copper_edge_clearance`
violations that the project's own `verify/drc_summary.py --gate` correctly
WAIVES (edge-launch USB-C). Because J3 was moved onto the north edge in this
respin, its SH shell pads now geometrically cross Edge.Cuts — a condition a
0mm `edge-clearance-usb-c` DRU min cannot suppress (copper-crossing-outline is
geometric, not a threshold). Consequence: the on-disk orderable fab package
`out/fab/thermometer-c6-gerbers-9100758-2026-07-18.zip` is **stale** (pre-respin,
commit 9100758) and cannot be regenerated via `make fab` as-is. The board itself
is gate-clean (REAL=0); this is a fab-export tooling gap, not a layout error.
*Fix (user's call, outside this review's edit scope): route the `fab` target's
DRC gate through `drc_summary.py --gate`, or add the 2 J3 shell-pad violations
as DRC exclusions in `thermometer-c6.kicad_pro`.*

## Run 2 verdict

**No new board defect; the respin is clean and, on the changed axes, better than
Run 1** (R4 off-edge, U3 ESD ground via added, J3/J4 fanouts simplified to fewer
vias). All new/changed analyzer findings resolve to existing Run-1 dispositions
or to expected consequences of the three already-approved value swaps. The board
gate (`drc_summary --gate` REAL=0, gnd_islands connected, 101/76 parity) passes.
The one actionable item is the **`make fab` gate blockage** above — a build-tool
gap that must be closed before a fresh e567982 fab package can be exported for
ordering.

---

# Run 1 — Pre-Order Review (2026-07-17)

**Project:** hardware/thermometer-c6 (KiCad 10, single sheet, 2-layer 48×35mm PCB)
**Date:** 2026-07-17 (run `2026-07-17_1727`, sources at git d609762/7b587b7)
**Tool:** [kicad-happy](https://github.com/aklofas/kicad-happy) @ f765dc0
**Analyzers run:** analyze_schematic.py, analyze_pcb.py --full, analyze_gerbers.py (out/fab/gerbers), cross_analysis.py, analyze_emc.py, analyze_thermal.py, simulate_subcircuits.py (ngspice, +PCB parasitics, 200-run Monte Carlo), lifecycle_audit.py (LCSC), Deep Review pass (72 findings, deep_review_gate.py: **72 verified, 7 partial, 0 quarantined**). Raw analyzer JSON: `out/kicad-happy/` (gitignored).

## Overview

Battery-powered ESP32-C6-MINI-1 e-paper thermometer: 1S LiPo + MCP73831 USB-C charger with Q1/D2 load-sharing power path and Q6 reverse-battery P-FET, RT9080-33 always-on LDO, BMP581/BMP585 populate-one barometer pair on LP-I2C, SSD1677-style gate-driver boost (Si1308EDL + jumper-selected L/RESE) behind a default-off P-FET gate, 24-pin FPC to a GDEH0576T81 panel. Deep-sleep product (~µA floor target); JLCPCB economy assembly, ENIG, POFV.

This review is the last outside-opinion gate before ordering. It complements the project's own `verify/` suite (geometry/netlist/DFM) with datasheet-driven verification: every IC, transistor, diode and connector pinout was checked against manufacturer PDFs (saved in `datasheets/`, gitignored), not KiCad symbols.

## Critical Findings

No CRITICAL (board-killing) issues found. All pinouts, polarities, straps, and the power tree verify against manufacturer datasheets at both schematic and PCB pad level.

Warnings (none blocks ordering). **Status added post-review** — ✅ = fixed in-place or already covered, ○ = open first-article/bring-up item:

| Status | Issue | Section |
|--------|-------|---------|
| ✅ FIXED (e6828d8) | 4.7µF/25V on the ~22–24V VGH/PREVGH booster rails DC-bias-derates to ~1–2µF (C17/PREVGH tightest, ~88% of rating). All nine 4.7µF caps swapped to a 50V X5R part (Samsung CL21A475KBQNNNE, C98192) — same 0805 pads, one BOM line, real margin | PCB / Deep Review |
| ✅ FIXED (e6828d8) | D7 (unidirectional SMF5.0A) sat on the bidirectional `D_TVS` symbol — polarity implicit for a hand-solder DNP part. Symbol changed to `Device:D_Zener`; schematic now shows cathode→VBUS explicitly, pin/net mapping unchanged | Deep Review |
| ✅ COVERED | U5/U6 populate-exactly-one (both answer at I²C 0x47; double-stuffing corrupts reads). Guard already exists — B.SilkS info block reads "Sensor: fit one only / U5 BMP581/U6 BMP585" (pcb_layout.py:511) plus BOM DNP flags; the reviewer missed the silk | Deep Review |
| ○ OPEN (first-article) | Booster ships JP2+JP5 (0.47Ω/10µH) but SSD1677/GDEH0576T81 app circuit wants 2.2Ω/47µH (=JP3+JP6). Deliberate DESPI-proven universal config — verify VGH reaches spec; JP3+JP6 is the on-board fallback | Deep Review |
| ○ OPEN (first power-up) | FPC pin-1 orientation verified only against SSD1677/DESPI-C02 transcription (Good Display gates the panel PDF). A mirrored cable puts −20V on logic pins — continuity-check pad1→panel pin1 before first power-up | Deep Review |
| ○ OPEN (bring-up) | RT9080 dropout margin is thin during the ~465mA EPD refresh peak if low-battery shutdown is ever lowered to 3.4–3.5V; keep ≥3.6V or measure refresh-peak VOUT | Deep Review |
| ○ OPEN (first-article) | FC-135 ESR spec (70kΩ) sits exactly at Espressif's 32k max; near-zero cold-start margin on the C6's low-gm oscillator. Mitigations already designed in: R9 10MΩ DNP provision, planned cold-start test | Deep Review |
| ○ OPEN (bring-up) | D2 SS14 reverse leakage grows steeply with temperature and lands on the sleep floor via the 66k VBUS pulldowns — measure warm floor; PMEG6010-class swap is the fallback (no SMA drop-in exists, so left in place) | Deep Review |
| ○ DEFERRED (BMP585 variant) | GND/SDA vias + a trace run under the U6 BMP585 land (violates Bosch "no vias under sensor") — harmless while U6 is DNP; fix before ever building the BMP585 variant | Deep Review |

Documentation staleness: ✅ FIXED (e6828d8) — README "Open item #3" now records Q6 reverse protection as fitted, and the sensor/BOM text reflects the restocked BMP581 (3,675 units) with U5 populated by default.

## Component Summary

101 components, 100% SMD (2 THT are the switch/connector pins' mounting only): 29 C, 24 R, 6 IC, 6 Q, 5 connectors, 6 solder jumpers, 11 test points, 2 LED, 5 D, 2 SW, 1 Y, 2 L, 2 mounting holes. 76 nets, single sheet. DNP provisions: D7 (VBUS TVS), R9 (32k bias), U6 (BMP585), plus open jumper variants.

Sourcing: 0/37 unique parts carry an `MPN` property; all 35 orderable line items carry LCSC codes (the assembly service's sourcing identity — see False Positives for the analyzer's SS-001 blocker). A per-code stock sweep at review time found **all 35 in stock**; thinnest: R14 0.47Ω (559), Si1308EDL (2,652), MCP73831 (2,727), ESP32-C6-MINI-1-N4 (3,344), BMP581 (3,675). Suggestion: embed the sweep's MPNs into `generator/circuit.py` properties so future tooling (and this analyzer) can verify parts without the side-channel.

## Power Tree

```
USB-C J3 VBUS ──D7 SMF5.0A (TVS, DNP)──┐
  │                                     │
  ├─ R22/R23 100k+100k → VBUS_SENSE (IO4)
  ├─ U4 MCP73831-2ACI (100mA via R3 10k; STAT→D1 LED) → VBAT ── J1 JST-PH ←Q6 AO3401A (rev-prot, G=GND)
  │                                                      ├─ R18 100k ↑, Q4 AO3401A ←Q5 2N7002 ←VDIV_EN (IO3)
  │                                                      │    └→ R20/R21 100k+100k → VBAT_ADC (IO2) + C29 10n
  ├─ D2 SS14 ──→ VSYS ←── Q1 AO3401A (G=VBUS: off on USB, on on battery) ── VBAT
  │             │
  │             └─ U2 RT9080-33 LDO (EN=VIN, always on; C1/C2 in, C3/C4 out) → +3V3
  │                  ├─ U1 ESP32-C6-MINI-1, U5 BMP581 (U6 BMP585 DNP), pull-ups
  │                  └─ Q2 AO3401A (G←R24/C28 soft-start ←IO14, R12 pull-off) → EPD_VCC
  │                       ├─ J4.15/16 (panel VCI/VDD), R17 pull-up for EPD_RST
  │                       └─ L1 10µH (JP5, bridged) / L2 47µH (JP6) → EPD_SW
  │                            Q3 Si1308EDL (G=EPD_GDR←panel, S=RESE R14 0.47Ω via JP2 bridged)
  │                            D4→EPD_PREVGH(+~22V), C16/D5/D6 pump→EPD_PREVGL(−~20V)
```

All regulator/charger output voltages datasheet-verified (`vref_source` equivalents: MCP73831-2 = 4.20V float, RT9080-33 = 3.3V fixed). Every rail has a declared source; the two RS-001 "sourceless" nets (VBAT_ADC, VBUS_SENSE) are divider sense taps — expected.

## Analyzer Verification

- **Component count**: 101 (schematic, excl. power symbols) = 101 PCB footprints = 101 raw-file `(symbol` blocks. Match.
- **Board outline**: 48.0×35.0mm (PCB) vs 48.1×35.1mm (gerber extents incl. edge stroke). Match.
- **Pinout verification**: all 6 ICs, 6 transistors, 5 diodes, both LEDs, J1/J3/J4/J5, Y1, and both sensors verified **Datasheet-verified** at schematic AND `pad_nets` level (see Deep Review; PDFs in `datasheets/`, page-cited quotes machine-checked by `deep_review_gate.py`). Custom `local.pretty` footprints (sensors, FPC) got priority — no pad-numbering transpositions found. Two **partial** verifications: TYPE-C-31-M-12 (standard Type-C pinout + analyzer usb_compliance pass; vendor PDF unfetchable) and the GDEH0576T81 FPC table (via SSD1677 controller datasheet + DESPI-C02 reference, panel PDF gated — hence the pin-1 warning above).
- **Net tracing**: VBUS→VSYS→+3V3, VBAT charge/discharge paths, EPD boost loop, I²C, USB, and battery-divider gate traced end-to-end (nets dict + raw .kicad_sch spot checks). No gaps.
- **Pinout ambiguity**: none open — every SOT-23 device has an LCSC-pinned MPN and was datasheet-checked (AO3401A ×4: 1=G 2=S 3=D; 2N7002: 1=G 2=S 3=D; Si1308EDL SC-70).

### Gerber Verification

9/9 expected layers found, PTH+NPTH drills present, layers aligned, outline closed. GR-004 (B-paste 4 flashes vs 225 copper pads) is the two DNP bottom-side provisions D7/R9 — expected, no bottom stencil needed.

## Deep Review

72 evidence-linked findings in `out/kicad-happy/deep_review.json` — 63 info (positive verifications + triage), 9 warnings (tabled above), 0 errors. Gate: 72 verified (7 partial where a vendor PDF was unfetchable), 0 quarantined. Highlights by subsystem:

- **Power/charging** (20): MCP73831 pinout/variant/PROG=100mA/caps verified; PU-001 on STAT is a false positive (D1+R4 LED is the datasheet STAT load, ~3mA ≪ 25mA sink). Q1/D2 load-sharing and Q6 reverse-protection topologies verified state-by-state (Vgs in-range both states; reversed cell contained at J1/Q6.3). RT9080 caps/EN/NC verified; TP4 probe-only rule confirmed from abs-max VOUT−VIN=+0.3V + 80Ω discharge. Charger sleep drain ≤2µA max (IDISCHARGE).
- **MCU/clocking** (16): all 53 module pins match Espressif Table 3-1 (incl. IO0/IO1=32k crystal, IO12/13=USB D∓, IO6/7=LP-I2C, TXD0/RXD0→J5). EN RC (R6 10k + C9 1µF) is verbatim the datasheet recommendation; BOOT strap correct; other straps don't-care. 20pF load caps exact for FC-135 CL=12.5pF. J5 header GND-first, no VBAT, BOOT unexposed — settled-decision compliant. "U1 thermal vias 0/5" triaged: optional module EPAD, <100mW application.
- **Sensors/I²C** (16): BMP581 (10-pin) and BMP585 (9-pin) pad maps each match their own datasheet; CSB/SDO straps → I²C addr 0x47 both (datasheet-quoted); 4.7k pull-ups → ~100ns rise on the 25–29mm 2-device bus; INT push-pull → PU-001 false positive; ports unobstructed; BMP585's optional 10Ω VDD resistor correctly omitted. C13 (U5's second 100nF) sits 7.9mm away near U6 — C12 at 1.8mm is the effective local cap; acceptable.
- **EPD/boost** (20): all 24 J4 pins map to the SSD1677 function table; boost + inverting charge pump orientations verified from the netlist; Si1308EDL and MBR0530 at ~73–80% of Vds/Vrrm ratings (no diode sees the full 40V swing); EPD gating default-OFF through reset/boot (R12 pull-to-source) with R24/C28 soft-start (the SPICE "C29 decoupling warn" was a misclassified sampling cap; R24/C28 is this soft-start RC); 0.3mm HV clearance OK *coated* per IPC-2221B (soldermask is load-bearing — note for any future mask-less rework near J4); EPD_VCC 0.5mm width OK for 465mA; the 4.7µF/25V caps on the ~22–24V rails (C17/PREVGH tightest) were **upgraded to 50V (C98192) in e6828d8**, replacing the ~1–2µF-effective derated originals with real margin.

## Signal Analysis Review

- **Voltage dividers**: R20/R21 (VBAT_ADC, ÷2, gated by Q4/Q5, off by default incl. during boot) and R22/R23 (VBUS_SENSE, ÷2, drains only when USB present). Both SPICE-confirmed ratio 0.5, 0.0% error.
- **RC filters**: R24/C28 = 1.59kHz (EPD gate soft-start), R6/C9 = 15.9Hz (EN reset delay) — SPICE-confirmed <0.3% error.
- **Crystal**: FC-135 32.768kHz, CL 12.5pF with 20pF+20pF+~2.5pF stray — exact; see ESR-margin warning.
- **Transistor circuits**: Q3 boost switch, Q5 level-shifter SPICE-pass; Q6 skip (reverse-protection topology unsupported by the generic testbench — verified manually instead, see Deep Review).
- **Protection**: D7 TVS provision on VBUS (standoff 5V correct; worst-case clamp 9.2V vs MCP73831 abs-max 7V only at full rated surge, USBLC6 co-clamps — acceptable); USBLC6 flow-through verified not crossed.
- **LED circuits**: D1 CHG ~3mA (VBUS−Vf−Vol)/1k; D3 STATUS ~30µA-class via 100k on GPIO — intentionally dim/low-power.
- **Simulation Verification**: ngspice 14 subcircuits: 12 pass, 1 warn (C29 — misclassification, see above), 1 skip (Q6). 200-run Monte Carlo: no concerns. PCB parasitics extracted from the --full PCB JSON and applied.
- **Decoupling Analysis**: +3V3: 2×10µF + 4×100nF (closest 1.65mm to U1); VSYS 32µF; VBUS 4.7µF; EPD rails per app circuit. U3 (ESD IC) closest bypass 2.19mm — within the ≤3mm guideline.

## Power Analysis

### Power Budget
+3V3 worst-case ~243mA estimate vs RT9080 600mA — fine; the real peak (465mA EPD refresh) is the dropout-margin warning above.

### PDN Impedance
Analyzer profile unremarkable for a 2-rail LDO design; +3V3 z_min 15mΩ (SPICE), no dangerous anti-resonance flagged.

### Power Sequencing
Single LDO always-on; EPD_VCC gated by IO14 with pull-off default — no EN/PG chain to mis-order.

### Sleep Current Audit
Analyzer worst-case 3.26mA / "realistic" 2.49mA is a **false positive for battery operation**: 3.08mA of it is VBUS-rail paths that exist only while USB is plugged (R5/R22 dividers, LEDs), and the +3V3 "2.39mA" line is a module-active heuristic, not deep-sleep Iq. On battery the audited always-on paths are: RT9080 Iq (~2µA), charger IDISCHARGE (≤2µA max), D2 reverse leakage (temperature-dependent — warning above), Q4-gated divider 0µA. Consistent with the ~16µA-class floors measured on the firmware's C6 rig.

### Inrush Analysis
SPICE-verified 0.136A estimated inrush into the 3V3 bank, settles at 3.3V (0.0% error); battery/JST source impedance limits hot-plug dI/dt; no IC supply-pin abs-max concerns at 101-component scale.

### Voltage Derating
1µF/50V on HV pump nodes — ample; the 4.7µF caps on the 22–24V VGH/PREVGH rails were upgraded 25V→50V (C98192, e6828d8) — see PCB section; 25V parts elsewhere on ≤5V rails — ample.

## PCB Layout Analysis

- **Board**: 2-layer 48×35×1.6mm, 948 track segments, 194 vias (69 GND stitching), 7 zones. Routing 100% complete.
- **DFM**: "advanced" tier trigger is the 0.1mm via annular ring (0.5/0.3 vias) — authored intent, within JLC capability (≥0.45mm pad on 0.3mm drill); the fab already passed full-severity kicad-cli DRC + `check_fab.py` (55 assertions). 1 violation count = same annular metric (DFM-001/002).
- **Placement/edge**: side-actuated SW1/SW2 (TS-1187A) at 0.1mm and J1/J3/H1 edge-mount overhangs are by design; J5 courtyard overhang 0.37mm (header at edge for probe access) and C24 0.42mm / R4 0.17mm body-to-edge pass KiCad's 0.3mm copper-to-edge rule — accepted with eyes open (V-cut/tab stress on R4 is the residual risk; board is routed outline, not V-scored).
- **Via-in-pad**: 46 untented instances — POFV (epoxy filled & capped) is selected at order time per ORDERING.md, which supersedes tenting. VP-001 waived.
- **Copper presence / antenna**: U5/U6 sensor keepouts correctly restrict pour only (thermal isolation); antenna + antenna-margin rule areas enforce the RF keep-out as DRC rules (5.3mm no-copper + margin band — short of Espressif's 15mm ideal, the 48mm board's best compromise; reduced RF range accepted for a brief-connect deep-sleep product). No stray copper found in either.

### Thermal Analysis
analyze_thermal.py: 0 findings — no component dissipates enough to matter (charger worst 0.2W transient, computed die ~91°C at 45°C ambient worst-case, within limits). TV-001 "U1 0/5 thermal vias" triaged (optional module EPAD, <100mW application).

## EMC / Cross-Domain Analysis

42 EMC findings, 8 "error"-severity — all triaged, none blocking for this unshielded low-duty IoT class:

- **RP-001 stitching** (21+ nets): 2-layer board with B.Cu GND pour; signal vias average 1.2–3.5mm from the nearest of 69 GND vias rather than the tool's 1.0mm ideal. The two "errors" (XTAL_32K_P/N) are 32.768kHz nets — negligible dI/dt; accepted.
- **DP-003 USB layer changes** (4): USB-FS only; total D+ path 29.0mm vs D− 29.1mm (Δ0.1mm ≪ ±25mm FS tolerance). Accepted.
- **GP-001 CC1 62% plane coverage**: CC is a DC configuration line (5.1k Rd) — no return-current issue. False positive.
- **ES-002 U3 no adjacent GND via**: U3's GND pad reaches the B.Cu pour through the F.Cu GND net; nearest GND via 3.14mm. Real but minor on this geometry — ESD strike energy also shunts via the USB-C shell (4 GND pads + SH). Accepted; a spare via next to U3.2 is a nice-to-have for a future spin.
- **PS-002 plane splits** (GND 8 islands / +3V3 9 / VBAT 5 / VBUS 5): island counts come from routing channels in the pours; the project's own `gnd_islands.py` audit governs here and the fab DRC passes connectivity. Watch item, not a defect.
- **GP-004 fill ratios** (B.Cu 35%, F.Cu 23%): consequence of a dense 48×35 2-layer board; same watch item.

## Schematic ↔ PCB Cross-Reference

Counts match (101/101); every IC/transistor/connector verified at pad_nets level (Deep Review); footprint properties match placed footprints; values/LCSC consistent between schematic and BOM/CPL. **DNP consistency**: D7/R9/U6 are DNP *with* routed provisions — intentional (bench-stuffable), excluded from BOM/CPL; jumper bridges JP2/JP5 present as copper, JP3/4/6 open — matches README defaults.

## Bus Topology

I²C: SDA/SCL (IO6/IO7, LP-I2C capable) + R10/R11 4.7k, devices U1+U5(+U6 provision), addr 0x47 — no conflict populated-one. SPI: EPD_SCK/MOSI/CS/DC to J4 (no MISO — write-only panel, BS1 strapped 4-wire). UART: TXD0/RXD0 to J5. USB: D+/D− through U3.

## USB Compliance

usb_compliance: all checks pass — CC1/CC2 independent 5.1k Rd (UFP), VBUS ESD (U3 pin5 + D7 provision), VBUS decoupling/capacitance in-window for a sink, ESD IC present on D±. Series resistors "info": C6 module integrates USB terminations — none needed externally.

## Quality & Manufacturing

### Assembly Complexity
Score 50/100 — 0402-dominant, SOT/LGA/FPC fine-pitch (0.3mm finest pad), single-side reflow + 2 optional hand-solder bottom provisions.

### Test Coverage
TE-001 "11%" is nominal-only: 11 test points cover every power rail (VBAT, VSYS via J2, +3V3, EPD_VCC, PREVGH/PREVGL), boost internals (GDR, RESE), battery sense, and GND ×2 — the nets a bring-up actually probes. Digital nets ride J4/J5. Adequate; accepted.

### BOM Optimization
35 orderable lines, healthy passive consolidation (100k ×7, 10k ×7, 100nF ×5, 4.7µF ×9). Nothing worth merging further.

### Component Lifecycle
LCSC-only audit gives no lifecycle status by construction (see Not Performed); the stock sweep in Component Summary stands in for order-time risk.

### Ordering Notes
2-layer, ENIG, POFV via covering, 1.6mm, JLC economy assembly (all settled in ORDERING.md); top-side stencil only; JLC order-number token authored on back silk; rotation checklist in `out/fab/rotation-checklist.md` still needs the human JLC-preview walk.

## False Positives / Reviewer Overrides

| Analyzer finding | Verdict |
|---|---|
| KO-001 ×27 "keepout violations" (vias/J4 in `fpc-fanout`, U5/U6 + vias in sensor areas) | **False positive** — tool ignores KiCad per-type allow flags; `fpc-fanout` allows everything (DRU marker area), sensor areas restrict pour only. kicad-cli full-severity DRC (which honors flags) passes |
| SS-001 "0/37 MPN, not pre-fab ready" | **Overridden** — LCSC codes are the sourcing identity for JLC economy assembly; all 35 lines stock-checked today. MPN back-fill recommended as hygiene, not a blocker |
| VP-001 ×46 untented via-in-pad | **Overridden** — POFV selected at order time |
| TV-001 ×9 U1 thermal vias | **False positive** — optional module EPAD, <100mW app |
| PU-001 ×3 (U4 STAT, U5/U6 INT) | **False positive** — STAT drives the LED load per datasheet; sensor INT is push-pull |
| Sleep audit 2.5–3.3mA | **False positive on battery** — VBUS-only paths + module-active heuristic; gated divider contributes 0 |
| SPICE warn C29 "inadequate decoupling" | **Misclassification** — ADC sampling cap on VBAT_ADC, not decoupling |
| GR-004 bottom paste 2% | **Expected** — D7/R9 DNP provisions |
| PM-002 edge "errors" (SW1/SW2/J5/C24/R4) | **Accepted by design** — side switches/edge header; C24/R4 pass the 0.3mm copper-edge rule |
| GP-001 CC1, DP-003 USB, RP-001 32k nets | **Accepted** — DC config line / FS USB Δ0.1mm / 32kHz |

## Not Performed / Review Limits

- **Lifecycle status** — LCSC exposes no lifecycle field (all "unknown" by construction); no DigiKey/Mouser/element14 API keys configured. Stock levels were verified instead.
- **GDEH0576T81 panel datasheet** — vendor-gated download; FPC pin table verified via the SSD1677 controller datasheet + DESPI-C02 reference design (hence the pin-1 orientation warning and 7 "partial" gate marks).
- **TYPE-C-31-M-12 vendor PDF** — unfetchable (distributor bot-wall); verified against the USB Type-C standard pinout + analyzer checks.
- **Previous review delta** — first kicad-happy run on this project; no prior manifest to diff. Future runs will auto-diff against `2026-07-17_1727`.
- **Datasheet extraction cache** — not built (PDF-direct verification used instead); `datasheets/*.pdf` retained locally, gitignored.

## Positive Findings

1. Zero pinout/polarity errors across 101 parts, including all four AO3401A orientations (each in a different circuit role) and both custom LGA sensor footprints.
2. Battery divider gating is exemplary: default-off through reset/boot via R18 pull-to-source, zero sleep drain, C29 sampling cap sized for the ADC.
3. EN reset RC matches Espressif's recommended 10k/1µF exactly; 32k load caps exact for CL=12.5pF.
4. EPD panel power is default-off with soft-start; the gated-rail EPD_RST pull-up (R17→EPD_VCC, not +3V3) avoids back-feeding an unpowered panel — a subtle bug class avoided.
5. USB D+/D− total-path matching within 0.1mm; ESD flow-through routing correct.
6. Every real keep-out (antenna, sensors) is a DRC-enforced rule area, not just an absence of copper.
7. Charge current (100mA), float (4.20V), and indoor 0–45°C gating all consistent with the cell-safety intent; charger's lack of battery-temp sensing is compensated by policy.

## Final verdict / readiness

**READY TO ORDER.** No critical findings; the fab package is internally consistent, datasheet-verified, and DRC/DFM-clean for the selected JLC options. Post-review the safe in-place fixes were applied and the package regenerated + re-gated (`make fab` at e6828d8, `check_fab` 55/55): 4.7µF caps upgraded to 50V, D7 symbol made unidirectional, README refreshed; the U5/U6 fit-one silk guard was confirmed already present. The remaining ○ items are all bring-up/first-article measurements, not board changes: FPC pin-1 continuity check, VGH-reaches-spec with JP2+JP5 (fallback JP3+JP6), cold-start the 32k crystal (R9 provision if marginal), warm-floor measurement (D2 leakage), and keep low-battery shutdown ≥3.6V pending the refresh-peak measurement. The only pre-order human step is the JLC upload-preview walk with `out/fab/rotation-checklist.md` against the e6828d8 zip.
