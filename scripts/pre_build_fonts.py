"""PlatformIO pre-build script: generate custom bitmap fonts and inject git hash."""
Import("env")

import subprocess
import os

project_dir = env.get("PROJECT_DIR", os.getcwd())
script = os.path.join(project_dir, "scripts", "generate_font.py")
secrets = os.path.join(project_dir, "include", "local-secrets.h")
font_config = os.path.join(project_dir, "include", "generated", "font_config.h")

# Regenerate fonts NOW, at script-eval time — before SCons builds the DAG.
# A buildprog pre-action fires at LINK time, after DisplayRenderer.o is already
# compiled, so a display change (or a stale font_config.h) would land one build
# late: the object keeps the previous panel's font and the temperature renders
# at the wrong size (e.g. 80pt on a 200x200 panel). Running here guarantees
# font_config.h exists and is fresh before any compilation, so SCons recompiles
# dependents in the same build.
args = ["python3", script]
# Force bitmap regen when display config (local-secrets.h) is newer than output
if os.path.isfile(secrets) and os.path.isfile(font_config):
    if os.path.getmtime(secrets) > os.path.getmtime(font_config):
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
