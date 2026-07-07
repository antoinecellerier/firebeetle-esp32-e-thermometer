#!/usr/bin/env python3
"""Compare the kicad-cli exported netlist against circuit.py's NETS.

Proves, through KiCad's own connectivity engine, that every net in the
design intent exists on the sheet with exactly the intended pins — the
defense against a visually-plausible-but-disconnected schematic.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(os.path.dirname(HERE), "generator")
sys.path.insert(0, GEN)

import sexp  # noqa: E402
import circuit  # noqa: E402


def load_netlist(path):
    with open(path) as f:
        root = sexp.parse_one(f.read())
    nets = {}
    nets_node = sexp.child(root, "nets")
    for net in sexp.children(nets_node, "net"):
        name = str(sexp.atom_after(net, "name"))
        pins = set()
        for node in sexp.children(net, "node"):
            ref = str(sexp.atom_after(node, "ref"))
            pin = str(sexp.atom_after(node, "pin"))
            pins.add((ref, pin))
        nets[name] = pins
    return nets


def main():
    netlist_path = sys.argv[1]
    actual = load_netlist(netlist_path)

    expected = {}
    for name, pins in circuit.NETS.items():
        expected[name] = {(ref, str(pin)) for ref, pin in pins}

    # Power-symbol and PWR_FLAG pseudo components (#PWR_*, #FLG*) appear in
    # netlists as nodes only if kicad-cli includes them; it does not — power
    # symbols merely name nets. Nothing to strip.
    failures = []

    # KiCad names a net after its label; power nets keep the label name.
    for name, pins in sorted(expected.items()):
        if name not in actual:
            # net might exist under a different name only if all its labels
            # were lost — that IS a failure.
            failures.append(f"MISSING NET: {name} (expected pins {sorted(pins)})")
            continue
        got = actual[name]
        if got != pins:
            extra = got - pins
            missing = pins - got
            msg = [f"NET {name} MISMATCH:"]
            if missing:
                msg.append(f"  missing pins: {sorted(missing)}")
            if extra:
                msg.append(f"  unexpected pins: {sorted(extra)}")
            failures.append("\n".join(msg))

    expected_names = set(expected)
    for name, pins in sorted(actual.items()):
        if name in expected_names:
            continue
        if name.startswith("unconnected-"):
            # every unconnected- net must correspond to a declared NC pin
            ncset = {(r, str(p)) for r, p in circuit.NC}
            for rp in pins:
                if rp not in ncset:
                    failures.append(f"PIN ON UNCONNECTED NET (not declared NC): {rp} in {name}")
            continue
        failures.append(f"UNEXPECTED NET: {name} with pins {sorted(pins)}")

    if failures:
        print(f"check_netlist: {len(failures)} FAILURES")
        for f_ in failures:
            print(f_)
        sys.exit(1)
    print(f"check_netlist: OK — {len(expected)} nets match exactly, "
          f"{sum(len(p) for p in expected.values())} pin connections verified")


if __name__ == "__main__":
    main()
