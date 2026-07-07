# thermometer-c6 — next phase: PCB layout → JLCPCB order

Self-contained instructions for a FRESH session (no prior conversation
context needed).

## 0. What this is / current state

Custom ESP32-C6-MINI-1 e-paper thermometer board in
`hardware/thermometer-c6/` — replaces the XIAO/FireBeetle dev-board rigs.
1S LiPo + RT9080 LDO tree, P-FET-gated on-board Good-Display EPD booster
(solder-jumper RESE 0.47/2.2/3Ω and L 10µH/47µH), universal 24-pin 0.5mm
FPC for all six owned panels, MCP73831 charger with load-sharing USB-C,
reverse-battery FET, high-side-switched battery divider, BMP581 with
BMP585 alternate footprint (populate exactly one), 32.768kHz crystal,
PPK2 series-measurement break. Design rationale, ESP32-C6 pin map, jumper
tables and bench procedures: **read `README.md` first**. Extra background:
memory file `project_custom_board.md`, expert-review outcomes in git log
(`d842fee`, `f25903e`).

**Schematic + BOM phase is DONE and verified**: `make check` green = ERC
zero violations at all severities, exported netlist exactly matches
`generator/circuit.py` (named + anonymous `~` nets), 50 hand-written
invariants, footprints resolve, zero label-over-wire/body overlaps
(build-fatal), zero wire crossings, zone frames auto-fit.

How this project works (do not break it):
- The `.kicad_sch` is GENERATED. Single source of truth =
  `generator/circuit.py` (components/nets/NC/LCSC) + `generator/layout.py`
  (schematic placement, wires, labels, power symbols, PWR_FLAG anchors).
  Never hand-edit the `.kicad_sch`. After any change: `make check`.
- Schematic changes → also update `verify/invariants.py` when intent
  changes, and README tables.
- Per-zone visual review recipe (200 DPI crops from the PDF):
  `make pdf`, then for a zone with origin (ox,oy) and size (w,h) from
  layout.ZONES:
  `pdftoppm -r 200 -png -x $((int((ox-10)*7.874))) -y ... -W ... -H ...
  out/thermometer-c6.pdf zone` (scale = 200/25.4 px/mm); Read the PNG,
  fix in layout.py, regenerate. Iterate until clean.
- Commits: directly on master, imperative present tense, no prefixes.

Decisions already made by the user (do not re-ask): indoor-only charging
0–45°C (goes on silkscreen), BMP581/585 populate-exactly-one, JP5 10µH
default / JP6 47µH (pair with JP3 2.2Ω for GDEH0576T81), 100mA charge
current, ~400–500mAh pouch, target fab JLCPCB with economy assembly.

Deliverables this phase: `thermometer-c6.kicad_pcb`, JLCPCB fab zip
(gerbers+drill), assembly BOM + CPL CSVs, updated README + this file.

## 1. Pre-layout tasks

1. **Draw the XUNPU FPC-05FB-24PH20 footprint** (`local.pretty/`) from the
   XUNPU drawing (LCSC C2856831 datasheet). The schematic currently points
   at the Hirose FH12-24S footprint as a stand-in — pinout identical,
   mechanicals differ. Verify contact orientation supports top/dual contact
   (DESPI-C02 spec §4.5) and pin-1 direction against a physical panel cable.
2. **Decide board outline** — suggest ~45×35mm 2-layer, 1.6mm, ENIG or HASL:
   fit ESP32-C6-MINI-1 antenna overhang on one short edge, FPC + jumpers on
   the opposite edge, USB-C on a long edge. 2× M2 mounting holes minimum.
   Check the MINI-1 antenna keep-out (Espressif HDG: antenna section
   overhangs or has ≥15mm keep-out, no copper any layer under antenna).
3. **Layout approach**: do the PCB interactively in KiCad (Update PCB from
   Schematic). Scripting placement like the schematic is possible via the
   pcbnew API but not worth it for a one-off — keep determinism at the
   schematic/netlist level and gate the PCB with DRC + the checklists below.
   Add to Makefile: `kicad-cli pcb drc --exit-code-violations` and
   `kicad-cli pcb export gerbers/drill/pos`.

## 2. Placement plan (blocks map ~1:1 to schematic zones)

- **EPD booster (zone G) — the only genuinely sensitive block.**
  Boost switching loop (L1/L2 → Q3 drain, Q3 source → RESE legs → GND →
  back to EPD_VCC caps) as tight as possible; C16 pump cap adjacent to the
  switch node; D4/D5/D6 short. RESE legs: the three resistors + jumpers
  right at Q3's source with a short, wide, shared GND return — RESE is a
  current-sense node (keep the jumper copper wide; joint mΩ vs 0.47Ω).
  Storage caps (C17/C18, panel caps) near the FPC pins they serve.
- **FPC connector**: panel caps (C19–C25) directly behind their pins;
  PREVGH/PREVGL are ±20V-class — 0.3mm+ clearance from logic.
- **BMP58x**: both footprints side by side, away from the LDO/charger heat
  (opposite corner from USB), per datasheets: **no vias/traces/mask under
  either sensor**, no copper pour beneath, slot or edge placement helps
  thermal fidelity; BMP585's Ø2.2mm port must map to an enclosure opening.
- **Battery/power (zones A/B/C)**: JST + Q6 + JP1/J2 grouped at board edge;
  MEAS jumper/header accessible with the board mounted. LDO input caps at
  VIN pin; 22µF close. Charger + USB-C grouped; USBLC6 next to the
  connector, D± as a matched-ish short pair (USB FS is forgiving).
- **Divider (zone I)**: 100k/100k + FETs near the ADC pin side of the
  module; keep the sense node short (it is 50k Thevenin).
- **Crystal**: FC-135 + caps tight to GPIO0/1 corner of the module, ground
  guard, away from SPI lines.
- **Test points/jumpers all on ONE face** (probing convenience), TP labels
  on silk.

## 3. Routing rules

- 2 layers: top = components + signal, bottom = as-unbroken-as-possible GND
  pour stitched with vias; pour top where free.
- Power widths: VBAT/VSYS/3V3/EPD_VCC ≥ 0.5mm (465mA bursts); booster
  switch node short and modest width (voltage node); RESE return wide.
- EPD SPI: plain 0.25mm, keep away from the booster loop and antenna.
- LP I2C (GPIO6/7): short, away from switching nodes.
- USB D±: short pair, no stubs, reference plane under.
- No traces under the MINI-1 antenna region, either layer.

## 4. Silkscreen (required text)

- "CHARGE INDOORS ONLY 0–45°C" near USB-C.
- Battery polarity + at JST (verify against the user's pigtails!).
- Jumper tables abbreviated: JP2 0.47R / JP3 2.2R / JP4 3R "bridge ONE";
  JP5 10µH / JP6 47µH "bridge ONE"; "JP6+JP3 for 5.76in T81".
- J2 = PPK2 (wick JP1); J5 pinout labels; TP names; U5/U6 "fit ONE".
- GIT hash / rev + board name.

## 5. Ordering (JLCPCB)

- `kicad-cli pcb export gerbers` + `drill` → zip; `pos` → CPL (map KiCad
  side/rotation quirks; JLCPCB rotation fixes usually needed for SOT-23-5,
  USB-C, FPC — check their preview).
- BOM: `bom/thermometer-c6-bom.csv` is assembly-ready (Comment, Designator,
  Footprint, LCSC). DNP list stays off the BOM by construction. Re-verify
  stock at order time: ESP32-C6-MINI-1-N4 (~1.7k), Si1308EDL (~1.4k, fall
  back to Si1304BDL clone C7419947), 10k C25744 (was transiently 0 — alt
  C60490), BMP581 C5362283 (out of stock → consign or populate U6 BMP585
  C18184976 instead).
- Economy PCBA is top-side only — placement must keep all assembled parts
  on top (TPs/jumpers are copper-only, headers DNP, fine on either face).

## 6. First-article bench checklist (PPK2)

1. Smoke: bench-supply via J2 (VBAT side), current-limited 50mA, no panel.
2. Sleep floor vs the 15.5–19µA dev-rig baselines; hunt surprises (SS14
   reverse leakage at temperature — swap to PMEG6010 class if hot floor
   drifts; MCP73831 BAT leakage).
3. EPD_VCC ramp with soft-start (R24/C28): scope for rail dip at gate-on;
   panel refresh energy vs DESPI numbers, both RESE/L configs.
4. 32k crystal: confirm oscillation + cold start (freezer test); populate
   R9 10M only if marginal; consider 7pF FC-135 variant if batch-marginal.
5. VBAT_ADC accuracy vs DMM across 3.3–4.2V; decide C29 populate; re-derive
   the firmware shutdown threshold (~3.4–3.5V; 3700mV is a buck-era number).
6. USB: enumerate, charge at 100mA, VBUS_SENSE reads, load-share handover
   (plug/unplug scope on VSYS), no-battery USB operation incl. refresh.
7. Reverse-battery test on a sacrificial JST pigtail (it should just block).

## 7. Firmware follow-ups (tracked, not this phase)

- New board define: pins per README map (EPD 18–23, gate 14, LED 15,
  divider 2/3, VBUS sense 4, 32k crystal sdkconfig, BMP58x INT config
  int_en=1/int_od=0/drv=0).
- **Implement `read_battery_level()`** — highest-priority firmware item;
  whole low-battery strategy currently stubs to 4321.
- Gate refreshes below ~0°C (panel spec) using BMP58x temperature; refuse
  charge-OK indication below 0°C; ignore VBAT_ADC while VBUS present.
