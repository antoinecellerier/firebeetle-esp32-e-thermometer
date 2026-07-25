---
name: pcb-fab
description: >-
  Exporting a JLCPCB-ready fab bundle for thermometer-c6 — what `make fab` does,
  the strict DRC gate it gates on, the revision stamp guarantee, and why
  violations get fixed rather than waived. Use when running make fab, cutting a
  new board revision, preparing or checking a JLCPCB order, or deciding what to
  do about a remaining DRC violation.
---

# Fab export

All commands run from `hardware/thermometer-c6/`. The order-page walk itself —
options, quote comparison, CPL rotation checks, the PCBA remark — is
**`ORDERING.md`**. This is the export that feeds it.

## `make fab`

`make fab` is the whole pipeline and it gates itself at three points:

1. **`make check`** must pass first (it is a prerequisite).
2. **A clean git tree.** The target refuses a dirty tree so the `rev A <hash>
   <date>` silk stamp names the exact committed source. `FAB_FORCE=1` downgrades
   this to a warning that says the stamp is a lie. It also does a defensive
   `git checkout --` of the board first, so non-byte-stable zone-fill noise
   doesn't trip the guard (see `pcb-edit`).
3. **Strict DRC on the stamped board.** A full-severity `kicad-cli pcb drc` runs
   against the board that actually ships — the stamped copy in `out/fab/board/`,
   not the committed one — gated by `verify/drc_summary.py --gate-fab`.

Then: gerbers + drill → `generator/fab_cpl.py` (CPL + rotation checklist) → BOM
copy → zip → `verify/check_fab.py`, which re-derives the same verdict
independently from the shipped bundle.

## The gate is stricter than `make drc`

`--gate-fab` passes **iff REAL=0 AND DEFERRED=0**. Every remaining violation must
be explicitly waived by a scoped rule in the `.kicad_dru`, and the accepted
waived list is printed to the fab log. There are currently **no waivers**.

The raw `make drc` target halts on *any* violation and is deliberately **not** a
`fab` prerequisite — it is for routing and manual use.

## Fix geometry, don't add waivers

The one waiver this board ever carried, `copper_edge_clearance` on the J3
edge-launch, was deleted 2026-07-20. It was not expressing a design intent: it
was waiving a **1.415mm placement error**, found by re-deriving J3's true datum.
A scoped rule that silences a real defect is worse than no rule, because the gate
then certifies the defect.

Before adding a waiver, prove the geometry is correct — numerically, per the
"physical reality beats inference" rule in `CLAUDE.md`.

## The stamp guarantee

- `circuit.REV` is the single source of truth for the revision letter.
- **Only the letter is committed.** The hash and date are injected at export time
  into the throwaway `out/fab/board/` copy — a file cannot contain the hash of
  the commit that contains it.
- `check_fab` asserts the **committed** board carries no stamp. That is what
  makes `rev A <hash> <date>` on a physical board name an exact commit.
- **Never bump `REV` retroactively.** The stamp is physically on boards already
  built, and `archive/order-*/` describes them.

## After an order

Archive the exact bundle that was ordered under `archive/order-<date>/` —
production files, BOM, CPL, rotation checklist, and the JLC order-page
screenshots. That directory is the only record of what a physical board actually
is; the repo moves on.
