#!/usr/bin/env python3
"""PPK2 trace analysis: charge per region, delimited by the firmware's own markers.

Two data sources, one analysis path:

    ppk2.py csv  trace.csv                 # export from nRF Connect Power Profiler
    ppk2.py live --seconds 30              # ampere meter (DUT externally powered)
    ppk2.py live --rail bat --power-cycle  # source meter; see SAFETY below

The point of the marker-driven regions is that charge figures stop depending on
where a human dragged a selection. `-DPPK2_DEBUG` drives two GPIOs:

    D0 (GPIO17)  HIGH for the whole awake phase (setup -> start_deep_sleep)
    D1 (GPIO16)  HIGH during a panel refresh, and again during an archive
                 flush -- the flush is preceded by three 50ms blips, which is
                 the only way to tell the two apart

`ppk2_selftest()` runs before D0 first goes high and emits 5x20ms on D0 then
10x10ms on D1. That fingerprint is the probe-orientation check, and on a
DISABLE_SERIAL build it is the *only* one available, since the selftest's
pass/fail line goes to a console that is not there.

SAFETY
------
The PPK2 exposes no VOUT sense, so nothing here can detect which rail the leads
are on. Ampere meter is therefore the default: in that mode the PPK2 does not
source at all and over-volting is structurally impossible. Sourcing requires an
explicit --rail, is clamped per rail, and demands a typed confirmation of the
physical connection. See .claude/skills/device-session/SKILL.md.
"""

import argparse
import csv
import json
import os
import re
import sys
import time

# The PPK2 samples at a fixed 100 kSps. ppk2_api does not expose this, so it is
# restated here: it is the device's specified rate, not something measured.
PPK2_SAMPLE_HZ = 100_000

# Per-rail limits. 3V3 feeds the MCU, panel and sensor directly and the C6's
# datasheet absolute-max VDD is 3.6V, so the ceiling is a refusal, not a clip.
# BAT goes to the XIAO's buck input; 3.7V is the lowest verified-healthy point
# from the fine sweep in docs/notes.md, below which the rail enters a sag band.
RAILS = {
    "3v3": {"min_mv": 3000, "max_mv": 3300, "abort_ma": 200.0,
            "check": "PPK2 leads on the 3V3 rail (NOT the battery pads)"},
    "bat": {"min_mv": 3000, "max_mv": 4200, "abort_ma": 600.0,
            "check": "PPK2 leads on the XIAO's soldered BAT connector "
                     "(NOT the hat's JST2, which sources nothing)"},
}

STATE_PATH = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "thermometer-ppk2-state.json")


# --- Trace container and analysis (source-agnostic) ------------------------

class Trace:
    """Samples plus optional digital channels. t in seconds, current in uA."""

    def __init__(self, t, current_ua, digital=None):
        self.t = t
        self.current_ua = current_ua
        # digital: dict {channel_index: [0/1, ...]} for channels present
        self.digital = digital or {}

    def __len__(self):
        return len(self.current_ua)

    def integrate(self, i0, i1):
        """Trapezoidal charge over [i0, i1). Returns (seconds, mean_uA, mC)."""
        i1 = min(i1, len(self.current_ua))
        if i1 - i0 < 2:
            return 0.0, 0.0, 0.0
        charge_uc = 0.0
        for k in range(i0, i1 - 1):
            dt = self.t[k + 1] - self.t[k]
            charge_uc += 0.5 * (self.current_ua[k] + self.current_ua[k + 1]) * dt
        dur = self.t[i1 - 1] - self.t[i0]
        mean = charge_uc / dur if dur > 0 else 0.0
        return dur, mean, charge_uc / 1000.0

    def spans(self, channel):
        """Contiguous HIGH runs on a digital channel, as (i0, i1) index pairs."""
        bits = self.digital.get(channel)
        if not bits:
            return []
        out, start = [], None
        for i, b in enumerate(bits):
            if b and start is None:
                start = i
            elif not b and start is not None:
                out.append((start, i))
                start = None
        if start is not None:
            out.append((start, len(bits)))
        return out

    def dur(self, span):
        i0, i1 = span
        return self.t[min(i1, len(self.t) - 1)] - self.t[i0]


def _near(value, target, tol=0.45):
    return abs(value - target) <= target * tol


def check_selftest(tr):
    """Verify the 5x20ms / 10x10ms fingerprint and that D0/D1 are not swapped."""
    d0, d1 = tr.spans(0), tr.spans(1)
    if not d0 or not d1:
        return "inconclusive: one or both digital channels never went high"

    def burst(spans, n, ms):
        head = spans[:n]
        return (len(head) == n
                and all(_near(tr.dur(s), ms / 1000.0) for s in head))

    if burst(d0, 5, 20) and burst(d1, 10, 10):
        return "OK: D0 5x20ms then D1 10x10ms — lanes correct, firmware driving pads"
    if burst(d0, 10, 10) and burst(d1, 5, 20):
        return "*** LANES SWAPPED *** D0 shows the 10x10ms burst — swap the probes"
    return ("inconclusive: no clean selftest fingerprint. Either the capture "
            "started after setup(), or PPK2_DEBUG is not in the build")


def classify_d1(tr):
    """Label each D1 HIGH span. The archive flush carries a 3x50ms preamble."""
    spans = tr.spans(1)
    labels = []
    for i, s in enumerate(spans):
        d = tr.dur(s)
        # Three ~50ms blips immediately before => history_store_flush()
        prev = spans[max(0, i - 3):i]
        preamble = (len(prev) == 3
                    and all(_near(tr.dur(p), 0.050) for p in prev)
                    and tr.t[s[0]] - tr.t[prev[-1][1] - 1] < 0.150)
        if preamble:
            labels.append((s, "archive flush (base snapshot)"))
        elif _near(d, 0.050):
            labels.append((s, "preamble blip"))
        elif _near(d, 0.010):
            labels.append((s, "selftest blip"))
        elif d > 0.5:
            labels.append((s, "panel refresh"))
        else:
            labels.append((s, "unclassified D1 high"))
    return labels


def window(tr, from_ms, to_ms):
    """Integrate an explicit time window. For the phases that carry no marker —
    the archive format and the WiFi exchange — locate them with --profile, then
    bracket them here."""
    t0, t1 = from_ms / 1000.0, to_ms / 1000.0
    i0 = next((i for i, t in enumerate(tr.t) if t >= t0), 0)
    i1 = next((i for i, t in enumerate(tr.t) if t >= t1), len(tr))
    dur, mean, mc = tr.integrate(i0, i1)
    print(f"\n-- Window {from_ms:.1f}-{to_ms:.1f} ms --\n"
          f"  {dur*1000:.1f} ms   {mean/1000:.3f} mA   {mc:.4f} mC")


def report(tr, bin_ms=None):
    print(f"Samples: {len(tr)}   span: {tr.t[-1] - tr.t[0]:.3f} s   "
          f"channels: {sorted(tr.digital) or 'none'}")
    if not tr.digital:
        print("\nNo digital channels in this capture — regions cannot be "
              "derived from markers. Enable logic capture on D0/D1 and re-export.")
    else:
        print("\nSelftest: " + check_selftest(tr))

        print("\n-- Awake phases (D0 high) --")
        for s in tr.spans(0):
            if tr.dur(s) < 0.100:      # selftest blips, not a wake
                continue
            dur, mean, mc = tr.integrate(*s)
            print(f"  t={tr.t[s[0]]:8.3f}s  {dur*1000:9.1f} ms  "
                  f"{mean/1000:8.3f} mA  {mc:9.4f} mC")

        print("\n-- D1 events --")
        for s, label in classify_d1(tr):
            if label in ("preamble blip", "selftest blip"):
                continue
            dur, mean, mc = tr.integrate(*s)
            print(f"  t={tr.t[s[0]]:8.3f}s  {dur*1000:9.1f} ms  "
                  f"{mean/1000:8.3f} mA  {mc:9.4f} mC   {label}")

        # Sleep floor: after the last real awake phase ends.
        wakes = [s for s in tr.spans(0) if tr.dur(s) >= 0.100]
        if wakes:
            i1 = wakes[-1][1]
            if len(tr) - i1 > 100:
                dur, mean, mc = tr.integrate(i1, len(tr))
                print(f"\n-- Sleep floor (after D0 low) --\n"
                      f"  {dur:.3f} s   {mean:.2f} uA")
                print("  Sanity: ~20 uA means the leads really are on the BAT "
                      "pads;\n  ~350-500 uA means the shield's ETA9740 path is "
                      "in series.")

    if bin_ms:
        print(f"\n-- Profile ({bin_ms} ms bins) — for locating unmarked phases "
              f"(archive format, WiFi) --")
        step = bin_ms / 1000.0
        edge, acc, n = tr.t[0] + step, 0.0, 0
        for k in range(len(tr)):
            acc += tr.current_ua[k]
            n += 1
            if tr.t[k] >= edge:
                print(f"  t={edge - step:8.3f}s  {acc / n / 1000:8.3f} mA")
                edge, acc, n = edge + step, 0.0, 0


# --- CSV source ------------------------------------------------------------

def load_csv(path):
    """Read a Power Profiler CSV, sniffing the header rather than assuming it."""
    with open(path, newline="") as fh:
        rows = csv.reader(fh)
        header = next(rows)
        cols = [h.strip() for h in header]

        t_idx = cur_idx = None
        t_scale = 1e-3        # default: milliseconds
        cur_scale = 1.0       # default: microamps
        dig = {}

        for i, h in enumerate(cols):
            unit = (re.search(r"\(([^)]*)\)", h) or [None, ""])[1].lower()
            name = re.sub(r"\(.*?\)", "", h).strip().lower()
            if t_idx is None and re.search(r"time", name):
                t_idx = i
                t_scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6}.get(unit, 1e-3)
            elif cur_idx is None and re.search(r"current|amp", name):
                cur_idx = i
                cur_scale = {"a": 1e6, "ma": 1e3, "ua": 1.0,
                             "µa": 1.0}.get(unit, 1.0)
            elif re.fullmatch(r"d[0-7]", name):
                dig[int(name[1])] = i

        if cur_idx is None:
            sys.exit(f"No current column found in {path!r}. Header: {cols}")

        t, cur = [], []
        digital = {ch: [] for ch in dig}
        for n, row in enumerate(rows):
            if not row or len(row) <= cur_idx:
                continue
            try:
                cur.append(float(row[cur_idx]) * cur_scale)
            except ValueError:
                continue           # non-numeric row (units line, blank, ...)
            if t_idx is not None and row[t_idx].strip():
                t.append(float(row[t_idx]) * t_scale)
            else:
                t.append(len(cur) / PPK2_SAMPLE_HZ)
            for ch, idx in dig.items():
                v = row[idx].strip() if len(row) > idx else ""
                digital[ch].append(1 if v not in ("", "0", "L", "false") else 0)

    if t_idx is None:
        print(f"note: no timestamp column; assuming {PPK2_SAMPLE_HZ} Hz",
              file=sys.stderr)
    # Drop channels that are flat-zero throughout — they were not probed.
    digital = {ch: v for ch, v in digital.items() if any(v)}
    return Trace(t, cur, digital)


# --- Live source -----------------------------------------------------------

def _load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh)


def confirm_connection(rail, mv):
    """Typed confirmation of the physical connection. Never inferred, never
    remembered across a rail change — see the memory note and the skill."""
    spec = RAILS[rail]
    last = _load_state().get("rail")
    print("\n" + "=" * 68)
    print(f"  ABOUT TO SOURCE {mv} mV  (rail: {rail})")
    print("=" * 68)
    print(f"  Confirm: {spec['check']}")
    if last and last != rail:
        print(f"\n  !! Last sourced run used rail {last!r}. You are now")
        print(f"     declaring {rail!r}. Confirm the leads actually moved.")
    if rail == "bat":
        print("\n  If these leads are on the 3V3 rail, this will exceed the")
        print("  C6's 3.6 V absolute maximum and destroy the MCU, the panel")
        print("  and the sensor together.")
    print(f"\n  Type exactly: {rail} {mv}")
    try:
        got = input("  > ").strip()
    except EOFError:
        sys.exit("aborted: no confirmation possible on a non-interactive stdin")
    if got != f"{rail} {mv}":
        sys.exit("aborted: confirmation did not match")
    _save_state({"rail": rail, "mv": mv, "when": time.time()})


def capture_live(args):
    try:
        from ppk2_api.ppk2_api import PPK2_API
    except ImportError:
        sys.exit("ppk2_api missing. .venv/bin/pip install -r tools/requirements.txt")

    ports = PPK2_API.list_devices()
    if not ports:
        sys.exit("no PPK2 found")
    port = args.port or (ports[0] if isinstance(ports[0], str) else ports[0][0])
    ppk = PPK2_API(port)
    ppk.get_modifiers()

    sourcing = args.rail is not None
    if not sourcing:
        # Default. The PPK2 does not supply the DUT, so no rail can be
        # over-volted regardless of how the leads are attached.
        ppk.use_ampere_meter()
        print(f"ampere meter on {port} (PPK2 is not sourcing)")
    else:
        spec = RAILS[args.rail]
        mv = args.voltage if args.voltage is not None else spec["max_mv"]
        if not spec["min_mv"] <= mv <= spec["max_mv"]:
            sys.exit(f"refusing {mv} mV on rail {args.rail!r}: allowed "
                     f"{spec['min_mv']}-{spec['max_mv']} mV")
        confirm_connection(args.rail, mv)
        ppk.use_source_meter()
        ppk.set_source_voltage(mv)
        print(f"source meter on {port} at {mv} mV, rail {args.rail}")

    samples, digital_raw = [], []
    ppk.start_measuring()
    if sourcing and args.power_cycle:
        ppk.toggle_DUT_power("OFF")
        time.sleep(args.off_seconds)
        # Sampling is already running, so the DUT's first boot cannot be missed.
        ppk.toggle_DUT_power("ON")
        print(f"DUT powered at t~{args.off_seconds:.1f}s into the capture")

    abort_ma = RAILS[args.rail]["abort_ma"] if sourcing else None
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(0.01)
            buf = ppk.get_data()
            if not buf:
                continue
            s, d = ppk.get_samples(buf)
            samples.extend(s)
            digital_raw.extend(d)
            if abort_ma and s and max(s) / 1000.0 > abort_ma:
                ppk.toggle_DUT_power("OFF")
                sys.exit(f"ABORTED: {max(s)/1000:.0f} mA exceeded the "
                         f"{abort_ma:.0f} mA ceiling for rail {args.rail!r}. "
                         f"Power cut. Check the connection before retrying.")
    finally:
        ppk.stop_measuring()
        if sourcing:
            ppk.toggle_DUT_power("OFF")

    chans = PPK2_API.digital_channels(ppk, digital_raw) if digital_raw else []
    digital = {i: chans[i] for i in range(len(chans)) if any(chans[i])}
    t = [i / PPK2_SAMPLE_HZ for i in range(len(samples))]
    tr = Trace(t, samples, digital)

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            ch = sorted(digital)
            w.writerow(["Timestamp(ms)", "Current(uA)"] + [f"D{c}" for c in ch])
            for i in range(len(samples)):
                w.writerow([f"{t[i]*1000:.3f}", f"{samples[i]:.3f}"]
                           + [digital[c][i] for c in ch])
        print(f"wrote {args.out}")

    if sourcing:
        print(f"\nFor docs/history-store-validation.md: sourced {args.rail} "
              f"at {mv} mV for {args.seconds}s")
    return tr


# --- CLI -------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("csv", help="analyse an exported Power Profiler CSV")
    c.add_argument("path")
    c.add_argument("--profile", type=float, metavar="MS",
                   help="also print mean current in bins of MS milliseconds")

    l = sub.add_parser("live", help="capture from a connected PPK2")
    l.add_argument("--rail", choices=sorted(RAILS),
                   help="REQUIRED to source. Omit for ampere meter (safe default)")
    l.add_argument("--voltage", type=int, metavar="MV",
                   help="source voltage; defaults to the rail maximum")
    l.add_argument("--seconds", type=float, default=30.0)
    l.add_argument("--power-cycle", action="store_true",
                   help="cut DUT power, then restore it with sampling already "
                        "running, so a cold boot cannot be missed")
    l.add_argument("--off-seconds", type=float, default=2.0)
    l.add_argument("--port")
    l.add_argument("--out", metavar="CSV", help="also save the capture")
    l.add_argument("--profile", type=float, metavar="MS")

    for sp in (c, l):
        sp.add_argument("--from", dest="from_ms", type=float, metavar="MS",
                        help="integrate an explicit window (with --to); use for "
                             "the unmarked archive-format and WiFi phases")
        sp.add_argument("--to", dest="to_ms", type=float, metavar="MS")

    args = p.parse_args()
    tr = load_csv(args.path) if args.cmd == "csv" else capture_live(args)
    report(tr, args.profile)
    if args.from_ms is not None and args.to_ms is not None:
        window(tr, args.from_ms, args.to_ms)


if __name__ == "__main__":
    main()
