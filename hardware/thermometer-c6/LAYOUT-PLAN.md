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

**PCB phase (the milestones at the bottom of this file): M1–M4 done, M5
signal routing in progress.** The board is 48×35mm, 2-layer, DRC copper-clean.
Placement and hand-authored copper live in `generator/pcb_layout.py`; the rest
is autorouted into `generator/pcb_routes.py`. `make route` prints the current
unrouted terminals — that list is the M5 to-do, so read it rather than trust
any list written down here. The routing rules the router and DRC actually
enforce, the geometry traps, and the review tools are all in `CLAUDE.md`; read
that before touching copper.

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

Intent, not mechanism. The clearances DRC enforces (0.2mm netclass, not the
0.15 board minimum), the min-width DRU rules, the geometry traps and the
router's ordering semantics are in `CLAUDE.md` — that is the operative
reference, and it is loaded automatically.

- 2 layers: top = components + signal, bottom = as-unbroken-as-possible GND
  pour stitched with vias; pour top where free.
- Power widths: VBAT/VSYS/3V3/EPD_VCC ≥ 0.5mm (465mA bursts); booster
  switch node short and modest width (voltage node); RESE return wide.
- EPD SPI: plain 0.25mm, keep away from the booster loop and antenna.
- LP I2C (GPIO6/7): short, away from switching nodes.
- USB D±: short pair, no stubs, reference plane under.
- VBAT_ADC is a 50k Thevenin node: short, and away from the EPD HV nets and
  the switch node.
- No traces under the MINI-1 antenna region, either layer.

### M5: how U1 reaches J5 (measured against authored copper only)

Every debug signal (`DBG_TX/RX/IO5/IO8`, `VBUS_SENSE`) has to cross the board
from U1 to J5's authored via row, and only two B.Cu corridors can carry a
bundle. Widths below are free *centres* for a 0.25mm lane, from
`verify/occupancy.py`'s bitmaps; they move only when authored copper moves.

**North corridor — open, 5 lanes.** Walled north by `~SW_10U`'s 45° B.Cu
diagonal and south by `VBAT`'s B.Cu lane at y25.15. It tapers west-to-east as
it follows the diagonal: 8.25mm at x24.5, 3.90mm at x28.0, **2.55mm at its
x29.0 neck** (y22.30..24.85), then the pocket at x31+ opens to 14mm. Enter it
from the north around x22.5..24.75, never from the field.

**The field west of x22.6 is one lane, structurally.** `C14.1` can only be
entered by a via — `~BAT_IN`'s 0.5mm F.Cu lane runs along C14's north edge,
that lane's leg down its west, `C14.2` sits east — and `verify/freespot.py`
says C14 has no other legal window. That via's F.Cu annulus must clear
`~BAT_IN`, so its centre is at y ≥ 23.65; its B.Cu halo then ends at 24.275,
and VBAT's lane starts at 24.575. **0.30mm.** `EPD_VCC`'s spine to `L2.1` and
`C14.1` is load-bearing and lives there; do not try to shorten it (see the
island-seeding rule in `CLAUDE.md`).

**South corridor — 4 lanes, but only once `TP7` moves.** Today `TP7`'s HV pad
pinches x28.7..31.1 to a 0.30mm slot at y≈27.0. Move it anywhere clear of that
band (legal 1.5×1.5 B.Cu centres run x ≥ 30.75 across most of y20..28) and the
path becomes: F.Cu down the **x17.10..19.15** column (2.05mm — the only place
a bundle crosses VBAT's B.Cu wall), vias to B.Cu at y ≥ 28.65 (clear of TP1's
pad), east at y28.50..31.00 under the test-point row, climb at x25..26.5, then
the new neck at **x28.5 (1.75mm, y26.65..28.40)** between `J2.1`'s through-hole
and VBAT's diagonal, and out into the pocket.

**U1's own escapes.**  The `+3V3` B.Cu trunk lies directly under U1's south
row, so `U1.9`/`U1.10` cannot drop through their pads; they need vias ~0.55mm
south of the pads (y ≈ 20.4), which clears the trunk. `U1.22`/`U1.30`/`U1.31`
take via-in-pads like the EPD signals already do. The east flank
(x17.9..19.4) is owed to USB and the crystal — no debug lane may use it.

Negative results, so they are not repeated (each is one `make route`; baseline
is 15 stragglers):

| change | stragglers | what it broke |
|---|---|---|
| debug nets early in `ROUTE_PLAN` | 20 | `DBG_IO8` takes U1's east flank → `USB_D±`, `XTAL_32K_P`; `EN`→J5.3, `+3V3`→J5.2 |
| authored `L2.1`↔`C14.1` link | 17 | re-seeds `EPD_VCC` → `EPD_CS`, `EPD_DC`, `EN` |
| `EPD_VCC` terminals, L2 before C14 | ≥21 | `DBG_TX`, `EN`×2, `XTAL_32K_P` |
| authored U1 escapes, UART north of the row | 18 | `BOOT`→`SW2` (SW2 sits directly north of those lanes) |

The last one is the near miss: `DBG_RX` and `DBG_IO8` stopped failing at U1 and
started failing at the J5 island, which is the correct next failure. Run the
UART lanes *under* the module instead — authored copper is claimed before the
EPD escapes route, so they will move — and leave BOOT its crossing to SW2.

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
