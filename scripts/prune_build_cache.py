"""PlatformIO post script: age out stale SCons CacheDir entries.

Nothing in SCons evicts from a CacheDir, and the cache grows on every build:
each one pushes a fresh firmware.elf (~11MB) plus whatever objects changed.
Left alone it reaches multiple GB.

Age is a true LRU here, not just a proxy for it — SCons os.utime()s an entry
every time it retrieves one (CacheDir.py CacheRetrieveFunc), so mtime is the
last time a build actually wanted that object.

Runs after the build, not before: this build's retrievals have already
refreshed the mtimes of everything it uses, so an env left alone for longer
than MAX_AGE_DAYS still gets its cache when it is finally rebuilt. Pruning
first would delete exactly the entries that build was about to ask for.

The stamp file keeps the common case to a single stat(). Delete it (or the
whole cache) to force a pass.
"""
Import("env")

import os
import time

MAX_AGE_DAYS = 30
PRUNE_EVERY_DAYS = 7
STAMP_NAME = ".last_prune"

_already_ran = [False]


def _is_shard(name):
    """CacheDir sharding is a 2-hex-char directory per entry prefix. Walking
    only those is what puts `config` and the SConsign DB out of reach: both sit
    at the cache root, and deleting the SConsign would cost every env its
    build state — a far worse outcome than the disk this reclaims."""
    return len(name) == 2 and all(c in "0123456789abcdefABCDEF" for c in name)


def prune_build_cache(source, target, env):
    if _already_ran[0]:  # both post-action hooks can fire in one build
        return
    _already_ran[0] = True

    cache_dir = env.get("BUILD_CACHE_DIR")
    if not cache_dir:
        return
    cache_dir = env.subst(cache_dir)
    if not os.path.isabs(cache_dir):
        cache_dir = os.path.join(env.subst("$PROJECT_DIR"), cache_dir)
    if not os.path.isdir(cache_dir):
        return

    now = time.time()
    stamp = os.path.join(cache_dir, STAMP_NAME)
    try:
        if now - os.path.getmtime(stamp) < PRUNE_EVERY_DAYS * 86400:
            return
    except OSError:
        pass  # never pruned here before

    cutoff = now - MAX_AGE_DAYS * 86400
    removed = kept = freed = 0
    try:
        for shard in os.listdir(cache_dir):
            if not _is_shard(shard):
                continue
            shard_dir = os.path.join(cache_dir, shard)
            for name in os.listdir(shard_dir):
                path = os.path.join(shard_dir, name)
                try:
                    st = os.stat(path)
                    if st.st_mtime < cutoff:
                        os.remove(path)
                        removed += 1
                        freed += st.st_size
                    else:
                        kept += 1
                except OSError:
                    pass  # raced with another build, or already gone
        with open(stamp, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    except OSError as e:  # housekeeping never fails a build
        print("Build cache prune: skipped (%s)" % e)
        return

    if removed:
        print("Build cache prune: removed %d of %d entries unused for %d days "
              "(%.0f MB freed)"
              % (removed, removed + kept, MAX_AGE_DAYS, freed / 1e6))


# Both hooks, matching post_build_check_rtc.py: "buildprog" under the arduino
# builder, the .bin artifact under espidf (which doesn't fire the alias).
env.AddPostAction("buildprog", prune_build_cache)
env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", prune_build_cache)
