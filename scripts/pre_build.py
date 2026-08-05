"""PlatformIO pre-build script: select the rig, generate fonts, inject git hash."""
Import("env")

import os
import re
import subprocess
import sys

project_dir = env.get("PROJECT_DIR", os.getcwd())
scripts_dir = os.path.join(project_dir, "scripts")
sys.path.insert(0, scripts_dir)
import gen_rig_config
import generate_font

font_config = os.path.join(project_dir, "include", "generated", "font_config.h")

# Everything here runs NOW, at script-eval time — before SCons builds the DAG.
# A buildprog pre-action fires at LINK time, after DisplayRenderer.o is already
# compiled, so a display change (or a stale font_config.h) would land one build
# late: the object keeps the previous panel's font and the temperature renders
# at the wrong size (e.g. 80pt on a 200x200 panel). Running here guarantees the
# rig selection and font_config.h are fresh before any compilation, so SCons
# recompiles dependents in the same build.

# The rig names the wired hardware: panel, sensor, power gate, LEDs. Each env
# declares its own, so a bare `pio run -e <env>` is unambiguous; RIG= overrides
# for a bench swap or a second board sharing one env.
rig = os.environ.get("RIG") or env.GetProjectOption("custom_rig", None)
rig_header = gen_rig_config.write(rig)
print(f"Rig: {rig} ({os.path.relpath(rig_header, project_dir)})")

gen_rig_config.check_template_lists_every_panel(generate_font.DISPLAYS)


def configured_size():
    """Panel dimensions the active rig asks for; None under DISABLE_DISPLAY.
    Font sizes derive from dimensions alone, so two same-sized panels are
    interchangeable here and switching between them needs no regeneration."""
    content = open(rig_header).read()
    for define, size in generate_font.DISPLAYS.items():
        if re.search(rf"^\s*#define\s+{define}\b", content, re.MULTILINE):
            return size
    return None


def generated_size():
    """Dimensions font_config.h was generated for. None when it is missing, was
    written by --all (simulator mode), or holds the no-display fallback."""
    if not os.path.isfile(font_config):
        return None
    text = open(font_config).read()
    dims = [re.search(rf"^#define\s+FONT_CONFIG_{ax}\s+(\d+)", text, re.MULTILINE)
            for ax in ("W", "H")]
    return tuple(int(m.group(1)) for m in dims) if all(dims) else None


# Regenerate when the fonts on disk were sized for a different panel than the
# rig asks for. A content test, not an mtime one: the config source is now
# swapped between files rather than edited in place, and a rig header checked
# out from git is routinely older than the fonts it invalidates.
args = ["python3", os.path.join(scripts_dir, "generate_font.py")]
if configured_size() != generated_size():
    args.append("--force")
subprocess.check_call(args)

# Inject short git commit hash as GIT_HASH define
try:
    git_hash = subprocess.check_output(
        ["git", "describe", "--always", "--dirty"],
        cwd=project_dir, text=True
    ).strip()
except Exception:
    git_hash = "unknown"
env.Append(CPPDEFINES=[("GIT_HASH", env.StringifyMacro(git_hash))])
