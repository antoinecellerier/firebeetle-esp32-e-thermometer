#!/usr/bin/env python3
"""Assert the Python decoder sees exactly what the C writer produced.

`make -C tools/hstest sample` is the gate CLAUDE.md names for keeping
src/HistoryStore.cpp and tools/history.py on one on-flash format. Printing a
decode is not a gate: a decoder that mis-parses the geometry and reports zero
records exits 0 just as happily as a correct one. So compare against the counts
hstest wrote down when it built the image.

Usage: check_sample.py <image> <expect-file>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import history  # noqa: E402


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__.strip())
    with open(argv[2]) as f:
        want = tuple(int(x) for x in f.read().split())
    with open(argv[1], "rb") as f:
        arc = history.Archive(f.read())
    # journal_hourly is checked separately from the deduped total on purpose:
    # the base snapshot and the journal both carry the same recent hours, so a
    # journal walk that decodes nothing still produces the right total. Without
    # this column, breaking the record layout in one implementation passes.
    got = (len(arc.hourly), len(arc.samples), len(arc.drifts), arc.journal_hourly)
    names = ("hourly", "sparkline", "drift", "journal-hourly")
    if got != want:
        detail = "\n".join(f"  {n:<15} got {g:<6} want {w}"
                           for n, g, w in zip(names, got, want))
        raise SystemExit(
            "FAIL: decoder disagrees with the C writer.\n" + detail +
            "\nThe two implementations of the on-flash format have diverged.")
    print("format cross-check OK: " +
          ", ".join(f"{g} {n}" for g, n in zip(got, names)))


if __name__ == "__main__":
    main(sys.argv)
