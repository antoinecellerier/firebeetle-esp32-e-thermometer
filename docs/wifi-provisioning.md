# WiFi credential provisioning via NVS

**Status: proposed, not implemented. 2026-08-10.** Nothing in this document describes
how the firmware behaves today — it is a design worked out and fact-checked in one
session, recorded so it can be picked up later. The authoritative logbooks remain
`docs/notes.md`, `docs/clock-drift.md`, `docs/footprint.md` and
`docs/history-store-validation.md`.

Facts below marked *verified* were checked against this machine's ESP-IDF 6.0.1 tree or
the repo on the date above. The one estimate is labelled as such.

## 1. Why

`MY_WIFI_NETWORKS` expands at `src/Thermometer.cpp:896-901` into a
`static const WifiNetwork s_wifi_networks[]` of `.rodata` string literals. The password
is therefore compiled into every image: it is in `firmware.bin`, in the intermediate
object files under `.pio/`, and recoverable with `strings` from any of them.

This is **not** a laptop→device move. The password is already in device flash today,
inside `firmware.bin` in the `factory` partition at `0x1F0000`. What changes is *which*
storage holds it and what rides along:

| | today | proposed |
|---|---|---|
| in the source tree | yes (`include/local-secrets-password.h`) | no |
| in `firmware.bin` / `.pio` objects | **yes** | no |
| in device flash | yes (`factory`) | yes (`nvs`) |
| identical on every board | yes | no — written per device |

The win is that the secret leaves the artifact that gets built, copied, analysed and
pasted into terminals. `strings` on a firmware image is a routine activity in this
project (size and symbol analysis), which is what makes the current arrangement a
latent accident rather than a theoretical one.

**This prevents future leakage; it does not revoke past leakage.** The repo history is
clean — `include/.gitignore` has always carried `local-secrets*.h` — but build artifacts
on disk are not. Rotating the AP password once the fleet is migrated is the only thing
that actually revokes the current one. That is a deployment decision, noted here rather
than assumed.

## 2. Feasibility across the fleet: no blockers

Plain NVS is target-agnostic and needs no partition work. *Verified:*

- `nvs` already exists at `0x9000`/`0x6000` (24 KB) — `partitions.csv:15`.
- That table is shared by every environment: `board_build.partitions` is declared once
  in `[env]` at `platformio.ini:39`, and no env, board JSON or CMake overrides it. Seven
  envs, two targets (`esp32` for the two FireBeetle envs, `esp32c6` for the rest).
- `CONFIG_PARTITION_TABLE_CUSTOM=y` is already set — `sdkconfig.defaults:18-22`.
- The partition is already live: `nvs_flash_init()` runs at `src/Thermometer.cpp:988`
  because `esp_wifi_init()` requires it, and `nvs_flash` is already a component
  dependency at `src/CMakeLists.txt:5`.

So: no CSV edit, no sdkconfig change, and `history` stays pinned at `0x10000`. This
matters more than it looks — the 4 MB map is fully allocated with no gap, so a design
needing a *new* partition would have had to shrink `factory`, which invalidates every
existing archive backup (`tools/history.py` refuses an image whose length does not match
the partition size, in both directions).

## 3. Considered and rejected: HMAC-encrypted NVS

ESP-IDF can encrypt NVS with XTS keys derived at runtime from an HMAC key in eFuse,
requiring no `nvs_keys` partition — which would otherwise have been disqualifying here,
given there is no free space. Rejected anyway, for two reasons.

**It cannot cover the fleet.** *Verified* in the 6.0.1 `soc_caps.h` that builds this
firmware:

| target | `SOC_HMAC_SUPPORTED` | `SOC_FLASH_ENC_SUPPORTED` |
|---|---|---|
| `esp32` (FireBeetle 2 ESP32-E) | absent | 1 |
| `esp32c6` (XIAO, rev A) | 1 | 1 |

The original ESP32 has no HMAC peripheral, so its only route to encrypted NVS is flash
encryption — permanent eFuse burns that collide with the routine `erase_flash`/reflash
cycle and with host-side archive access.

**On the C6 it would not buy much.** Without Secure Boot the app partition stays
plaintext, so an attacker holding the board flashes their own firmware, calls
`nvs_get_str`, and the HMAC peripheral derives the key for whatever code is running. It
defends against someone who will read the flash but not reflash it — a narrow adversary —
and does nothing at all for the leak paths in §1, which are closed by moving to NVS
whether or not it is encrypted.

**What would change the answer:** a board living somewhere physically untrusted, or one
given away or sold. At that point the right bundle is HMAC *plus* Secure Boot, decided
together, not incrementally.

## 4. Firmware design

### 4.1 New module

`include/WifiCreds.h` + `src/WifiCreds.cpp`. `src/CMakeLists.txt:1` globs `*.cpp`, so no
build change is needed.

Moves out of `Thermometer.cpp`: `struct WifiNetwork` / `s_wifi_networks[]` /
`s_wifi_net_count` (`:896-901`), `wifi_is_configured()` (`:905-911`), and the `#error`
guard at `:1923-1925` — that belongs with the table, not inside `on_first_boot()`.

```c
bool wifi_creds_load(void);              // idempotent; true if >=1 usable network
uint8_t wifi_creds_count(void);
const char *wifi_creds_ssid(uint8_t i);  // and _pass(i)
WifiCredsSource wifi_creds_source(void); // NONE | BUILTIN | NVS
esp_err_t wifi_nvs_ready(void);          // the single nvs_flash_init owner
```

### 4.2 The ordering trap

`wifi_connect()` gates on `wifi_is_configured()` at `:1182` and returns *before*
`wifi_driver_start()` at `:1183` — which is where `nvs_flash_init()` currently lives
(`:988-998`). `on_first_boot():1926` has the same shape. Credentials must be readable
before that gate, so NVS must be initialised earlier.

Fix: hoist the init into `wifi_nvs_ready()`, which runs `nvs_flash_init()` plus its
existing erase-and-retry recovery at most once per boot and caches the `esp_err_t`.
`wifi_driver_start()` drops its own block and calls it. **Exactly one call site** — the
recovery must not be duplicated and allowed to diverge.

This costs nothing on ordinary wakes: `wifi_creds_load()` is reachable only from
`wifi_connect():1182` and `on_first_boot():1926`, both already on paths that were going
to power the radio. Worth stating in the module header so the load is never "helpfully"
moved into `setup()`.

### 4.3 Key schema

Namespace `wifi`, `WIFI_CREDS_MAX = 4` (a 392 B `.bss` arena):

| key | type | meaning |
|---|---|---|
| `ver` | u8 | schema version, currently `1` |
| `n` | u8 | declared network count |
| `ssid0`..`ssid3` | str | ≤32 chars |
| `pw0`..`pw3` | str | ≤64 chars |

Indexed keys rather than one blob: a blob needs its own struct, CRC and endianness
discipline — a second `HistoryStore` for 200 bytes. Indexed keys let the generator and
the reader agree with no shared binary format, and make "add a network" additive.

### 4.4 Validation — log, never erase

Per `.claude/rules/history-store.md`, everything read back from flash is untrusted, and
a format-version mismatch must never reformat. The same reasoning applies here for the
same reason: a firmware downgrade must not destroy a board's provisioning.

- Namespace or `ver` absent ⇒ unprovisioned. Normal, not an error.
- `ver > 1` ⇒ log, fall through to the fallback, **leave the stored image intact**.
- `n > WIFI_CREDS_MAX` ⇒ clamp and log.
- `nvs_get_str` into a 33-byte buffer returning `ESP_ERR_NVS_INVALID_LENGTH` gives the
  length check for free ⇒ skip that entry.
- Empty SSID ⇒ skip, matching the existing "a placeholder, not a network" convention at
  `:903-904`.
- Surviving entries pack densely, so exposed indices stay contiguous.

### 4.5 Fallback layering

NVS **replaces**, never merges. Merging would make the index space a function of two
sources and "what is this board using?" unanswerable at a glance.

1. `wifi_nvs_ready()`; on failure, log and go to 3.
2. Validate the `wifi` namespace. ≥1 surviving entry ⇒ source is NVS. Stop.
3. Otherwise point at the built-in list; any non-empty SSID ⇒ source is BUILTIN.
4. Otherwise NONE.

One log line per boot naming the source and count.

### 4.6 `WIFI_NO_BUILTIN_CREDS`

A compile flag that empties the built-in list. **Without it the migration cannot
finish.** "Keep a fallback" and "migrate board by board" contradict each other
otherwise: the X-macro expands regardless of provisioning, so the password stays in
`firmware.bin` and provisioning a board buys nothing against §1.

Pass via `build_src_flags`, never `build_flags` — per `.claude/rules/build.md:65-71` a
changed global define recompiles the whole framework; `[debug]`'s `-DSLEEP_INTERVAL_S=5`
is the existing pattern.

`include/local-secrets.h` stays mandatory either way: `MY_TZ` is consumed at
`Thermometer.cpp:865-871`, outside the `DISABLE_WIFI` guard. The flag empties the network
list; it does not make the header optional.

### 4.7 What deliberately does not change

**No new RTC state, and no `RTC_STATE_VERSION` bump.** `wifi_last_net` (`:338`) stays a
bare index into the active list. Only one path can change that list while RTC survives —
`nvs_flash_erase()` at `:991` — and the cost is one wrong association at
`WIFI_HINT_TIMEOUT_MS` (8 s) before the existing scan fallback at `:1193`, which is the
tier-0 miss the design already budgets for. A validating tag byte would spend RTC
headroom that `.claude/rules/rtc-state.md` says is not free, to buy back 8 s in a
self-correcting case. The version bump would be redundant: no RTC variable is added or
reinterpreted, and every path that lands new firmware wipes `.rtc.data` anyway, routing
through `:2690` into `reset_rtc_state()` at `:2410`.

**No new badge.** An unprovisioned board with no built-ins already renders `! NO WIFI`
(`src/DisplayRenderer.cpp:1263-1264`, from `DisplayStats::wifi_ok`) and picks up
`! NOSYNC` as `resync_fail_count` climbs — so the degradation is already visible, which
is what the house rule requires. A provenance badge would cost a 12th slot in the
un-bounds-checked `tok[IND_MAX_TOKENS=12]` at `DisplayRenderer.cpp:1167` (11 used, per
the warning at `:1099-1103`), an entry in the healthy-early-return guard at `:1158-1163`,
a sim variant, a `MockData.h` field and new mock PNGs per display size — for a normal
operating state during a deliberately incremental migration. Provenance belongs in the
boot log and in `wifi_provision.py verify`.

**The simulator needs no change**, because no badge is added: `tools/sim/Makefile`
compiles only `sim_main.cpp` + `src/DisplayRenderer.cpp`, and
`tools/sim/stubs/local-secrets.h` continues to shadow the real header.

### 4.8 Two existing bugs to fix while in there

- **`:1114` becomes misleading.** `"check the password in local-secrets.h"` is wrong when
  the credential came from NVS — and it is exactly the message an operator reads during a
  failed provisioning. It should name the source.
- **`:1078` truncates a 32-character SSID.** `wifi_sta_config_t::ssid` is `uint8_t[32]`
  and IDF treats a full 32 bytes as unterminated, but `strncpy(..., sizeof(...) - 1)`
  only ever writes 31. Pre-existing and currently invisible; NVS makes long SSIDs easy
  to set. `memcpy` of `strnlen(ssid, 32)` fixes it.

## 5. Provisioning tool sketch

`tools/wifi_provision.py`, following the `tools/history.py:622-666` structure
(subcommands + `set_defaults(func=)`, a `dev(sp)` helper adding `--port`/`--baud` only to
the hardware subcommands).

```
build  -o out.bin [--file F] [--schema-version N]   # host only
show             [--file F] [--reveal-ssid]         # host only
write  [--port] [--file F] [--force] [--no-identity-check]
verify [--port] [--file F] [--reveal-ssid]
clear  [--port] --force
```

**Reuse rather than duplicate:** generalise `history.history_partition()` (`:73`) into
`partition(name)`, keeping the old name as a wrapper — it has two callers,
`scripts/upload_gate.py:106` and `tools/hstest/check_sample.py`. Reuse
`history._resolve_port()` (`:336`, and its never-cache-the-port discipline),
`history._connect()` (`:352`), the `finally: hard_reset + close` block (`:417-428`), and
`upload_gate.read_device_header()` for a pre-write identity check that skips out loud
rather than blocking.

**Credential file:** `local/secrets/wifi.json` via `artifacts.artifact_dir("secrets")`,
so it honours `$THERMO_LOCAL_DIR` and lands under the gitignored `local/`. JSON so an
SSID containing a comma or non-ASCII round-trips. `--file -` reads stdin, so a password
manager can pipe in without touching disk. Two hard refusals, no interactive prompts
(the `history.py cmd_restore:471-496` precedent): refuse if the file mode has any
group/other bits, and refuse if the path is inside the work tree but not
`git check-ignore`d.

**Reject `--ssid` / `--password` as arguments outright** — a password on argv lands in
shell history, in `ps`, and in session transcripts.

**Do not source credentials from `include/local-secrets.h`.** Tempting, since it would
keep one source of truth, and self-defeating: it keeps the secret in the build inputs,
so `firmware.bin` still contains it.

**Bounding the write.** `history.partition("nvs")` → `(0x9000, 0x6000)`. Refuse any
image whose length differs, in both directions, and additionally assert that
`off + size` does not exceed the next partition's offset so a future table edit cannot
silently un-bound it. The refusal message should name what is downstream: `phy_init` at
`0xF000`, then **`history` at `0x10000`, eight sectors away** — an oversized write does
not merely corrupt a neighbour, it eats the archive's store header and base snapshots.

**Output prints no secrets by default:** SSID and PSK *lengths* plus short
`sha256(...)[:4]` fingerprints, and a `MATCH` line against the source file. The
fingerprint should be labelled in `--help` as a comparison aid, not a secrecy mechanism —
a short SSID is recoverable from its hash by wordlist. `--reveal-ssid` exists for the
bench; the password is never revealed under any flag.

**Round-trip requirement.** `.claude/rules/history-store.md` requires host tooling to
round-trip. The image *writer* should stay vendored (a hand-rolled NVS page writer fails
only on device and puts this project on the hook for an Espressif-owned format), but a
read-only decoder is worth writing: `build` then decodes its own output and **asserts**
equality with the input JSON before anything is written — a pure host gate, no device and
no secrets on screen. `tools/hstest`'s `sample` target is the precedent, including its
rule that the check must assert rather than print.

## 6. Verification plan

- **L1 — host round-trip, no device.** `build` decodes its own image and asserts equality
  with the source JSON.
- **L2 — prove NVS is actually being used.** Provision the *real* credentials, then flash
  firmware whose built-in list carries a *deliberately wrong* password. Pass: the board
  joins. **Without this control a successful join proves nothing**, because the fallback
  would produce an identical result. Same reasoning as the 2026-08-09 resync-backoff
  entry in `docs/history-store-validation.md`.
- **L3 — fallback.** `clear`, reset ⇒ log names the built-in list, board joins, no
  `! NO WIFI`.
- **L4 — unprovisioned.** `clear` plus a `-DWIFI_NO_BUILTIN_CREDS` build ⇒ `! NO WIFI`
  then `! NOSYNC`, temperature still renders, no boot loop, sleep floor unchanged from
  the last measured figure for that rig.
- **L5 — survives a reflash.** After L2, `pio run -t upload` and confirm the board still
  joins on the wrong-password build. Proves NVS lives outside the app slot.
- **L6 — survives nothing.** `esptool erase_flash` ⇒ behaves as L3 or L4 depending on the
  build; then run the documented recovery and confirm both credentials and archive
  return.
- **L7 — untrusted input.** Write a `--schema-version 99` image ⇒ firmware logs that it
  does not understand the schema and is not erasing, falls back, joins; a later `verify`
  shows the v99 image **still on the device**. That last clause is the point.
- **L8 — timing.** `ms_now()` around `wifi_creds_load()` on both a C6 and the E, recorded
  in `docs/notes.md` with date and conditions, per the measure-don't-guess rule.
- **L9 — size.** A row in `docs/footprint.md`.
- Regression: `make -C tools/sim screenshots` and `make -C tools/hstest sample` should
  both be unchanged. A diff in either means something moved that should not have.

Rollout order, when it happens: bench scratch board first and the whole matrix on it;
then the FireBeetle, which is the only rig with a real UART bridge and therefore the only
one whose boot log is comfortably capturable, and which proves the non-C6 path; then the
XIAO rigs, scheduled at a drift-experiment arm boundary since every provisioning session
costs the in-progress window; and the long-soak board last, as part of its harvest.

## 7. Risks

**`nvs_flash_erase()` at `Thermometer.cpp:991` would silently destroy provisioning.**
Today that line costs nothing — NVS holds only PHY calibration. Under this design it
becomes an automatic, operator-free path that deletes the board's WiFi configuration, and
on a `WIFI_NO_BUILTIN_CREDS` board the result is a permanent `! NO WIFI` recoverable only
by a physical visit. It fires on `ESP_ERR_NVS_NO_FREE_PAGES` or
`ESP_ERR_NVS_NEW_VERSION_FOUND`. The erase should stay — a WiFi stack that cannot
initialise is worse — but it must log loudly what was lost. **This is the worst new
failure mode in the design.**

**PHY calibration shares the partition.** *Verified:*
`CONFIG_ESP_PHY_CALIBRATION_AND_DATA_STORAGE=y` and `CONFIG_ESP_PHY_RF_CAL_PARTIAL=y` on
both targets. Two consequences: the `nvs` partition is already written at runtime, so it
is not a quiet read-only region and page exhaustion is not purely theoretical; and a
whole-partition provisioning write discards stored calibration, so the next bring-up does
a fuller calibration. That one-time cost is **an estimate, order 100 ms — not measured**;
capture it during the first bench pass.

**esptool version skew.** *Verified:* `~/.platformio/penv` resolves esptool 4.11.0, the
project `.venv` resolves 5.3.1, where the CLI verbs are hyphenated (`write-flash`).
`history.write_device():431-441` works under both; copy it exactly rather than improving
it, and test under both interpreters.

**Rejected alternative worth recording:** storing credentials in the `history` partition
(custom subtype, plenty of room, no NVS format work). It would put the password inside
every `history.py backup --full` image — files that land in `local/archives/`, get named
in `docs/history-store-validation.md`, and get handed to an assistant for decoding.
Strictly worse than the status quo.

## 8. Prerequisite not yet met

`esp_idf_nvs_partition_gen` is **not installed**. *Verified:*
`~/.platformio/packages/framework-espidf/components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py`
is a 12-line shim that shells out to `python -m esp_idf_nvs_partition_gen`, and the module
imports in neither `~/.platformio/penv/bin/python3` nor the system interpreter. Adding
`esp-idf-nvs-partition-gen` to `tools/requirements.txt` is a prerequisite for the `build`
and `write` subcommands, and the tool should catch the `ImportError` the way
`history._connect():353-358` does for esptool.

Note also that the generator consumes a CSV, so during `build` the password is briefly
written to a temporary file. That is the design's weakest point on the host side and
should be handled explicitly — `$XDG_RUNTIME_DIR`, mode 0600 before writing, `unlink` in
a `finally`, never inside the repo tree — and documented rather than glossed over.

## 9. If implemented, these also need updating

`.claude/rules/` gains a path-scoped `provisioning.md`; `.claude/rules/build.md` gains a
line noting `nvs` now carries device configuration; the `/device-session` skill gains
re-provisioning alongside `history.py restore` in post-`erase_flash` recovery;
`CLAUDE.md` line 75 changes from "gitignored credentials only" to describe the NVS
arrangement (run `/claude-md-audit` first, per that file's own house rule);
`docs/build-system.md` gains the procedure and `WIFI_NO_BUILTIN_CREDS`;
`include/local-secrets-example.h` notes the list is now a fallback.
