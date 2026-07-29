<!-- House rules for THIS file. Block-level HTML comments are stripped before
  it is injected into context, so this note is free.
  - This is a directory-scoped CLAUDE.md: it loads when Claude reads a file
    under hardware/thermometer-c6/, NOT at launch, and it is NOT re-injected
    after /compact. Anything catastrophic must also be one line in the root
    CLAUDE.md, which does survive compaction.
  - Target <= ~110 lines of loaded content (Claude Code docs cap CLAUDE.md at
    < 200). Prune one stale line before adding one.
  - Deep procedure -> a skill in .claude/skills/. Long rationale or a finished
    phase -> a doc beside README.md. This file holds only what stays true
    across phases.
  - Run /claude-md-audit before committing changes here. -->

# CLAUDE.md — hardware/thermometer-c6 (custom PCB)

## Where the project is

**rev A is in hand and working**: ordered 2026-07-20
(`archive/order-2026-07-20/`); board 1 passed Phases 0–2 on 2026-07-29.
**Current phase: `BRINGUP.md` Phase 3** + the quick sweep on boards 2–4.

| Doc | For |
|---|---|
| `README.md` | design rationale, pin map, jumper tables, bench procedures — read first for anything electrical |
| `BRINGUP.md` | **the current phase** |
| `ORDERING.md` | fab/assembly decisions and the JLCPCB order walk |
| `HAND-ROUTING.md` | the GUI → generator harvest loop |
| `EE-PRIMER.md`, `SCHEMATIC-VERIFICATION.md`, `REVIEW-KICAD-HAPPY.md` | background and review records |
| `LAYOUT-PLAN.md`, `ROUTER-NOTES.md`, `PATHFINDER-NOTES.md` | **completed phases — historical** |

Skills in `.claude/skills/`: **`pcb-edit`** (board edits, DRC, geometry traps,
`verify/` tools) and **`pcb-fab`** (`make fab` → JLCPCB bundle).

## Generated artifacts — never hand-edit

Three files are generated; editing them is silently undone by the next `make`.

| Generated | Authored in |
|---|---|
| `thermometer-c6.kicad_sch` | `generator/circuit.py` (parts/nets/NC/LCSC) + `generator/layout.py` (placement/wires/labels) |
| `thermometer-c6.kicad_pcb` | `generator/pcb_layout.py` (PLACE / KEEPOUTS / authored GND TRACKS / STITCH) + `generator/pcb_routes.py` (the hand-routed copper, `HAND_ROUTED` sentinel) |
| `thermometer-c6.kicad_dru` | `generator/pcb.py` |

Copper changes happen in the KiCad GUI on a copy and are harvested back
(`HAND-ROUTING.md`), or by editing the polyline data in `pcb_routes.py` directly
for small mechanical tweaks — both are legitimate, and DRC is the gate either
way. `make route` is retired: it aborts on the `HAND_ROUTED` sentinel.

## The gate

`make check` must be fully green before committing. `LAYOUT ERRORS` output is a
build failure by design — fix the layout, never weaken the check. For a board
change, add `verify/hand_diff.py` (exit 0), `verify/drc_summary.py --gate`
(REAL=0) and `verify/check_pcb.py`.

A circuit-intent change touches three files together: `generator/circuit.py`,
`verify/invariants.py` (an independent restatement of the intent) and the README
tables.

## Physical reality beats inference

Orientation and footprint claims have cost more time on this board than
everything else combined; J3 and J4 each flipped more than once.

- **Prove it numerically**, from the STEP file or the datasheet. A community CPL
  rotation table, a part-family analogy, and an eyeballed render have each been
  wrong here.
- **A render or a photo of the real part is evidence to explain, not noise to
  explain away.** Twice the user's observation was right and the analysis was
  wrong.
- **State the proof so someone else can check it** — the numbers, which pin sits
  where, what datum you measured from.
- **"Verified" is unearned until one check confirms it end to end.** J3 once read
  as correct because two errors cancelled: the 3D model was mis-seated 180° *and*
  the placement was wrong.
- **Fix geometry; don't add a DRC waiver.** The only waiver this board carried
  turned out to be masking a placement error, not expressing design intent — the
  `pcb-fab` skill has the case.

## Revisions

`circuit.REV` (`generator/circuit.py`) is the single source of truth, consumed by
`generate.py`, `pcb_layout.SILK`, `pcb.py` and `check_fab.py`. Change it,
`make check`, `make fab`.

**Only the LETTER is committed.** The hash and date are injected at fab-export
time into the throwaway `out/fab/board/` copy from a clean tree — a file cannot
contain the hash of the commit that contains it — and `check_fab` asserts the
committed board carries no stamp, which is what lets a stamp on a physical board
name an exact commit. **Never bump `REV` retroactively**: the stamp is on boards
already built, and `archive/order-*/` describes them.

## Conventions & traps

- `~`-prefixed nets are anonymous: no sheet label, matched by pin set in
  `check_netlist`, must be fully routed (no label fallback).
- Wire diodes/FETs by function (A/K, G/S/D), never by pin number — numbering
  differs across libraries.
- Don't "simplify" the transform/field-rotation code in `generate.py` without
  re-running a netlist probe; KiCad rotates property text with the symbol and
  mirrors justification at effective 180°.
- Populate-exactly-one pairs: U5/U6 sensors (both addr 0x47); one RESE jumper
  (JP2/3/4); one inductor jumper (JP5/6).
- **Never back-feed TP4 (3V3)** — RT9080 forbids VOUT > VIN + 0.3V. Inject bench
  power at the J2/JP1 battery-side break.
- Re-verify LCSC stock at order time (thin: MINI-1, Si1308EDL; if BMP581
  dries up, populate U6 BMP585 instead — rev A boards carry U5 BMP581).

## Settled decisions — don't re-ask

The reasoning lives in the cited file; this list exists to stop re-litigation.

- **Standard PCBA, top side only.** Economy is *impossible* for this board: ENIG
  and POFV each disable it, and U1 + U5 are Standard-only parts (`ORDERING.md`).
- ENIG finish; POFV (epoxy filled & capped) via covering; **no order mark** — JLC
  support confirmed 2026-07-20 that the order-number-at-a-specified-position
  service is discontinued, so the authored back-silk token was deleted rather
  than left as a stale artifact (`ORDERING.md`).
- LDO not buck; 100mA charge; indoor-only charging 0–45°C (silkscreen);
  GND-first debug header without VBAT (`README.md`).
