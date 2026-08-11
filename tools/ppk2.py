#!/usr/bin/env python3
"""PPK2 trace analysis: charge per region, delimited by the firmware's own markers.

Two data sources, one analysis path:

    ppk2.py csv  trace.csv                 # export from nRF Connect Power Profiler
    ppk2.py live --seconds 30              # ampere meter (DUT externally powered)
    ppk2.py live --rail bat --power-cycle  # source meter; see SAFETY below
    ppk2.py sweep --rail reva-j1           # battery-floor sweep -> local/sweeps/

The point of the marker-driven regions is that charge figures stop depending on
where a human dragged a selection. `-DPPK2_DEBUG` drives two GPIOs:

    D0 (GPIO17)  HIGH for the whole awake phase (setup -> start_deep_sleep)
    D1 (GPIO16)  HIGH during a panel refresh, and again during an archive
                 flush -- the flush is preceded by three 50ms blips, which is
                 the only way to tell the two apart

`ppk2_selftest()` runs before D0 first goes high and emits 2x10ms on D0 then
5x4ms on D1 (older captures with the 5x20/10x10 fingerprint still verify).
That fingerprint is the probe-orientation check, and on a DISABLE_SERIAL build
it is the *only* one available, since the selftest's pass/fail line goes to a
console that is not there.

`sweep` maps the rev A board's operating regimes vs battery voltage: one typed
confirmation of the whole plan, then unattended fresh-boot steps down the
list, each classified from current alone (floor, LP-blip liveness, refresh,
boot-loops, storms), then an automatic bisect of the topmost
healthy/unhealthy edge plus a re-run of each side. Device firmware for it:

    PLATFORMIO_BUILD_FLAGS="-DBATTERY_SHUTDOWN_DISABLED -DDISABLE_WIFI" \\
        pio run -e thermometer_c6_debug -t upload

then detach serial and unplug USB. Results land in <out-dir>/report.md (a
paste-ready logbook table), summary.json, and replayable per-step raw
captures (`sweep --replay DIR`, `sweep --classify-file F --vin MV`;
`sweep --selftest` checks the classifier against synthesized signatures).

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

import artifacts

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
    # thermometer-c6 rev A battery injection, hardware/thermometer-c6/README.md
    # "Bench procedures". J1 is the deployment path (Q6 + charger leakage in the
    # measurement); J2 pin 2 is the VBAT node behind Q6. Same 900mA ceiling: it
    # must clear the 0.67A first-power inrush measured in Phase 1. NEVER source
    # into TP4/3V3 — RT9080 abs-max forbids VOUT > VIN + 0.3V.
    "reva-j1": {"min_mv": 3000, "max_mv": 4200, "abort_ma": 900.0,
                "check": "rev A board: PPK2 through the Dupont-into-JST harness "
                         "at J1, JP1 untouched, no battery, USB unplugged"},
    "reva-j2": {"min_mv": 3000, "max_mv": 4200, "abort_ma": 900.0,
                "check": "rev A board: PPK2 on J2 pin 2 (VBAT) + GND, JST "
                         "empty, JP1 cut open, USB unplugged"},
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
        """Find n consecutive spans of ~ms ANYWHERE in the list.

        Not just at the head: the ROM bootloader parks a UART pin high for ~218 ms
        and glitches around it before the app claims the pad, so the fingerprint is
        never the first thing on the channel. Checking spans[:n] meant a perfectly
        good fingerprint went undetected and the mapping was reported unverified.
        """
        want = ms / 1000.0
        for k in range(len(spans) - n + 1):
            if all(_near(tr.dur(sp), want) for sp in spans[k:k + n]):
                return True
        return False

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

    if cpu_here and disp_there:
        return (f"*** BOTH FINGERPRINTS ON D{tr.cpu_ch} *** "
                f"{cpu_n}x{cpu_ms}ms and {disp_n}x{disp_ms}ms both appear there, "
                f"and D{tr.disp_ch} carries nothing. The firmware drives them on "
                f"two separate GPIOs, so one lane showing both is a harness fault "
                f"of some kind — candidates, not a diagnosis: a lead loose enough "
                f"to float and capacitively pick up its neighbour, both leads on "
                f"one pin, or the two pins joined somewhere. Marker-attributed "
                f"figures below (which charge belongs to the refresh vs the rest "
                f"of the wake) are not trustworthy until it is resolved; "
                f"current-derived figures are unaffected.")
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


# --- Sweep step classification ----------------------------------------------
#
# Labels one voltage step of a battery-floor sweep from the current signature
# alone: the rev A board's UART is unusable mid-measurement (DTR reaches GPIO9,
# the BOOT strap and shutdown button) and PPK2_DEBUG markers land on the same
# J5 UART pins, so current is the only honest witness. The XIAO's "sag = input
# power drops" tell is a buck bootstrap artefact and deliberately not ported —
# through an LDO, input current tracks output current, and the expected failure
# is graceful dropout, brownout boot-loops, or a refresh that never completes.
#
# Thresholds come from measured numbers (docs/notes.md power logbook,
# 2026-07-29 rev A entries; Phase 1 in hardware/thermometer-c6/BRINGUP.md).
# All tests run on fixed 1 ms bin means, so they behave the same for a live
# decimated capture and a full-rate CSV replay; a sub-bin peak is only a lower
# bound here, and the orchestrator checks the decimator's raw peak separately.

STEP_BIN_S = 0.001
EV_UA = 200.0             # event floor: ~10x the 18-19 uA sleep floor, ~0.4x
                          # the 494 uA LP-poll mean — survives a blip split
                          # across two bins
EV_MERGE_S = 0.002
BLIP_MAX_S = 0.050        # LP poll measured 8 ms / 3.96 uC / 1.11 mA peak
BLIP_CEIL_UA = 5000.0
WAKE_MIN_S = 0.100        # non-refresh CPU wake measured ~0.5 s at ~15 mA
WAKE_MIN_UA = 5000.0
REFRESH_MIN_S = 1.0       # wake+refresh measured 23.4-24.6 mC over seconds
REFRESH_MIN_MC = 10.0
REFRESH_SURE_MC = 15.0    # charge alone proves a refresh when 1 ms bins
                          # average the EPD inrush below REFRESH_PEAK_UA (the
                          # 2026-07-29 hour capture hides 5 of its 8 that way):
                          # a non-refresh wake measured 7.74 mC, a wake+refresh
                          # 23.4-24.6 mC — 15 sits between
REFRESH_PEAK_UA = 50e3    # EPD boost inrush measured 571-605 mA on the C6
                          # prototype rig — far above any WiFi-less CPU wake
INRUSH_PEAK_UA = 100e3    # first-power inrush measured 0.67 A for 1-2 ms
INRUSH_MAX_S = 0.100
INRUSH_QUIET_S = 0.100    # a quiet lead-in separates a cold boot from the EPD
INRUSH_QUIET_UA = 1000.0  # inrush mid-wake, which mA-scale drive precedes
BOOTLOOP_MIN = 3
STORM_PEAK_UA = 50e3
DEAD_SAG_UA = 5.0         # a starved LDO input reads uA-scale while the board
                          # does nothing — distinct from PPK2-output-off ~0.1 uA
CLUSTER_GAP_S = 3.0       # the EPD busy-wait light-sleeps mid-refresh, dropping
                          # the current under EV_UA for seconds — the hour-long
                          # 2026-07-29 capture splits each wake+refresh into
                          # ~mA fragments. Non-blip activity closer than this is
                          # one episode; blips stay their own events
WAKE_MIN_MC = 1.0


def _bin_means(tr, t0, t1, bin_s=STEP_BIN_S):
    """Mean current per fixed bin over [t0, t1), from the cumulative array.

    For a 1 kS/s capture and 1 ms bins this is the identity; for a full-rate
    CSV it is the resample that makes the thresholds above rate-independent.
    """
    out_t, out_ua = array("d"), array("f")
    i0 = tr.index_at(t0)
    t = t0
    while t < t1 and i0 < len(tr):
        i1 = tr.index_at(t + bin_s)
        if i1 > i0 + 1:
            mean = tr.integrate(i0, i1)[1]
        else:
            # Zero or one new sample in this bin (source coarser than the bin):
            # hold the nearest sample rather than fabricating an integral.
            mean = tr.current_ua[min(i0, len(tr) - 1)]
        out_t.append(t)
        out_ua.append(mean)
        i0 = max(i0, i1)
        t += bin_s
    return out_t, out_ua


def _events(bt, bua, bin_s=STEP_BIN_S, thresh_ua=EV_UA, merge_s=EV_MERGE_S):
    """Merge above-threshold bins into events with width/mean/peak/charge."""
    gap_bins = max(1, int(merge_s / bin_s))
    runs, start, last_hi = [], None, None
    for k in range(len(bua)):
        if bua[k] > thresh_ua:
            if start is None:
                start = k
            last_hi = k
        elif start is not None and k - last_hi > gap_bins:
            runs.append((start, last_hi + 1))
            start = None
    if start is not None:
        runs.append((start, last_hi + 1))
    out = []
    for k0, k1 in runs:
        seg = bua[k0:k1]
        w = (k1 - k0) * bin_s
        mean = sum(seg) / len(seg)
        out.append({"k0": k0, "k1": k1, "t0": bt[k0], "w": w, "mean": mean,
                    "peak": max(seg), "mc": mean * w / 1000.0})
    return out


def _clusters(events, gap_s=CLUSTER_GAP_S):
    """Group events into activity episodes: one wake+refresh is one cluster even
    though its busy-wait light sleeps split it into many events."""
    out = []
    for ev in events:
        if out and ev["t0"] - out[-1]["t1"] < gap_s:
            c = out[-1]
            c["t1"] = ev["t0"] + ev["w"]
            c["mc"] += ev["mc"]
            c["peak"] = max(c["peak"], ev["peak"])
        else:
            out.append({"t0": ev["t0"], "t1": ev["t0"] + ev["w"],
                        "mc": ev["mc"], "peak": ev["peak"]})
    for c in out:
        c["span"] = c["t1"] - c["t0"]
        c["kind"] = _cluster_kind(c)
    return out


def _cluster_kind(c):
    if c["span"] >= REFRESH_MIN_S and (
            (c["mc"] >= REFRESH_MIN_MC and c["peak"] >= REFRESH_PEAK_UA)
            or c["mc"] >= REFRESH_SURE_MC):
        return "refresh"
    if (c["span"] >= WAKE_MIN_S and c["mc"] >= WAKE_MIN_MC
            and c["peak"] < STORM_PEAK_UA):
        return "wake"
    mean_ua = c["mc"] / max(c["span"], 1e-9) * 1000.0
    if c["peak"] > STORM_PEAK_UA or mean_ua > WAKE_MIN_UA:
        return "storm"
    return "other"


def _median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


def classify_step(tr, cfg):
    """Label one sweep step. Pure: a Trace and a config dict in, a dict out.

    cfg keys: mv, boot_s, blip_period_s, power_cycle, t_on (trace time of the
    commanded power-on; None falls back to the current-derived index, which a
    deeply sagged board can defeat — see the note on POWER_ON_UA).
    """
    t_end = tr.t[-1]
    t_on = cfg.get("t_on")
    t_cur = tr.t[tr.power_on]
    if t_on is None:
        t_on = t_cur
    notes = []
    # Only a LATE current-derived power-on is anomalous (no draw when power was
    # commanded). An early one is the previous step's caps discharging through
    # the board during the off window — every step after the first shows it.
    if cfg.get("t_on") is not None and t_cur - cfg["t_on"] > 1.0:
        notes.append(f"no current until t={t_cur:.2f}s despite power commanded "
                     f"at t={cfg['t_on']:.2f}s — open leads or a board drawing "
                     f"nothing")
    boot_end = min(t_on + cfg["boot_s"], t_end) if cfg["power_cycle"] else t_on

    bt, bua = _bin_means(tr, t_on, t_end)
    res = {"label": None, "mv": cfg.get("mv"), "notes": notes,
           "floor_ua": None, "power_uw": None, "peak_ma": None,
           "blips": 0, "blips_expected": 0, "blip_median_s": None,
           "wakes": 0, "dwell_refreshes": 0, "refresh": None, "bootloops": 0,
           "bootloop_median_s": None, "storms": 0, "storm_peak_ma": None,
           "alive": False, "dwell_s": max(0.0, t_end - boot_end)}
    if not len(bua):
        res["label"] = "DEAD"
        notes.append("empty capture window")
        return res

    peak_bin = max(bua)
    res["peak_ma"] = peak_bin / 1000.0
    if peak_bin < POWER_ON_UA:
        res["label"] = "DEAD"
        notes.append(f"current never rose above {POWER_ON_UA} uA — open "
                     f"leads, or the output never came on")
        return res

    evs = _events(bt, bua)
    blips_all, solid = [], []
    for ev in evs:
        (blips_all if ev["w"] <= BLIP_MAX_S and ev["peak"] < BLIP_CEIL_UA
         else solid).append(ev)

    # A cold boot announces itself: an inrush-class spike out of silence. The
    # EPD inrush mid-wake fails the quiet lead-in; the very first event of the
    # window (power-on) passes it by construction. Counted on raw events, not
    # clusters — a ~600 ms boot loop merges into one cluster and would hide.
    lead = int(INRUSH_QUIET_S / STEP_BIN_S)
    boots = []
    for ev in solid:
        if ev["w"] < INRUSH_MAX_S and ev["peak"] > INRUSH_PEAK_UA:
            pre = bua[max(0, ev["k0"] - lead):ev["k0"]]
            if not len(pre) or max(pre) < INRUSH_QUIET_UA:
                boots.append(ev)
    res["bootloops"] = len(boots)
    res["bootloop_median_s"] = _median(
        [b["t0"] - a["t0"] for a, b in zip(boots, boots[1:])])

    clusters = _clusters(solid)
    blips = [e for e in blips_all if e["t0"] >= boot_end]
    dwell = [c for c in clusters if c["t0"] >= boot_end]
    wakes = [c for c in dwell if c["kind"] == "wake"]
    refr_d = [c for c in dwell if c["kind"] == "refresh"]
    storms = [c for c in dwell if c["kind"] == "storm"]
    odd = [c for c in dwell if c["kind"] == "other"]
    res["blips"], res["wakes"], res["storms"] = len(blips), len(wakes), len(storms)
    res["dwell_refreshes"] = len(refr_d)
    if storms:
        res["storm_peak_ma"] = max(c["peak"] for c in storms) / 1000.0
    if odd:
        notes.append(f"{len(odd)} unclassified small episode(s) in the dwell")
    long_c = [c for c in dwell if c["span"] > 0.2 * max(res["dwell_s"], 1e-9)]
    if long_c and res["dwell_s"] > 30:
        notes.append(f"continuous activity: an episode spans "
                     f"{max(c['span'] for c in long_c):.0f}s of the "
                     f"{res['dwell_s']:.0f}s dwell — burst/churn regime, "
                     f"not sleep")

    refresh_b = [c for c in clusters
                 if c["kind"] == "refresh" and c["t0"] < boot_end]
    if refresh_b:
        c = max(refresh_b, key=lambda c: c["mc"])
        res["refresh"] = {"mc": c["mc"], "s": c["span"],
                          "peak_ma": c["peak"] / 1000.0}

    # Liveness: the LP core polls the sensor every blip_period, so a living
    # board cannot be quiet for long. Wakes and delta refreshes count too — a
    # volatile room converts blips into wakes, not into silence.
    expected = res["dwell_s"] / cfg["blip_period_s"]
    res["blips_expected"] = expected
    live = len(blips) + len(wakes) + len(refr_d)
    count_ok = live >= 0.5 * expected
    res["blip_median_s"] = _median(
        [b["t0"] - a["t0"] for a, b in zip(blips, blips[1:])])
    cadence_ok = True
    if len(blips) >= 3:
        cadence_ok = (0.5 * cfg["blip_period_s"] <= res["blip_median_s"]
                      <= 1.5 * cfg["blip_period_s"])
    res["alive"] = count_ok and cadence_ok

    i0, i1 = tr.index_at(boot_end), len(tr)
    if i1 - i0 > 2:
        res["floor_ua"] = floor_of(tr, i0, i1)
        if cfg.get("mv"):
            res["power_uw"] = res["floor_ua"] * cfg["mv"] / 1000.0

    if res["bootloops"] >= BOOTLOOP_MIN:
        res["label"] = "BOOTLOOP"
    elif not res["alive"]:
        # A completed boot render is proof the board runs — a broken sleep
        # after it degrades, it does not kill (rev A at 3.31 V boots, renders,
        # then idles at ~104 uA with ~55 Hz small events; run 2026-07-30).
        res["label"] = "DEGRADED" if refresh_b else "DEAD"
        if res["blips"] > 5 * max(expected, 1.0) and res["blip_median_s"]:
            notes.append(f"sleep is broken: {res['blips']} sub-50ms events at "
                         f"~{1.0/res['blip_median_s']:.0f} Hz — oscillation/"
                         f"churn, not idle")
        elif res["floor_ua"] is not None and res["floor_ua"] < DEAD_SAG_UA:
            notes.append(f"floor {res['floor_ua']:.2f} uA — sagged/starved, "
                         f"not merely idle")
        else:
            notes.append("no liveness at the expected cadence")
    elif res["storms"] or (cfg["power_cycle"] and not refresh_b):
        res["label"] = "DEGRADED"
        if cfg["power_cycle"] and not refresh_b:
            notes.append("no completed refresh in the boot window")
    else:
        res["label"] = "HEALTHY"
    return res


def _synth_trace(dur_s, base_ua, events, dt=0.001):
    """A synthetic 1 kS/s trace: a base level with (t0, width_s, ua) overlays,
    applied in order so later entries paint over earlier ones."""
    n = int(dur_s / dt)
    cur = array("f", [base_ua] * n)
    for t0, w, ua in events:
        for i in range(int(t0 / dt), min(n, int((t0 + w) / dt))):
            cur[i] = ua
    t, cum = array("d"), array("d")
    acc, prev = 0.0, None
    for i in range(n):
        if prev is not None:
            acc += 0.5 * (prev + cur[i]) * dt
        t.append(i * dt)
        cum.append(acc)
        prev = cur[i]
    return Trace(t, cur, cum)


def run_selftest():
    """Classifier checks on synthesized signatures. No hardware, no files."""
    cfg = {"mv": 3800, "boot_s": 20.0, "blip_period_s": 5.0,
           "power_cycle": True, "t_on": 2.0}
    powered = [(2.0, 110.0, 19.0)]
    boot_wake = [(2.0, 0.002, 500e3), (2.002, 0.5, 15e3)]
    refresh = [(2.5, 4.0, 20e3), (2.6, 0.003, 450e3)]
    blips = [(10.0 + 5 * k, 0.008, 500.0) for k in range(21)]

    cases = [
        ("healthy", cfg, powered + boot_wake + refresh + blips, "HEALTHY",
         lambda r: r["refresh"] and r["storms"] == 0 and r["alive"]
         and 18.0 < r["floor_ua"] < 20.0),
        ("bootloop", cfg, [(2.0 + 0.6 * k, 0.02, 300e3) for k in range(180)],
         "BOOTLOOP", lambda r: r["bootloops"] >= 3
         and 0.5 < (r["bootloop_median_s"] or 0) < 0.7),
        ("dead-sagged", cfg, [(2.0, 0.002, 500e3), (2.002, 109.998, 3.0)],
         "DEAD", lambda r: r["floor_ua"] < DEAD_SAG_UA),
        ("degraded-storms", cfg,
         powered + boot_wake + refresh + blips
         + [(40.0, 0.03, 8e3), (60.0, 0.03, 8e3), (80.0, 0.02, 120e3)],
         "DEGRADED", lambda r: r["storms"] == 3),
        ("degraded-no-refresh", cfg, powered + boot_wake + blips,
         "DEGRADED", lambda r: r["refresh"] is None and r["alive"]),
        ("wrong-cadence", cfg,
         powered + boot_wake + refresh
         + [(10.0, 0.008, 500.0), (70.0, 0.008, 500.0)],
         "DEGRADED", lambda r: not r["alive"] and r["floor_ua"] > 15.0),
        ("no-boot-no-liveness", cfg, powered,
         "DEAD", lambda r: not r["alive"] and r["refresh"] is None),
        ("oscillating-sleep", cfg,
         powered + boot_wake + refresh
         + [(25.0 + 0.018 * k, 0.004, 500.0) for k in range(4800)],
         "DEGRADED", lambda r: not r["alive"]
         and any("oscillation" in n for n in r["notes"])),
        ("ampere-dwell",
         {"mv": 4200, "boot_s": 0.0, "blip_period_s": 5.0,
          "power_cycle": False, "t_on": None},
         [(5.0 + 5 * k, 0.008, 500.0) for k in range(21)],
         "HEALTHY", lambda r: r["alive"] and r["refresh"] is None),
    ]

    failed = 0
    for name, c, events, want, extra in cases:
        base = 0.1 if c["power_cycle"] else 19.0
        res = classify_step(_synth_trace(112.0, base, events), c)
        ok = res["label"] == want and extra(res)
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:20s} -> {res['label']:9s}"
              f" floor={res['floor_ua'] if res['floor_ua'] is None else round(res['floor_ua'], 2)}"
              f" blips={res['blips']} storms={res['storms']}"
              f" bootloops={res['bootloops']}"
              + (f"  notes={res['notes']}" if not ok else ""))
    print(f"selftest: {len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


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


def _connection_banner(rail, mv_text):
    """The what-is-about-to-be-energised block, shared by live and sweep."""
    spec = RAILS[rail]
    last = _load_state().get("rail")
    print("\n" + "=" * 68)
    print(f"  ABOUT TO SOURCE {mv_text}  (rail: {rail})")
    print("=" * 68)
    print(f"  Confirm: {spec['check']}")
    if last and last != rail:
        print(f"\n  !! Last sourced run used rail {last!r}. You are now")
        print(f"     declaring {rail!r}. Confirm the leads actually moved.")
    # Any rail allowed above 3.3V is a battery-voltage rail, and battery voltage
    # on the 3V3 rail is the destructive mix-up.
    if spec["max_mv"] > 3300:
        print("\n  If these leads are on the 3V3 rail, this will exceed the")
        print("  C6's 3.6 V absolute maximum and destroy the MCU, the panel")
        print("  and the sensor together.")


def confirm_connection(rail, mv):
    """Typed confirmation of the physical connection. Never inferred, never
    remembered across a rail change — see the device-session skill."""
    _connection_banner(rail, f"{mv} mV")
    _typed_confirmation(f"{rail} {mv}")
    _save_state({"rail": rail, "mv": mv, "when": time.time()})


def _typed_confirmation(expected):
    """Demand `expected` typed back on a real terminal, or abort.

    A pipe is not a person. CLAUDE.md encourages delegating long capture loops
    to subagents, so `printf 'bat 4200\\n' | ppk2.py live --rail bat` is a
    realistic invocation — and it would source 4.2V with nobody having looked at
    the leads. Requiring a tty is the only thing standing between that and a
    3.6V-absolute-max rail.
    """
    if not sys.stdin.isatty():
        sys.exit("aborted: stdin is not a terminal, so nobody can confirm the "
                 "leads. Sourcing requires an interactive confirmation — run this "
                 "in a terminal, not piped, redirected, or from a subagent.")
    print(f"\n  Type exactly: {expected}")
    try:
        got = input("  > ").strip()
    except EOFError:
        sys.exit("aborted: no confirmation possible on a non-interactive stdin")
    if got != expected:
        sys.exit("aborted: confirmation did not match")


def _connect(args):
    """Open the PPK2's measurement interface. Reads calibration only — does not
    source, measure, or touch DUT power, so it is safe with any wiring.

    The PPK2 exposes two CDC interfaces and pyserial enumerates them in either
    order. Only interface .1 carries the measurement stream; commands written to
    the other are accepted silently and no samples ever arrive. So probe rather
    than guess: get_modifiers() returns False unless it actually parsed the
    calibration blob back."""
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
        # One counter per logic channel. A single scalar here collapsed all eight
        # channels into bit 0, so every marker appeared on D0 and D1 was always
        # empty — majority has to be decided per channel, not across them.
        self.dig_hi = [0] * 8
        # Peak of the RAW samples, tracked before averaging. The over-current
        # ceiling has to test this: a 2A fault lasting 200us averages to ~400mA
        # in a 1ms bin and slips under a 900mA limit, and any capture over ~200s
        # auto-decimates, so testing bin means disables the check exactly when
        # captures are long enough to matter.
        self.peak = 0.0

    def feed(self, vals, bits, out_samples, out_bits):
        n, hi = self.n, self.dig_hi
        if n == 1:
            # Identity: nothing to average, so pass the channel bitmask straight
            # through. Also the fast path for marker captures, which must run at
            # --decimate 1 for the fingerprint to survive.
            for i, v in enumerate(vals):
                if v > self.peak:
                    self.peak = v
                out_samples.append(v)
                out_bits.append(bits[i] if i < len(bits) else 0)
            return
        half = n // 2
        for i, v in enumerate(vals):
            if v > self.peak:
                self.peak = v
            self.acc += v
            b = bits[i] if i < len(bits) else 0
            if b:
                for c in range(8):
                    if (b >> c) & 1:
                        hi[c] += 1
            self.cnt += 1
            if self.cnt == n:
                out_samples.append(self.acc / n)
                # Per-channel majority, not OR. OR turned microsecond pad ringing
                # into a solid HIGH bin, so at N>=4 a 0.6 s burst became one 600 ms
                # span reported as a real awake phase carrying ~9 mC. A real marker
                # fills its bin; ringing occupies a few percent of it.
                mask = 0
                for c in range(8):
                    if hi[c] > half:
                        mask |= 1 << c
                    hi[c] = 0
                out_bits.append(mask)
                self.acc = 0.0
                self.cnt = 0


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
    # __del__ closes self.ser under `if self.ser:` — None satisfies it quietly;
    # absent, every GC of a decoder logs a spurious closing error.
    d.ser = None
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
    # v2: caches written before the per-channel majority fix hold digital data
    # with all eight channels collapsed into bit 0, so they must not be reused.
    return f"{raw_path}.dec{n}.v2.f32", f"{raw_path}.dec{n}.v2.d8"


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
            # Unsigned: array("b") is signed char, and the previous guard mapped
            # any byte >=128 to 0, silently discarding every channel for those
            # points whenever D7 was high.
            array("B", [b & 0xFF for b in digital_raw]).tofile(fh)
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
    dig = array("B")
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
    # Same choice the capture path makes, for the same reason: decoding is what
    # runs out of memory, and an hour of raw is 360M samples. Deriving it here
    # rather than trusting `--decimate` fixes two failures that looked unrelated.
    # A bare `raw` used to decode undecimated and needed ~10 GB — it is the one
    # command likely to be pointed at the largest file on disk. And because the
    # cache is keyed on N, it also missed the cache the capture had just written,
    # so the reward for surviving was a ten-minute re-decode of data already on
    # disk. File size is exact here (4 bytes/sample), where the capture path can
    # only estimate from --seconds.
    dec_n = _choose_decimation(os.path.getsize(args.path) // 4, args.decimate)

    cached = _cache_read(args.path, dec_n)
    if cached is not None:
        samples, digital_raw = cached
        dt = dec_n / PPK2_SAMPLE_HZ
        print(f"decoded from cache: {len(samples)} points ({len(samples)*dt:.1f} s)"
              + (f", decimated {dec_n}x" if dec_n > 1 else ""))
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
    dec = _Decimator(dec_n)
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


class _Stream:
    """Acquisition state for one capture: raw bytes in, decoded samples out.

    Owns the read loop, the progress peeker and the byte buffers, so a caller
    can run several captures over one connection (the sweep does) without
    re-plumbing the acquisition rules.

    Acquisition and decode are separated deliberately. The PPK2 streams
    4 bytes per sample at a fixed 100 kSps = ~400 kB/s, and get_samples() is
    pure Python doing per-sample work, so decoding inline cannot keep up: the
    kernel serial buffer backs up and samples are lost silently. The capture
    loop therefore does nothing but read bytes and stash them; everything is
    decoded afterwards. Nothing is decoded during acquisition, including the
    over-current check: that is post-hoc, because a live check fast enough to
    matter would have to decode inline and would corrupt the capture it is
    protecting.
    """

    CHUNK = 1 << 20
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

    def __init__(self, ppk, meta, raw_out=None, label=""):
        self.ppk = ppk
        self.raw_out = raw_out
        self.label = label
        self.pending = bytearray()
        self.nbytes = 0
        self.t_start = None
        self.state = {"awake": None, "wakes": 0,
                      "next_peek": 0.0, "next_print": 0.0}
        self.raw_fh = open(raw_out, "wb") if raw_out else None
        if raw_out:
            # Save what decoding needs so the capture stays analysable later
            # without the PPK2 attached — the modifiers are device calibration,
            # not in the stream, and the conversion is mode-dependent.
            # vdd_mv is the real voltage in both modes: get_adc_result() folds
            # current_vdd into its offset term with no mode guard, so writing 0
            # for ampere captures biased every offline decode.
            with open(raw_out + ".json", "w") as fh:
                json.dump(meta, fh)
            print(f"wrote {raw_out}.json (calibration sidecar)")
        self.peeker = None
        try:
            self.peeker = _offline_decoder(meta)
        except Exception as exc:
            print(f"  (no live progress: {exc})")

    def start(self, sanity=True):
        self.ppk.start_measuring()
        self.t_start = time.time()
        if sanity:
            # Stream sanity: fail in under a second rather than after the full
            # capture. Getting the wrong CDC interface yields a trickle of bytes
            # and an empty capture.
            self.drain(0.4)
            if self.nbytes < 1000:
                self.stop()
                raise RuntimeError(
                    f"stream is dead: {self.nbytes} bytes in 0.4s, expected "
                    f"~160000. Wrong CDC interface, or another process is "
                    f"draining the port.")

    def stop(self):
        try:
            self.ppk.stop_measuring()
        finally:
            if self.raw_fh:
                self.raw_fh.close()
                self.raw_fh = None

    def drain(self, seconds):
        """Read for `seconds`, never leaving the port unread.

        At 400 kB/s the kernel CDC buffer overflows in a fraction of a second, so
        any time.sleep() longer than a few ms loses samples and desyncs the
        stream — get_samples() carries a remainder, so a gap corrupts every
        sample after it, not just the missing ones.
        """
        end_t = time.time() + seconds
        while time.time() < end_t:
            buf = self.ppk.get_data()
            if not buf:
                time.sleep(0.002)
                continue
            self.nbytes += len(buf)
            if self.raw_fh:
                self.raw_fh.write(buf)
            else:
                self.pending.extend(buf)
            now = time.time()
            if now >= self.state["next_peek"]:
                self.state["next_peek"] = now + self.PEEK_EVERY_S
                self.progress(now, buf)

    def progress(self, now, buf):
        """Estimate current from a small aligned slice of the newest bytes.

        Peeks go through a throwaway decoder: get_samples() carries remainder
        state forward, so peeking through the real one would corrupt the full
        decode afterwards.
        """
        state = self.state
        if self.peeker is None or len(buf) < 8:
            return
        off = len(buf) % 4                      # align to a 4-byte sample boundary
        slice_ = bytes(buf[off:off + self.PEEK_BYTES])
        if len(slice_) < 8:
            return
        try:
            self.peeker.remainder = {"sequence": b"", "len": 0}
            sm, _ = self.peeker.get_samples(slice_)
        except Exception:
            return
        if not sm:
            return
        ua = sum(sm) / len(sm)
        awake = ua > self.AWAKE_UA
        changed = state["awake"] is not None and awake != state["awake"]
        if awake and not state["awake"]:
            state["wakes"] += 1
        state["awake"] = awake
        if changed or now >= state["next_print"]:
            el = now - self.t_start
            rate = self.nbytes / 4 / max(el, 1e-6) / 1000
            label = ("sleep -> AWAKE" if changed and awake else
                     "AWAKE -> sleep" if changed else "....")
            # Tilde because this is a few milliseconds of signal, not a figure: a
            # short slice of a PFM floor reads anywhere from 12 to 100 uA
            # depending on whether a spike lands in it. It is here to show
            # liveness and sleep-vs-awake, both of which survive that noise
            # against a 1000 uA threshold. Never quote it.
            shown = f"~{ua/1000:7.2f} mA" if awake else f"~{ua:7.1f} uA"
            pre = f"[{self.label}] " if self.label else ""
            print(f"{pre}t={el:8.1f}s  {label:14s} {shown}  {rate:5.1f} kSps  "
                  f"{state['wakes']} wake(s)", flush=True)
            state["next_print"] = now + self.PRINT_EVERY_S

    def print_capture_stats(self):
        elapsed = time.time() - self.t_start
        got = self.nbytes // 4
        expect = int(elapsed * PPK2_SAMPLE_HZ)
        print(f"captured {self.nbytes} bytes = {got} samples in {elapsed:.2f}s "
              f"({got/elapsed/1000:.1f} kSps of an expected "
              f"{PPK2_SAMPLE_HZ/1000:.0f})")
        if got < expect * 0.98:
            print(f"  WARNING: {expect - got} samples short "
                  f"({100*(1-got/expect):.1f}%). Charge over a region is still "
                  f"the integral of what arrived, but a gap inside a region "
                  f"under-reports it.")

    def decode(self, dec_n):
        """Decode everything captured. Returns (samples, digital_raw, decimator).

        get_samples() keeps cross-chunk remainder state on the ppk object, so it
        is cleared first — a previous capture on the same connection must not
        bleed a partial sample into this one.
        """
        samples = array("f")
        digital_raw = []
        dec = _Decimator(dec_n)
        self.ppk.remainder = {"sequence": b"", "len": 0}

        def feed(buf):
            sm, dg = self.ppk.get_samples(buf)
            dec.feed(sm, dg, samples, digital_raw)

        if self.raw_out:
            with open(self.raw_out, "rb") as fh:
                while True:
                    b = fh.read(self.CHUNK)
                    if not b:
                        break
                    feed(b)
        else:
            for off in range(0, len(self.pending), self.CHUNK):
                feed(self.pending[off:off + self.CHUNK])
            self.pending = bytearray()
        return samples, digital_raw, dec


def _choose_decimation(expect_samples, requested):
    """Pick the decode decimation. Decoding is what runs out of memory, and it
    happens after the capture — so a forgotten --decimate would waste the whole
    run. Cap the decoded point count instead of trusting the flag."""
    if requested is not None:
        # Explicit beats implicit. Overriding a requested --decimate 1 defeated the
        # reason for asking: the marker fingerprint does not survive decimation.
        dec_n = max(1, requested)
        est_mb = expect_samples / dec_n * 28 / 1e6
        if est_mb > 600:
            print(f"note: --decimate {dec_n} on {expect_samples/1e6:.0f}M samples "
                  f"needs ~{est_mb:.0f} MB to decode. Honouring it as asked.")
        return dec_n
    dec_n = max(1, math.ceil(expect_samples / 20e6))
    if dec_n > 1:
        print(f"auto-decimating {dec_n}x: {expect_samples/1e6:.0f}M samples would "
              f"not fit undecimated (means and charge are unaffected; pass "
              f"--decimate 1 to override, e.g. for marker captures)")
    return dec_n


def _overcurrent_msg(peak_ma, rail):
    return (f"  *** {peak_ma:.0f} mA peak exceeded the "
            f"{RAILS[rail]['abort_ma']:.0f} mA ceiling for rail {rail!r}. "
            f"Power is already off. Check the connection before trusting "
            f"this capture.")


def capture_live(args):
    ppk, port = _connect(args)

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
        if not args.power_cycle:
            # --power-cycle wants the capture to begin with the DUT unpowered, so
            # energising here would boot the board and then kill it 2 s later,
            # leaving a truncated boot in front of the real one.
            ppk.toggle_DUT_power("ON")
        print(f"source meter on {port} at {mv} mV, rail {args.rail}"
              + (", output held off until the power cycle" if args.power_cycle
                 else ", output ON"))

    meta = {"modifiers": ppk.modifiers,
            "mode": "SOURCE_MODE" if sourcing else "AMPERE_MODE",
            "vdd_mv": mv if sourcing else args.vdd}
    stream = _Stream(ppk, meta, raw_out=args.raw_out)
    abort_ma = RAILS[args.rail]["abort_ma"] if sourcing else None
    dec_n = _choose_decimation(args.seconds * PPK2_SAMPLE_HZ, args.decimate)

    try:
        stream.start()
    except RuntimeError as exc:
        if sourcing:
            ppk.toggle_DUT_power("OFF")
        sys.exit(str(exc))

    t_power = None
    try:
        if sourcing and args.power_cycle:
            # Output is already on; this is the OFF/wait/ON sequence that puts a
            # cold boot inside the capture.
            ppk.toggle_DUT_power("OFF")
            stream.drain(args.off_seconds)
            ppk.toggle_DUT_power("ON")
            t_power = time.time()
            print(f"DUT powered at t~{t_power - stream.t_start:.2f}s into the capture")
        stream.drain(max(0.0, args.seconds - (time.time() - stream.t_start)))
    finally:
        stream.stop()
        if sourcing:
            ppk.toggle_DUT_power("OFF")

    stream.print_capture_stats()

    print("decoding...")
    samples, digital_raw, dec = stream.decode(dec_n)

    # The inrush abort is post-hoc, not live, and deliberately so: decoding
    # inside the capture loop cannot sustain 400 kB/s, and a safety check that
    # corrupts the measurement it is protecting is worse than an honest absence.
    # The real safeguards are the typed confirmation and the per-rail clamp.
    # Note this reads the decimator's raw peak, not max(samples) — see _Decimator.
    if abort_ma and len(samples):
        peak = dec.peak / 1000.0
        if peak > abort_ma:
            print(_overcurrent_msg(peak, args.rail))

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


# --- Sweep orchestration ----------------------------------------------------
#
# One interactive typed confirmation of the whole plan (rail, full voltage
# range, dwell), then an unattended walk down the list with a fresh power-cycled
# boot per step, classification per step, and an automatic bisect of the
# topmost healthy/unhealthy edge. The firmware on the device must be a sweep
# build — thermometer_c6_debug with -DBATTERY_SHUTDOWN_DISABLED -DDISABLE_WIFI —
# or every step below 3700 mV latches the board off (and writes flash) before
# a single LP blip can prove it alive.


class _SweepAbort(Exception):
    pass


def _git_describe():
    import subprocess
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"],
                             cwd=os.path.dirname(os.path.abspath(__file__)),
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _sweep_mv_list(args):
    spec = RAILS[args.rail]
    if args.mv:
        try:
            mvs = [int(v) for v in args.mv.split(",")]
        except ValueError:
            sys.exit(f"--mv wants comma-separated integers, got {args.mv!r}")
    else:
        if args.step <= 0:
            sys.exit("--step must be positive")
        mvs = list(range(args.start, args.stop - 1, -args.step))
        if mvs and mvs[-1] != args.stop:
            mvs.append(args.stop)
    mvs = sorted(set(mvs), reverse=True)
    if not mvs:
        sys.exit("empty voltage list")
    for mv in mvs:
        if not spec["min_mv"] <= mv <= spec["max_mv"]:
            sys.exit(f"refusing {mv} mV on rail {args.rail!r}: allowed "
                     f"{spec['min_mv']}-{spec['max_mv']} mV")
    return mvs


def _step_row(res):
    fl = res.get("floor_ua")
    pw = res.get("power_uw")
    rf = res.get("refresh")
    floor_s = f"{fl:9.2f} uA" if fl is not None else "      n/a"
    power_s = f"{pw:7.1f} uW" if pw is not None else "    n/a"
    rf_s = f"{rf['mc']:.1f}mC/{rf['peak_ma']:.0f}mA" if rf else "-"
    return (f"  {res['mv']/1000:5.2f} V  floor {floor_s}  {power_s}  "
            f"{res['label']:10s} "
            f"blips {res['blips']:3d}/{res['blips_expected']:4.0f}  "
            f"refresh {rf_s:>14s}  "
            f"storms {res['storms']:2d}  peak {(res['peak_ma'] or 0):6.0f} mA  "
            f"[{res.get('phase', '?')}]")


def _md_row(res):
    fl = res.get("floor_ua")
    pw = res.get("power_uw")
    rf = res.get("refresh")
    cells = [
        f"{res['mv']/1000:.2f} V",
        f"{fl:.2f} uA" if fl is not None else "n/a",
        f"{pw:.0f} uW" if pw is not None else "n/a",
        res["label"],
        f"{rf['mc']:.1f} mC / {rf['s']:.1f} s / {rf['peak_ma']:.0f} mA" if rf else "-",
        f"{res['blips']}/{res['blips_expected']:.0f}",
        str(res["storms"]) + (f" (pk {res['storm_peak_ma']:.0f} mA)"
                              if res.get("storm_peak_ma") else ""),
        f"{(res['peak_ma'] or 0):.0f} mA",
        res.get("phase", "?"),
        "; ".join(res.get("notes", [])) or "-",
    ]
    return "| " + " | ".join(cells) + " |"


def _write_outputs(plan, steps, status, edge):
    out_dir = plan["out_dir"]
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump({"status": status, "plan": plan, "edge": edge,
                   "steps": steps}, fh, indent=1)
    lines = [f"# Battery-floor sweep — rail {plan['rail']} — {plan['date']}", ""]
    lines.append(f"- status: **{status}**")
    lines.append(f"- connection: {RAILS[plan['rail']]['check']}")
    lines.append(f"- host git: {plan['git']}; on-device build: "
                 + (plan["build_note"] or "**not recorded — record it!**"))
    lines.append(f"- dwell {plan['dwell_s']} s, boot window {plan['boot_s']} s, "
                 f"off {plan['off_s']} s, decimate {plan['decimate']} "
                 f"({plan['decimate']/PPK2_SAMPLE_HZ*1000:g} ms bins), "
                 f"blip period {plan['blip_period_s']} s, "
                 f"power-cycle per step: {plan['power_cycle']}")
    lines.append("")
    lines.append("| VIN | floor | input power | regime | refresh | blips "
                 "| storms | peak | phase | notes |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in steps:
        lines.append(_md_row(r))
    lines.append("")
    if edge:
        if edge.get("first_unhealthy_mv"):
            lines.append(f"**Edge**: lowest HEALTHY fresh boot "
                         f"{edge['lowest_healthy_mv']} mV; first non-healthy "
                         f"{edge['first_unhealthy_mv']} mV.")
        else:
            lines.append(f"**Edge**: none — every step down to "
                         f"{edge['lowest_healthy_mv']} mV was HEALTHY.")
        for a in edge.get("anomalies", []):
            lines.append(f"- anomaly: {a}")
    lines.append("")
    lines.append("A fresh-boot regime map, not a deployment threshold by "
                 "itself: re-derive Thermometer.cpp thresholds with margin for "
                 "cold (VTH rises), battery ESR + protection-PCB drop, and the "
                 "refresh peak. Raw steps replay with "
                 "`ppk2.py raw <step>.bin` or `sweep --replay`.")
    with open(os.path.join(out_dir, "report.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _run_step(ppk, args, mv, dec_n, out_dir, seq, phase):
    power_cycle = not args.no_power_cycle
    raw = (None if args.no_raw else
           os.path.join(out_dir, f"step{seq:02d}-{mv}mv.bin"))
    meta = {"modifiers": ppk.modifiers, "mode": "SOURCE_MODE", "vdd_mv": mv}
    if power_cycle:
        ppk.toggle_DUT_power("OFF")
    ppk.set_source_voltage(mv)
    stream = _Stream(ppk, meta, raw_out=raw, label=f"{mv}mV")
    stream.start()
    t_on = None
    try:
        if power_cycle:
            stream.drain(max(0.0, args.off_seconds - 0.4))
            # Commanded, not inferred: a deeply sagged board floats below
            # POWER_ON_UA and current-based detection would blind the classifier
            # exactly in the regime the sweep exists to find.
            t_on = stream.nbytes // 4 / PPK2_SAMPLE_HZ
            ppk.toggle_DUT_power("ON")
            stream.drain(args.boot_window + args.dwell)
        else:
            ppk.toggle_DUT_power("ON")
            stream.drain(args.dwell)
    finally:
        stream.stop()
        if power_cycle:
            ppk.toggle_DUT_power("OFF")
    stream.print_capture_stats()
    samples, digital_raw, dec = stream.decode(dec_n)
    if raw:
        _cache_write(raw, dec.n, samples, digital_raw)
    tr = _trace_from_samples(samples, digital_raw, ppk, dec.n / PPK2_SAMPLE_HZ)
    cfg = {"mv": mv, "boot_s": args.boot_window,
           "blip_period_s": args.blip_period,
           "power_cycle": power_cycle, "t_on": t_on}
    res = classify_step(tr, cfg)
    # The decimator's raw peak sees sub-bin spikes the 1 ms means cannot.
    res["peak_ma"] = max(res["peak_ma"] or 0.0, dec.peak / 1000.0)
    res["phase"] = phase
    res["capture"] = os.path.basename(raw) if raw else None
    if raw:
        # Patch the calibration sidecar with what --replay needs.
        with open(raw + ".json") as fh:
            side = json.load(fh)
        side["sweep"] = cfg
        with open(raw + ".json", "w") as fh:
            json.dump(side, fh)
    return res


def _classify_file(args):
    path = args.classify_file
    if path.endswith(".csv"):
        tr = load_csv(path)
    else:
        ns = argparse.Namespace(path=path, port=args.port, vdd=args.vin,
                                mode="source", decimate=args.decimate)
        tr = decode_raw(ns)
    cfg = {"mv": args.vin, "boot_s": args.boot_window,
           "blip_period_s": args.blip_period,
           # A capture that starts unpowered contains a boot to judge.
           "power_cycle": tr.power_on > 0, "t_on": None}
    res = classify_step(tr, cfg)
    print(json.dumps(res, indent=1))
    return 0


def _replay_dir(args):
    names = sorted(n for n in os.listdir(args.replay) if n.endswith("mv.bin"))
    if not names:
        sys.exit(f"no step-*.bin captures in {args.replay!r}")
    for name in names:
        path = os.path.join(args.replay, name)
        with open(path + ".json") as fh:
            side = json.load(fh)
        cfg = side.get("sweep")
        if cfg is None:
            print(f"  {name}: no sweep config in sidecar, skipping")
            continue
        ns = argparse.Namespace(path=path, port=None, vdd=side["vdd_mv"],
                                mode="source", decimate=args.decimate)
        res = classify_step(decode_raw(ns), cfg)
        res["phase"] = "replay"
        print(_step_row(res))
    return 0


def run_sweep(args):
    if args.selftest:
        return run_selftest()
    if args.classify_file:
        return _classify_file(args)
    if args.replay:
        return _replay_dir(args)
    if not args.rail:
        sys.exit("sweep needs --rail (or --selftest/--classify-file/--replay)")

    mv_list = _sweep_mv_list(args)
    power_cycle = not args.no_power_cycle
    cap_s = ((args.off_seconds + args.boot_window if power_cycle else 0.0)
             + args.dwell)
    # ~671k samples/s decode (see _cache_write) plus per-step housekeeping;
    # an estimate for the ETA line, nothing downstream depends on it.
    step_s = cap_s + cap_s * PPK2_SAMPLE_HZ / 671e3 + 3.0
    worst_steps = (len(mv_list) + args.max_bisect_steps
                   + 2 * args.confirm_edge)
    out_dir = args.out_dir or os.path.join(
        artifacts.artifact_dir("sweeps"),
        time.strftime("ppk2-sweep-%Y%m%d-%H%M%S"))
    plan = {"rail": args.rail, "mv_list": mv_list, "dwell_s": args.dwell,
            "boot_s": args.boot_window, "off_s": args.off_seconds,
            "decimate": args.decimate, "blip_period_s": args.blip_period,
            "power_cycle": power_cycle, "abort_ma": RAILS[args.rail]["abort_ma"],
            "bisect_mv": args.bisect_mv, "out_dir": out_dir,
            "date": time.strftime("%Y-%m-%d %H:%M"), "git": _git_describe(),
            "build_note": args.build_note, "no_raw": args.no_raw}

    need_b = 0 if args.no_raw else int(worst_steps * cap_s * 400e3)
    print(f"Sweep plan: rail {args.rail}, {len(mv_list)} linear steps "
          f"{mv_list[0]}->{mv_list[-1]} mV"
          + (f", then bisect to {args.bisect_mv} mV" if args.bisect_mv else ""))
    print(f"  steps: {' '.join(str(m) for m in mv_list)}")
    print(f"  per step: off {args.off_seconds}s + boot {args.boot_window}s + "
          f"dwell {args.dwell}s, decimate {args.decimate}, fresh boot: "
          f"{power_cycle}")
    print(f"  duration ~{worst_steps * step_s / 60:.0f} min worst-case "
          f"({len(mv_list)} linear + up to "
          f"{args.max_bisect_steps + 2 * args.confirm_edge} probes, estimate)")
    print(f"  output: {artifacts.rel(out_dir)}/ (~{need_b/1e6:.0f} MB raw"
          + (", disabled by --no-raw)" if args.no_raw else ")"))
    print(f"  liveness assumes SLEEP_INTERVAL_S={args.blip_period:g} on the "
          f"device; the sweep build is thermometer_c6_debug + "
          f"-DBATTERY_SHUTDOWN_DISABLED -DDISABLE_WIFI (a stock build latches "
          f"off below 3700 mV and reads DEAD)")
    if args.dry_run:
        print("dry run: no serial port opened, nothing energised.")
        return 0

    if not args.no_raw:
        st = os.statvfs(os.path.dirname(os.path.abspath(out_dir)))
        free_b = st.f_bavail * st.f_frsize
        if need_b > free_b * 0.9:
            sys.exit(f"~{need_b/1e6:.0f} MB of raw captures won't fit in "
                     f"{free_b/1e6:.0f} MB free at {artifacts.rel(out_dir)!r} — "
                     f"free space, pass --no-raw, or point $THERMO_LOCAL_DIR at "
                     f"a bigger disk")

    _connection_banner(args.rail,
                       f"{mv_list[0]} down to {mv_list[-1]} mV "
                       f"({len(mv_list)} steps + bisect)")
    print(f"\n  After this single confirmation the sweep runs unattended for "
          f"~{worst_steps * step_s / 60:.0f} min (estimate). Every bisect "
          f"probe stays inside {mv_list[-1]}-{mv_list[0]} mV.")
    _typed_confirmation(f"{args.rail} {mv_list[-1]}-{mv_list[0]}")
    _save_state({"rail": args.rail, "mv": mv_list[0], "when": time.time()})

    os.makedirs(out_dir, exist_ok=True)
    ppk, _port = _connect(args)
    ppk.use_source_meter()
    dec_n = max(1, args.decimate)
    abort_ma = RAILS[args.rail]["abort_ma"]
    steps, edge, seq = [], None, 0
    status = "interrupted"

    def step(mv, phase):
        nonlocal seq
        seq += 1
        print(f"\n-- step {seq}: {mv} mV [{phase}] --")
        res = _run_step(ppk, args, mv, dec_n, out_dir, seq, phase)
        steps.append(res)
        print(_step_row(res))
        with open(os.path.join(out_dir, f"step{seq:02d}-{mv}mv.step.json"),
                  "w") as fh:
            json.dump(res, fh, indent=1)
        _write_outputs(plan, steps, "running", edge)
        if res["peak_ma"] and res["peak_ma"] > abort_ma:
            res["label"] = "OVERCURRENT"
            raise _SweepAbort(
                f"aborted: {res['peak_ma']:.0f} mA peak exceeded the "
                f"{abort_ma:.0f} mA ceiling at {mv} mV — power is off, check "
                f"the connection")
        return res

    try:
        try:
            linear = []
            for i, mv in enumerate(mv_list):
                res = step(mv, "linear")
                linear.append(res)
                if i == 0 and res["label"] != "HEALTHY":
                    raise _SweepAbort(
                        f"aborted: the first (highest) step at {mv} mV is "
                        f"{res['label']}, not HEALTHY — wiring, build "
                        f"(BATTERY_SHUTDOWN_DISABLED? blip period?) or panel "
                        f"suspect. Not descending.")

            anomalies = []
            hi = lo = None
            for a, b in zip(linear, linear[1:]):
                if a["label"] == "HEALTHY" and b["label"] != "HEALTHY":
                    if hi is None:
                        hi, lo = a["mv"], b["mv"]
                    else:
                        anomalies.append(f"additional healthy->unhealthy "
                                         f"transition {a['mv']}->{b['mv']} mV")
                elif a["label"] != "HEALTHY" and b["label"] == "HEALTHY":
                    anomalies.append(f"recovery below a failure: {b['mv']} mV "
                                     f"HEALTHY under {a['mv']} mV "
                                     f"{a['label']}")

            if hi is None:
                edge = {"lowest_healthy_mv": mv_list[-1],
                        "first_unhealthy_mv": None, "anomalies": anomalies}
                print(f"\nno edge: every linear step was HEALTHY down to "
                      f"{mv_list[-1]} mV")
            else:
                probes = 0
                while (args.bisect_mv and hi - lo > args.bisect_mv
                       and probes < args.max_bisect_steps):
                    mid = lo + (hi - lo) // 2
                    mid = int(round(mid / args.bisect_mv) * args.bisect_mv)
                    if mid in (hi, lo):
                        break
                    probes += 1
                    res = step(mid, "bisect")
                    if res["label"] == "HEALTHY":
                        hi = mid
                    else:
                        lo = mid
                for _ in range(args.confirm_edge):
                    if step(hi, "confirm-hi")["label"] != "HEALTHY":
                        anomalies.append(f"bistable: {hi} mV HEALTHY during "
                                         f"bisect, not on re-run")
                    if step(lo, "confirm-lo")["label"] == "HEALTHY":
                        anomalies.append(f"bistable: {lo} mV unhealthy during "
                                         f"bisect, HEALTHY on re-run")
                edge = {"lowest_healthy_mv": hi, "first_unhealthy_mv": lo,
                        "anomalies": anomalies}
                print(f"\nedge: lowest HEALTHY {hi} mV, first non-healthy "
                      f"{lo} mV" + (f"; {len(anomalies)} anomaly(ies)"
                                    if anomalies else ""))
            status = "complete"
        except _SweepAbort as exc:
            status = str(exc)
            print(f"\n{status}")
        except KeyboardInterrupt:
            status = "interrupted (^C)"
            print(f"\n{status}")
        except (RuntimeError, OSError) as exc:
            status = f"aborted: {exc}"
            print(f"\n{status}")
    finally:
        for act in (ppk.stop_measuring,
                    lambda: ppk.toggle_DUT_power("OFF")):
            try:
                act()
            except Exception:
                pass
        _write_outputs(plan, steps, status, edge)
        print(f"\n{len(steps)} step(s) recorded -> "
              f"{artifacts.rel(out_dir)}/report.md")
    return 0 if status == "complete" else 2


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

    s = sub.add_parser("sweep", help="automated battery-floor voltage sweep "
                                     "(source meter; one typed confirmation, "
                                     "then unattended)")
    s.add_argument("--rail", choices=sorted(RAILS),
                   help="REQUIRED to run on hardware; names the injection point")
    s.add_argument("--start", type=int, default=4200, metavar="MV")
    s.add_argument("--stop", type=int, default=3000, metavar="MV")
    s.add_argument("--step", type=int, default=100, metavar="MV")
    s.add_argument("--mv", metavar="LIST",
                   help="explicit comma-separated voltage list; beats "
                        "--start/--stop/--step")
    s.add_argument("--dwell", type=float, default=90.0, metavar="S",
                   help="sleep-observation window per step; storms need >=60s "
                        "to show (XIAO sweep, notes.md 2026-07-05)")
    s.add_argument("--boot-window", type=float, default=20.0, metavar="S",
                   help="boot->render allowance after power-on; assumes a "
                        "DISABLE_WIFI build")
    s.add_argument("--off-seconds", type=float, default=2.0, metavar="S")
    s.add_argument("--bisect-mv", type=int, default=10, metavar="MV",
                   help="bisect the topmost healthy/unhealthy edge down to "
                        "this resolution; 0 disables")
    s.add_argument("--max-bisect-steps", type=int, default=8, metavar="N")
    s.add_argument("--confirm-edge", type=int, default=1, metavar="N",
                   help="re-runs of each side of the found edge; the XIAO "
                        "showed a bistable band, one boot proves little")
    s.add_argument("--no-power-cycle", action="store_true",
                   help="step the voltage live instead of a fresh boot per "
                        "step (hysteresis exploration; no refresh evidence, "
                        "excluded from HEALTHY/bisect semantics)")
    s.add_argument("--blip-period", type=float, default=5.0, metavar="S",
                   help="SLEEP_INTERVAL_S of the flashed build; liveness is "
                        "judged against it (5 = *_debug envs)")
    s.add_argument("--out-dir", metavar="DIR")
    s.add_argument("--decimate", type=int, default=100, metavar="N",
                   help="fixed decode decimation (100 = 1 ms bins, matches "
                        "the classifier); never auto-scaled")
    s.add_argument("--no-raw", action="store_true",
                   help="skip step-*.bin raw captures (saves ~44 MB/step, "
                        "loses --replay)")
    s.add_argument("--build-note", metavar="TEXT",
                   help="what is flashed (env, PLATFORMIO_BUILD_FLAGS, git "
                        "hash) — lands in the report header")
    s.add_argument("--dry-run", action="store_true",
                   help="print the plan and exit; opens no serial port, works "
                        "without a tty")
    s.add_argument("--replay", metavar="DIR",
                   help="re-classify the step-*.bin captures of an earlier "
                        "sweep; no hardware")
    s.add_argument("--classify-file", metavar="PATH",
                   help="classify one capture (.csv or raw .bin); no hardware")
    s.add_argument("--vin", type=int, default=4200, metavar="MV",
                   help="supply voltage of --classify-file, for the power "
                        "column and (bin) the conversion")
    s.add_argument("--selftest", action="store_true",
                   help="classifier checks on synthesized signatures")
    s.add_argument("--port")

    for sp in (c, r, l):
        sp.add_argument("--cpu-ch", type=int, default=0, metavar="N",
                        help="PPK2 channel carrying CPU_ACTIVE/GPIO17 (default 0)")
        sp.add_argument("--display-ch", type=int, default=1, metavar="N",
                        help="PPK2 channel carrying DISPLAY/GPIO16 (default 1)")
        sp.add_argument("--decimate", type=int, default=None, metavar="N",
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
    if args.cmd == "sweep":
        sys.exit(run_sweep(args))
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
