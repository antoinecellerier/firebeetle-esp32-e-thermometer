#!/usr/bin/env python3
"""Back up, restore and decode the device's flash temperature archive.

The firmware mirrors its history into the `history` flash partition (see
src/HistoryStore.cpp), which `pio run -t upload` does not touch. This reads it
out over USB, so backups outlive the device and the archive can be decoded
without one.

    history.py backup                    # incremental read, auto-named
    history.py dump hist.bin --csv       # hourly + sparkline
    history.py dump hist.bin --drift     # the docs/clock-drift.md table
    history.py restore hist.bin          # MAC-checked
    history.py merge a.bin b.bin -o all.csv

Every download-mode entry resets the chip, so taking a backup costs the device
its in-progress hour (<=1h of sub-hour min/max). Everything else is restored
from flash on the next boot.
"""

import argparse
import csv
import datetime as dt
import os
import struct
import sys
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- on-flash format (mirrors src/HistoryStore.cpp) --------------------------

HS_MAGIC = 0x54534948  # "HIST"
HS_FORMAT = 2
HS_SECTOR = 4096
HS_BASE_A_OFF = 0x1000
HS_BASE_B_OFF = 0x3000
HS_BASE_SIZE = 0x2000
HS_JOURNAL_OFF = 0x5000
HS_REC = 16

# Only hourly entries are journaled. The 24h sparkline comes from the base
# snapshot, which already contains it.
# REC_PAD fills the ring's last slot when a two-slot REC_DRIFT cannot fit before
# the end; the walk below steps over it like any other type it does not decode.
REC_FREE, REC_HOURLY, REC_DRIFT, REC_PAD = 0xFF, 1, 3, 4

HOURLY_NO_DATA = -32768

STORE_HDR = struct.Struct("<IHHIIHHq6sBB24s16s16s16sI")
BASE_HDR = struct.Struct("<IHHIIqIHH8HI")
REC = struct.Struct("<BBHIhhhH")
DRIFT_REC = struct.Struct("<BBHIiihhIIHH")
DRIFT_STATE = struct.Struct("<iiiqHBB6h6H")


def crc32(buf):
    return zlib.crc32(buf) & 0xFFFFFFFF


def crc16(buf):
    """The firmware folds its CRC-32 rather than carrying a second table."""
    c = crc32(buf)
    return (c ^ (c >> 16)) & 0xFFFF


def cstr(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


# --- partition table ---------------------------------------------------------

def history_partition(csv_path=None):
    """(offset, size) of the `history` partition, read from partitions.csv so a
    future resize needs no change here."""
    path = csv_path or os.path.join(REPO, "partitions.csv")
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5 and parts[0] == "history":
                return int(parts[3], 0), int(parts[4], 0)
    raise SystemExit(f"no 'history' partition in {path}")


# --- decoding ----------------------------------------------------------------

class Archive:
    """A decoded partition image. Accepts a truncated image: `backup` only reads
    up to the journal cursor, so anything past it is simply absent."""

    def __init__(self, blob):
        self.blob = blob
        self.header = self._store_header()
        self.base, self.base_off = self._base()
        self.hourly = []    # (epoch, min, max, avg)
        self.samples = []   # (epoch, temp_x10)
        self.drifts = []    # dict
        self._decode()

    def _store_header(self):
        if len(self.blob) < STORE_HDR.size:
            raise SystemExit("image too short for a store header")
        f = STORE_HDR.unpack_from(self.blob, 0)
        h = dict(zip(
            "magic format hdr_size journal_off journal_size rec_size base_slots "
            "created_at base_mac chip_model chip_revision board panel sensor "
            "git_hash crc32".split(), f))
        if h["magic"] != HS_MAGIC:
            raise SystemExit("not a history image (bad magic) — wrong offset?")
        if h["format"] != HS_FORMAT:
            raise SystemExit(f"unsupported store format {h['format']}")
        want = crc32(self.blob[:STORE_HDR.size - 4])
        if want != h["crc32"]:
            raise SystemExit("store header CRC mismatch")
        h["mac"] = ":".join(f"{b:02x}" for b in h["base_mac"])
        for k in ("board", "panel", "sensor", "git_hash"):
            h[k] = cstr(h[k])
        return h

    def _base(self):
        """Newest valid base slot, or (None, None)."""
        best, best_off = None, None
        for off in (HS_BASE_A_OFF, HS_BASE_B_OFF):
            if off + BASE_HDR.size > len(self.blob):
                continue
            f = BASE_HDR.unpack_from(self.blob, off)
            keys = ("magic format hdr_size seq payload_len written_at "
                    "journal_cursor hourly_count temp_count".split())
            h = dict(zip(keys, f[:9]))
            (h["temp_history_size"], h["hourly_history_size"],
             h["sizeof_temp_reading"], h["sizeof_hourly_entry"],
             h["sizeof_time_t"], h["sizeof_rtc_history"],
             h["sizeof_drift_state"], h["drift_ppm_hist_size"]) = f[9:17]
            h["crc32"] = f[17]
            if h["magic"] != HS_MAGIC or h["format"] != HS_FORMAT:
                continue
            end = off + BASE_HDR.size + h["payload_len"]
            if end > len(self.blob):
                continue
            body = (self.blob[off:off + BASE_HDR.size - 4] +
                    self.blob[off + BASE_HDR.size:end])
            if crc32(body) != h["crc32"]:
                continue
            if best is None or h["seq"] > best["seq"]:
                best, best_off = h, off
        return best, best_off

    def _decode_rtc_history(self):
        """Unpack the RtcHistory payload using the geometry the header records,
        rather than assuming this script and the firmware agree."""
        b = self.base
        off = self.base_off + BASE_HDR.size
        n_temp = b["temp_history_size"]
        n_hourly = b["hourly_history_size"]
        sz_t, sz_h = b["sizeof_temp_reading"], b["sizeof_hourly_entry"]

        temp_off = off + 8
        count_off = temp_off + n_temp * sz_t
        hourly_off = count_off + 2
        tail = hourly_off + n_hourly * sz_h

        temp_count = struct.unpack_from("<H", self.blob, count_off)[0]
        hourly_count, hourly_idx = struct.unpack_from("<HH", self.blob, tail)
        # 2 bytes of padding before the 8-byte-aligned time_t pair.
        latest = struct.unpack_from("<q", self.blob, tail + 6)[0]

        for i in range(min(temp_count, n_temp)):
            ts, x10 = struct.unpack_from("<Ih", self.blob, temp_off + i * sz_t)
            self.samples.append((ts, x10))

        # Circular: the newest entry sits at hourly_idx-1 and names `latest`.
        for k in range(min(hourly_count, n_hourly)):
            idx = (hourly_idx - 1 - k) % n_hourly
            mn, mx, av = struct.unpack_from("<hhh", self.blob,
                                            hourly_off + idx * sz_h)
            self.hourly.append((latest - k * 3600, mn, mx, av))
        self.hourly.reverse()

        d_off = off + b["sizeof_rtc_history"]
        if b["sizeof_drift_state"] >= DRIFT_STATE.size:
            f = DRIFT_STATE.unpack_from(self.blob, d_off)
            self.drift_state = dict(zip(
                "resync_interval_s last_drift_ms last_drift_window_s "
                "last_sync_time resync_fail_count drift_ppm_count rsvd".split(),
                f[:7]))
            self.drift_state["ppm_hist"] = list(f[7:13])
            self.drift_state["win_min"] = list(f[13:19])
        else:
            self.drift_state = None

    def _decode_journal(self):
        """Walk every record in time order.

        Deliberately ignores base_seq: that filter exists so the firmware can
        replay only what postdates its snapshot, whereas the archive reader
        wants the whole history the ring still holds.
        """
        jsize = min(self.header["journal_size"], len(self.blob) - HS_JOURNAL_OFF)
        if jsize <= 0:
            return
        pos = 0
        while pos + HS_REC <= jsize:
            raw = self.blob[HS_JOURNAL_OFF + pos:HS_JOURNAL_OFF + pos + HS_REC]
            t = raw[0]
            if t == REC_FREE:
                pos += HS_REC
                continue
            n = 2 if t == REC_DRIFT else 1
            if pos + n * HS_REC > jsize:
                break
            raw = self.blob[HS_JOURNAL_OFF + pos:HS_JOURNAL_OFF + pos + n * HS_REC]
            if t == REC_DRIFT:
                f = DRIFT_REC.unpack_from(raw)
                if crc16(raw[:DRIFT_REC.size - 2]) == f[11]:
                    self.drifts.append(dict(
                        sync_time=f[3], drift_ms=f[4], window_s=f[5], ppm=f[6],
                        ambient_mean_x10=f[7], boot_count=f[8],
                        refresh_count=f[9], ambient_hours=f[10]))
            elif t == REC_HOURLY:
                f = REC.unpack_from(raw)
                if crc16(raw[:REC.size - 2]) == f[7]:
                    self.hourly.append((f[3], f[4], f[5], f[6]))
            pos += n * HS_REC

    def _decode(self):
        if self.base:
            self._decode_rtc_history()
        else:
            self.drift_state = None
        self._decode_journal()
        # The base and the journal overlap by design (the base contains records
        # written before its own cursor). Dedupe by timestamp, journal wins.
        self.hourly = _dedupe(self.hourly)
        self.samples = _dedupe(self.samples)
        self.drifts.sort(key=lambda d: d["sync_time"])

    def describe(self):
        h = self.header
        # The store is formatted in setup(), before the first NTP sync, so
        # created_at is usually an epoch-zero stamp rather than a real date.
        created = (_iso(h["created_at"]) if h["created_at"] > 1704067200
                   else "(before first NTP sync)")
        out = [f"device   {h['board']} {h['mac']} ({h['panel']}/{h['sensor']})",
               f"built    {h['git_hash']}  store created {created}"]
        if self.base:
            b = self.base
            out.append(f"base     seq {b['seq']} written {_iso(b['written_at'])} "
                       f"cursor 0x{b['journal_cursor']:06x}")
        else:
            out.append("base     (none — journal only)")
        out.append(f"records  {len(self.hourly)} hourly, {len(self.samples)} "
                   f"sparkline, {len(self.drifts)} drift")
        if self.hourly:
            out.append(f"span     {_iso(self.hourly[0][0])} .. "
                       f"{_iso(self.hourly[-1][0])}")
        return "\n".join(out)


def _dedupe(rows):
    """Later entries win, then sort by timestamp."""
    by_ts = {}
    for r in rows:
        by_ts[r[0]] = r
    return [by_ts[k] for k in sorted(by_ts)]


def _iso(epoch):
    if not epoch:
        return "-"
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%SZ")


# --- device I/O --------------------------------------------------------------

def _resolve_port(explicit=None):
    """Re-resolved on every connection, never cached: entering download mode
    re-enumerates the C6's USB-Serial-JTAG endpoint, so /dev/ttyACM1 can come
    back as /dev/ttyACM0 between invocations."""
    if explicit:
        return explicit
    from serial.tools import list_ports
    cands = [p.device for p in list_ports.comports()
             if "ttyUSB" in p.device or "ttyACM" in p.device]
    if not cands:
        raise SystemExit("no /dev/ttyUSB* or /dev/ttyACM* found — is it plugged in?")
    if len(cands) > 1:
        raise SystemExit(f"multiple ports {cands}; pass --port")
    return cands[0]


def _connect(port, baud):
    try:
        import esptool
    except ImportError:
        raise SystemExit(
            "esptool not importable. Use PlatformIO's interpreter:\n"
            "  ~/.platformio/penv/bin/python3 tools/history.py ...\n"
            "or: pip install -r tools/requirements.txt")
    esp = esptool.detect_chip(port)
    esp = esp.run_stub()
    # Decisive on the FireBeetle's CP2102 (a full read is ~3min at 115200 vs
    # ~25s at 921600); inert on the C6, whose USB-Serial-JTAG ignores baud.
    try:
        esp.change_baud(baud)
    except Exception:
        pass
    return esp


def _journal_wrapped(esp, off, jsize, cursor):
    """Has the ring wrapped? A prefix read is only correct while it has not.

    Once it has, the cursor is low while the bulk of the archive sits above it,
    so reading to the cursor would quietly return a few KB and drop years of
    records — with a plausible-looking record count on top.

    The firmware keeps exactly one sector erased ahead of the cursor, so above
    the cursor a wrapped ring has at most two blank sectors and every other one
    holds data. Probing cursor_sector + 2 separates the two cases with a single
    sector read. It can only err toward a full read, and only in the sector
    before the very first wrap — years into a device's life.
    """
    nsec = jsize // HS_SECTOR
    if nsec < 4:
        return True                    # too small to probe; just read it all
    probe_sec = (cursor // HS_SECTOR + 2) % nsec
    data = esp.read_flash(off + HS_JOURNAL_OFF + probe_sec * HS_SECTOR, HS_SECTOR)
    return data.count(0xFF) != HS_SECTOR


def read_device(port=None, baud=921600, full=False):
    """One session: identity, base slots, then only the used part of the journal.

    Reading to the cursor rather than the whole partition is what keeps a
    backup quick on the UART-bridged board — a young device is a few KB, not
    1920KB. Only valid before the ring wraps, hence the probe below.
    """
    off, size = history_partition()
    esp = _connect(_resolve_port(port), baud)
    try:
        head = esp.read_flash(off, HS_JOURNAL_OFF)
        if full:
            return head + esp.read_flash(off + HS_JOURNAL_OFF, size - HS_JOURNAL_OFF)

        jsize = size - HS_JOURNAL_OFF
        probe = Archive(head + b"\xff" * HS_REC)
        if not probe.base or _journal_wrapped(esp, off, jsize,
                                              probe.base["journal_cursor"]):
            return head + esp.read_flash(off + HS_JOURNAL_OFF, jsize)

        cursor = probe.base["journal_cursor"]
        # Round up past the cursor so the trailing free slot is included, and
        # always take at least one sector so a fresh store still decodes.
        want = min(jsize, max(HS_SECTOR, (cursor + HS_SECTOR) & ~(HS_SECTOR - 1)))
        return head + esp.read_flash(off + HS_JOURNAL_OFF, want)
    finally:
        # Must release the port, not just reset the chip: `restore` reconnects
        # for the write step, and pyserial holds an exclusive lock, so leaving
        # it open fails the write with "port is busy" after a successful read.
        try:
            esp.hard_reset()
        except Exception:
            pass
        try:
            esp._port.close()
        except Exception:
            pass


def write_device(blob, port=None, baud=921600):
    """Whole-partition write. Unlike backup this can't be incremental, so it is
    the slow direction — a couple of minutes on the FireBeetle's UART bridge."""
    import esptool
    off, _ = history_partition()
    # Re-resolve the port: the read that preceded this reset the chip, and the
    # C6 re-enumerates its USB-Serial-JTAG endpoint when it does.
    esptool.main(["--port", _resolve_port(port), "--baud", str(baud),
                  "write_flash", hex(off), blob])


# --- commands ----------------------------------------------------------------

def cmd_backup(args):
    blob = read_device(args.port, args.baud, args.full)
    arc = Archive(blob)
    name = args.output or (
        f"hist-{arc.header['board']}-"
        f"{arc.header['base_mac'][-3:].hex()}-"
        f"{dt.date.today().isoformat()}.bin")
    with open(name, "wb") as f:
        f.write(blob)
    _, size = history_partition()
    print(arc.describe())
    # Say which it is. A prefix image holds every record the device had, but it
    # is not a partition image, so `restore` will refuse it — better to learn
    # that here than when the device it came from is gone.
    kind = ("full partition image" if len(blob) == size
            else f"prefix of a {size}-byte partition; re-run with --full to restore")
    print(f"wrote    {name} ({len(blob)} bytes, {kind})")


def cmd_restore(args):
    with open(args.file, "rb") as f:
        blob = f.read()
    arc = Archive(blob)
    print(arc.describe())

    live = Archive(read_device(args.port, args.baud, full=False))
    same = live.header["base_mac"] == arc.header["base_mac"]
    if not same:
        msg = (f"MAC mismatch: file is {arc.header['mac']} "
               f"({arc.header['board']}), device is {live.header['mac']} "
               f"({live.header['board']})")
        if not args.force:
            raise SystemExit(msg + "\nrefusing; pass --force to override")
        print("WARNING: " + msg)
    for k in ("board", "panel", "sensor"):
        if arc.header[k] != live.header[k]:
            print(f"WARNING: {k} differs: {arc.header[k]} -> {live.header[k]}")

    off, size = history_partition()
    if len(blob) != size:
        # Both directions are refused. Short is an incremental backup, which
        # cannot be restored. Long is the dangerous one: `history` sits directly
        # below `factory` (CLAUDE.md documents growing it upward as the
        # supported resize), so an image taken from a device with a larger
        # partition would be written straight through the app slot and leave the
        # board unbootable — from the command whose whole job is to be
        # non-destructive.
        how = ("re-take the backup with --full" if len(blob) < size else
               "this image is for a larger `history` partition than "
               "partitions.csv describes; writing it would overwrite `factory`")
        raise SystemExit(
            f"file is {len(blob)} bytes but the partition is {size}; {how}")
    write_device(args.file, args.port, args.baud)
    print("restored; the device rebuilds RTC state from it on next boot")


def cmd_dump(args):
    with open(args.file, "rb") as f:
        arc = Archive(f.read())
    if not (args.csv or args.drift):
        print(arc.describe())
        return

    at = args.at
    w = csv.writer(sys.stdout)
    for line in arc.describe().splitlines():
        print(f"# {line}")

    if args.drift:
        w.writerow(["sync_time", "drift_s", "window_s", "ppm", "ambient_c",
                    "ambient_hours", "boot_count", "d_boot", "refresh_count",
                    "d_refresh"])
        prev = None
        for d in arc.drifts:
            if at and d["sync_time"] > at:
                continue
            db = d["boot_count"] - prev["boot_count"] if prev else ""
            dr = d["refresh_count"] - prev["refresh_count"] if prev else ""
            amb = ("" if d["ambient_mean_x10"] == HOURLY_NO_DATA
                   else d["ambient_mean_x10"] / 10.0)
            w.writerow([_iso(d["sync_time"]), d["drift_ms"] / 1000.0,
                        d["window_s"], d["ppm"], amb, d["ambient_hours"],
                        d["boot_count"], db, d["refresh_count"], dr])
            prev = d
        return

    w.writerow(["kind", "time", "min_c", "max_c", "avg_c"])
    for ts, mn, mx, av in arc.hourly:
        if at and ts > at:
            continue
        if mn == HOURLY_NO_DATA:
            w.writerow(["hourly", _iso(ts), "", "", ""])  # device was off
        else:
            w.writerow(["hourly", _iso(ts), mn / 10.0, mx / 10.0, av / 10.0])
    for ts, x10 in arc.samples:
        if at and ts > at:
            continue
        w.writerow(["sample", _iso(ts), "", "", x10 / 10.0])


def cmd_merge(args):
    """Union of several backups.

    On-device capacity is years, but the ring does eventually wrap and
    `erase_flash` does not care how long you collected — merged backups on the
    PC are the copy that outlives all of it.
    """
    hourly, samples, drifts, macs = {}, {}, {}, set()
    for path in args.files:
        with open(path, "rb") as f:
            arc = Archive(f.read())
        macs.add(arc.header["mac"])
        for r in arc.hourly:
            hourly[r[0]] = r
        for r in arc.samples:
            samples[r[0]] = r
        for d in arc.drifts:
            drifts[d["sync_time"]] = d
    if len(macs) > 1 and not args.force:
        raise SystemExit(f"backups are from different devices {sorted(macs)}; "
                         "pass --force to merge anyway")

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    w = csv.writer(out)
    w.writerow(["kind", "time", "min_c", "max_c", "avg_c"])
    for ts in sorted(hourly):
        _, mn, mx, av = hourly[ts]
        if mn == HOURLY_NO_DATA:
            w.writerow(["hourly", _iso(ts), "", "", ""])
        else:
            w.writerow(["hourly", _iso(ts), mn / 10.0, mx / 10.0, av / 10.0])
    for ts in sorted(samples):
        w.writerow(["sample", _iso(ts), "", "", samples[ts][1] / 10.0])
    if args.output:
        out.close()
        print(f"merged {len(args.files)} backups -> {args.output} "
              f"({len(hourly)} hourly, {len(samples)} sparkline, "
              f"{len(drifts)} drift)", file=sys.stderr)


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def dev(sp):
        sp.add_argument("--port", help="serial port (auto-detected otherwise)")
        sp.add_argument("--baud", type=int, default=921600,
                        help="decisive on the FireBeetle's UART bridge, "
                             "ignored by the C6's USB-Serial-JTAG")

    b = sub.add_parser("backup", help="read the archive off a device")
    dev(b)
    b.add_argument("-o", "--output")
    b.add_argument("--full", action="store_true",
                   help="read the whole partition (needed for restore)")
    b.set_defaults(func=cmd_backup)

    r = sub.add_parser("restore", help="write a backup back to a device")
    dev(r)
    r.add_argument("file")
    r.add_argument("--force", action="store_true",
                   help="proceed despite a MAC/board mismatch")
    r.set_defaults(func=cmd_restore)

    d = sub.add_parser("dump", help="decode a backup")
    d.add_argument("file")
    d.add_argument("--csv", action="store_true")
    d.add_argument("--drift", action="store_true",
                   help="the docs/clock-drift.md collection table")
    d.add_argument("--at", type=int,
                   help="only records at or before this unix time")
    d.set_defaults(func=cmd_dump)

    m = sub.add_parser("merge", help="union several backups into one CSV")
    m.add_argument("files", nargs="+")
    m.add_argument("-o", "--output")
    m.add_argument("--force", action="store_true",
                   help="merge across different devices")
    m.set_defaults(func=cmd_merge)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
