"""Load KiCad symbol library files and extract pin geometry.

Symbols are returned with absolute pin connection points in *symbol* space
(y up). Placement transforms live in generate.py; this project places every
instance at rotation 0, unmirrored, so schematic position is simply
(sx + px, sy - py).

Handles `extends` (derived symbols) within the same library file. Multi-unit
symbols and alternate body styles are rejected: every part used on this board
is single-unit.
"""

import copy
import functools
import os

import sexp

SYSTEM_SYMBOL_DIR = "/usr/share/kicad/symbols"


class Pin:
    def __init__(self, number, name, x, y, angle, length, etype):
        self.number = str(number)
        self.name = str(name)
        self.x = float(x)  # connection point, symbol space (y up)
        self.y = float(y)
        self.angle = float(angle)  # direction pin points toward the body
        self.length = float(length)
        self.etype = etype  # electrical type: passive/input/output/power_in...

    def __repr__(self):
        return f"Pin({self.number} {self.name!r} at ({self.x},{self.y}) {self.etype})"


class Symbol:
    def __init__(self, lib_id, node, pins, rects=()):
        self.lib_id = lib_id  # e.g. "Device:R"
        self.node = node      # full sexp node, ready to embed in lib_symbols
        self.pins = pins      # list[Pin]
        self.rects = list(rects)  # body rectangles [(x1, y1, x2, y2)] symbol space

    def pin(self, number):
        for p in self.pins:
            if p.number == str(number):
                return p
        raise KeyError(f"{self.lib_id}: no pin {number!r}")


@functools.lru_cache(maxsize=None)
def _load_library(path):
    with open(path) as f:
        root = sexp.parse_one(f.read())
    if root[0] != "kicad_symbol_lib":
        raise ValueError(f"{path}: not a symbol library")
    syms = {}
    for s in sexp.children(root, "symbol"):
        syms[str(s[1])] = s
    return syms


def _resolve_extends(syms, name):
    node = syms.get(name)
    if node is None:
        raise KeyError(f"symbol {name!r} not found")
    ext = sexp.atom_after(node, "extends")
    if ext is None:
        return node
    parent = copy.deepcopy(_resolve_extends(syms, str(ext)))
    # Derived symbol: parent body/pins, child's own properties override.
    parent[1] = node[1]  # take child's name
    parent_props = {str(p[1]): i for i, p in enumerate(parent) if isinstance(p, list) and p and p[0] == "property"}
    for prop in sexp.children(node, "property"):
        key = str(prop[1])
        if key in parent_props:
            parent[parent_props[key]] = prop
        else:
            parent.append(prop)
    # Rename inner unit symbols "Parent_0_1" -> "Child_0_1"
    child_name = str(node[1])
    for sub in sexp.children(parent, "symbol"):
        subname = str(sub[1])
        base, _, suffix = subname.rpartition("_")
        base2, _, mid = base.rpartition("_")
        sub[1] = sexp.Quoted(f"{child_name}_{mid}_{suffix}")
    # Drop extends marker if it leaked through
    parent[:] = [c for c in parent if not (isinstance(c, list) and c and c[0] == "extends")]
    return parent


def _extract_pins(sym_node):
    pins = []
    units = set()
    for sub in sexp.children(sym_node, "symbol"):
        subname = str(sub[1])
        parts = subname.rsplit("_", 2)
        if len(parts) == 3:
            unit, style = int(parts[1]), int(parts[2])
        else:
            unit, style = 1, 1
        if style > 1:
            raise ValueError(f"{subname}: alternate body styles unsupported")
        if unit > 1:
            raise ValueError(f"{subname}: multi-unit symbols unsupported")
        units.add(unit)
        for pin in sexp.children(sub, "pin"):
            etype = pin[1]
            at = sexp.child(pin, "at")
            length = sexp.atom_after(pin, "length", 0)
            name = sexp.atom_after(pin, "name", "~")
            number = sexp.atom_after(pin, "number", "")
            pins.append(Pin(number, name, at[1], at[2],
                            at[3] if len(at) > 3 else 0, length, etype))
    return pins


def _extract_rects(sym_node):
    """Body graphic extents: rectangles and circles (transistor bodies)."""
    rects = []
    for sub in sexp.children(sym_node, "symbol"):
        for r in sexp.children(sub, "rectangle"):
            s = sexp.child(r, "start")
            e = sexp.child(r, "end")
            rects.append((min(s[1], e[1]), min(s[2], e[2]),
                          max(s[1], e[1]), max(s[2], e[2])))
        for c in sexp.children(sub, "circle"):
            ctr = sexp.child(c, "center")
            end = sexp.child(c, "end")
            rad = sexp.atom_after(c, "radius")
            if rad is None:
                rad = ((ctr[1] - end[1]) ** 2 + (ctr[2] - end[2]) ** 2) ** 0.5
            rects.append((ctr[1] - rad, ctr[2] - rad, ctr[1] + rad, ctr[2] + rad))
    return rects


def load_symbol(lib_id, local_lib_path=None):
    """lib_id is "LibName:SymbolName"; LibName "local" resolves to local_lib_path."""
    libname, _, symname = lib_id.partition(":")
    if libname == "local":
        path = local_lib_path
        if path is None:
            raise ValueError("local symbol requested but no local_lib_path given")
    else:
        path = os.path.join(SYSTEM_SYMBOL_DIR, libname + ".kicad_sym")
    syms = _load_library(path)
    node = copy.deepcopy(_resolve_extends(syms, symname))
    pins = _extract_pins(node)
    rects = _extract_rects(node)
    # Embedded lib_symbols entries use the full "Lib:Name" id
    node[1] = sexp.Quoted(lib_id)
    return Symbol(lib_id, node, pins, rects)
