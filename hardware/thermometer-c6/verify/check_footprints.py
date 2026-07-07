#!/usr/bin/env python3
"""Assert every footprint referenced by circuit.py resolves to a real
.kicad_mod file in the system footprint libraries (or a project .pretty)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))

import circuit  # noqa: E402

SYSTEM = "/usr/share/kicad/footprints"


def resolve(fp):
    lib, _, name = fp.partition(":")
    candidates = [
        os.path.join(SYSTEM, lib + ".pretty", name + ".kicad_mod"),
        os.path.join(PROJECT, lib + ".pretty", name + ".kicad_mod"),
    ]
    return any(os.path.exists(c) for c in candidates)


def main():
    bad = []
    for c in circuit.COMPONENTS:
        fp = c.get("footprint", "")
        if not fp:
            continue
        if not resolve(fp):
            bad.append((c["ref"], fp))
    if bad:
        print(f"check_footprints: {len(bad)} unresolved footprints")
        for ref, fp in bad:
            print(f"  {ref}: {fp}")
        sys.exit(1)
    print("check_footprints: OK — all footprints resolve")


if __name__ == "__main__":
    main()
