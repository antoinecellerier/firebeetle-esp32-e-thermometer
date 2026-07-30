#!/usr/bin/env python3
"""Read the device's serial console, with or without resetting it first.

    devserial.py boot                        # DTR/RTS reset, then stream the boot log
    devserial.py boot --grep "Boot count|rst:"
    devserial.py watch                       # attach to a running board, no reset
    devserial.py flashwait --env thermometer_c6_release   # upload on the next wake

`boot` drives the classic auto-reset pulse (DTR low, RTS pulsed) so the banner is
captured from the first line — `pio run -t upload` resets on exit and the banner
is usually gone before you can attach.

`watch` deasserts DTR and RTS as early as it can, but **it cannot make attaching
safe**: on Linux the cdc-acm driver raises both lines during port activation,
before any of this code runs. On the C6 boards DTR reaches GPIO9 — both the BOOT
strap and the firmware's shutdown button — and RTS reaches EN, so opening the
port at all can reset the chip (wiping the boot counters, the in-progress hour
and the drift window), park it in the ROM bootloader, or press its shutdown
button. Attaching is intrusive; on a board mid-measurement, do not attach.

`flashwait` polls /dev/serial/by-id for the board and runs `pio run -t upload` the
instant it enumerates. A deep-sleeping C6 is not on the bus at all, so this is how
a sleeping board gets reflashed without reaching for BOOT+RST. The custom board
can hold the port open by itself (USB service window); everywhere else, this is
the way.

Needs pyserial. The zero-install path is the PlatformIO venv, which already has
it:

    ~/.platformio/penv/bin/python3 tools/devserial.py boot
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import time

PIO = os.path.expanduser("~/.platformio/penv/bin/pio")

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


# Stable across re-enumeration, unlike the ttyACM number: when the ESP32 drops
# off the bus another device can inherit ttyACM0, and esptool then syncs against
# the wrong thing.
ESPRESSIF_BY_ID = "/dev/serial/by-id/*Espressif*"


def find_espressif_port():
    ports = sorted(glob.glob(ESPRESSIF_BY_ID))
    return ports[0] if ports else None


def flashwait(env, poll_s, timeout_s, extra):
    """Wait for a sleeping C6 to show up on the bus, then flash it in that window.

    A deep-sleeping C6 presents no USB device at all, so there is nothing for
    esptool to reset into download mode until the board wakes on its own. Polling
    for the port and launching the moment it appears catches that window, which is
    what makes an unattended reflash possible without the BOOT button — the
    firmware-side USB service window (custom board only) is the standing version
    of the same trick.
    """
    # Build first. The window this waits for is one wake — a second or two — and
    # a cold PlatformIO invocation spends longer than that on its own startup and
    # dependency check, so building after the port appears would miss the window
    # it just caught and burn the wake.
    print(f"[building {env}]", file=sys.stderr)
    rc = subprocess.call([PIO, "run", "-e", env] + list(extra))
    if rc != 0:
        return rc

    print(f"[waiting up to {timeout_s:g}s for {ESPRESSIF_BY_ID}]", file=sys.stderr)
    deadline = time.time() + timeout_s
    while True:
        port = find_espressif_port()
        if port:
            break
        if time.time() >= deadline:
            sys.exit("no Espressif device appeared — is the board powered, and "
                     "is its wake interval shorter than the timeout?")
        time.sleep(poll_s)

    print(f"[{port} appeared — uploading {env}]", file=sys.stderr)
    cmd = [PIO, "run", "-e", env, "-t", "upload", "--upload-port", port] + list(extra)
    # esptool's own default_reset drives download mode from here; the board being
    # awake is the only thing that was missing. Its exit code is the result.
    return subprocess.call(cmd)


def stream(port, baud, timeout_s, pattern, reset):
    # Configure before opening, so the lines are released as early as userspace
    # can release them. It narrows the window, it does not close it: cdc-acm
    # raises DTR and RTS during port activation, before this code gets control,
    # and on the C6 those reach GPIO9 (BOOT strap and shutdown button) and EN.
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 1
    s.dtr = False
    s.rts = False
    with s:
        if reset:
            # Classic auto-reset: EN low via RTS while BOOT (DTR) stays high, the
            # same pulse esptool uses. On USB-Serial-JTAG the controller emulates
            # the same two signals, so DTR/RTS still reach GPIO9/EN — the port
            # then drops off the bus and re-enumerates rather than staying up.
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
    p.add_argument("mode", choices=["boot", "watch", "flashwait"],
                   help="boot: reset then stream. watch: attach without "
                        "resetting. flashwait: wait for a wake, then upload")
    p.add_argument("--port", help="default: first ttyUSB*, else first ttyACM*")
    p.add_argument("--baud", type=int, default=115200,
                   help="ignored by USB-Serial-JTAG (C6); default 115200")
    p.add_argument("--timeout", type=float,
                   help="seconds to stream before exiting (default 25); for "
                        "flashwait, how long to wait for the board to appear "
                        "(default 180)")
    p.add_argument("--grep", metavar="REGEX",
                   help="only print matching lines, e.g. 'Boot count|base snapshot'")
    p.add_argument("--env", default="thermometer_c6_debug",
                   help="flashwait: PlatformIO env to upload (default "
                        "thermometer_c6_debug)")
    p.add_argument("--poll", type=float, default=0.2,
                   help="flashwait: seconds between port checks (default 0.2)")
    p.add_argument("pio_args", nargs="*", metavar="-- PIO ARG",
                   help="flashwait: extra args passed through to pio run")
    args = p.parse_args(argv)

    # Only flashwait passes anything through. Without this, `watch /dev/ttyACM1`
    # — the natural slip for `--port /dev/ttyACM1` — parses fine, the path lands
    # here unused, and the capture silently comes from whatever find_port()
    # picked first, which with two boards attached is the wrong one.
    if args.pio_args and args.mode != "flashwait":
        p.error(f"unexpected argument(s) for {args.mode}: "
                f"{' '.join(args.pio_args)}")

    if args.mode == "flashwait":
        # Waiting out a whole sleep interval is the normal case, and a release
        # build sleeps 60s between wakes, so the streaming default is far too
        # short here. Left unset rather than compared against, so an explicitly
        # requested timeout is honoured whatever value it happens to be.
        timeout = 180.0 if args.timeout is None else args.timeout
        return flashwait(args.env, args.poll, timeout, args.pio_args)

    timeout = 25.0 if args.timeout is None else args.timeout
    port = args.port or find_port()
    print(f"[{port} @ {args.baud}, {args.mode}, {timeout:g}s]", file=sys.stderr)
    try:
        stream(port, args.baud, timeout, args.grep, reset=args.mode == "boot")
    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        # The C6 re-enumerates on reset, so a mid-capture disappearance is normal.
        sys.exit(f"serial error: {e}")


if __name__ == "__main__":
    sys.exit(main())
