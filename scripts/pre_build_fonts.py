"""PlatformIO pre-build script: generate custom bitmap fonts if needed."""
Import("env")

import subprocess
import os

project_dir = env.get("PROJECT_DIR", os.getcwd())
script = os.path.join(project_dir, "scripts", "generate_font.py")

def generate_fonts(source, target, env):
    subprocess.check_call(["python3", script])

env.AddPreAction("buildprog", generate_fonts)
