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


def load_components(path):
    """{ref: {value, footprint, lcsc, dnp, exclude_from_bom}} from the
    exported netlist's components section."""
    with open(path) as f:
        root = sexp.parse_one(f.read())
    comps = {}
    for comp in sexp.children(sexp.child(root, "components"), "comp"):
        ref = str(sexp.atom_after(comp, "ref"))
        props = {}
        for prop in sexp.children(comp, "property"):
            pname = str(sexp.atom_after(prop, "name"))
            props[pname] = sexp.atom_after(prop, "value")
        comps[ref] = dict(
            value=str(sexp.atom_after(comp, "value", "")),
            footprint=str(sexp.atom_after(comp, "footprint", "")),
            lcsc=str(props.get("LCSC") or ""),
            dnp="dnp" in props,
            exclude_from_bom="exclude_from_bom" in props,
        )
    return comps


def main():
    netlist_path = sys.argv[1]
    actual = load_netlist(netlist_path)

    # Nets named "~..." in circuit.py carry no label on the sheet; KiCad
    # auto-names them. They are matched by exact pin set instead of by name.
    expected = {}
    anon = {}
    for name, pins in circuit.NETS.items():
        pinset = {(ref, str(pin)) for ref, pin in pins}
        if name.startswith("~"):
            anon[name] = pinset
        else:
            expected[name] = pinset

    failures = []

    # KiCad names a net after its label; power nets keep the label name.
    for name, pins in sorted(expected.items()):
        if name not in actual:
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
    remaining = {}
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
        remaining[name] = pins

    for name, pins in sorted(anon.items()):
        hit = None
        for aname, apins in remaining.items():
            if apins == pins:
                hit = aname
                break
        if hit is None:
            failures.append(f"ANONYMOUS NET {name} NOT FOUND: expected pins {sorted(pins)}")
        else:
            del remaining[hit]

    for name, pins in sorted(remaining.items()):
        failures.append(f"UNEXPECTED NET: {name} with pins {sorted(pins)}")

    # NC is bidirectional: every declared-NC pin must actually appear on an
    # unconnected- net (a pin mistakenly moved into NC, or dropped from the
    # sheet entirely, fails here instead of silently losing its requirement).
    unconnected_pins = set()
    for name, pins in actual.items():
        if name.startswith("unconnected-"):
            unconnected_pins |= pins
    for r, p in circuit.NC:
        if (str(r), str(p)) not in unconnected_pins:
            failures.append(f"DECLARED NC BUT NOT UNCONNECTED ON SHEET: ({r}, {p})")

    # Component metadata: the sheet must carry exactly circuit.py's
    # value/footprint/LCSC/dnp for every part (the netlist components
    # section is what KiCad-side exports see; drift here is invisible to
    # the nets comparison above).
    comps = load_components(netlist_path)
    expected_comps = {c["ref"]: c for c in circuit.COMPONENTS}
    for ref in sorted(set(comps) | set(expected_comps)):
        if ref not in comps:
            failures.append(f"COMPONENT MISSING FROM SHEET: {ref}")
            continue
        if ref not in expected_comps:
            failures.append(f"UNEXPECTED COMPONENT ON SHEET: {ref}")
            continue
        want, got = expected_comps[ref], comps[ref]
        for key, wanted in (("value", want["value"]),
                            ("footprint", want["footprint"]),
                            ("lcsc", want.get("lcsc", "")),
                            ("dnp", bool(want.get("dnp", False)))):
            if got[key] != wanted:
                failures.append(
                    f"COMPONENT {ref} {key.upper()} MISMATCH: "
                    f"sheet={got[key]!r} circuit.py={wanted!r}")
        # generator policy: anything DNP or without an orderable part number
        # must be excluded from KiCad-side BOM exports
        want_exbom = bool(want.get("dnp", False)) or not want.get("lcsc", "")
        if got["exclude_from_bom"] != want_exbom:
            failures.append(
                f"COMPONENT {ref} EXCLUDE_FROM_BOM MISMATCH: "
                f"sheet={got['exclude_from_bom']} expected={want_exbom}")

    if failures:
        print(f"check_netlist: {len(failures)} FAILURES")
        for f_ in failures:
            print(f_)
        sys.exit(1)
    print(f"check_netlist: OK — {len(expected)} named + {len(anon)} anonymous "
          f"nets match exactly, "
          f"{sum(len(p) for p in expected.values()) + sum(len(p) for p in anon.values())} "
          f"pin connections verified, {len(circuit.NC)} NC pins confirmed "
          f"unconnected, {len(comps)} components match on "
          f"value/footprint/LCSC/dnp")


if __name__ == "__main__":
    main()
