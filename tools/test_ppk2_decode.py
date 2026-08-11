#!/usr/bin/env python3
"""Check the vectorized PPK2 decoder against ppk2_api's own implementation.

The reference is the oracle here, not a second opinion: `_NpDecoder` exists only
to produce the same numbers faster, and every current figure this project has
recorded came out of the reference path. A silent divergence would not fail, it
would shift results — so this compares them sample for sample.

Chunk boundaries are part of the contract: the spike filter carries state across
calls, so the test feeds both decoders the same *sequence* of chunks and uses a
chunk size that is deliberately not a multiple of 4 bytes, which exercises the
unaligned-remainder handling on every call.

    tools/test_ppk2_decode.py [capture.bin ...]

With no argument it uses whatever is in local/captures/. Skips (does not fail)
when no capture is available, since captures are gitignored bench artifacts.
"""
import glob
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_ppk2():
    spec = importlib.util.spec_from_file_location("ppk2mod",
                                                  os.path.join(HERE, "ppk2.py"))
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["ppk2.py"]
    sys.path.insert(0, HERE)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def check(mod, path, max_bytes=48 << 20, chunk=(1 << 20) + 3):
    side = path + ".json"
    if not os.path.exists(side):
        print(f"  {os.path.basename(path)}: no sidecar, skipped")
        return None
    meta = json.load(open(side))

    ref = mod._offline_decoder(meta)
    fast = mod._NpDecoder(mod._offline_decoder(meta))

    ref_all, fast_all = [], []
    ref_bits, fast_bits = [], []
    read = 0
    with open(path, "rb") as fh:
        while read < max_bytes:
            buf = fh.read(min(chunk, max_bytes - read))
            if not buf:
                break
            read += len(buf)
            sm, dg = ref.get_samples(buf)
            ref_all.append(np.asarray(sm, dtype=np.float64))
            ref_bits.append(np.asarray(dg, dtype=np.uint8))
            fs, fb = fast.feed(buf)
            fast_all.append(fs)
            fast_bits.append(fb)

    r = np.concatenate(ref_all)
    f = np.concatenate(fast_all)
    rb = np.concatenate(ref_bits)
    fb = np.concatenate(fast_bits)

    name = os.path.basename(path)
    if r.size != f.size:
        print(f"  {name}: FAIL sample count {r.size} vs {f.size}")
        return False
    if rb.size != fb.size or not np.array_equal(rb, fb):
        print(f"  {name}: FAIL logic bits differ")
        return False

    # Absolute tolerance matters more than relative: currents span 6 decades and
    # a relative test on a near-zero sleep sample is meaningless noise.
    delta = np.abs(r - f)
    scale = np.maximum(np.abs(r), 1e-3)
    rel = delta / scale
    worst = int(np.argmax(delta))
    ok = delta.max() < 1e-6 and rel.max() < 1e-9
    print(f"  {name}: {'PASS' if ok else 'FAIL'}  n={r.size}  "
          f"max|d|={delta.max():.3e} uA  max rel={rel.max():.3e}  "
          f"(worst at i={worst}: ref={r[worst]:.6f} fast={f[worst]:.6f})")
    if not ok:
        bad = np.flatnonzero(delta > 1e-6)
        print(f"    {bad.size} sample(s) over tolerance, first at {bad[:5]}")
    return ok


def check_pipeline(mod, path, dec_n=18, max_bytes=48 << 20, chunk=(1 << 20) + 3):
    """Same comparison one level up: decode *and* decimate, as decode_raw runs it.

    Worth testing separately because the decimator carries its own cross-chunk
    state (a partial group and per-channel majority counts), and a vectorized
    version can agree sample-for-sample while still misplacing a group boundary.
    """
    side = path + ".json"
    if not os.path.exists(side):
        return None
    from array import array as _array
    meta = json.load(open(side))

    ref, ref_s, ref_b = mod._offline_decoder(meta), _array("f"), []
    rdec = mod._Decimator(dec_n)
    fast, fast_s, fast_b = mod._NpDecoder(mod._offline_decoder(meta)), _array("f"), []
    fdec = mod._NpDecimator(dec_n)

    read = 0
    with open(path, "rb") as fh:
        while read < max_bytes:
            buf = fh.read(min(chunk, max_bytes - read))
            if not buf:
                break
            read += len(buf)
            sm, dg = ref.get_samples(buf)
            rdec.feed(sm, dg, ref_s, ref_b)
            fs, fb = fast.feed(buf)
            fdec.feed(fs, fb, fast_s, fast_b)

    name = os.path.basename(path)
    r = np.frombuffer(ref_s, dtype=np.float32).astype(np.float64)
    f = np.frombuffer(fast_s, dtype=np.float32).astype(np.float64)
    if r.size != f.size or ref_b != fast_b:
        print(f"  {name} [pipeline]: FAIL  points {r.size} vs {f.size}, "
              f"bits equal={ref_b == fast_b}")
        return False
    rel = np.abs(r - f) / np.maximum(np.abs(r), 1e-3)
    # Not bit-exact by construction: numpy sums pairwise where the reference
    # accumulates sequentially. 1e-9 is ~7 orders below the PPK2's resolution.
    ok = bool(rel.max() < 1e-9) and abs(rdec.peak - fdec.peak) < 1e-9
    print(f"  {name} [pipeline]: {'PASS' if ok else 'FAIL'}  n={r.size}  "
          f"max rel={rel.max():.3e}  peak {rdec.peak:.6f} vs {fdec.peak:.6f}")
    return ok


def main():
    mod = _load_ppk2()
    paths = sys.argv[1:] or sorted(
        glob.glob(os.path.join(HERE, "..", "local", "captures", "*.bin")))
    paths = [p for p in paths if os.path.exists(p + ".json")]
    if not paths:
        print("no captures with sidecars in local/captures/ — skipped")
        return 0
    print(f"comparing vectorized decode against ppk2_api on {len(paths)} capture(s)")
    results = []
    for p in paths:
        results.append(check(mod, p))
        results.append(check_pipeline(mod, p))
    results = [r for r in results if r is not None]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
