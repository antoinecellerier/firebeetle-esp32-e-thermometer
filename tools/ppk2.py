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
import math
import json
import os
import re
import sys
import time
from array import array

# The PPK2 samples at a fixed 100 kSps. ppk2_api does not expose this, so it is
# restated here: it is the device's specified rate, not something measured.
PPK2_SAMPLE_HZ = 100_000

# Above this, the DUT is considered powered. It has to sit between "PPK2 output
# off" (~0.1 uA measured) and "DUT asleep" (~20 uA on this rig) — NOT above the
# sleep floor. At 100 uA it latched on the first wake instead, so an
# externally-powered board that was asleep when sampling started was reported
# "unpowered" for its whole leading sleep window, and that window — usually the
# longest and cleanest floor in the capture — was silently discarded.
POWER_ON_UA = 5.0

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
    # 900mA, not 600: the EPD power-gate turn-on is a boost inrush measured at
    # ~405mA on the E rig and 571-605mA on this one, so a 600mA ceiling flags
    # normal operation. The PPK2 itself tops out near 1A.
    "bat": {"min_mv": 3000, "max_mv": 4200, "abort_ma": 900.0,
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


# Mirrors the fingerprint emitted by ppk2_selftest() in src/Thermometer.cpp.
# Both count and width differ per lane, so a lane stays identifiable when a pulse
# is clipped at a capture boundary. Keep in sync with PPK2_FP_* there.
FP_CPU_PULSES, FP_CPU_MS = 2, 10
FP_DISP_PULSES, FP_DISP_MS = 5, 4
# The 400ms fingerprint this replaced, still recognised so captures taken before
# the change stay verifiable rather than reading as unverified forever.
FP_LEGACY = ((5, 20), (10, 10))


def check_selftest(tr):
    """Identify each lane from the firmware's fingerprint, or say it is unverified.

    Never claim a mapping is fine when it was not checked. The lanes really were
    crossed on this rig, and the previous version of this function reported that as
    "expected, the CPU lane is continuously high" — a reassuring sentence covering
    an unverified declaration, which then put a floor figure tens of times too high
    into the logbook.
    """
    cpu, disp = tr.spans(tr.cpu_ch), tr.spans(tr.disp_ch)

    def burst(spans, n, ms):
        head = spans[:n]
        return (len(head) == n
                and all(_near(tr.dur(s), ms / 1000.0) for s in head))

    cpu_n, cpu_ms = FP_CPU_PULSES, FP_CPU_MS
    disp_n, disp_ms = FP_DISP_PULSES, FP_DISP_MS
    era = ""
    if not (burst(cpu, cpu_n, cpu_ms) or burst(disp, cpu_n, cpu_ms)):
        (lc_n, lc_ms), (ld_n, ld_ms) = FP_LEGACY
        if burst(cpu, lc_n, lc_ms) or burst(disp, lc_n, lc_ms):
            cpu_n, cpu_ms, disp_n, disp_ms = lc_n, lc_ms, ld_n, ld_ms
            era = " (pre-80ms fingerprint)"

    cpu_here = burst(cpu, cpu_n, cpu_ms)
    cpu_there = burst(disp, cpu_n, cpu_ms)
    disp_here = burst(disp, disp_n, disp_ms)
    disp_there = burst(cpu, disp_n, disp_ms)

    if cpu_there or disp_there:
        return (f"*** LANES CROSSED *** the {cpu_n}x{cpu_ms}ms CPU "
                f"fingerprint is on D{tr.disp_ch}, which you declared as display. "
                f"Re-run with --cpu-ch {tr.disp_ch} --display-ch {tr.cpu_ch}. "
                f"Every figure below is mislabelled until you do.")
    if cpu_here:
        tail = (" (display fingerprint also clean)" if disp_here else
                " (display fingerprint not resolved — GPIO16 is U0TXD and the ROM "
                "bootloader parks it high, so this is expected)")
        return f"OK: {cpu_n}x{cpu_ms}ms on the CPU lane D{tr.cpu_ch}{era}{tail}"

    return (f"*** LANE MAPPING UNVERIFIED *** no fingerprint found, so "
            f"--cpu-ch {tr.cpu_ch} / --display-ch {tr.disp_ch} is taken on trust. "
            f"The firmware emits one every wake, so expect this only when the build "
            f"lacks -DPPK2_DEBUG, the capture starts mid-wake, or decimation "
            f"exceeded the pulse width (analyse marker captures with --decimate 1).")


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
            labels.append((s, f"unclassified D{tr.disp_ch} high"))
    return labels


def window(tr, from_s, to_s):
    """Integrate an explicit time window, in SECONDS.

    Seconds, not milliseconds, because --profile prints seconds and the docstring
    tells you to chain them: `--from 12.345` after spotting a phase at t=12.345s
    used to select a 0.65 ms window twelve seconds earlier and print it as if it
    had worked. Units that disagree across two features meant to be used together
    are a trap, not a convention.
    """
    i0, i1 = tr.index_at(from_s), tr.index_at(to_s)
    dur, mean, mc = tr.integrate(i0, i1)
    st = tr.stats(i0, i1)
    print(f"\n-- Window {from_s:.3f}-{to_s:.3f} s --")
    print(f"  {dur*1000:.1f} ms   {mean/1000:.4f} mA   {mc:.4f} mC")
    if st:
        print(f"  raw current {st[0]:.1f} .. {st[1]:.1f} uA")


def floor_of(tr, i0, i1, win_s=10.0):
    """The lowest sustained current in a region — what "floor" actually means.

    The quietest rolling `win_s` mean, which unlike a median or a percentile does
    not move with how much of the region a transient occupies. A region's mean is
    what the battery pays; this is the level it settles to. When the two diverge
    the region is not homogeneous and no single number describes it.
    """
    span = tr.t[min(i1, len(tr) - 1)] - tr.t[i0]
    if span <= win_s:
        return tr.integrate(i0, i1)[1]
    step = max(1, tr.index_at(tr.t[i0] + win_s) - i0)
    best = None
    k = i0
    while k + step <= i1:
        _, mean, _ = tr.integrate(k, k + step)
        if best is None or mean < best:
            best = mean
        k += max(1, step // 2)          # half-overlapping windows
    return best if best is not None else tr.integrate(i0, i1)[1]


def _marker_plausible(tr, ch, stride=97, max_hi_in_sleep=0.20):
    """Is this channel a marker, or an undriven pin floating into the logic input?

    Both real markers are driven LOW while the CPU sleeps. An undriven pad floats
    high the whole time, which is what a build without -DPPK2_DEBUG produces.
    Duty is not a valid test (a boot-dominated capture has CPU_ACTIVE high most
    of the time) and neither is correlation with current — the display marker is
    high exactly while the CPU light-sleeps through the panel's busy wait, so it
    anti-correlates. Strided, because the distinction is gross, not subtle.
    """
    bits = tr.digital[ch]
    hi_sleep = n_sleep = 0
    for i in range(tr.power_on, len(tr), stride):
        if tr.current_ua[i] < 1000.0:
            n_sleep += 1
            if bits[i]:
                hi_sleep += 1
    if n_sleep < 50:
        return True, 0.0          # no sleep to judge against; do not reject
    frac = hi_sleep / n_sleep
    return frac <= max_hi_in_sleep, frac


def _current_regions(tr, thresh_ua=1000.0, block_s=0.25):
    """Segment into awake/sleep by current alone, for builds with no markers.

    Run-length encoding over fixed blocks, with NO minimum-duration filter. The
    previous version discarded regions shorter than min_s but flipped its state
    anyway, so a sub-min_s wake ended up inside the neighbouring sleep region and
    inflated that region's reported floor 4.9x (a 0.1 s 15 mA wake turned a true
    19 uA floor into a reported 93 uA, labelled "sleep", unflagged). Nothing is
    absorbed now: a short excursion becomes its own labelled region, which is the
    only honest place to put charge that really happened.

    A PFM spike cannot fake a block: 12 mA for 60 us averages to ~3 uA over
    0.25 s, three orders under the threshold. So a block reading high is a real
    event, and there is nothing for a duration filter to protect against.
    """
    n = len(tr)
    step = max(1, tr.index_at(tr.t[tr.power_on] + block_s) - tr.power_on)
    out, start, cur = [], tr.power_on, None
    i = tr.power_on
    while i < n:
        j = min(i + step, n)
        _, mean, _ = tr.integrate(i, j)
        hi = mean > thresh_ua
        if cur is None:
            cur = hi
        elif hi != cur:
            out.append((start, i))
            start, cur = i, hi
        i = j
    if start < n - 1:
        out.append((start, n))
    return out


def report(tr, bin_ms=None):
    total = tr.t[-1] - tr.t[0]
    print(f"Samples: {len(tr)}   span: {total:.3f} s   "
          f"channels: {sorted(tr.digital) or 'none'}")
    if tr.power_on:
        print(f"DUT unpowered until t={tr.t[tr.power_on]:.3f}s "
              f"({tr.power_on} samples ignored — probed pins float there)")

    # Validate markers physically rather than by duty cycle. A real CPU_ACTIVE
    # marker is high exactly when the CPU is drawing current; an undriven pin
    # floating into the PPK2's logic input has no relationship to current at all.
    # Duty is the wrong test — a boot-dominated capture legitimately has the
    # marker high most of the time.
    for ch in list(tr.digital):
        ok, ratio = _marker_plausible(tr, ch)
        if not ok:
            print(f"\nD{ch} is high for {ratio*100:.0f}% of sleep samples — an "
                  f"undriven pin, not a marker. Expected without -DPPK2_DEBUG.")
            del tr.digital[ch]

    # The marker branch needs the CPU lane specifically, so test for that rather
    # than for any channel at all — a capture with a usable display lane and no
    # usable CPU lane otherwise produced zero numbers and no explanation.
    if tr.cpu_ch not in tr.digital:
        extra = (f" (D{tr.disp_ch} is present but cannot bound a region on its own)"
                 if tr.digital else "")
        print(f"\nNo usable CPU-lane marker{extra} — reporting current only. "
              f"Expected in a build without -DPPK2_DEBUG.")
        for lo, hi in _current_regions(tr):
            dur, mean, mc = tr.integrate(lo, hi)
            kind = "AWAKE" if mean > 1000 else "sleep"
            print(f"  {kind:6s} t={tr.t[lo]:8.3f}s  {dur:8.3f} s  "
                  f"{mean:10.2f} uA  {mc:10.4f} mC")
            if kind == "sleep":
                fl = floor_of(tr, lo, hi)
                if mean > fl * 1.2:
                    excess = mc - fl * dur / 1000.0
                    print(f"         NOT homogeneous: settles to {fl:.2f} uA, so "
                          f"{excess:.4f} mC of this is transient, not floor. Do not "
                          f"quote the mean as a floor.")
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
            # Never trim so hard that nothing is left: a short gap gets a
            # proportional trim instead, since reporting a zero-width window as
            # a floor is worse than reporting a slightly contaminated one.
            gap = tr.t[min(i1, len(tr) - 1)] - tr.t[i0]
            trim_s = min(SLEEP_TRIM_S, gap * 0.25)
            trim = tr.index_at(tr.t[i0] + trim_s) - i0
            j0, j1 = i0 + trim, max(i0 + trim + 1, i1 - trim)
            dur, mean, mc = tr.integrate(i0, i1)
            tdur, tmean, tmc = tr.integrate(j0, j1)
            fl = floor_of(tr, j0, j1)
            excess = tmc - fl * tdur / 1000.0
            print(f"  t={tr.t[i0]:9.3f}s  {tdur:8.3f} s  floor {fl:9.2f} uA  "
                  f"mean {tmean:8.2f} uA  excess {excess:8.4f} mC")
            if tmean > fl * 1.2:
                print(f"      NOT homogeneous — the mean is not a floor. "
                      f"{excess:.4f} mC sits above the settled level, which at one "
                      f"such event per wake is what a wake really costs beyond its "
                      f"marker.")
            if mean > tmean * 1.2:
                print(f"      (untrimmed mean over the full {dur:.3f}s gap is "
                      f"{mean:.2f} uA — wake transition charge, excluded)")
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
        unitless_time = False
        dig = {}
        for i, h in enumerate(cols):
            unit = (re.search(r"\(([^)]*)\)", h) or [None, ""])[1].lower()
            name = re.sub(r"\(.*?\)", "", h).strip().lower()
            if t_idx is None and re.search(r"time", name):
                t_idx = i
                # No default. A unit-less time column guessed as milliseconds turns
                # a seconds-based CSV into durations and charge 1000x too small,
                # and mean current is unaffected (integrate() divides by the same
                # corrupted duration) so nothing looks wrong. Reconstructing from
                # the known sample rate is the safe read, exactly as a missing
                # column already does.
                t_scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6}.get(unit)
                if t_scale is None:
                    print(f"note: time column {h!r} states no unit — ignoring it "
                          f"and reconstructing from {PPK2_SAMPLE_HZ} Hz",
                          file=sys.stderr)
                    t_idx, unitless_time = None, True
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
        power_on, idx = None, 0      # None, not 0: a trace already powered at
                                     # sample 0 must report 0, not be falsy

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
            if power_on is None and ua > POWER_ON_UA:
                power_on = idx
            prev_i, prev_t = ua, ts
            idx += 1

    if not len(t):
        sys.exit(f"No samples parsed from {path!r}")
    if t_idx is None and verbose and not unitless_time:
        print(f"note: no timestamp column; assuming {PPK2_SAMPLE_HZ} Hz",
              file=sys.stderr)
    digital = {ch: v for ch, v in digital.items() if any(v)}
    return Trace(t, cur, cum, digital, power_on or 0)


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
    # A pipe is not a person. CLAUDE.md encourages delegating long capture loops
    # to subagents, so `printf 'bat 4200\n' | ppk2.py live --rail bat` is a
    # realistic invocation — and it would source 4.2V with nobody having looked at
    # the leads. Requiring a tty is the only thing standing between that and a
    # 3.6V-absolute-max rail.
    if not sys.stdin.isatty():
        sys.exit("aborted: stdin is not a terminal, so nobody can confirm the "
                 "leads. Sourcing requires an interactive confirmation — run this "
                 "in a terminal, not piped, redirected, or from a subagent.")
    print(f"\n  Type exactly: {rail} {mv}")
    try:
        got = input("  > ").strip()
    except EOFError:
        sys.exit("aborted: no confirmation possible on a non-interactive stdin")
    if got != f"{rail} {mv}":
        sys.exit("aborted: confirmation did not match")
    _save_state({"rail": rail, "mv": mv, "when": time.time()})


def _connect(args):
    """Open the PPK2's measurement interface. Reads calibration only — does not
    source, measure, or touch DUT power, so it is safe with any wiring."""
    try:
        from ppk2_api.ppk2_api import PPK2_API
    except ImportError:
        sys.exit("ppk2_api missing. .venv/bin/pip install -r tools/requirements.txt")
    import serial.tools.list_ports as _lp

    if args.port:
        cands = [args.port]
    else:
        found = [(pt.location or "", pt.device) for pt in _lp.comports()
                 if pt.product == "PPK2"]
        cands = [d for _, d in sorted(found,
                 key=lambda x: (not x[0].endswith(".1"), x[1]))]
    if not cands:
        sys.exit("no PPK2 found")
    for cand in cands:
        try:
            trial = PPK2_API(cand)
            # A previous capture can leave sample bytes queued, and the metadata
            # parser decodes what it reads as text — so stop any stream and
            # discard the backlog before asking.
            try:
                trial.stop_measuring()
            except Exception:
                pass
            time.sleep(0.1)
            trial.ser.reset_input_buffer()
            if trial.get_modifiers():
                print(f"PPK2 on {cand} (probed {len(cands)} interface(s))")
                return trial, cand
            trial.ser.close()
        except Exception as exc:
            print(f"  {cand}: {exc}")
    sys.exit(f"none of {cands} answered GET_META_DATA — is nrfconnect holding it?")


class _Decimator:
    """Average groups of N samples down as they arrive.

    Averaging, not sampling: the mean of equal-sized bins is exactly the mean of
    the whole, so charge over any region spanning whole bins is preserved. What is
    lost is sub-bin shape — PFM pulses at N=100 — which a floor or a multi-second
    event does not need. Memory is the reason this exists: a decoded sample costs
    ~20 bytes across the sample/time/cumulative arrays, so an hour at 100 kSps is
    ~10 GB undecimated and ~100 MB at N=100.
    """

    def __init__(self, n):
        self.n = max(1, int(n))
        self.acc = 0.0
        self.cnt = 0
        self.dig_hi = 0
        # Peak of the RAW samples, tracked before averaging. The over-current
        # ceiling has to test this: a 2A fault lasting 200us averages to ~400mA
        # in a 1ms bin and slips under a 900mA limit, and any capture over ~200s
        # auto-decimates, so testing bin means disables the check exactly when
        # captures are long enough to matter.
        self.peak = 0.0

    def feed(self, vals, bits, out_samples, out_bits):
        for i, v in enumerate(vals):
            if v > self.peak:
                self.peak = v
            self.acc += v
            if i < len(bits) and bits[i]:
                self.dig_hi += 1         # counted, not OR-ed — see below
            self.cnt += 1
            if self.cnt == self.n:
                out_samples.append(self.acc / self.n)
                # Majority, not OR. OR-ing turned microsecond pad ringing into a
                # solid HIGH bin, so at N>=4 a 0.6 s burst of ringing became one
                # 600 ms span that passed the debounce and was reported as a real
                # awake phase carrying ~9 mC. A real marker fills its bin; ringing
                # occupies a few percent of it.
                out_bits.append(1 if self.dig_hi * 2 > self.n else 0)
                self.acc = 0.0
                self.cnt = 0
                self.dig_hi = 0


def _trace_from_samples(samples, digital_raw, ppk, dt=None):
    if digital_raw and ppk is not None:
        chans = ppk.digital_channels(digital_raw)
    elif digital_raw:
        # From cache: bits already unpacked per channel by the writer's encoding.
        chans = [[(b >> c) & 1 for b in digital_raw] for c in range(8)]
    else:
        chans = []
    digital = {i: array("b", chans[i]) for i in range(len(chans)) if any(chans[i])}
    t_arr, cum = array("d"), array("d")
    acc, power_on, prev = 0.0, None, None
    if dt is None:
        dt = 1.0 / PPK2_SAMPLE_HZ
    for i in range(len(samples)):
        ua = samples[i]
        if prev is not None:
            acc += 0.5 * (prev + ua) * dt
        t_arr.append(i * dt)
        cum.append(acc)
        if power_on is None and ua > POWER_ON_UA:
            power_on = i
        prev = ua
    return Trace(t_arr, samples, cum, digital, power_on or 0)


def _offline_decoder(meta):
    """A decoder built from a sidecar, with no serial port.

    Decoding needs only the calibration modifiers, the measurement mode and the
    bit masks — none of which require the device once they have been recorded. So
    the fields the constructor would set are set here directly, which is coupled
    to ppk2_api's internals but is the price of captures that stay analysable
    without the hardware attached (and without fighting nrfconnect for the port).
    """
    from ppk2_api.ppk2_api import PPK2_API, PPK2_Modes
    d = PPK2_API.__new__(PPK2_API)
    d.modifiers = meta["modifiers"]
    d.mode = getattr(PPK2_Modes, meta["mode"])
    # get_adc_result() folds the supply voltage into its offset term, so this is
    # required, not cosmetic — left unset it is None and every sample dies in the
    # library's bare except, reported as "Measurement outside of range!".
    d.current_vdd = meta["vdd_mv"]
    d.adc_mult = 1.8 / 163840
    d.MEAS_ADC = d._generate_mask(14, 0)
    d.MEAS_RANGE = d._generate_mask(3, 14)
    d.MEAS_LOGIC = d._generate_mask(8, 24)
    d.rolling_avg = d.rolling_avg4 = d.prev_range = None
    d.consecutive_range_samples = 0
    d.spike_filter_alpha = 0.18
    d.spike_filter_alpha5 = 0.06
    d.spike_filter_samples = 3
    d.after_spike = 0
    d.remainder = {"sequence": b"", "len": 0}
    return d


def _cache_paths(raw_path, n):
    return f"{raw_path}.dec{n}.f32", f"{raw_path}.dec{n}.d8"


def _cache_write(raw_path, n, samples, digital_raw):
    """Save the decoded result so re-analysis is free.

    Decoding runs at ~671k samples/s, so 45 s for a 300 s capture and 4.5 min for
    a 30-minute one. The cost that actually hurts is repetition: one capture got
    decoded four times in a session to answer four questions, which on a
    30-minute capture is 18 minutes of waiting for bytes that never change.
    """
    f32, d8 = _cache_paths(raw_path, n)
    try:
        with open(f32, "wb") as fh:
            samples.tofile(fh)
        with open(d8, "wb") as fh:
            array("b", [b & 0xFF if b < 128 else 0 for b in digital_raw]).tofile(fh)
        print(f"cached decode -> {os.path.basename(f32)} (+ .d8)")
    except OSError as exc:
        print(f"  (could not cache: {exc})")


def _cache_read(raw_path, n):
    f32, d8 = _cache_paths(raw_path, n)
    if not (os.path.exists(f32) and os.path.exists(d8)):
        return None
    # A cache older than its source is stale by definition.
    if os.path.getmtime(f32) < os.path.getmtime(raw_path):
        print(f"  (ignoring cache older than {os.path.basename(raw_path)})")
        return None
    samples = array("f")
    dig = array("b")
    with open(f32, "rb") as fh:
        samples.frombytes(fh.read())
    with open(d8, "rb") as fh:
        dig.frombytes(fh.read())
    if len(dig) != len(samples):
        print("  (ignoring cache: sample/digital length mismatch)")
        return None
    return samples, list(dig)


def decode_raw(args):
    """Decode a stream saved by --raw-out.

    Prefers the sidecar written alongside the capture; falls back to reading
    calibration off an attached PPK2, which then needs --mode to match how the
    capture was taken, since the conversion is mode-dependent.
    """
    cached = _cache_read(args.path, max(1, args.decimate))
    if cached is not None:
        samples, digital_raw = cached
        dt = max(1, args.decimate) / PPK2_SAMPLE_HZ
        print(f"decoded from cache: {len(samples)} points ({len(samples)*dt:.1f} s)"
              + (f", decimated {args.decimate}x" if args.decimate > 1 else ""))
        return _trace_from_samples(samples, digital_raw, None, dt)

    side = args.path + ".json"
    if os.path.exists(side):
        with open(side) as fh:
            meta = json.load(fh)
        print(f"calibration from {side} (mode {meta['mode']}) — no device needed")
        ppk = _offline_decoder(meta)
    else:
        print(f"no sidecar at {side} — reading calibration from the device")
        ppk, _ = _connect(args)
        from ppk2_api.ppk2_api import PPK2_Modes
        ppk.mode = (PPK2_Modes.SOURCE_MODE if args.mode == "source"
                    else PPK2_Modes.AMPERE_MODE)
        ppk.current_vdd = args.vdd
        print(f"  assuming mode={args.mode}, vdd={args.vdd} mV — both affect the "
              f"conversion; pass --mode/--vdd if the capture differed")
    samples = array("f")
    digital_raw = []
    dec = _Decimator(args.decimate)
    done = 0
    with open(args.path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            sm, dg = ppk.get_samples(b)
            dec.feed(sm, dg, samples, digital_raw)
            done += len(b)
    dt = dec.n / PPK2_SAMPLE_HZ
    print(f"decoded {done} bytes -> {len(samples)} points "
          f"({len(samples)*dt:.1f} s"
          + (f", decimated {dec.n}x -> {1/dt:.0f} Hz" if dec.n > 1 else "") + ")")
    _cache_write(args.path, dec.n, samples, digital_raw)
    if not len(samples):
        sys.exit("every sample was rejected. ppk2_api swallows any conversion "
                 "error as 'Measurement outside of range!', so this usually means "
                 "a missing decoder field (mode, vdd, modifiers) rather than bad "
                 "data. Check the sidecar, or pass --mode/--vdd.")
    return _trace_from_samples(samples, digital_raw, ppk, dt)


def capture_live(args):
    try:
        from ppk2_api.ppk2_api import PPK2_API
    except ImportError:
        sys.exit("ppk2_api missing. .venv/bin/pip install -r tools/requirements.txt")

    # The PPK2 exposes two CDC interfaces and list_devices() returns both in
    # whatever order pyserial enumerated them. Only interface .1 carries the
    # measurement stream; commands written to the other are accepted silently
    # and no samples ever arrive. So probe rather than guess: get_modifiers()
    # returns False unless it actually parsed the calibration blob back.
    import serial.tools.list_ports as _lp

    def _candidates():
        if args.port:
            return [args.port]
        found = [(pt.location or "", pt.device) for pt in _lp.comports()
                 if pt.product == "PPK2"]
        # Interface .1 first, then by device name for determinism.
        return [d for _, d in sorted(found, key=lambda x: (not x[0].endswith(".1"), x[1]))]

    cands = _candidates()
    if not cands:
        sys.exit("no PPK2 found")
    ppk, port = None, None
    for cand in cands:
        try:
            trial = PPK2_API(cand)
            # A previous capture can leave sample bytes queued, and the metadata
            # parser decodes what it reads as text — so stop any stream and
            # discard the backlog before asking.
            try:
                trial.stop_measuring()
            except Exception:
                pass
            time.sleep(0.1)
            trial.ser.reset_input_buffer()
            if trial.get_modifiers():
                ppk, port = trial, cand
                break
            trial.ser.close()
        except Exception as exc:
            print(f"  {cand}: {exc}")
    if ppk is None:
        sys.exit(f"none of {cands} answered GET_META_DATA — is nrfconnect still "
                 f"holding the port?")
    print(f"PPK2 on {port} (probed {len(cands)} interface(s))")

    sourcing = args.rail is not None
    mv = None
    if not sourcing:
        # Default. The PPK2 does not supply the DUT, so no rail can be
        # over-volted regardless of how the leads are attached.
        ppk.use_ampere_meter()
        # Required even here: ppk2_api's start_measuring() raises "Input voltage
        # not set!" unless current_vdd is set, and use_ampere_meter() does not set
        # it — so this mode, the documented default, could not run at all. The
        # value is not a supply here (the DUT is externally powered); it feeds the
        # offset term of the raw->current conversion, so it has to be the DUT's
        # actual rail voltage to decode correctly.
        ppk.current_vdd = args.vdd
        print(f"ampere meter on {port} (PPK2 is not sourcing), "
              f"DUT rail declared as {args.vdd} mV for the conversion")
    else:
        spec = RAILS[args.rail]
        mv = args.voltage if args.voltage is not None else spec["max_mv"]
        if not spec["min_mv"] <= mv <= spec["max_mv"]:
            sys.exit(f"refusing {mv} mV on rail {args.rail!r}: allowed "
                     f"{spec['min_mv']}-{spec['max_mv']} mV")
        confirm_connection(args.rail, mv)
        ppk.use_source_meter()
        ppk.set_source_voltage(mv)
        # Enabling the output is a separate command from setting the regulator.
        # This used to live inside the --power-cycle branch, so a run without that
        # flag never energised the board and reported a plausible sub-microamp
        # "floor" from a DUT that was switched off — guaranteed rather than
        # intermittent, because the previous run's finally turns the output off.
        ppk.toggle_DUT_power("ON")
        print(f"source meter on {port} at {mv} mV, rail {args.rail}, output ON")

    # Acquisition and decode are separated deliberately. The PPK2 streams
    # 4 bytes per sample at a fixed 100 kSps = ~400 kB/s, and get_samples() is
    # pure Python doing per-sample work, so decoding inline cannot keep up: the
    # kernel serial buffer backs up and samples are lost silently. The capture
    # loop therefore does nothing but read bytes and stash them; everything is
    # decoded afterwards, from the same object so the calibration modifiers and
    # the cross-chunk remainder state still apply.
    #
    # Nothing is decoded during acquisition, including the over-current check:
    # that is post-hoc, because a live check fast enough to matter would have to
    # decode inline and would corrupt the capture it is protecting.
    CHUNK = 1 << 20

    t_arr, cur, cum = array("d"), array("f"), array("d")
    digital_raw = []
    pending = bytearray()
    meta_for_peek = {"modifiers": ppk.modifiers,
                     "mode": "SOURCE_MODE" if sourcing else "AMPERE_MODE",
                     "vdd_mv": mv if sourcing else args.vdd}
    raw_fh = open(args.raw_out, "wb") if args.raw_out else None
    if args.raw_out:
        # Save what decoding needs so the capture stays analysable later without
        # the PPK2 attached — the modifiers are device calibration, not in the
        # stream, and the conversion is mode-dependent.
        # The real voltage in both modes: get_adc_result() folds current_vdd into
        # its offset term with no mode guard, so writing 0 for ampere captures
        # biased every offline decode.
        with open(args.raw_out + ".json", "w") as fh:
            json.dump(meta_for_peek, fh)
        print(f"wrote {args.raw_out}.json (calibration sidecar)")

    abort_ma = RAILS[args.rail]["abort_ma"] if sourcing else None
    nbytes = 0

    # Decoding is what runs out of memory, and it happens after the capture — so
    # a forgotten --decimate would waste the whole run. Cap the decoded point
    # count instead of trusting the flag.
    expect = args.seconds * PPK2_SAMPLE_HZ
    dec_n = max(args.decimate, math.ceil(expect / 20e6))
    if dec_n > args.decimate:
        print(f"auto-decimating {dec_n}x: {expect/1e6:.0f}M samples would not fit "
              f"undecimated (means and charge are unaffected)")

    def stash(buf):
        if raw_fh:
            raw_fh.write(buf)
        else:
            pending.extend(buf)

    # Progress is sampled often enough never to miss a 3 s HP wake, but printed
    # only on a state change or once a minute — a 24-minute quiet stretch should
    # cost 24 lines, not 700. LP wakes (~3 ms at ~1 mA) cannot show up here: a
    # sampled peek essentially never lands on one, and catching them would need
    # the continuous decoding that cannot keep up with the stream. Read the lp
    # counter off the panel footer instead.
    # PEEK_BYTES is a ceiling: a single read at 400 kB/s with millisecond polling
    # returns a few hundred bytes, so a peek is typically 1-4 ms of signal.
    PEEK_EVERY_S, PRINT_EVERY_S, PEEK_BYTES = 1.0, 60.0, 4000
    AWAKE_UA = 1000.0
    peeker = None
    if meta_for_peek is not None:
        try:
            peeker = _offline_decoder(meta_for_peek)
        except Exception as exc:
            print(f"  (no live progress: {exc})")
    state = {"awake": None, "wakes": 0, "next_peek": 0.0, "next_print": 0.0}

    def progress(now, buf):
        """Estimate current from a small aligned slice of the newest bytes.

        Peeks go through a throwaway decoder: get_samples() carries remainder
        state forward, so peeking through the real one would corrupt the full
        decode afterwards.
        """
        if peeker is None or len(buf) < 8:
            return
        off = len(buf) % 4                      # align to a 4-byte sample boundary
        slice_ = bytes(buf[off:off + PEEK_BYTES])
        if len(slice_) < 8:
            return
        try:
            peeker.remainder = {"sequence": b"", "len": 0}
            sm, _ = peeker.get_samples(slice_)
        except Exception:
            return
        if not sm:
            return
        ua = sum(sm) / len(sm)
        awake = ua > AWAKE_UA
        changed = state["awake"] is not None and awake != state["awake"]
        if awake and not state["awake"]:
            state["wakes"] += 1
        state["awake"] = awake
        if changed or now >= state["next_print"]:
            el = now - t_start
            rate = nbytes / 4 / max(el, 1e-6) / 1000
            label = ("sleep -> AWAKE" if changed and awake else
                     "AWAKE -> sleep" if changed else "....")
            # Tilde because this is a few milliseconds of signal, not a figure: a
            # short slice of a PFM floor reads anywhere from 12 to 100 uA
            # depending on whether a spike lands in it. It is here to show
            # liveness and sleep-vs-awake, both of which survive that noise
            # against a 1000 uA threshold. Never quote it.
            shown = f"~{ua/1000:7.2f} mA" if awake else f"~{ua:7.1f} uA"
            print(f"t={el:8.1f}s  {label:14s} {shown}  {rate:5.1f} kSps  "
                  f"{state['wakes']} wake(s)", flush=True)
            state["next_print"] = now + PRINT_EVERY_S

    def drain(seconds):
        """Read for `seconds`, never leaving the port unread.

        At 400 kB/s the kernel CDC buffer overflows in a fraction of a second, so
        any time.sleep() longer than a few ms loses samples and desyncs the
        stream — get_samples() carries a remainder, so a gap corrupts every
        sample after it, not just the missing ones.
        """
        nonlocal nbytes
        end_t = time.time() + seconds
        while time.time() < end_t:
            buf = ppk.get_data()
            if not buf:
                time.sleep(0.002)
                continue
            nbytes += len(buf)
            stash(buf)
            now = time.time()
            if now >= state["next_peek"]:
                state["next_peek"] = now + PEEK_EVERY_S
                progress(now, buf)

    ppk.start_measuring()
    t_start = time.time()

    # Stream sanity: fail in under a second rather than after --seconds. Getting
    # the wrong CDC interface yields a trickle of bytes and an empty capture.
    drain(0.4)
    if nbytes < 1000:
        ppk.stop_measuring()
        if sourcing:
            ppk.toggle_DUT_power("OFF")
        sys.exit(f"stream is dead: {nbytes} bytes in 0.4s, expected ~160000. "
                 f"Wrong CDC interface, or another process is draining the port.")

    t_power = None
    try:
        if sourcing and args.power_cycle:
            # Output is already on; this is the OFF/wait/ON sequence that puts a
            # cold boot inside the capture.
            ppk.toggle_DUT_power("OFF")
            drain(args.off_seconds)
            ppk.toggle_DUT_power("ON")
            t_power = time.time()
            print(f"DUT powered at t~{t_power - t_start:.2f}s into the capture")
        drain(max(0.0, args.seconds - (time.time() - t_start)))
    finally:
        ppk.stop_measuring()
        if sourcing:
            ppk.toggle_DUT_power("OFF")
        if raw_fh:
            raw_fh.close()

    elapsed = time.time() - t_start
    got = nbytes // 4
    expect = int(elapsed * PPK2_SAMPLE_HZ)
    print(f"captured {nbytes} bytes = {got} samples in {elapsed:.2f}s "
          f"({got/elapsed/1000:.1f} kSps of an expected "
          f"{PPK2_SAMPLE_HZ/1000:.0f})")
    if got < expect * 0.98:
        print(f"  WARNING: {expect - got} samples short ({100*(1-got/expect):.1f}%). "
              f"Charge over a region is still the integral of what arrived, but "
              f"a gap inside a region under-reports it.")

    print("decoding...")
    samples = array("f")
    dec = _Decimator(dec_n)

    def feed(buf):
        sm, dg = ppk.get_samples(buf)
        dec.feed(sm, dg, samples, digital_raw)

    if raw_fh:
        with open(args.raw_out, "rb") as fh:
            while True:
                b = fh.read(CHUNK)
                if not b:
                    break
                feed(b)
    else:
        for off in range(0, len(pending), CHUNK):
            feed(pending[off:off + CHUNK])
        del pending

    # The inrush abort is post-hoc, not live, and deliberately so: decoding
    # inside the capture loop cannot sustain 400 kB/s, and a safety check that
    # corrupts the measurement it is protecting is worse than an honest absence.
    # The real safeguards are the typed confirmation and the per-rail clamp.
    # Note this reads the decimator's raw peak, not max(samples) — see _Decimator.
    if abort_ma and len(samples):
        peak = dec.peak / 1000.0
        if peak > abort_ma:
            print(f"  *** {peak:.0f} mA peak exceeded the {abort_ma:.0f} mA "
                  f"ceiling for rail {args.rail!r}. Power is already off. "
                  f"Check the connection before trusting this capture.")

    if args.raw_out:
        _cache_write(args.raw_out, dec.n, samples, digital_raw)
    tr = _trace_from_samples(samples, digital_raw, ppk, dec.n / PPK2_SAMPLE_HZ)
    del digital_raw

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            ch = sorted(tr.digital)
            w.writerow(["Timestamp(ms)", "Current(uA)"] + [f"D{c}" for c in ch])
            step_ms = dec.n / PPK2_SAMPLE_HZ * 1000
            for i in range(len(samples)):
                w.writerow([f"{i*step_ms:.3f}", f"{samples[i]:.3f}"]
                           + [tr.digital[c][i] for c in ch])
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

    r = sub.add_parser("raw", help="decode a stream saved by live --raw-out "
                                   "(needs the PPK2 attached for calibration)")
    r.add_argument("path")
    r.add_argument("--port")
    r.add_argument("--vdd", type=int, default=4200, metavar="MV",
                   help="supply voltage of the capture; only used without a "
                        "sidecar, and it enters the conversion's offset term")
    r.add_argument("--mode", choices=("source", "ampere"), default="source",
                   help="how the capture was taken; only used when there is no "
                        "sidecar, since the raw->current conversion depends on it")

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
    l.add_argument("--vdd", type=int, default=4200, metavar="MV",
                   help="in ampere-meter mode, the DUT's actual rail voltage — it "
                        "feeds the conversion's offset term, so a wrong value "
                        "biases every sample. Ignored when --rail sources.")
    l.add_argument("--port")
    l.add_argument("--out", metavar="CSV", help="also save the capture as CSV")
    l.add_argument("--raw-out", metavar="BIN",
                   help="stream raw PPK2 bytes here during capture instead of "
                        "buffering in RAM (~400 kB/s); use for long captures")

    for sp in (c, r, l):
        sp.add_argument("--cpu-ch", type=int, default=0, metavar="N",
                        help="PPK2 channel carrying CPU_ACTIVE/GPIO17 (default 0)")
        sp.add_argument("--display-ch", type=int, default=1, metavar="N",
                        help="PPK2 channel carrying DISPLAY/GPIO16 (default 1)")
        sp.add_argument("--decimate", type=int, default=1, metavar="N",
                        help="average N samples into one before analysis. Exact "
                             "for means and charge; needed for long captures, "
                             "which are ~28 bytes/sample decoded (use 100 for an "
                             "hour). Ignored by the csv reader.")
        sp.add_argument("--profile", type=float, metavar="MS",
                        help="print mean current in bins of MS milliseconds")
        sp.add_argument("--from", dest="from_s", type=float, metavar="SECONDS",
                        help="integrate an explicit window (with --to), in the same "
                             "seconds --profile prints; use for the unmarked "
                             "archive-format and WiFi phases")
        sp.add_argument("--to", dest="to_s", type=float, metavar="SECONDS")

    args = p.parse_args()
    if args.cmd == "csv":
        tr = load_csv(args.path)
    elif args.cmd == "raw":
        tr = decode_raw(args)
    else:
        tr = capture_live(args)
    tr.cpu_ch, tr.disp_ch = args.cpu_ch, args.display_ch
    report(tr, args.profile)
    if args.from_s is not None and args.to_s is not None:
        window(tr, args.from_s, args.to_s)


if __name__ == "__main__":
    main()
