# Archive — not part of the generated flow

Nothing here is read by the generator or the build. These are point-in-time
snapshots kept so hard-won states can never be lost to a bad harvest or
later rework.

## hand-routed-2026-07-12.kicad_pcb

The user's complete GUI hand-routing of M5, verbatim as routed (copied from
the `out/hand/` working copy). Provenance:

- Base: generated board at commit 6bb2696 (12 unrouted straggler terminals).
- All non-GND connections routed; copper DRC-clean under the project rules
  (zero clearance/width/short violations); unconnected items = GND only
  (awaits the M6 pour).
- Board outline extended to 49×36mm (+1mm east, +1mm south); no component
  moved; R9 (10MΩ 32k-crystal bias resistor) deleted on the board — restored
  with a local splice when this copper was harvested into the generator.
- Harvested wholesale into `generator/pcb_routes.py` (see the HAND_ROUTED
  sentinel there and HAND-ROUTING.md for the round-trip workflow).

## hand-routed-2026-07-14-rotations-widths.kicad_pcb

GUI board after the user's **rotation/alignment pass on 11 R/C parts** and the
reroute that followed (`ccc9546`): the SE storage-cap row shifted east, the SW
sensor column aligned with its +3V3 pads facing west, C13 turned horizontal
clear of H2. 0 unconnected. Harvested wholesale, then a trace-width audit
normalised the signal nets (+3V3 sensor branch, EPD_RST, XTAL_32K_N and
EPD_GDR 0.2→0.25mm; EN/VBUS/EPD_RESE deliberately left mixed where a tight
parallel run or a clearance fix blocked it).

Board still 49×36 here: shrinking the outline re-fragments the hand-tuned GND
pour, which is what the next snapshot deals with.

## hand-routed-2026-07-14-48x35-gnd-solved.kicad_pcb

GUI board after **reclaiming the 48×35 outline** — the east and south strips
added at M5 given back (`06161f6`). The shrink re-fragmented the GND pour into
three opens (C12.2, U3.2, and an F↔B split); the user hand-closed them, and the
harvest took 56 GND tracks and 44 stitch vias wholesale. Gate: unconnected 0,
REAL=0 (2 dangling GND stubs deferred), `check_pcb` OK.

This is the snapshot `verify/gnd_islands.py` was written against. GND was
connected but **low-redundancy** at this point — two sub-planes of ~49 and ~38
pads each hanging off a single 0.15mm neck, which is what the 07-15 and 07-16
SPOF rounds below then hardened.

## hand-routed-2026-07-15-gnd-spof-fixes.kicad_pcb

Intermediate GUI snapshot (mtime 00:37) captured mid GND-hardening — single-via
and thin-neck SPOFs partially reduced. Superseded by the neck+east-cap board
below; kept as a step in the hardening sequence.

## hand-routed-2026-07-15-neck-eastcap-spof.kicad_pcb

The GUI board (mtime 14:28) with the two headline GND single-point-of-failure
ties eliminated by hand. Provenance:

- Base: generated board at commit 0abdc4c.
- **North F.Cu GND neck** (0.25mm at 14.16–16.30, 5.78; previously the SOLE
  tie for a ~34-pad region) re-laced so the north cluster no longer hangs off
  one thin neck.
- **East-cap SPOF**: a 0.6/0.3 GND stitch added at (44.70, 6.40) so the
  16-pad east cap/connector cluster (C17–C25, C5/C6, D7, J4.8/17, JP2.2, …)
  has a second independent tie.
- Plus the accumulated GUI signal routing since the prior partial harvest
  (~30 nets re-synced).
- Harvested into `generator/pcb_routes.py` (signals) + `generator/pcb_layout.py`
  STITCH (66→68 vias, grown 0.6/0.3 sizes preserved) and GND TRACKS. `out/hand`
  == generated is copper-identical (1075 segments / 191 vias, +0/−0 per net);
  DRC REAL=0, unconnected=0, starved_thermal=0; `make check` green.
- Known remaining SPOFs (reported, not blockers): U5.3/U6.6 single-via ties
  in the sensor keep-out (1 pad each, no legal stitch spot); a 0.15mm B.Cu
  neck (22.42→27.63, ~y6) now sole tie for 27 pads.

## hand-routed-2026-07-15-reroute-pass.kicad_pcb

The GUI board (mtime 18:10) after a large hand simplification/reroute pass —
~30 nets tidied (LED_STATUS −11, DBG_TX −10, VSYS −8, SDA −7, VBAT −7, SCL −5,
USB_D+ −5, EPD_MOSI +4, …; ~56 fewer signal segments, vias unchanged at 191).
As-saved, so it still contains one slip: the **DBG_TX gap was bridged with a
copper graphic line** (`PCB_SHAPE` on B.Cu, ~(28.9,22.8)→(30.1,24.0)) instead
of a track. `extract_tracks` reads only `GetTracks()`, so on harvest that
bridge was reproduced as a proper netted DBG_TX track (connectivity restored,
DRC-validated); a 0.099mm EPD_DC dangling stub was trimmed. Provenance:

- Base: generated board at commit bf49e23 (straighten+widen simplification).
- Harvested into `generator/pcb_routes.py` (signals) + `generator/pcb_layout.py`
  STITCH (68 vias, grown 0.6/0.3 preserved) + GND TRACKS (47 polylines).
- `out/hand` == generated is copper-identical (topo 59/59, only the trimmed
  EPD_DC stub differs); DRC REAL=0, unconnected=0, starved_thermal=0;
  `make check` green; byte-stable.
- Known remaining SPOFs (unaddressed this pass): 0.15mm B.Cu neck
  (22.42→27.63, ~y6) sole tie for 27 pads; U5.3/U6.6 single-via sensor-keepout
  ties (1 pad each).

## hand-routed-2026-07-15-widen-antenna.kicad_pcb

The GUI board (mtime 19:58) after the user widened every sub-0.25mm trace to
≥0.25 (min width now exactly 0.25mm), cleaned up LED_STATUS/SDA/SCL routing near
the antenna B side, widened+straightened the 27-pad B.Cu GND neck 0.15→0.25, and
relocated one 0.5/0.3 GND stitch. As-saved (before the scripted straighten +
3-stub trim applied on harvest). Provenance:

- Base: generated board at commit c6bf143.
- Harvested into `generator/pcb_routes.py` (signals, 34 nets) + `generator/pcb_layout.py`
  STITCH (68 vias, 40 grown 0.6/0.3 preserved) + GND TRACKS (44 polylines).
- On harvest: 3 dangling stubs (EN / VDIV_EN / LED_STATUS) trimmed; scripted
  straighten to fixpoint (−50 verts / −7.54mm; no widen). Generated board gated:
  DRC REAL=0, unconnected=0, starved=0; `make check` green; byte-stable;
  out/hand-vs-generated differs only by the trim + straighten.
- Remaining SPOFs: 27-pad B.Cu neck (now 0.25mm but still a single path — GUI
  2nd-path needed); 15-pad east-cap via@(44.70,6.40) — a redundant 2nd stitch
  at (44.49,5.58) is added in the following commit.

## hand-routed-2026-07-16-gnd-loop.kicad_pcb

The GUI board (mtime 00:41) the user called done — added a full-board GND loop
return path, improved GND connectivity, shortened traces, preserved the antenna
counterpoise. Provenance:

- Base: generated board at commit cc6d380.
- The loop path RESOLVES the 27-pad B.Cu neck: `gnd_islands` narrow-neck SPOFs
  11→0, the old 21–22-pad single-via SPOFs collapse to 1-pad stubs; GND = one
  connected system. Antenna GND counterpoise intact (coverage slightly up: F
  66/96, B 95/96 zones), keepout clean on both layers.
- Harvested into `generator/pcb_routes.py` (signals) + `generator/pcb_layout.py`
  STITCH (73 vias: 28×0.5/0.3, 45×0.6/0.3 grown preserved) + GND TRACKS (43).
  out/hand == generated copper-identical (topo sim=1.00; only split_tees vertex
  artifacts). DRC REAL=0, unconnected=0, starved=0; `make check` green; byte-stable.
- Voltage rails verified: no series bottleneck (every trunk ≥ its needed min;
  +3V3 burst path 0.5mm, VBUS charge path 0.4mm) — uniformizing is cosmetic only.
- Remaining: 4 single-via 1-pad ties (U6.6/U5.3/R21.2/C6.2, keep-out, accepted);
  3 dangling tails (+3V3/DBG_RX/EPD_SCK) trimmed in the following commit.

## hand-routed-2026-07-16-h1-clearance.kicad_pcb

GUI board after the user rerouted **VBAT + EPD_SCK away from mounting hole H1**
to open its board-edge/copper clearance, and re-stitched the NE GND (added
0.5/0.3 @ (43.5,5.8) and 0.6/0.3 @ (46.5,6.6)/(46.5,7.6); dropped (46.6,6.7)).
Base: generated at cd3a9e4. H1 nearest non-pour copper **2.32mm → 3.05mm** (a
full 5mm M2 flat washer now clears). Harvested: pcb_routes.py (VBAT/EPD_SCK
signals) + pcb_layout.py STITCH. GND fully connected (0 unconnected). Note: 2
redundant NE stitch vias (44.49,5.58 / 46.6,5.7) render one-sided in the
generated zone-fill (`via_dangling`, benign — neither is the sole tie for any
pad; GND still one connected system). `make check` green.

## hand-routed-2026-07-17-mounthole-q1.kicad_pcb

GUI board after the mounting-hole + NE-corner rework: (1) H1/H2 repositioned to
(45.8,2.2)/(2.2,32.8) — symmetric (180° about board center), **≥1mm wall to every
board edge** (was H1 0.30mm, a JLC hole-to-edge DFM fail); (2) user hand-moved
**Q1→(41.6,5.04), R22→(41.2,7.6 rot0), R23→(44.0,7.11)** and rerouted VSYS/VBUS to
clear the H1↔Q1 courtyard overlap the reposition surfaced. GND re-stitched (7 vias
removed incl the 2 now-redundant ones the user deleted → **via_dangling 0**). Base:
aa55505. Harvested: PLACE (H1/H2/Q1/R22/R23), pcb_routes.py, pcb_layout STITCH/TRACKS.
Gate: 0 unconnected, 0 DRC, **courtyards_overlap=0**, make check green, byte-stable,
out/hand == generated.

## hand-routed-2026-07-19-j4-fanout-reroute.kicad_pcb

GUI board after the **J4 24-pin FPC fanout + a board-wide signal re-route +
testpoint simplification**. Base: generated at 77c3ebd (J4 re-placed mouth-east
after the tail-side STEP correction; 21 pads unconnected, fanout pending, seeds
kept). The session:

- **J4 fanout completed** — every FPC pin routed; the board is now **0
  unconnected** (was disconnected, GND included) and **GND is one connected
  system** (gnd_islands `connected: True`, was `False`; narrow-neck SPOFs 8→3).
- **Significant re-routing beyond the fanout** — ~30 signal nets re-laid
  (DBG_RX/TX, all EPD_* including CS/DC/SCK/MOSI/RST/BUSY/VCC/GDR/RESE/PREVGL,
  USB_D+, VBAT, +3V3, J4 pins, JP5); board grew 870→1049 GUI segments.
- **9 testpoints moved to simplify** (board-relative, side B):
  TP1 (18.5,27.4)→(15.2,26.108), TP4 (11.6,30.6)→(11.37,23.295),
  TP5 (24.0,10.0)→(21.34,21.8), TP6 (38.4,23.9)→(38.45,21.95),
  TP7 (33.4,24.7)→(35.45,25.55), TP8 (29.0,12.6)→(31.29,14.423),
  TP9 (36.35,10.5)→(35.45,9.813), TP10 (44.4,25.9)→(38.28,25.55),
  TP11 (13.2,23.4)→(12.12,27.7).

Harvested: `pcb_routes.py` (signals, `--all`), `pcb_layout.py` PLACE (9 TPs via
`hand_diff --apply`), STITCH (**+6 / −9** vias, 0.6/0.3 overrides preserved),
GND TRACKS (re-authored from the hand board, 41→42 polylines). Gate: `make
check` green; **DRC REAL=0, unconnected=0, schematic-parity=0**; `check_pcb`
green incl. the §9 J4 mouth-east orientation guard. hand_diff A–F/H clean; its G
(signal) shows sub-µm residual only — every net's board/authored segment counts
match (topology faithful), differing by `extract_tracks` 3dp rounding on the
GUI's fine-grid vertices (worst 1.7µm; one 0.5µm degenerate VBAT stub at moved
TP1 harvests to zero-length and is dropped). **Deferred to a later silk task:**
5 silk warnings near the moved TPs (`silk_over_copper` PREVGH; `silk_overlap`
TP5/R9-10M, TP7/MOUNT-TOP, TP10/MOUNT-TOP, TP6/PREVGH) plus stale bench labels
(3V3-probe-only, EPD_VCC, VBAT_ADC) that still sit at the old TP positions.

## hand-routed-2026-07-20-j3-usb-reroute.kicad_pcb

GUI board after the **J3 USB-C reroute + cleanup pass**. Base: generated at
26cebbc (J3 re-placed mouth-north / rot 180, USB fan-out to the old north pad
row cut; 12 non-GND unconnected items pending). The session:

- **J3 USB routing completed** — VBUS / D+ / D- / CC1 / CC2 / VSYS / CHG_STAT /
  EPD_RST re-laid to the new south pad row and the displaced through-nets
  reconnected; the board is now **0 unconnected** and **GND is one connected
  system** (gnd_islands `connected: True`; single-via SPOF ties 10->6,
  narrow-neck SPOFs 4->3 vs the rough pass).
- **5 components hand-moved** (harvested via `hand_diff --apply`):
  D1 (16.5,3.7,90)->(34.4875,5.1,180), R4 (16.5,1.1,270)->(33.9,6.5,180),
  R17 (34.9,5.33,0)->(31.8,5.28,90), R1/R2 swapped to
  (21.98,10.63,270)/(20.79,10.63,270). D1's rotation change (90->180) voids its
  LED_0603 CPL preview verification -- reset to a low-confidence
  REF_ROTATION_OVERRIDES["D1"] entry (re-walk the JLC preview with J3/J4).

Harvested: `pcb_routes.py` (signals, `--all`), `pcb_layout.py` PLACE (5 parts),
STITCH (**+16 / -18** vias, 0.6/0.3 overrides preserved), GND TRACKS
re-authored from the hand board (33 polylines; the orphaned (22.01,10.06) stub
serving R2's old courtyard is gone). Two harvest-time copper nudges kept the
generated board DRC-clean: a ~11um shift of a GND spur off a U4-PROG via
(0.6um 3dp-rounding artifact), and lowering the `~EPD_VGL` (J4-Pin_4) HV track
y8.654->8.63 -- the cleanup pass had raised it to 0.2838mm from TP9's EPD_RESE
pad (hv-clearance needs 0.3), a real violation present on the hand board.
Gate: `make check` green; **DRC REAL=0, unconnected=0, schematic-parity=0**;
`check_pcb` green incl. the §9/§9b J4-mouth-east / J3-mouth-north guards.
**Deferred to a later silk task:** the same 6 silk warnings as the J4 harvest
(`silk_over_copper` PREVGH + the rev-A footer; `silk_overlap` TP5/R9-10M,
TP7/MOUNT-TOP, TP10/MOUNT-TOP, TP6/PREVGH -- the 5 moves added none) plus the
stale bench labels (3V3-probe-only, EPD_VCC, VBAT_ADC) still at old TP spots.

## hand-routed-2026-07-20-cleanup-round.kicad_pcb

GUI board after a small **C14 re-place + copper/silk cleanup round**. Base:
generated at e567982 (the silk rework; 5e5cf42/309333e are tooling-only, so the
working copy was current). The session:

- **C14 moved** (23.0,24.0) -> (24.0,24.1), taking its GND stitch with it
  (23.775,24.0 -> 24.775,24.1, the moved pad's own via) and forcing a short
  reroute of the three nets that terminate on it: `EPD_VCC`'s via follows to
  (23.225,24.1) on a new vertical+45° leg, `~BAT_IN` shifts its east-west run
  y22.9 -> 23.0 and lands on Q6.3 through a 45° drop, and a new 0.2mm F.Cu GND
  spur ties the stitch east to Q6.1's via (which grew 0.5 -> 0.6mm).
- **`+3V3` 0.5mm staircase straightened** north of TP5: the (22.3,18.05)/
  (22.34,15.765) dogleg with its 40µm jog becomes one exact 45° —
  (20.5,18.05)-(21.887,18.05)-(23.105,16.832)-(23.105,15.0).
- **Two degenerate zero-length stubs deleted**: `EPD_CS` at (35.57,15.05) and
  `USB_D-` at (25.927,10.39). The board now has **0 zero-length segments**.
- **Silk cleanup**: `CHG` moved (33.1,7.9) -> (36.1,6.7) (NE of D1, past R17);
  a `-` polarity marker added at (22.0,24.2) over J1.2 to pair with the
  existing `+` over J1.1; the B.SilkS footer lost its blank line (four tight
  lines now); `MOUNT TOP` became `MOUNT\nON TOP`, stood vertical (rot 90) at
  (31.0,32.325) on the J5 legend's own y-centre.

Harvested: `pcb_routes.py` (signals, `--all`), `pcb_layout.py` PLACE (C14 via
`hand_diff --apply`), STITCH (**+1 / -1** via plus Q6.1's 0.5->0.6 size
override), GND TRACKS (+1 polyline for the new spur), SILK (4 edits,
hand-mirrored — `hand_diff` F is report-only). No harvest-time copper nudge was
needed: the round is DRC-clean as drawn, and the only geometric liberty taken is
authoring the GND spur's diagonal at (26.118,24.1)->(26.5,23.718) so it is an
exact 45° landing on the via centre (0.5µm off the GUI's 26.1175/23.7175).
No alignment nudge survived: C14 lands on (24.0,24.1), already exact on the
0.1mm grid in both axes, with no local row/column partner to share an axis with.
Gate: `make check` green; **DRC REAL=0, DEFERRED=0, unconnected=0,
schematic-parity=0** (the 2 J3 edge-launch `copper_edge_clearance` waivers
remain, pending the J3 re-place); `check_pcb` green incl. the §9/§9b
J4-mouth-east / J3-mouth-north guards; `gnd_islands` connected (6 single-via
SPOF ties, 3 narrow necks — unchanged). **Silk is now 0 violations at full
severity** — the e567982 rework holds and this round's four edits added none.

## hand-routed-2026-07-20-corner-round-usb-reroute.kicad_pcb

The last hand-routing snapshot before the order (`a93ffa9`) — the completed
corner-round and USB reroute pass, harvested whole-board: signal copper into
`pcb_routes.py`, GND polylines and stitch vias into `pcb_layout.py`, plus the
button-row move (SW1/SW2 +1.4 east, R7 +2.1, C23/C24 west onto a 2.5mm pitch)
and the RST/BOOT/back-footer silk that went with it. **Fully routed: 0
unconnected, DRC REAL=0 and DEFERRED=0 at full severity.**

Two generator fixes the harvest forced out, both round-trip precision bugs:
mm→nm conversion now rounds rather than truncating (`pcbnew.FromMM` truncates,
so an nm-exact vertex came back a nanometre light every render, and harvesting
at µm on top of that turned an exactly 0.2000mm EPD_VCC/DBG_TX clearance into a
DRC error); and the new west GND spur drops to the y7.17 lane from x3.6 rather
than diagonally off the stitch.

## order-2026-07-20/ — the rev A production order (FIRST ORDER)

The exact files uploaded to JLCPCB, kept verbatim. This is the only record of
what was physically built, so nothing here is regenerated — `make fab` at any
later commit produces a different stamp and would not describe these boards.

Two subdirectories were added after this section was first written, both with
their own READMEs: `jlc-production-files/` (JLC's CAM output and SMT previews,
plus the independent 75-placement verification) and `xray/` (the first-article
X-ray frames and the script that annotates them).

- `thermometer-c6-gerbers-3ed40fe-2026-07-20.zip` — 12 members (9 gerbers +
  drill + drill map + job). sha256
  `f025e08ac4a70a5289ad974c08c9be281db49b9dec091edb9515b8177fbb1e7c`
- `thermometer-c6-cpl.csv` (75 placements) · `thermometer-c6-bom.csv`
  (37 lines) · `rotation-checklist.md` (22 orientation-critical parts)

**Provenance.** Commit `3ed40fe` ("Delete the JLCJLCJLCJLC order-mark token
from back silk"), silk stamp **`rev A 3ed40fe 2026-07-20`** — the stamp is
physically on the boards, so that hash identifies them forever. Clean tree at
export. Gates at the time: `make check` green, DRC **REAL=0 DEFERRED=0
WAIVED=0** at full severity (the first strict pass with zero waivers),
`check_pcb` OK, `check_fab` OK (54 assertions), 0 unconnected.

**The order number is deliberately NOT recorded here** — the owner asked to
keep it out of the repo. This is a choice, not an omission; do not "fix" it.

**Options ordered.** 5 PCBs / 4 assembled. FR-4, 2 layers, 1.6mm, 1oz outer,
TG135, min via 0.3mm, outline tolerance ±0.2mm. **ENIG** (1 U"). **Via
covering: Epoxy Filled & Capped (POFV)**, horizontal electroless copper
plating. **Mark on PCB: Remove Mark** — the board carries no order-mark token
at all (JLC support confirmed 2026-07-20 that the specify-position service is
discontinued, so the `JLCJLCJLCJLC` string was deleted rather than shipped).
Flying-probe fully tested, IPC Class 2, ink-jet silkscreen. **White solder
mask with black silk** and **lead-free / high-temp solder paste** — both
deliberate. Standard PCBA, **top side only**, parts selection by customer,
Confirm Production File **and** Confirm Parts Placement both Yes. Board
cleaning **No**, conformal coating **No** (U5 is a vented sensor). JLC grew
the panel to 70×71mm for its own edge rails; depanel-before-delivery Yes.
X-Ray inspection auto-added.

**Cost.** PCB €64.49 + Standard PCBA €140.46 = €204.94 merchandise, less a
€17.46 coupon → €198.94, plus shipping and two charges quoted only after
review (`Depanel` €2.58, `PCBA remark` "quote after review"). Note the
advertised "Global Standard Direct Line" shipping is capped to orders under
$150 and was therefore unavailable — see ORDERING.md §8.

**Known items carried into the order, all consciously accepted:**
- **J3 (USB-C) renders ~1.3mm off its land in JLC's preview.** Established as
  a JLC 3D-model seating artifact, not a placement error: the whole model
  (housing, tails, shell legs) displaces as one rigid body, matching the
  `(0,−1.050,0)` correction `MODELS_3D` applies to that EasyEDA STEP. Board
  copper verified against the HRO drawing straight from the shipped gerbers
  (front shell slot 2.110, rear 6.290, NPTH 5.760). JLC support confirmed the
  model issue and that their engineer corrects it, with DFM pausing the job
  rather than proceeding. A PCBA remark asks them to place to the land
  pattern and not silently adjust it.
- **J3 and J4 CPL rotation deltas were never preview-verified** (both `0`,
  `confidence: low`). Covered by Confirm Parts Placement + the DFM gate.
- **D1's delta needed no re-verification** despite its `unverified` marker:
  its `0` was directly preview-verified 2026-07-18 (cathode cue S), and a
  rotation delta corrects a footprint↔library convention offset, so it is
  independent of the 90°→180° placement change that voided the annotation.
- Deferred polish, unchanged: 6 single-via GND SPOF ties, 4 narrow necks,
  34 sub-0.05mm slivers, 15 acute corners.

## worktrees/*.patch

Uncommitted diffs of the 2026-07-11 routing-agent worktrees at deletion time.
Their useful results (~EPD_VPP lane, EN spine + route.py hweight, +3V3 y23.9
detour freeing XTAL_32K_P) were merged to master as b51af3a / 1db17ea /
1773b61 and later superseded by the hand routing; the two `a48e…`/`ab05…`
patches are partial west-yard / NE-notch experiments interrupted mid-run.
Kept only as archaeology.
