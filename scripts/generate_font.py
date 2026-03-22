#!/usr/bin/env python3
"""
Generate optimal Adafruit GFX bitmap fonts based on display configuration.

Computes the ideal temperature font point size from the display resolution
so the temperature fills the right proportion of the screen. Only generates
fonts for the configured display, saving flash on smaller panels.

Usage:
    python3 scripts/generate_font.py                  # generate for configured display
    python3 scripts/generate_font.py --force           # regenerate even if cached
    python3 scripts/generate_font.py --all             # generate for all displays (simulator)
"""

import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GFX_LIB = os.path.join(PROJECT_ROOT, ".pio", "libdeps",
                        "dfrobot_firebeetle2_esp32e_debug", "Adafruit GFX Library")
FONTCONVERT_DIR = os.path.join(GFX_LIB, "fontconvert")
FONTCONVERT_BIN = os.path.join(FONTCONVERT_DIR, "fontconvert")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "include", "generated")

TTF_PATH = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"

# Character ranges for generated fonts
TEMP_CHAR_FIRST = 32   # space
TEMP_CHAR_LAST = 67    # 'C' — only digits, punctuation, and C suffix needed
ALERT_CHAR_FIRST = 32  # space
ALERT_CHAR_LAST = 90   # 'Z' — full uppercase for "EMPTY BATTERY RECHARGE!"

# GFXglyph uses int8_t for yOffset, so max font size is ~80pt
MAX_PT = 80

# Display configurations: (define_name, width, height, rotation)
# Width/height are AFTER rotation (what display.width()/height() returns)
DISPLAYS = {
    "USE_576_T81":  (920, 680),
    "USE_290_I6FD": (296, 128),
    "USE_213_M21":  (212, 104),
    "USE_154_Z90":  (200, 200),
    "USE_154_M09":  (200, 200),
    "USE_154_GDEY": (200, 200),
}

# Adafruit GFX library already ships these sizes — no need to regenerate
LIBRARY_FONT_SIZES = {9, 12, 18, 24}


def px_to_pt(pixels):
    """Convert desired pixel height to font point size.
    Empirical: FreeSansBold digits are ~1.4px per pt."""
    return min(int(pixels / 1.4), MAX_PT)


def compute_font_sizes(w, h):
    """Compute optimal font point sizes for all display text elements.

    Returns a dict with keys: 'temp', 'alert'
    - temp: main temperature reading
    - alert: empty battery warning text

    Library fonts (9pt, 12pt, 18pt, 24pt) are used for chart labels,
    info bar, and footer — they're already clean at native size.
    """
    landscape = w > h * 1.5

    # Temperature zone dimensions (must match compute_layout in DisplayRenderer.cpp)
    if landscape:
        temp_zone_h = h - 10  # full content height
        temp_zone_w = int(w * 0.45)  # left 45%
    elif min(w, h) >= 400:
        remaining = h - 30 - 24
        temp_zone_h = int(remaining * 0.25)
        temp_zone_w = w
    else:
        remaining = h - 22 - 12
        temp_zone_h = int(remaining * 0.38)
        temp_zone_w = w

    # Temperature: as large as possible within both height and width.
    # Height constraint: fill ~80% of zone height
    height_pt = px_to_pt(temp_zone_h * 0.8)
    # Width constraint: "XX.X C" is approximately 4.8 × pt pixels wide
    width_pt = min(MAX_PT, int(temp_zone_w * 0.9 / 4.8))
    temp_pt = min(height_pt, width_pt)

    # Alert (empty battery): fill ~25% of the total display height,
    # so "EMPTY BATTERY RECHARGE!" (3 lines) is prominent
    alert_pt = px_to_pt(h * 0.25 / 3)

    return {'temp': temp_pt, 'alert': alert_pt}


def detect_display():
    """Read local-secrets.h to find which display is configured."""
    secrets_path = os.path.join(PROJECT_ROOT, "include", "local-secrets.h")
    if not os.path.isfile(secrets_path):
        return None

    with open(secrets_path) as f:
        content = f.read()

    for define in DISPLAYS:
        # Match uncommented #define lines
        if re.search(rf"^\s*#define\s+{define}\b", content, re.MULTILINE):
            return define
    return None


def build_fontconvert():
    """Build fontconvert from source if the binary doesn't exist."""
    if os.path.isfile(FONTCONVERT_BIN):
        return
    if not os.path.isdir(FONTCONVERT_DIR):
        print(f"ERROR: Adafruit GFX library not found at {GFX_LIB}")
        print("Run 'pio run' first to download dependencies.")
        sys.exit(1)
    print("Building fontconvert...")
    subprocess.check_call(["make", "-C", FONTCONVERT_DIR], stdout=subprocess.DEVNULL)


def generate_font(pt_size, char_first, char_last, force=False):
    """Generate a font header at the given point size and char range."""
    name = f"FreeSansBold{pt_size}pt7b"
    # Include char range in filename to distinguish temp vs alert variants
    suffix = "" if char_last == TEMP_CHAR_LAST else f"_az"
    full_name = f"FreeSansBold{pt_size}pt7b{suffix}"
    output_path = os.path.join(OUTPUT_DIR, f"{full_name}.h")

    if os.path.isfile(output_path) and not force:
        return full_name

    if not os.path.isfile(TTF_PATH):
        print(f"ERROR: TTF font not found: {TTF_PATH}")
        print("Install: sudo apt install fonts-freefont-ttf")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    build_fontconvert()

    print(f"Generating {full_name} ({pt_size}pt, chars {char_first}-{char_last})...")
    result = subprocess.run(
        [FONTCONVERT_BIN, TTF_PATH, str(pt_size), str(char_first), str(char_last)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: fontconvert failed: {result.stderr}")
        sys.exit(1)

    # fontconvert names the struct based on the font name and size, not our suffix.
    # We need the struct name to match what C code expects.
    output_text = result.stdout
    if suffix:
        # Rename the struct/array to include our suffix
        output_text = output_text.replace(
            f"FreeSansBold{pt_size}pt7b", full_name)

    with open(output_path, "w") as f:
        f.write(output_text)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"  -> {output_path} ({size_kb:.0f}KB)")
    return full_name


def write_font_config(display_fonts):
    """Write include/generated/font_config.h with font selection logic.

    display_fonts: list of (define_name, w, h, temp_pt, alert_pt, temp_name, alert_name)
    """
    config_path = os.path.join(OUTPUT_DIR, "font_config.h")

    # Collect unique font names (may include _az suffix for alert variants)
    all_fonts = {}  # name -> pt
    for _, _, _, temp_pt, alert_pt, temp_name, alert_name in display_fonts:
        all_fonts[temp_name] = temp_pt
        all_fonts[alert_name] = alert_pt

    with open(config_path, "w") as f:
        f.write("// Auto-generated by scripts/generate_font.py — do not edit\n")
        f.write("#pragma once\n\n")
        for name, pt in sorted(all_fonts.items(), key=lambda x: x[1]):
            if pt in LIBRARY_FONT_SIZES and '_az' not in name:
                f.write(f'#include <Fonts/{name}.h>\n')
            else:
                f.write(f'#include "generated/{name}.h"\n')

        f.write("\n// Select optimal font based on display dimensions\n")
        f.write("inline const GFXfont* get_temp_font(int16_t w, int16_t h) {\n")
        for _, dw, dh, _, _, temp_name, _ in display_fonts:
            f.write(f"  if (w == {dw} && h == {dh}) return &{temp_name};\n")
        default_name = display_fonts[-1][5]
        f.write(f"  return &{default_name};\n")
        f.write("}\n\n")

        f.write("inline const GFXfont* get_alert_font(int16_t w, int16_t h) {\n")
        for _, dw, dh, _, _, _, alert_name in display_fonts:
            f.write(f"  if (w == {dw} && h == {dh}) return &{alert_name};\n")
        default_alert = display_fonts[-1][6]
        f.write(f"  return &{default_alert};\n")
        f.write("}\n")


def main():
    force = "--force" in sys.argv
    gen_all = "--all" in sys.argv

    def ensure_temp_font(pt, force):
        """Generate a temperature font (digits + C only)."""
        if pt in LIBRARY_FONT_SIZES:
            return f"FreeSansBold{pt}pt7b"
        return generate_font(pt, TEMP_CHAR_FIRST, TEMP_CHAR_LAST, force)

    def ensure_alert_font(pt, force):
        """Generate an alert font (full uppercase alphabet)."""
        if pt in LIBRARY_FONT_SIZES:
            return f"FreeSansBold{pt}pt7b"
        return generate_font(pt, ALERT_CHAR_FIRST, ALERT_CHAR_LAST, force)

    if gen_all:
        # Simulator mode: generate for all displays
        display_fonts = []
        seen = set()
        for define, (w, h) in DISPLAYS.items():
            key = (w, h)
            if key in seen:
                continue
            seen.add(key)
            sizes = compute_font_sizes(w, h)
            temp_name = ensure_temp_font(sizes['temp'], force)
            alert_name = ensure_alert_font(sizes['alert'], force)
            display_fonts.append((define, w, h, sizes['temp'], sizes['alert'], temp_name, alert_name))
            print(f"  {define} ({w}x{h}): temp={sizes['temp']}pt alert={sizes['alert']}pt")
        write_font_config(display_fonts)
    else:
        # Device mode: generate only for the configured display
        display = detect_display()
        if display is None:
            print("No display configured (DISABLE_DISPLAY or missing)")
            write_font_config([("NONE", 200, 200, 24, 18,
                                 "FreeSansBold24pt7b", "FreeSansBold18pt7b")])
            return

        w, h = DISPLAYS[display]
        sizes = compute_font_sizes(w, h)
        print(f"Display: {display} ({w}x{h})")
        print(f"  Temperature font: {sizes['temp']}pt")
        print(f"  Alert font: {sizes['alert']}pt")

        temp_name = ensure_temp_font(sizes['temp'], force)
        alert_name = ensure_alert_font(sizes['alert'], force)
        write_font_config([(display, w, h, sizes['temp'], sizes['alert'], temp_name, alert_name)])


if __name__ == "__main__":
    main()
