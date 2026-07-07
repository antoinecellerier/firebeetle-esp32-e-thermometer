# CLAUDE.md — hardware/thermometer-c6 (custom PCB)

Read first: `README.md` (design rationale, pin map, jumper tables, bench
procedures); `LAYOUT-PLAN.md` (next-phase instructions).

## Workflow

- **IMPORTANT: never hand-edit `thermometer-c6.kicad_sch` — it is generated.**
  Edit `generator/circuit.py` (parts/nets/NC/LCSC) and `generator/layout.py`
  (placement/wires/labels), then run `make check`.
- `make check` must be fully green before committing. `LAYOUT ERRORS` output
  is a build failure by design — fix the layout, never weaken the check.
- A circuit-intent change touches three files together: `circuit.py`,
  `verify/invariants.py` (independent restatement of intent), README tables.
- After visual changes, review zones as images: `make pdf`, crop each zone
  with `pdftoppm -r 200 -png -x/-y/-W/-H` (px = mm × 200/25.4; origins/sizes
  in `layout.ZONES`), Read the PNGs, iterate until clean.

## Conventions & traps

- `~`-prefixed nets are anonymous: no sheet label, matched by pin set in
  check_netlist, must be fully routed (no label fallback).
- Wire diodes/FETs by function (A/K, G/S/D), never by pin number — numbering
  differs across libraries.
- Don't "simplify" the transform/field-rotation code in generate.py without
  re-running a netlist probe; KiCad rotates property text with the symbol
  and mirrors justification at effective 180°.
- Populate-exactly-one pairs: U5/U6 sensors (both addr 0x47); one RESE
  jumper (JP2/3/4); one inductor jumper (JP5/6).
- TP4 (3V3) is probe-only — RT9080 forbids back-drive; inject bench power at
  the J2/JP1 battery-side break.
- Re-verify LCSC stock at order time (thin: MINI-1, Si1308EDL; BMP581 out of
  stock → populate U6 BMP585 instead).

## Settled decisions — don't re-ask

LDO not buck; indoor-only charging 0–45°C (silkscreen); 100mA charge;
JLCPCB economy assembly; GND-first debug header without VBAT.
