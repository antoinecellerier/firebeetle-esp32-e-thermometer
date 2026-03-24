"""PlatformIO pre-build script: generate custom bitmap fonts if needed."""
Import("env")

import subprocess
import os

project_dir = env.get("PROJECT_DIR", os.getcwd())
script = os.path.join(project_dir, "scripts", "generate_font.py")
secrets = os.path.join(project_dir, "include", "local-secrets.h")
font_config = os.path.join(project_dir, "include", "generated", "font_config.h")

def generate_fonts(source, target, env):
    # Force regeneration when display config (local-secrets.h) has changed
    args = ["python3", script]
    if os.path.isfile(secrets) and os.path.isfile(font_config):
        if os.path.getmtime(secrets) > os.path.getmtime(font_config):
            args.append("--force")
    subprocess.check_call(args)

env.AddPreAction("buildprog", generate_fonts)
