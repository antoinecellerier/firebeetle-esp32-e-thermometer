#!/usr/bin/env python3
"""Where the tools put the artifacts they pull off a device.

Sweeps, archive images and PPK2 captures are hundreds of MB, gitignored, and
cited from docs/ by relative path. That combination needs one home that does
not move: resolve it from the repo root rather than the CWD, so an artifact
lands in the same place whether the tool was launched from the checkout, from
tools/, or from anywhere else.

    local/sweeps/     ppk2.py sweep output directories
    local/archives/   history.py backup partition images
    local/captures/   PPK2 raw/CSV captures (live --out, --raw-out, GUI exports)
    local/scratch/    ad-hoc bench files

$THERMO_LOCAL_DIR relocates the lot: a full sweep is a few hundred MB and
ppk2.py refuses to start when the target filesystem is short, so there has to
be a way to point it at a bigger disk without passing --out-dir every time.
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.environ.get("THERMO_LOCAL_DIR", os.path.join(REPO, "local"))


def artifact_dir(kind):
    """local/<kind>/, created if absent.

    Created eagerly because callers hand the path straight to os.statvfs or to
    open() for a file inside it.
    """
    path = os.path.join(LOCAL_DIR, kind)
    os.makedirs(path, exist_ok=True)
    return path


def rel(path):
    """Repo-relative form for printing, so the output pastes into docs/.

    Falls back to the absolute path for anything outside the checkout, which
    is where $THERMO_LOCAL_DIR and an explicit --out-dir can land.
    """
    abs_path = os.path.abspath(path)
    prefix = REPO + os.sep
    return abs_path[len(prefix):] if abs_path.startswith(prefix) else abs_path
