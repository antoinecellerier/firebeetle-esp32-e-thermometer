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

### M5 state at b5dfecf: 13 stragglers

The corridor survey below is superseded where noted; the two-corridor
geometry itself still holds. Authored since (all committed): TP7 (33.4,24.7),
TP9 (36.35,10.5) kissing the RESE column, R7 (9.0,6.4), the sensor corner
rot-90 rebuild with C12/C13/C26 out of the picket strip; end-to-end B.Cu
lanes for DBG_TX/RX/IO8 (y12.75..13.65 band under the module, dive cascade
past the +3V3 elbow, descents x30.2/30.65/31.75, pocket floor to the J5
fan-in vias); BOOT's crossing (via x10.3, B.Cu leg onto R7.2); XTAL_32K_N's
U1.13 hop; +3V3's J5.2 feed along the south edge; SCL anchors at U5.2 and
U1.16. `make route` prints the live list; trust it, not this paragraph.

**The rule that fell out of this phase:** an authored lane needs clearance
only against other *authored* copper — routed nets re-place every pass. The
exceptions are routed structures with a single legal window, which are
de-facto rigid: EPD_VCC's Q2.3 escape (the B.Cu channel over TP8 at
~x29.9..30.15 y7.9..9.2 plus its diagonal to R17 — the ROUTE_PLAN comment's
"only escape is north"), EPD_VCC's C14 spine (the x~21.95 B.Cu vertical the
C14 window forces, top via copper down to y14.45 — crossing its longitude
below that evicts EPD_VCC into the pocket as a 0.5mm wall), and EPD_VCC's
authored staircase diagonal (x−y=26.55), which seals J4.12/13/14's stubs
from the NE: approach them only from the SW.

**Pocket floor slots** (0.45 pitch between EPD_PREVGL's HV diagonal and the
via row): 26.15 IO8 / 26.6 kept free for ~EPD_VPP / 27.05 RX / 27.55 TX /
28.1 seam. The five J5 fan-in vias all sit at y28.75, which leaves no
through-lane between the row and VBAT's y29.75 lane (0.45mm gap, a lane
needs 0.65) — this is what still blocks VBUS_SENSE and DBG_IO5.

Remaining 13, with fix directions:

- **VBUS_SENSE ×2, DBG_IO5** — re-stagger the authored J5 fan-in via row:
  the vias are authored geometry; give the VBUS/IO5 vias their own y (longer
  F.Cu drops) so each has a private approach instead of fighting the
  y28.75 line and the TX/IO8 tails.
- **NE gate cluster** (EPD_SCK→U1.25, EPD_CS→island@15.0,8.1, EPD_DC→J4.11,
  EPD_RST→R17.2/U1.28, EPD_BUSY→island@40,15.1, USB_D+→U1.18) — the U1 NE
  gate (x15.3..18, y7.5..10.4) cannot carry MOSI+SCK+CS+DC at once. Needs a
  coherent authored escape set (via-in-pads exist for CS/DC/BUSY; add RST at
  (13.4,8.05) — BOOT's authored crossing already keeps clear of it — and one
  for SCK) plus east lanes that respect the rigid EPD_VCC structures. MOSI
  currently loops the NE successfully; its authored staircase via
  (43.4,18.55) dangles until this is reworked.
- **SCL→island@15.9,15.6** — the west path to the authored U1.16 anchor.
  SDA crosses the module on the F.Cu paddle seam at x14.85; SCL needs a
  parallel seam (paddle pad grid spans x9.1..14.5, y11.25..16.65 in a 3×3;
  the inter-pad F.Cu seams are the candidates, minus TX/RX's B verticals at
  x11.0/11.8 which don't block F).
- **~EPD_VPP→C22.1** — slot 26.6 is reserved but unused; the block is at its
  C22 exit or the J4.19 end. Re-derive with occupancy against the routed
  board.
- **LED_STATUS→R8.1** — the west B.Cu descent died with the debug verticals.
  Candidates: F flank east then around, or move D3/R8 (the step-4
  investigation of what D3's placement costs was never done).

Negative results (each one `make route`; do not repeat):

| change | stragglers | what it broke |
|---|---|---|
| debug nets early in `ROUTE_PLAN` | 20 | `DBG_IO8` takes U1's east flank → `USB_D±`, `XTAL_32K_P`; `EN`→J5.3, `+3V3`→J5.2 |
| authored `L2.1`↔`C14.1` link | 17 | re-seeds `EPD_VCC` → `EPD_CS`, `EPD_DC`, `EN` |
| `EPD_VCC` terminals, L2 before C14 | ≥21 | `DBG_TX`, `EN`×2, `XTAL_32K_P` |
| authored U1 escapes, UART north of the row | 18 | `BOOT`→`SW2` (SW2 sits directly north) |
| debug bands at y16.45..17.35 | 21 | crystal cell (XTAL via halos at y17.55) + SDA/SCL diagonals + CS/DC via displacement |
| debug bands crossing x21.95 below y14.45 | 25 | evicts EPD_VCC's C14 spine → 0.5mm pocket wall → J4 five + TX/RX loop the board edge |
| debug band/descent ending x30.7..31.4 | +5 | evicts ~EPD_VGH's x31.05 weave → F.Cu SE sweep → `VCOM`×2, `VSL`, `VDD`, `PREVGH` |
| authored pocket tails east of x34 | 25 | panel-cap service area starved (`VDD`'s C21 via zone, `VCOM`→C25/TP10) |
| SCK authored: y7.75 band + x32.3 column | 26 | crossed EPD_VCC's Q2.3 channel → `EPD_VCC`×6, `MOSI`, `USB_D-`, `EN`×2, `VBUS` (reverted) |

### M5 corridor survey (historical; U1 escapes and TP7 now done)

Every debug signal (`DBG_TX/RX/IO5/IO8`, `VBUS_SENSE`) has to cross the board
from U1 to J5's authored via row, and only two B.Cu corridors can carry a
bundle. Widths below are free *centres* for a 0.25mm lane, from
`verify/occupancy.py`'s bitmaps; they move only when authored copper moves.

**North corridor — open, 5 lanes.** Walled north by `~SW_10U`'s 45° B.Cu
diagonal and south by `VBAT`'s B.Cu lane at y25.15. It tapers west-to-east as
it follows the diagonal: 8.25mm at x24.5, 3.90mm at x28.0, **2.55mm at its
x29.0 neck** (y22.30..24.85), then the pocket at x31+ opens to 14mm. Enter it
from the north around x22.5..24.75, never from the field. (In practice the
committed debug lanes bypass it via the x30.2..31.75 descents; the corridor
band remains available.)

**The field west of x22.6 is one lane, structurally.** `C14.1` can only be
entered by a via — `~BAT_IN`'s 0.5mm F.Cu lane runs along C14's north edge,
that lane's leg down its west, `C14.2` sits east — and `verify/freespot.py`
says C14 has no other legal window. That via's F.Cu annulus must clear
`~BAT_IN`, so its centre is at y ≥ 23.65; its B.Cu halo then ends at 24.275,
and VBAT's lane starts at 24.575. **0.30mm.** `EPD_VCC`'s spine to `L2.1` and
`C14.1` is load-bearing and lives there; do not try to shorten it (see the
island-seeding rule in `CLAUDE.md`).

**South corridor — 4 lanes (TP7 moved).** F.Cu down the **x17.10..19.15**
column (4 lanes now that R7 is gone — the only place a bundle crosses VBAT's
B.Cu wall), vias to B.Cu at y ≥ 28.65 (clear of TP1's pad), east at
y28.50..31.00 under the test-point row, climb at x25..26.5, the neck at
**x28.5 (1.75mm, y26.65..28.40)** between `J2.1`'s through-hole and VBAT's
diagonal, and out into the pocket. EN's J5.3 leg uses it today.

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
