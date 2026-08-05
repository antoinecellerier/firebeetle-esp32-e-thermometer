"""PlatformIO pre-upload gate: refuse to flash a rig the board disagrees with.

Both rev A boards share one env, so `pio run -e thermometer_c6_* -t upload`
compiles cleanly for whichever panel that env's rig names and then meets whatever
panel is actually on the bench. Nothing catches it: the rig cross-checks only see
board macros, both rigs are valid for the env, and the failure it produces cannot
report itself — the panel is what breaks, so there is no frame to put a badge on.

The board already knows, though. HistoryStore stamps the panel, sensor and board
its firmware was built for into the `history` partition header, and that
partition survives reflashing (`.claude/rules/build.md`). So read 52 bytes back
before writing anything.

Only the panel is checked. A wrong sensor or a wrong board macro still renders a
frame, and the running firmware says so on it — `! SENSOR`, and a reading it
refuses to trust. Those need no upload gate; the panel is the gap.

Skipped, out loud, whenever the answer would not be decisive: no archive yet, an
unreadable header, no port. Overrides:

    ALLOW_RIG_CHANGE=1   proceed despite a real mismatch (a deliberate panel swap)
    SKIP_BOARD_CHECK=1   skip the read entirely (tight reflash loops)

Costs one esptool connect. That enters download mode and so resets the chip,
wiping RTC — but the upload about to follow does that anyway, so it adds no
hazard the flash did not already carry.

Importable without SCons so the parsing and the verdict can be tested against a
saved archive image, with no board attached — see the __main__ block.
"""

import os
import re
import sys

try:
    Import("env")  # noqa: F821 — injected by SCons; absent when imported for tests
    PROJECT_DIR = env.get("PROJECT_DIR", os.getcwd())
except NameError:
    env = None
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(PROJECT_DIR, "tools"))


def panel_names():
    """USE_* -> the string the firmware writes into the archive header.

    Parsed out of HistoryStore.cpp's own panel_name() rather than copied here: a
    second table would be free to drift, and it would drift silently into
    blocking correct uploads — a gate that cries wolf gets switched off.
    """
    src = os.path.join(PROJECT_DIR, "src", "HistoryStore.cpp")
    with open(src) as f:
        body = f.read()
    m = re.search(r"panel_name\(void\)\s*\{(.*?)\n\}", body, re.S)
    if not m:
        return {}
    return dict(re.findall(r'defined\((USE_\w+)\)\s*\n\s*return\s+"([^"]+)"',
                           m.group(1)))


def expected_panel(rig=None):
    """(rig name, panel string) for a rig; panel None when none is wired.

    Defaults to the rig this build selected, via the file pre_build.py generated.
    """
    if rig is None:
        generated = os.path.join(PROJECT_DIR, "include", "generated", "rig_config.h")
        with open(generated) as f:
            m = re.search(r'#define\s+RIG_NAME\s+"([^"]+)"', f.read())
        if not m:
            return None, None
        rig = m.group(1)

    header = os.path.join(PROJECT_DIR, "include", "rigs", rig + ".h")
    if not os.path.isfile(header):
        return rig, None
    with open(header) as f:
        text = f.read()
    # Uncommented directives only — the menu in _template.h is all "//#define".
    defines = set(re.findall(r"^\s*#define\s+(\w+)", text, re.MULTILINE))
    if "DISABLE_DISPLAY" in defines:
        return rig, None
    for macro, panel in panel_names().items():
        if macro in defines:
            return rig, panel
    return rig, None


def verdict(rig, want, header):
    """None when it is safe to flash, else the message explaining why not."""
    got = header["panel"]
    if got == want:
        return None
    return (f"\n*** BOARD CHECK FAILED ***\n"
            f"  device {header['mac']} ({header['board']}) last ran {got}\n"
            f"  this build is rig {rig}, which drives {want}\n"
            f"  last flashed from {header['git_hash']}\n\n"
            f"  Flashing it would drive the wrong panel — which fails silently:\n"
            f"  the frame on screen stays as it is and nothing can report it.\n\n"
            f"  Wrong rig?  RIG=<name> pio run -e <env> -t upload\n"
            f"  Deliberate panel swap?  ALLOW_RIG_CHANGE=1 pio run ...\n")


def read_device_header(port=None):
    """The board's stored identity. 52 bytes, one connect."""
    import history

    off, _ = history.history_partition()
    esp = history._connect(history._resolve_port(port), 921600)
    try:
        blob = esp.read_flash(off, history.STORE_HDR.size)
    finally:
        # Same reason read_device() does it: pyserial holds an exclusive lock,
        # and the upload that follows needs the port back.
        try:
            esp.hard_reset()
        except Exception:
            pass
        try:
            esp._port.close()
        except Exception:
            pass
    return history.store_header(blob)


def check_board_identity(target, source, env):
    if os.environ.get("SKIP_BOARD_CHECK"):
        return

    rig, want = expected_panel()
    if not want:
        print(f"Board check: rig {rig} drives no panel — skipped")
        return

    try:
        header = read_device_header(env.get("UPLOAD_PORT") or None)
    except (Exception, SystemExit) as e:
        # Never block on the check itself failing. A virgin board, one that has
        # never slept, an old format, a busy port — none of those are evidence of
        # a wrong rig, and refusing to flash would make the gate into the problem
        # it exists to prevent.
        #
        # SystemExit is listed explicitly because history.py signals every one of
        # those that way, and it derives from BaseException — a bare
        # `except Exception` lets it straight through and turns each into a hard
        # upload failure. A board that had merely gone to sleep was enough.
        print(f"Board check: no usable archive header ({e}) — skipped")
        return

    bad = verdict(rig, want, header)
    if not bad:
        print(f"Board check: {header['mac']} {header['board']} carries "
              f"{header['panel']} — matches rig {rig}")
        return
    if os.environ.get("ALLOW_RIG_CHANGE"):
        print(bad + "  ALLOW_RIG_CHANGE set — proceeding anyway.\n")
        return
    raise SystemExit(bad)


if env is not None:
    # Run straight off the command-line target rather than through a SCons hook.
    #
    # AddPreAction does not work here, in either spelling and from either script
    # phase. PlatformIO registers `upload` with AddPlatformTarget *after* every
    # extra script has been evaluated, so at this point there is no node to attach
    # to: passing the name "upload" makes SCons resolve a File node of that name,
    # which nothing ever builds, and asking for the Alias creates a fresh empty
    # one. Both register successfully and then never fire — the gate printed
    # nothing and flashed the wrong rig anyway, which is worse than no gate at
    # all, because silence reads as a pass. Verified on hardware, not reasoned:
    # rev A board 2 took two wrong-rig images before this line was right.
    #
    # Checking the target directly also fails before the ~60s compile rather than
    # after it.
    from SCons.Script import COMMAND_LINE_TARGETS

    if "upload" in COMMAND_LINE_TARGETS:
        check_board_identity(None, None, env)


if __name__ == "__main__":
    # Offline self-check: decode a saved archive image and run every rig against
    # it, so the parsing and the verdict are exercised without a board.
    #   python3 scripts/upload_gate.py hist-xiao_esp32c6-fffe16-2026-08-05.bin
    import history

    with open(sys.argv[1], "rb") as f:
        hdr = history.store_header(f.read())
    print(f"image: {hdr['mac']} {hdr['board']} {hdr['panel']}/{hdr['sensor']} "
          f"@{hdr['git_hash']}")
    print(f"panel_name() table: {panel_names()}\n")
    rigs = sorted(n[:-2] for n in os.listdir(os.path.join(PROJECT_DIR, "include", "rigs"))
                  if n.endswith(".h") and not n.startswith("_"))
    for rig in rigs:
        _, want = expected_panel(rig)
        if not want:
            print(f"  {rig:20} no panel — would skip")
            continue
        bad = verdict(rig, want, hdr)
        print(f"  {rig:20} {want:15} {'BLOCK' if bad else 'allow'}")
