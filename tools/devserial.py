#!/usr/bin/env python3
"""Read the device's serial console, with or without resetting it first.

    devserial.py boot                        # DTR/RTS reset, then stream the boot log
    devserial.py boot --grep "Boot count|rst:"
    devserial.py watch                       # attach to a running board, no reset

`boot` drives the classic auto-reset pulse (DTR low, RTS pulsed) so the banner is
captured from the first line — `pio run -t upload` resets on exit and the banner
is usually gone before you can attach.

`watch` never touches the control lines. Use it on a board you must not disturb:
a reset presents as POWERON_RESET and wipes RTC state (boot counters, the
in-progress hour, the drift window).

Needs pyserial. The zero-install path is the PlatformIO venv, which already has
it:

    ~/.platformio/penv/bin/python3 tools/devserial.py boot
"""

import argparse
import glob
import re
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial missing — run with ~/.platformio/penv/bin/python3, "
             "or pip install -r tools/requirements.txt")


def find_port():
    """FireBeetle enumerates as ttyUSB (CP2102/CH340); the C6 boards as ttyACM
    (USB-Serial-JTAG). Prefer the UART bridge when both are present."""
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    sys.exit("no /dev/ttyUSB* or /dev/ttyACM* found")


def stream(port, baud, timeout_s, pattern, reset):
    with serial.Serial(port, baud, timeout=1) as s:
        if reset:
            # Classic auto-reset: EN low via RTS while BOOT (DTR) stays high, the
            # same pulse esptool uses. A no-op on USB-Serial-JTAG, which reboots
            # by re-enumerating instead.
            s.setDTR(False)
            s.setRTS(True)
            time.sleep(0.1)
            s.setRTS(False)
        deadline = time.time() + timeout_s
        rx = re.compile(pattern) if pattern else None
        while time.time() < deadline:
            line = s.readline()
            if not line:
                continue
            text = line.decode("utf8", "replace").rstrip()
            if rx is None or rx.search(text):
                print(text, flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["boot", "watch"],
                   help="boot: reset then stream. watch: attach without resetting")
    p.add_argument("--port", help="default: first ttyUSB*, else first ttyACM*")
    p.add_argument("--baud", type=int, default=115200,
                   help="ignored by USB-Serial-JTAG (C6); default 115200")
    p.add_argument("--timeout", type=float, default=25.0,
                   help="seconds to stream before exiting (default 25)")
    p.add_argument("--grep", metavar="REGEX",
                   help="only print matching lines, e.g. 'Boot count|base snapshot'")
    args = p.parse_args(argv)

    port = args.port or find_port()
    print(f"[{port} @ {args.baud}, {args.mode}, {args.timeout:g}s]", file=sys.stderr)
    try:
        stream(port, args.baud, args.timeout, args.grep, reset=args.mode == "boot")
    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        # The C6 re-enumerates on reset, so a mid-capture disappearance is normal.
        sys.exit(f"serial error: {e}")


if __name__ == "__main__":
    main()
