# CLAUDE.md — hardware/thermometer-c6 (custom PCB)

Scoped rules for working in this directory. Start points: `README.md`
(design rationale, pin map, jumper tables, bench procedures) and
`LAYOUT-PLAN.md` (next-phase instructions).

## Non-negotiable workflow

- **The `.kicad_sch` is generated — never hand-edit it.** Single source of
  truth: `generator/circuit.py` (components, nets, NC, LCSC fields) +
  `generator/layout.py` (placement, wire routes, labels, power symbols,
  PWR_FLAG anchors). Regenerate + verify with `make check`.
- `make check` must be fully green before any commit: ERC (zero violations,
  all severities, no exclusions), netlist exact-match against circuit.py,
  hand-written invariants, footprint resolution, and the generator's own
  fatal geometry checks (cross-net coincidence, label-over-wire/body,
  off-grid). `LAYOUT ERRORS` output is a build failure by design — fix the
  layout, never weaken the check.
- When changing circuit intent, update **all three together**:
  `circuit.py`, `verify/invariants.py` (they restate intent independently —
  that redundancy is the point), and the README tables.
- After visual-affecting changes, do a per-zone visual pass: `make pdf`,
  crop zones at 200 DPI with pdftoppm (scale 200/25.4 px/mm, origins/sizes
  from `layout.ZONES`), Read the PNGs, iterate until clean.

## Conventions and traps

- Net names starting with `~` are anonymous: no label on the sheet, matched
  by exact pin set in check_netlist. Anonymous nets must be fully routed
  (no label fallback). Named nets need at least one label/power symbol.
- Schematic transform is empirically derived (rot 0/90/270 only for field
  text; KiCad renders property text at symbol+property angle and mirrors
  justification at effective 180°). Don't "simplify" the transform code
  without re-running a netlist probe.
- KiCad symbol pin numbering is not trustworthy across libraries (e.g.
  Diode pin1=K here, Protel refs elsewhere) — wire by function (A/K, G/S/D)
  and let the invariants confirm.
- Populate-exactly-one pairs: U5 BMP581 / U6 BMP585 (both strap 0x47);
  bridge exactly one RESE jumper (JP2/3/4) and one inductor jumper (JP5/6).
- The 3V3 test pad is probe-only (RT9080 forbids back-drive); bench power
  injection happens at the J2/JP1 battery-side break.
- User decisions already settled — don't re-litigate: LDO not buck,
  indoor-only charging 0–45°C, 100mA charge, JLCPCB economy assembly,
  GND-first debug header with no VBAT pin.
- LCSC availability was verified 2026-07-07; re-verify stock at order time
  (known-thin: ESP32-C6-MINI-1-N4, Si1308EDL; BMP581 out of stock — U6 is
  the mitigation).

## Verification philosophy

Connectivity is computed, never trusted from drawing: the generator aborts
on geometric net merges, KiCad's own netlist is diffed against the design
intent, and invariants assert the intent a second time from first
principles. Extend this pattern to the PCB phase (DRC gating in the
Makefile, checklists in LAYOUT-PLAN.md) rather than replacing it.
