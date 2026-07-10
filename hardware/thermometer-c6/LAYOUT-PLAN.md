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

### M5 state: 12 stragglers after the NE-gate harvest (2026-07-10)

The NE-gate discovery below is HARVESTED (committed): DBG_TX climbs 45
degrees into its via from the y27.55 slot; VBUS_SENSE lost its fan-in via
entirely (J5.6 is entered from below off a between-the-rows F run its west
leg reaches over the south corridor); SCK, MOSI, EPD_PWR_EN, ~EPD_VDD and
most of XTAL_32K_P are now authored end to end (see the comment blocks in
pcb_layout.py); XTAL_32K_P is boxed in ROUTE_PLAN like BOOT. `make route`
now writes out/stragglers.txt and prints only the delta (fixed/new/re-placed
nets); `verify/net.py NET` dumps one net's authored+routed state.

Structural facts that fell out of the harvest (do not re-derive):
- West-to-east crossings for late signals: the EPD_VCC spine (x21.95,
  y14.45..23.65 + its top via ~y14.15) has exactly two doors -- the
  y12.75..13.65 debug-band latitude (full: TX/RX/IO8 at 0.45 pitch) and the
  y24.3 slot + its single x21.15..21.3 descent lane (MOSI's, authored).
  EPD_PWR_EN therefore crosses UNDER the VBAT wall at y26.1 on B and
  bridges back over it on F, twice (its authored course).
- The east edge carries exactly ONE net (SCK): VBAT's x45.75 B column
  walls B from y4.6 to 28.9, and the J4 pad row + one descent seal F.
  MOSI's J4.14 leg goes through the pocket to the staircase via instead.
- The NE corner notch (between Q1's VSYS yard, VBAT's hook and H1) fits
  one F crossing + one via: SCK's (44.3,4.5).
- ~EPD_VDD never enters the pocket: its C21.1 feed is an all-F authored
  link down x36.65 (between C18 and C21.2), and J4.18 joins over y19.55.
- XTAL_32K_P's C10.1/R9.1 island remains THE straggler of this cluster:
  PWR_EN's forced x17.75 column + the +3V3 elbow (via (20.5,18.05) + diag)
  + the C10/C11 cap column seal every bridge to the Y1 tree that A* or
  authored copper could take (all candidate slots enumerated and dead by
  0.01..0.15mm). Candidates if it must die: move C10+R9 (cascades into
  XTAL_32K_N's authored cell), or PathFinder-class rip-up routing.

Remaining 12: ~EPD_VPP->C22.1, EPD_CS->island@15.0,8.1, EPD_DC->J4.11,
EPD_RST->R17.2 + U1.28, EPD_BUSY->island@40,15.1, USB_D-->U1.17 (its old
x20.35/y8.4 crossing died with SCK's y7.75 band -- needs a fresh course to
U3.6), XTAL_32K_P->island@18.4,20.7 (above), SCL->island@15.9,15.6,
EN->J5.3, DBG_IO5->island@15.0,19.9, VBUS_SENSE->island@14.2,19.9.
The NE gate cluster (CS/DC/RST/BUSY/VPP) is unchanged from before the
harvest; the west-funnel trio (EN.J5.3/IO5/VBUS_SENSE-west) still waits on
the third south-funnel lane. `make route` prints the live list; trust it.

### M5 state: 12 stragglers (historical; superseded by the harvest above)

Since b5dfecf (all committed): the VBUS_SENSE divider moved beside Q1
(R22/R23 at 42.3/43.5, 6.3 -- at the old spot the mid-node was walled on
every side: VBUS fanout on F, D7 + EPD_VCC's rigid Q2.3 channel on B; the
node now exits east on F into the east-edge margin, and the J5.6 leg
routes down the x46.55 B column east of VBAT's leg). The C9/R6 yard is
fully authored -- EN's U1.8 drop + all-F C9.1->R6.2 link at y22.3,
VBUS_SENSE's x14.9 and IO5's x15.5 B descents crossing under it -- because
greedy neighbours (VDIV_EN's Q5.1 diagonal, EN's own sweep, +3V3's R6.1
feed) otherwise squeeze one another out in whichever order they run; see
the yard comment block in pcb_layout.py. VBUS_SENSE routes LAST of the
signals (most-adaptable net; routed earlier its west leg sweeps the
south-edge lanes EN's J5.3 and IO5 need). DBG_TX now runs the y28.1 seam.

New review tooling (verify/, all support the mid-pass obstacle state via
`PCB_NO_ROUTES=1 ... --upto=NET`, which is THE way to debug a straggler:
a net's true obstacle set is authored copper + nets EARLIER in ROUTE_PLAN):
- `reach.py NET W OUT.png [crop] [--seed=N] [--upto=NET]` -- flood-fill
  with A*'s exact move rules from island N; prints REACHED/UNREACHED per
  island and the closest-approach chokepoint. The single most useful tool.
- `probe.py NET W --upto=NET SEED x,y ...` -- per-cell trk/via blockage +
  flood membership (SEED = island index or "x,y,F|B").
- `who.py NET W --upto=NET x,y [radius]` -- every copper element near a
  point with distances and trk/via margins (Chebyshev-correct for
  diagonals).
- `gap.py NET W --upto=NET seedA seedB` -- narrowest gap between two
  islands' flood regions: where one authored bridge would connect them.

Router semantics found this phase (also see CLAUDE.md traps):
- stamp_seg rasterizes DIAGONAL segments as squares: a 45-degree lane
  shadows sqrt(2)x its inflation -- ~0.64mm per side against a 0.25 track,
  ~0.88mm against a via centre. H/V segments stamp exact. Prefer H/V
  authored copper beside via windows.
- A* cannot place a via within Chebyshev 0.8mm of an existing via centre
  or 0.55mm of any hole (stamp_hole). Authored vias bypass route.py and
  answer only to DRC, so an authored 0.8mm pair is fine -- but it pins A*
  out of the whole neighbourhood.
- Re-placement dominos: 0.025mm at one via window can reroute a net into
  a 60mm loop three nets later (+3V3's R6.1 window at (16.1,20.8) -> XTAL
  around the west+south edges -> SDA/EN dead). Diff the villain nets'
  routes between passes; the failure list names victims, not culprits.

**NE-gate discovery (not committed -- next chunk's starting point).** With
(a) DBG_TX climbing 45 degrees straight into its via, no y28.75 row
segment (keeps the y28.5..29.35 under-band open from the neck), and
(b) VBUS_SENSE's fan-in via at (35.17,28.75) + an L-drop entering J5.6
from below (south through the J5.2/J5.4 channel, east between the pin
rows), the router SOLVED six of the hard NE nets in one pass:
- EPD_SCK: via-in-pad (15.9,7.75), B y7.75 east to x24, dodges NORTH of
  the Q2.3 channel via y4.75, joins the y4.1 north-edge lane, F down the
  x47.6 east-edge column into J4.13. (The negative-table y7.75 attempt
  failed because it was AUTHORED straight through the channel longitudes;
  routed, it ducks to y4.75 first.)
- EPD_MOSI: south crossing -- via (20.1,14.55), B x21.3 descent BESIDE the
  C14 spine (0.65 west), east y24.3 between C14 and the VBAT wall, F over
  the pocket, B diagonal to its staircase via (43.4,18.55).
- USB_D+: the east-pad-row strip as designed (vias 15.75/18.4/18.9, B
  y14.3 and y12.1 bands to U3).
- EPD_CS, EPD_DC, ~EPD_VPP, EPD_RST->R17.2 also routed.
Cost in that pass: USB_D- (MOSI's x20.1 F vertical takes its x20.35
column), SDA x3, VDIV_EN->Q5.1, EN x3 -- net 14. The harvest plan is to
author those discovered paths one cluster at a time (SCK first, shifted
so D-'s column survives), re-running the west-side fixes that already
worked once per re-placement wave.

Remaining 12: the six NE-gate terminals (SCK->U1.25, CS->island@15.0,8.1,
DC->J4.11, RST->R17.2 + U1.28, BUSY->island@40.0,15.1), USB_D+->U1.18,
~EPD_VPP->C22.1, SCL->island@15.9,15.6, LED_STATUS->R8.1,
DBG_IO5->island@15.0,19.9, VBUS_SENSE->island@14.2,19.9 (U1.9 leg only).
IO5's and VBUS_SENSE's remaining legs are the same structural problem:
three west-to-pocket crossers (EN's J5.3 sweep is the third) into two
south-edge funnel lanes; the seam/under-band rework above is the intended
third lane.

### M5 state at b5dfecf: 13 stragglers (historical)

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
