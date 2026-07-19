"""Shared pcbnew board-load + geometry helpers for verify/ tools and ad-hoc scripts.

Usage (from anywhere; module handles the generator import path itself):
    sys.path.insert(0, "<repo>/hardware/thermometer-c6/verify")
    from geom import load, rel, vi, seg_width, OX, OY
    b = load()                      # committed board, zones filled, connectivity built
    b = load("out/hand/thermometer-c6.kicad_pcb", fill=False)
    x, y = rel(pad.GetPosition())   # nm -> board-mm (origin removed)
    w = seg_width(track_or_via)     # handles the KiCad 10 track/via GetWidth split

Run ad-hoc scripts with PYTHONDONTWRITEBYTECODE=1; via width queries can spam
harmless "PCB_VIA::GetWidth called without a layer" asserts from OTHER code
paths to stderr -- drop with 2>/dev/null.
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "generator"))
import pcb_layout as pl  # noqa: E402

OX, OY = pl.BOARD["origin"]
DEFAULT_BOARD = os.path.join(PROJECT, "thermometer-c6.kicad_pcb")


def load(path=None, fill=True):
    """LoadBoard (default: the committed board); optionally fill zones and
    build connectivity -- needed before any GetUnconnectedCount()/pour query."""
    b = pcbnew.LoadBoard(path or DEFAULT_BOARD)
    if fill:
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.BuildConnectivity()
    return b


def rel(p):
    """VECTOR2I (nm) -> (x, y) board-mm with the (100,100) origin removed."""
    return (p.x / 1e6 - OX, p.y / 1e6 - OY)


def vi(x, y):
    """(x, y) board-mm -> VECTOR2I nm."""
    return pcbnew.VECTOR2I(int(round((x + OX) * 1e6)), int(round((y + OY) * 1e6)))


def seg_width(t):
    """Width in mm of a track, arc or via. Vias require a layer argument in
    KiCad 10 (PCB_VIA::GetWidth asserts without one); tracks take none."""
    if t.Type() == pcbnew.PCB_VIA_T:
        return t.GetWidth(pcbnew.F_Cu) / 1e6
    return t.GetWidth() / 1e6


def footprint(b, ref):
    """Footprint by reference, or raise KeyError."""
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        raise KeyError(ref)
    return fp
