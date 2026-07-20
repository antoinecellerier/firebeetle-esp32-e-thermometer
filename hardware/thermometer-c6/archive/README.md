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

## worktrees/*.patch

Uncommitted diffs of the 2026-07-11 routing-agent worktrees at deletion time.
Their useful results (~EPD_VPP lane, EN spine + route.py hweight, +3V3 y23.9
detour freeing XTAL_32K_P) were merged to master as b51af3a / 1db17ea /
1773b61 and later superseded by the hand routing; the two `a48e…`/`ab05…`
patches are partial west-yard / NE-notch experiments interrupted mid-run.
Kept only as archaeology.
