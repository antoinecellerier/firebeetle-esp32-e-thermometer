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

## worktrees/*.patch

Uncommitted diffs of the 2026-07-11 routing-agent worktrees at deletion time.
Their useful results (~EPD_VPP lane, EN spine + route.py hweight, +3V3 y23.9
detour freeing XTAL_32K_P) were merged to master as b51af3a / 1db17ea /
1773b61 and later superseded by the hand routing; the two `a48e…`/`ab05…`
patches are partial west-yard / NE-notch experiments interrupted mid-run.
Kept only as archaeology.
