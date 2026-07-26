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

Traces run to millions of samples (100 kSps fills 14M rows in 144 s), so samples
are held in `array` rather than lists and charge is accumulated once into a
cumulative array at load. Every region query is then O(1) rather than a fresh
pass over the file.

Before the DUT is powered the probed GPIOs float and the PPK2's logic inputs
read them as HIGH, so markers before power-on are meaningless. Power-on is
detected from current and everything earlier is ignored.

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
from array import array

# The PPK2 samples at a fixed 100 kSps. ppk2_api does not expose this, so it is
# restated here: it is the device's specified rate, not something measured.
PPK2_SAMPLE_HZ = 100_000

# Above this, the DUT is considered powered. Well under any real awake current
# and far above the ~0 uA the PPK2 reports with its output off.
POWER_ON_UA = 100.0

# Debounce floor for digital spans. An undriven pin rings at us scale until the
# app claims it, so anything shorter than this is not a marker. The shortest real
# marker is a 10ms selftest blip.
MIN_SPAN_MS = 1.0

# Trimmed off each end of a between-wakes gap before calling it a floor.
# Covers the un-marked boot preamble (~450ms of mA-scale draw before
# PPK2_CPU_ACTIVE_HIGH()) and any tail after the marker drops.
SLEEP_TRIM_S = 1.5

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
    """Samples plus optional digital channels. t seconds, current uA.

    cum_uc[i] is the integrated charge from sample 0 to i, so any region's
    charge is one subtraction regardless of how many samples it spans.
    """

    def __init__(self, t, current_ua, cum_uc, digital=None, power_on=0,
                 cpu_ch=0, disp_ch=1):
        self.t = t
        self.current_ua = current_ua
        self.cum_uc = cum_uc
        self.digital = digital or {}
        self.power_on = power_on
        # Which PPK2 lane carries which marker. The firmware's convention is
        # CPU_ACTIVE=GPIO17, DISPLAY=GPIO16, but which PPK2 channel each lands on
        # is a property of the harness, so it is stated rather than assumed.
        self.cpu_ch = cpu_ch
        self.disp_ch = disp_ch

    def __len__(self):
        return len(self.t)

    def integrate(self, i0, i1):
        """Charge over [i0, i1). Returns (seconds, mean_uA, mC)."""
        i1 = min(i1, len(self))
        i0 = max(i0, 0)
        if i1 - i0 < 2:
            return 0.0, 0.0, 0.0
        dur = self.t[i1 - 1] - self.t[i0]
        uc = self.cum_uc[i1 - 1] - self.cum_uc[i0]
        mean = uc / dur if dur > 0 else 0.0
        return dur, mean, uc / 1000.0

    def stats(self, i0, i1):
        """min/max/duty of the raw current, for characterising a noisy region."""
        i1 = min(i1, len(self))
        seg = self.current_ua[i0:i1]
        if not len(seg):
            return None
        lo, hi = min(seg), max(seg)
        _, mean, _ = self.integrate(i0, i1)
        thresh = mean * 2.0
        above = sum(1 for v in seg if v > thresh)
        return lo, hi, mean, above / len(seg)

    def index_at(self, seconds):
        """First sample at or after a time. Bisect, not a scan."""
        lo, hi = 0, len(self)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.t[mid] < seconds:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def spans(self, channel, min_ms=MIN_SPAN_MS):
        """Contiguous HIGH runs on a channel, as (i0, i1). Ignores anything
        before power-on, and debounces.

        The debounce is not cosmetic: an undriven pin rings at microsecond scale
        until gpio_out_init() takes it over, which produces thousands of spurious
        spans right after power-on and swamps every real marker. The shortest
        real marker is a 10ms selftest blip, so a 1ms floor is safe.
        """
        bits = self.digital.get(channel)
        if not bits:
            return []
        out, start = [], None
        for i in range(self.power_on, len(bits)):
            b = bits[i]
            if b and start is None:
                start = i
            elif not b and start is not None:
                out.append((start, i))
                start = None
        if start is not None:
            out.append((start, len(bits)))
        return [s for s in out if self.dur(s) * 1000.0 >= min_ms]

    def dur(self, span):
        i0, i1 = span
        return self.t[min(i1, len(self) - 1)] - self.t[i0]


def _near(value, target, tol=0.45):
    return abs(value - target) <= target * tol


def check_selftest(tr):
    """Verify the 5x20ms / 10x10ms fingerprint and that D0/D1 are not swapped."""
    cpu, disp = tr.spans(tr.cpu_ch), tr.spans(tr.disp_ch)
    if not cpu or not disp:
        return "inconclusive: one or both digital channels never went high"

    def burst(spans, n, ms):
        head = spans[:n]
        return (len(head) == n
                and all(_near(tr.dur(s), ms / 1000.0) for s in head))

    if burst(cpu, 5, 20):
        # GPIO16 is U0TXD, so the ROM bootloader parks the DISPLAY lane at UART
        # idle-high and its 10x10ms burst can be buried. The CPU burst is the
        # reliable half of the fingerprint.
        tail = " (display burst also clean)" if burst(disp, 10, 10) else \
               " (display burst not resolved — GPIO16 is U0TXD, expected)"
        return f"OK: 5x20ms on the CPU lane D{tr.cpu_ch}{tail}"
    if burst(disp, 5, 20):
        return (f"*** LANES CROSSED *** the 5x20ms CPU burst is on D{tr.disp_ch}, "
                f"which you declared as display. Re-run with "
                f"--cpu-ch {tr.disp_ch} --display-ch {tr.cpu_ch}")
    return ("inconclusive: no clean selftest fingerprint. Either the capture "
            "started after setup(), or PPK2_DEBUG is not in the build")


def classify_display(tr):
    """Label each DISPLAY-lane HIGH span. The flush carries a 3x50ms preamble."""
    spans = tr.spans(tr.disp_ch)
    labels = []
    for i, s in enumerate(spans):
        d = tr.dur(s)
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
    i0, i1 = tr.index_at(from_ms / 1000.0), tr.index_at(to_ms / 1000.0)
    dur, mean, mc = tr.integrate(i0, i1)
    st = tr.stats(i0, i1)
    print(f"\n-- Window {from_ms:.1f}-{to_ms:.1f} ms --")
    print(f"  {dur*1000:.1f} ms   {mean/1000:.4f} mA   {mc:.4f} mC")
    if st:
        print(f"  raw current {st[0]:.1f} .. {st[1]:.1f} uA")


def report(tr, bin_ms=None):
    total = tr.t[-1] - tr.t[0]
    print(f"Samples: {len(tr)}   span: {total:.3f} s   "
          f"channels: {sorted(tr.digital) or 'none'}")
    if tr.power_on:
        print(f"DUT unpowered until t={tr.t[tr.power_on]:.3f}s "
              f"({tr.power_on} samples ignored — probed pins float there)")

    if not tr.digital:
        print("\nNo digital channels — regions cannot be derived from markers. "
              "Enable logic capture on D0/D1 and re-export.")
    else:
        print("\nSelftest: " + check_selftest(tr))

        wakes = [s for s in tr.spans(tr.cpu_ch) if tr.dur(s) >= 0.100]
        print(f"\n-- Awake phases (CPU lane D{tr.cpu_ch} high, >100ms) — "
              f"{len(wakes)} found --")
        for s in wakes:
            dur, mean, mc = tr.integrate(*s)
            print(f"  t={tr.t[s[0]]:9.3f}s  {dur*1000:10.1f} ms  "
                  f"{mean/1000:9.3f} mA  {mc:10.4f} mC")

        print(f"\n-- Display lane D{tr.disp_ch} events --")
        for s, label in classify_display(tr):
            if label in ("preamble blip", "selftest blip"):
                continue
            dur, mean, mc = tr.integrate(*s)
            print(f"  t={tr.t[s[0]]:9.3f}s  {dur*1000:10.1f} ms  "
                  f"{mean/1000:9.3f} mA  {mc:10.4f} mC   {label}")

        # Sleep floors: the gaps between awake phases, plus the tail.
        print("\n-- Sleep (between/after awake phases) --")
        bounds = [(wakes[i][1], wakes[i + 1][0]) for i in range(len(wakes) - 1)]
        if wakes:
            bounds.append((wakes[-1][1], len(tr)))
        for i0, i1 in bounds:
            if i1 - i0 < 1000:
                continue
            # The CPU_ACTIVE marker does not cover the boot preamble: the ROM
            # bootloader, IDF startup and ppk2_selftest() all run before
            # PPK2_CPU_ACTIVE_HIGH(). So the raw gap between two awake phases
            # contains the tail of one wake and the ramp of the next, and its
            # mean is not a floor. Trim generously and report both, loudly, so a
            # contaminated window can never be mistaken for a sleep current.
            trim = tr.index_at(tr.t[i0] + SLEEP_TRIM_S) - i0
            j0, j1 = i0 + trim, max(i0 + trim + 1, i1 - trim)
            dur, mean, mc = tr.integrate(i0, i1)
            tdur, tmean, tmc = tr.integrate(j0, j1)
            print(f"  t={tr.t[i0]:9.3f}s  {tdur:8.3f} s  floor {tmean:9.2f} uA  "
                  f"{tmc:9.4f} mC   (trimmed {SLEEP_TRIM_S:.1f}s each end)")
            if mean > tmean * 1.2:
                print(f"      untrimmed mean over the full {dur:.3f}s gap is "
                      f"{mean:.2f} uA — that is wake transition charge, not "
                      f"floor. Using the trimmed figure.")
            st = tr.stats(j0, j1)
            if st:
                print(f"      raw {st[0]:.1f} .. {st[1]:.1f} uA, "
                      f"{st[3]*100:.3f}% of samples above 2x mean")
                print(f"      (a buck in PFM delivers charge in narrow packets, "
                      f"so a spiky floor at a low duty is expected)")

    if bin_ms:
        print(f"\n-- Profile ({bin_ms} ms bins) — locates unmarked phases "
              f"(archive format, WiFi) --")
        step = bin_ms / 1000.0
        t0 = tr.t[0]
        n = int(total / step)
        for b in range(n):
            i0 = tr.index_at(t0 + b * step)
            i1 = tr.index_at(t0 + (b + 1) * step)
            dur, mean, _ = tr.integrate(i0, i1)
            if dur > 0:
                print(f"  t={t0 + b*step:9.3f}s  {mean/1000:9.4f} mA")


# --- CSV source ------------------------------------------------------------

def load_csv(path, verbose=True):
    """Read a Power Profiler CSV, sniffing the header rather than assuming it."""
    with open(path) as fh:
        header = next(csv.reader([fh.readline()]))
        cols = [h.strip() for h in header]

        t_idx = cur_idx = None
        t_scale, cur_scale = 1e-3, 1.0
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

        # Only D0/D1 are driven by PPK2_DEBUG; parsing eight more columns over
        # millions of rows costs real time for channels that are always zero.
        dig = {ch: i for ch, i in dig.items() if ch in (0, 1)}
        need = max([cur_idx, t_idx or 0] + list(dig.values())) + 1

        t = array("d")
        cur = array("f")
        cum = array("d")
        digital = {ch: array("b") for ch in dig}
        acc, prev_i, prev_t = 0.0, None, None
        power_on, idx = 0, 0

        for line in fh:
            f = line.split(",", need)
            if len(f) < need:
                continue
            try:
                ua = float(f[cur_idx]) * cur_scale
                ts = (float(f[t_idx]) * t_scale if t_idx is not None
                      else idx / PPK2_SAMPLE_HZ)
            except ValueError:
                continue
            if prev_i is not None:
                acc += 0.5 * (prev_i + ua) * (ts - prev_t)
            t.append(ts)
            cur.append(ua)
            cum.append(acc)
            for ch, ci in dig.items():
                digital[ch].append(1 if f[ci].strip() not in
                                   ("", "0", "L", "false") else 0)
            if not power_on and ua > POWER_ON_UA:
                power_on = idx
            prev_i, prev_t = ua, ts
            idx += 1

    if not len(t):
        sys.exit(f"No samples parsed from {path!r}")
    if t_idx is None and verbose:
        print(f"note: no timestamp column; assuming {PPK2_SAMPLE_HZ} Hz",
              file=sys.stderr)
    digital = {ch: v for ch, v in digital.items() if any(v)}
    return Trace(t, cur, cum, digital, power_on)


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
    remembered across a rail change — see the device-session skill."""
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
    mv = None
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

    chans = ppk.digital_channels(digital_raw) if digital_raw else []
    digital = {i: array("b", chans[i]) for i in range(len(chans)) if any(chans[i])}

    t, cur, cum = array("d"), array("f"), array("d")
    acc, power_on = 0.0, 0
    for i, ua in enumerate(samples):
        ts = i / PPK2_SAMPLE_HZ
        if i:
            acc += 0.5 * (samples[i - 1] + ua) / PPK2_SAMPLE_HZ
        t.append(ts)
        cur.append(ua)
        cum.append(acc)
        if not power_on and ua > POWER_ON_UA:
            power_on = i
    tr = Trace(t, cur, cum, digital, power_on)

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

    for sp in (c, l):
        sp.add_argument("--cpu-ch", type=int, default=0, metavar="N",
                        help="PPK2 channel carrying CPU_ACTIVE/GPIO17 (default 0)")
        sp.add_argument("--display-ch", type=int, default=1, metavar="N",
                        help="PPK2 channel carrying DISPLAY/GPIO16 (default 1)")
        sp.add_argument("--profile", type=float, metavar="MS",
                        help="print mean current in bins of MS milliseconds")
        sp.add_argument("--from", dest="from_ms", type=float, metavar="MS",
                        help="integrate an explicit window (with --to); use for "
                             "the unmarked archive-format and WiFi phases")
        sp.add_argument("--to", dest="to_ms", type=float, metavar="MS")

    args = p.parse_args()
    tr = load_csv(args.path) if args.cmd == "csv" else capture_live(args)
    tr.cpu_ch, tr.disp_ch = args.cpu_ch, args.display_ch
    report(tr, args.profile)
    if args.from_ms is not None and args.to_ms is not None:
        window(tr, args.from_ms, args.to_ms)


if __name__ == "__main__":
    main()
