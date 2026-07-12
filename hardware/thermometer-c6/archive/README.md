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

## worktrees/*.patch

Uncommitted diffs of the 2026-07-11 routing-agent worktrees at deletion time.
Their useful results (~EPD_VPP lane, EN spine + route.py hweight, +3V3 y23.9
detour freeing XTAL_32K_P) were merged to master as b51af3a / 1db17ea /
1773b61 and later superseded by the hand routing; the two `a48e…`/`ab05…`
patches are partial west-yard / NE-notch experiments interrupted mid-run.
Kept only as archaeology.
