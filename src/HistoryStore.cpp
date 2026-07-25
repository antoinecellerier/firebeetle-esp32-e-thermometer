// Flash-backed temperature archive — see include/HistoryStore.h for the why.
//
// Partition layout (offsets relative to the `history` partition):
//
//   0x0000  store header   4KB   magic + geometry + device identity, written once
//   0x1000  base slot A    8KB   RtcHistory + drift state, CRC32
//   0x3000  base slot B    8KB   ping-pong; highest valid seq wins
//   0x5000  journal        rest  16-byte append records, wraps as a ring
//
// Invariant that makes cursor discovery terminate: the sector FOLLOWING the
// cursor's sector is always fully erased. Without it, a wrapped ring has no
// 0xFF gap to scan to, and the first wrap is years out — a defect that would
// never surface in testing.

#include "HistoryStore.h"

#include <stdlib.h>
#include <string.h>

#include "app_common.h"

#ifdef MOCK_DISPLAY_DATA
// fill_mock_data() writes synthetic readings straight into historical_data.
// With the store live those would be journaled and snapshotted into the real
// archive, permanently. Compile every write out rather than relying on a
// runtime check — CLAUDE.md already records that debug defines leak into
// commits, and this one would poison years of data.
// #pragma message, not #warning: the build runs -Werror, and a hard failure
// here would break the documented on-device mock-render workflow (the
// commented-out build flag in platformio.ini). Compiling the writes out is the
// safety property; the message is just so it cannot happen silently.
#pragma message("MOCK_DISPLAY_DATA: HistoryStore disabled, flash archive not touched")
bool history_store_available(void) { return false; }
// No fault to report: a mock build has no archive ON PURPOSE, and its "! MOCK"
// badge already says the screen is synthetic.
uint8_t history_store_fault(void) { return HS_FAULT_NONE; }
uint16_t history_store_flash_format(void) { return 0; }
bool history_store_restore(RtcHistory *, HistoryDriftState *) { return false; }
void history_store_append_hourly(time_t, const HourlyEntry *) {}
void history_store_append_drift(const HistoryDriftSample *) {}
void history_store_mark_base_dirty(void) {}
void history_store_flush(const RtcHistory *, const HistoryDriftState *, time_t) {}
#else

#include "esp_chip_info.h"
#include "esp_mac.h"
#include "esp_partition.h"
#include "TempHistory.h"  // temp_history_record() — sparkline backfill reuses the real eviction

// --- geometry ---------------------------------------------------------------

#define HS_MAGIC        0x54534948u  // "HIST"
#define HS_FORMAT       2  // 2: sparkline samples no longer journaled
#define HS_SECTOR       4096u
#define HS_HDR_OFF      0u
#define HS_BASE_A_OFF   0x1000u
#define HS_BASE_B_OFF   0x3000u
#define HS_BASE_SIZE    0x2000u
#define HS_JOURNAL_OFF  0x5000u
#define HS_REC          16u          // journal slot size

// How many journal records may pass before a fresh base snapshot is taken.
//
// This is NOT what bounds the archive's exposure. The archive's recovery-point
// objective is **one hour**, and the journal alone delivers it: an hourly entry
// is programmed to flash the moment its hour finalizes, so a reflash, panic or
// battery pull costs at most the hour in progress. Nothing about the snapshot
// cadence changes that.
//
// What a snapshot adds is secondary, and worth its 7.14mC (0.1% of budget)
// only because it is that cheap:
//   - it is the ONLY copy of the 24h sparkline, which is never journaled;
//   - it is the anchor restore needs — without a valid base, history_store_
//     restore() bails even with a journal full of timestamped records;
//   - it bounds replay to this many records instead of a full sector.
//
// 24 keeps that at about a day. Note the sparkline gets little from that
// number specifically: it is a 24h window, so a snapshot a day old restores a
// chart whose every point has just aged out. Going finer would fix that and
// cost proportionally more; it has not been worth it, since the sparkline
// refills within a day of running.
//
// Counted in records rather than seconds because hourly entries are journaled
// exactly one per clock hour, gap fills included — so 24 records is 24 hours
// without a flash read on quiet wakes or an RTC variable. A drift record takes
// two slots and so counts double, which can only make a snapshot early.
#define HS_BASE_MAX_RECORDS 24

#define REC_FREE    0xFF
#define REC_HOURLY  1
// 2 was REC_SAMPLE: the 24h sparkline is restored from the base snapshot
// instead, so short-lived data can't crowd out the permanent archive.
#define REC_DRIFT   3   // occupies two consecutive slots
// Filler for the final slot when a two-slot record cannot fit before the ring
// end. Carries a valid CRC and a type nothing dispatches on, so scan and replay
// step over it; older firmware reads it as a one-slot record it ignores.
#define REC_PAD     4

// Written once at init. Identity lives here rather than in each base snapshot:
// it never changes for a given chip, and the host tool reads it from a fixed
// offset to name backups and to refuse restoring onto the wrong board.
struct __attribute__((packed)) HsStoreHeader {
  uint32_t magic;
  uint16_t format;
  uint16_t hdr_size;
  uint32_t journal_off;
  uint32_t journal_size;
  uint16_t rec_size;
  uint16_t base_slots;
  int64_t  created_at;
  uint8_t  base_mac[6];
  uint8_t  chip_model;
  uint8_t  chip_revision;
  char     board[24];   // "firebeetle2_esp32e" needs 19 with its NUL
  char     panel[16];
  char     sensor[16];
  char     git_hash[16];
  uint32_t crc32;  // over the preceding bytes; MUST stay last
};

// Base snapshot header. crc32 covers the header (up to but excluding itself)
// followed by the payload, so validation is one continuous pass.
struct __attribute__((packed)) HsBaseHeader {
  uint32_t magic;
  uint16_t format;
  uint16_t hdr_size;
  uint32_t seq;             // monotonic; highest valid slot wins
  uint32_t payload_len;
  int64_t  written_at;      // device wall clock when written
  uint32_t journal_cursor;  // cursor at write time — the replay start hint
  uint16_t hourly_count;    // mirrored so the write guard needs no payload read
  uint16_t temp_count;
  // Layout descriptors: make the blob self-describing so the host needs no
  // firmware-version knowledge, and a geometry change is detected rather than
  // silently misparsed.
  uint16_t temp_history_size;
  uint16_t hourly_history_size;
  uint16_t sizeof_temp_reading;
  uint16_t sizeof_hourly_entry;
  uint16_t sizeof_time_t;
  uint16_t sizeof_rtc_history;
  uint16_t sizeof_drift_state;
  uint16_t drift_ppm_hist_size;
  uint32_t crc32;  // MUST stay last
};

struct __attribute__((packed)) HsRec {
  uint8_t  type;
  uint8_t  rsvd;
  uint16_t base_seq;   // low 16 bits of the base this record was written under
  uint32_t time;       // start-of-hour this entry covers
  int16_t  a, b, c;    // min, max, avg
  uint16_t crc16;      // MUST stay last
};

struct __attribute__((packed)) HsDriftRec {
  uint8_t  type;
  uint8_t  rsvd;
  uint16_t base_seq;
  uint32_t time;       // last_sync_time
  int32_t  drift_ms;
  int32_t  window_s;
  int16_t  ppm;
  int16_t  ambient_mean_x10;
  uint32_t boot_count;
  uint32_t refresh_count;
  uint16_t ambient_hours;
  uint16_t crc16;      // MUST stay last
};

static_assert(sizeof(HsRec) == HS_REC, "journal record must be one slot");
static_assert(sizeof(HsDriftRec) == 2 * HS_REC, "drift record must be two slots");
static_assert(sizeof(HsBaseHeader) + sizeof(RtcHistory) + sizeof(HistoryDriftState)
                  <= HS_BASE_SIZE,
              "base snapshot does not fit its slot");

// --- CRC --------------------------------------------------------------------

// Standard IEEE CRC-32 (zlib-compatible), nibble table: 64 bytes of rodata and
// no dependence on esp_rom_crc32_le's pre/post-inversion convention, so
// tools/history.py can just call zlib.crc32().
static const uint32_t kCrc32Nib[16] = {
  0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC,
  0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
  0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C,
  0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C,
};

static uint32_t crc32_up(uint32_t crc, const void *buf, size_t len)
{
  const uint8_t *p = (const uint8_t *)buf;
  while (len--)
  {
    crc ^= *p++;
    crc = (crc >> 4) ^ kCrc32Nib[crc & 0x0F];
    crc = (crc >> 4) ^ kCrc32Nib[crc & 0x0F];
  }
  return crc;
}
static inline uint32_t crc32_begin(void) { return 0xFFFFFFFFu; }
static inline uint32_t crc32_end(uint32_t crc) { return crc ^ 0xFFFFFFFFu; }
static uint32_t crc32_of(const void *buf, size_t len)
{
  return crc32_end(crc32_up(crc32_begin(), buf, len));
}
// Records are tiny; fold the 32-bit result rather than carrying a second table.
static uint16_t crc16_of(const void *buf, size_t len)
{
  uint32_t c = crc32_of(buf, len);
  return (uint16_t)(c ^ (c >> 16));
}

// --- state ------------------------------------------------------------------

static const esp_partition_t *s_part = nullptr;
static bool     s_ready = false;
static bool     s_probed = false;
static bool     s_base_dirty = false;
static uint32_t s_jrn_size = 0;     // bytes, multiple of HS_SECTOR
static uint32_t s_cursor = UINT32_MAX;  // byte offset into the journal, or unknown
static uint32_t s_base_seq = 0;     // seq of the active base (0 = none yet)
static uint16_t s_base_hourly = 0;  // hourly_count recorded in the active base
static uint32_t s_base_cursor = 0;  // journal cursor at the active base's write
static uint32_t s_base_off = UINT32_MAX;  // slot the active base lives in
static uint8_t  s_fault = HS_FAULT_NONE;  // why the archive is not recording
static uint16_t s_flash_format = 0;       // on-flash format, when it is foreign

static inline uint32_t jrn_abs(uint32_t off) { return HS_JOURNAL_OFF + off; }
static inline uint32_t jrn_next(uint32_t off, uint32_t n)
{
  off += n;
  return (off >= s_jrn_size) ? 0 : off;
}

static bool part_read(uint32_t off, void *dst, size_t len)
{
  return s_part && esp_partition_read(s_part, off, dst, len) == ESP_OK;
}
static bool part_write(uint32_t off, const void *src, size_t len)
{
  return s_part && esp_partition_write(s_part, off, src, len) == ESP_OK;
}
static bool part_erase(uint32_t off, size_t len)
{
  return s_part && esp_partition_erase_range(s_part, off, len) == ESP_OK;
}

// --- identity ---------------------------------------------------------------

static const char *board_name(void)
{
#if defined(THERMOMETER_C6_BOARD)
  return "thermometer_c6";
#elif defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  return "firebeetle2_esp32e";
#elif defined(ARDUINO_XIAO_ESP32C6)
  return "xiao_esp32c6";
#else
  return "unknown";
#endif
}

static const char *panel_name(void)
{
#if defined(USE_154_Z90)
  return "GDEH0154Z90";
#elif defined(USE_154_M09)
  return "GDEH0154M09";
#elif defined(USE_213_M21)
  return "GDEY0213M21";
#elif defined(USE_290_I6FD)
  return "GDEW029I6FD";
#elif defined(USE_154_GDEY)
  return "GDEM0154I61";
#elif defined(USE_576_T81)
  return "GDEH0576T81";
#else
  return "none";
#endif
}

static const char *sensor_name(void)
{
#if defined(USE_BMP390L)
  return "BMP390L";
#elif defined(USE_BMP58x)
  return "BMP58x";
#elif defined(USE_DS18B20_PAR)
  return "DS18B20";
#elif defined(USE_DUMMY_SENSOR)
  return "dummy";
#else
  return "unknown";
#endif
}

static void copy_str(char *dst, size_t n, const char *src)
{
  memset(dst, 0, n);
  strncpy(dst, src, n - 1);
}

// --- store header / init ----------------------------------------------------

static bool header_valid(const HsStoreHeader *h)
{
  if (h->magic != HS_MAGIC || h->format != HS_FORMAT) return false;
  if (h->hdr_size != sizeof(HsStoreHeader)) return false;
  if (h->rec_size != HS_REC || h->journal_off != HS_JOURNAL_OFF) return false;
  if (h->journal_size == 0 || h->journal_size % HS_SECTOR) return false;
  const size_t n = offsetof(HsStoreHeader, crc32);
  return crc32_of(h, n) == h->crc32;
}

// Erase sector 0 and stamp a fresh header. Every field in the header is either
// a build-time constant or immutable device identity, so it is fully derivable
// — losing it costs nothing, and the header sector is disjoint from the base
// slots and the journal. That is what lets a damaged header be repaired
// in place instead of taken as grounds to erase the archive behind it.
static bool store_write_header(void)
{
  if (!part_erase(HS_HDR_OFF, HS_SECTOR))
  {
    LOGI("HistoryStore: header erase failed");
    return false;
  }

  HsStoreHeader h;
  memset(&h, 0, sizeof(h));
  h.magic = HS_MAGIC;
  h.format = HS_FORMAT;
  h.hdr_size = sizeof(HsStoreHeader);
  h.journal_off = HS_JOURNAL_OFF;
  h.journal_size = s_part->size - HS_JOURNAL_OFF;
  h.rec_size = HS_REC;
  h.base_slots = 2;
  h.created_at = (int64_t)time(nullptr);
  esp_efuse_mac_get_default(h.base_mac);
  esp_chip_info_t ci;
  esp_chip_info(&ci);
  h.chip_model = (uint8_t)ci.model;
  h.chip_revision = (uint8_t)ci.revision;
  copy_str(h.board, sizeof(h.board), board_name());
  copy_str(h.panel, sizeof(h.panel), panel_name());
  copy_str(h.sensor, sizeof(h.sensor), sensor_name());
#ifdef GIT_HASH
  copy_str(h.git_hash, sizeof(h.git_hash), GIT_HASH);
#endif
  h.crc32 = crc32_of(&h, offsetof(HsStoreHeader, crc32));

  if (!part_write(HS_HDR_OFF, &h, sizeof(h)))
  {
    LOGI("HistoryStore: header write failed");
    return false;
  }
  s_jrn_size = h.journal_size;
  return true;
}

// Erase the WHOLE partition, then stamp a header. Only ever reached when
// nothing in the region is ours — a virgin partition, or the ~1MB of old app
// image left behind by the partition-table move. Costs ~480 sector erases
// (~24s, ~1C) exactly once, on the flashing bench. Every other repair path
// goes through store_write_header(), which touches one sector.
static bool store_format(void)
{
  LOGI("HistoryStore: nothing recognizable — formatting %u KB (one-time, ~%us)",
       (unsigned)(s_part->size / 1024), (unsigned)(s_part->size / HS_SECTOR / 20));

  // Chunked so the log shows progress rather than ~24s of silence that reads
  // like a hang. Safe against the 5s task WDT either way:
  // CONFIG_SPI_FLASH_YIELD_DURING_ERASE yields to the idle task every 20ms of
  // erasing, which is exactly what that option exists for.
  const uint32_t step = 64 * 1024;
  for (uint32_t off = 0; off < s_part->size; off += step)
  {
    uint32_t n = s_part->size - off;
    if (n > step) n = step;
    if (!part_erase(off, n))
    {
      LOGI("HistoryStore: erase failed at 0x%06x", (unsigned)off);
      return false;
    }
    if ((off / step) % 8 == 0)
      LOGI("HistoryStore: formatting %u%%",
           (unsigned)(100ULL * off / s_part->size));
  }
  return store_write_header();
}

// --- base slots -------------------------------------------------------------

// Validate a slot's header and, optionally, its payload. Returns false on any
// mismatch; never mutates anything.
static bool base_read_header(uint32_t off, HsBaseHeader *h)
{
  if (!part_read(off, h, sizeof(*h))) return false;
  if (h->magic != HS_MAGIC || h->format != HS_FORMAT) return false;
  if (h->hdr_size != sizeof(HsBaseHeader)) return false;
  if (h->temp_history_size != TEMP_HISTORY_SIZE) return false;
  if (h->hourly_history_size != HOURLY_HISTORY_SIZE) return false;
  if (h->sizeof_temp_reading != sizeof(TempReading)) return false;
  if (h->sizeof_hourly_entry != sizeof(HourlyEntry)) return false;
  if (h->sizeof_time_t != sizeof(time_t)) return false;
  if (h->drift_ppm_hist_size != DRIFT_PPM_HIST_SIZE) return false;
  // A payload shorter than the running struct is fine — RtcHistory fields are
  // appended at the end by convention, so the tail zero-fills. Longer means a
  // newer firmware wrote it; refuse rather than truncate.
  if (h->sizeof_rtc_history > sizeof(RtcHistory)) return false;
  if (h->sizeof_drift_state > sizeof(HistoryDriftState)) return false;
  if (h->payload_len != (uint32_t)h->sizeof_rtc_history + h->sizeof_drift_state)
    return false;
  if (sizeof(HsBaseHeader) + h->payload_len > HS_BASE_SIZE) return false;
  return true;
}

// Streaming CRC over header-then-payload, so no 6.3KB bounce buffer is needed.
static bool base_verify(uint32_t off, const HsBaseHeader *h)
{
  uint32_t crc = crc32_up(crc32_begin(), h, offsetof(HsBaseHeader, crc32));
  uint8_t chunk[256];
  uint32_t left = h->payload_len, pos = off + sizeof(HsBaseHeader);
  while (left)
  {
    uint32_t n = left < sizeof(chunk) ? left : sizeof(chunk);
    if (!part_read(pos, chunk, n)) return false;
    crc = crc32_up(crc, chunk, n);
    pos += n;
    left -= n;
  }
  return crc32_end(crc) == h->crc32;
}

// Pick the newest valid slot. Returns its offset, or UINT32_MAX if neither is
// usable. Sequence comparison is plain unsigned: seq is bumped once per base
// write (<=1/day), so 32 bits will not wrap in any realistic device lifetime.
static uint32_t base_find(HsBaseHeader *out)
{
  const uint32_t slots[2] = { HS_BASE_A_OFF, HS_BASE_B_OFF };
  uint32_t best = UINT32_MAX;
  HsBaseHeader h;
  for (int i = 0; i < 2; i++)
  {
    if (!base_read_header(slots[i], &h)) continue;
    if (best != UINT32_MAX && h.seq <= out->seq) continue;
    if (!base_verify(slots[i], &h)) continue;
    *out = h;
    best = slots[i];
  }
  return best;
}

// --- journal ----------------------------------------------------------------

static uint8_t rec_slots(uint8_t type)
{
  return (type == REC_DRIFT) ? 2 : 1;
}

static bool rec_crc_ok(const uint8_t *raw, uint8_t type)
{
  if (type == REC_DRIFT)
  {
    const HsDriftRec *r = (const HsDriftRec *)raw;
    return crc16_of(r, offsetof(HsDriftRec, crc16)) == r->crc16;
  }
  const HsRec *r = (const HsRec *)raw;
  return crc16_of(r, offsetof(HsRec, crc16)) == r->crc16;
}

// Walk forward from `from` to the first free slot. Records between a base's
// cursor hint and the live cursor are valid by construction, so this is bounded
// by records-since-last-base in the common case; the full-journal bound is only
// a backstop.
static uint32_t journal_scan(uint32_t from)
{
  uint8_t raw[2 * HS_REC];
  uint32_t off = from;
  const uint32_t limit = s_jrn_size / HS_REC;
  for (uint32_t steps = 0; steps < limit; steps++)
  {
    if (!part_read(jrn_abs(off), raw, HS_REC)) return UINT32_MAX;
    if (raw[0] == REC_FREE) return off;
    uint8_t n = rec_slots(raw[0]);
    // A record must not straddle the ring end; the writer never creates one.
    if (off + (uint32_t)n * HS_REC > s_jrn_size) { off = 0; continue; }
    off = jrn_next(off, (uint32_t)n * HS_REC);
  }
  return UINT32_MAX;  // no gap anywhere — should be impossible
}

static bool sector_is_blank(uint32_t off)
{
  // Probe both ends: a completed erase leaves the whole sector 0xFF, and an
  // interrupted one is caught later by the pre-write check in journal_append().
  uint8_t a[HS_REC], b[HS_REC];
  if (!part_read(jrn_abs(off), a, sizeof(a))) return false;
  if (!part_read(jrn_abs(off) + HS_SECTOR - HS_REC, b, sizeof(b))) return false;
  for (size_t i = 0; i < sizeof(a); i++)
    if (a[i] != 0xFF || b[i] != 0xFF) return false;
  return true;
}

// Keep the sector AFTER the cursor's sector erased at all times. This is what
// guarantees journal_scan() terminates once the ring has wrapped, and doing it
// a sector early removes the power-loss window that erasing on arrival would
// leave.
static void journal_erase_ahead(void)
{
  uint32_t next = (s_cursor / HS_SECTOR + 1) * HS_SECTOR;
  if (next >= s_jrn_size) next = 0;
  if (sector_is_blank(next)) return;
  if (part_erase(jrn_abs(next), HS_SECTOR))
    LOGI("HistoryStore: erased journal sector at 0x%06x", (unsigned)next);
}

static bool journal_locate(void)
{
  if (s_cursor != UINT32_MAX) return true;
  uint32_t c = journal_scan(s_base_cursor < s_jrn_size ? s_base_cursor : 0);
  if (c == UINT32_MAX)
  {
    // Every slot written and no gap: an invariant was violated (torn erase,
    // or foreign content). Reclaim one sector rather than the whole archive —
    // the one AFTER the base cursor's, never the base cursor's own. In ring
    // order that is where the blank sector should have been, and failing that
    // it holds the oldest records, which the ring was about to overwrite
    // anyway. The base cursor's own sector holds everything written since the
    // last snapshot: the only copy of up to a day of history, and the last
    // thing that should be spent recovering from a flash fault.
    uint32_t s = (s_base_cursor / HS_SECTOR + 1) * HS_SECTOR;
    if (s >= s_jrn_size) s = 0;
    LOGI("HistoryStore: no free slot found — reclaiming sector 0x%06x", (unsigned)s);
    if (!part_erase(jrn_abs(s), HS_SECTOR)) return false;
    c = s;
  }
  s_cursor = c;
  return true;
}

// Occupy one slot so it cannot be mistaken for the ring's free gap. A no-op if
// the slot already holds something.
static void journal_write_pad(uint32_t off)
{
  uint8_t probe[HS_REC];
  if (!part_read(jrn_abs(off), probe, sizeof(probe))) return;
  for (size_t i = 0; i < sizeof(probe); i++)
    if (probe[i] != 0xFF) return;

  HsRec pad;
  memset(&pad, 0, sizeof(pad));
  pad.type = REC_PAD;
  pad.base_seq = (uint16_t)(s_base_seq & 0xFFFF);
  pad.crc16 = crc16_of(&pad, offsetof(HsRec, crc16));
  part_write(jrn_abs(off), &pad, sizeof(pad));
}

static void journal_append(const void *rec, uint8_t slots)
{
  if (!s_ready || !journal_locate()) return;

  uint32_t len = (uint32_t)slots * HS_REC;
  if (s_cursor + len > s_jrn_size)
  {
    // A two-slot record must not straddle the ring end. Simply wrapping left
    // the final slot erased forever, and journal_scan() tests for a free slot
    // BEFORE it tests for a straddle — so that hole was reported as the cursor,
    // restore skipped every record written after the wrap, and the next append
    // then erased sector 0 and destroyed them. Pad the slot instead. Only ever
    // one slot: s_cursor is slot-aligned and records are at most two slots.
    journal_write_pad(s_cursor);
    s_cursor = 0;
  }

  // Belt and braces: NOR can only clear bits, so writing over a torn record
  // would silently corrupt it. If the target is not blank, reclaim its sector.
  uint8_t probe[2 * HS_REC];
  if (part_read(jrn_abs(s_cursor), probe, len))
  {
    bool blank = true;
    for (uint32_t i = 0; i < len; i++)
      if (probe[i] != 0xFF) { blank = false; break; }
    if (!blank)
    {
      uint32_t s = (s_cursor / HS_SECTOR) * HS_SECTOR;
      if (!part_erase(jrn_abs(s), HS_SECTOR)) return;
      s_cursor = s;
    }
  }

  if (!part_write(jrn_abs(s_cursor), rec, len)) return;
  uint32_t before = s_cursor / HS_SECTOR;
  s_cursor = jrn_next(s_cursor, len);
  if (s_cursor / HS_SECTOR != before || s_cursor == 0)
    journal_erase_ahead();

  // Keep a snapshot within reach, and bound how far a restore has to replay.
  // The NTP-resync trigger alone cannot do either: restore needs a base to
  // anchor to, so a device that never syncs would journal records it could
  // never restore, and the resync interval is adaptive over [1d, 28d] — a board
  // with an accurate clock would go 28 days between snapshots, so the better the
  // oscillator the longer it could not restore. Owning the cadence here makes it
  // a property of the store instead of a side effect of clock quality.
  uint32_t since = (s_cursor >= s_base_cursor)
                       ? s_cursor - s_base_cursor
                       : s_jrn_size - s_base_cursor + s_cursor;
  if (s_base_seq == 0 || since >= HS_BASE_MAX_RECORDS * HS_REC)
    s_base_dirty = true;
}

// --- public API -------------------------------------------------------------

static bool store_init(void)
{
  if (s_probed) return s_ready;
  s_probed = true;

  s_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                    ESP_PARTITION_SUBTYPE_ANY, "history");
  if (!s_part)
  {
    // Old partition table. Degrade rather than panic a battery device — but the
    // status line says so, since nothing is being archived.
    LOGI("HistoryStore: no 'history' partition — archive disabled");
    s_fault = HS_FAULT_NO_PARTITION;
    return false;
  }

  HsStoreHeader h;
  const bool hdr_read = part_read(HS_HDR_OFF, &h, sizeof(h));

  // Canonical geometry, needed before the header is trusted so the content
  // probe below can address the base slots and the journal at all. A valid
  // header only ever mirrors this.
  s_jrn_size = s_part->size - HS_JOURNAL_OFF;

  if (hdr_read && h.magic == HS_MAGIC && h.format != HS_FORMAT)
  {
    // A format this firmware does not speak. Erasing here would destroy years
    // of records on nothing worse than a version skew, so refuse to touch the
    // partition at all — a stalled archive is recoverable, an erased one is
    // not. tools/history.py decodes by the header's own format field, so the
    // content is still readable from the host.
    LOGI("HistoryStore: on-flash format %u, firmware speaks %u — archive left "
         "intact and DISABLED. Back it up (tools/history.py backup), then "
         "erase_flash to start a new one.",
         (unsigned)h.format, (unsigned)HS_FORMAT);
    s_fault = HS_FAULT_FOREIGN_FORMAT;
    s_flash_format = h.format;
    return false;
  }

  if (hdr_read && header_valid(&h))
  {
    s_jrn_size = h.journal_size;
  }
  else
  {
    // The header is unusable, but it is not evidence that anything behind it
    // is: it is written once at format time and never rewritten, so a bad one
    // is a torn first write or a bit flip, and the base slots and journal carry
    // their own CRCs. Only erase the archive when nothing behind the header
    // validates either. A base exists from the first sleep onward, so its
    // absence really does mean the region was never ours.
    HsBaseHeader probe;
    if (base_find(&probe) != UINT32_MAX)
    {
      LOGI("HistoryStore: header damaged but base seq %u is intact — "
           "rewriting the header only", (unsigned)probe.seq);
      if (!store_write_header()) { s_fault = HS_FAULT_IO; return false; }
    }
    else if (!store_format())
    {
      s_fault = HS_FAULT_IO;
      return false;
    }
  }

  HsBaseHeader bh;
  uint32_t off = base_find(&bh);
  if (off != UINT32_MAX)
  {
    s_base_seq = bh.seq;
    s_base_hourly = bh.hourly_count;
    s_base_cursor = bh.journal_cursor < s_jrn_size ? bh.journal_cursor : 0;
    s_base_off = off;
  }
  else
  {
    // No base yet. Ask for one at the next sleep rather than waiting for the
    // first journal append: now that only hourly entries are journaled, that
    // would be up to an hour away, and the sparkline is only persisted by the
    // base.
    s_base_dirty = true;
  }
  s_ready = true;
  return true;
}

// Physical slot of logical entry `i` (0 = oldest, count-1 = newest), matching
// the mapping Display.h documents and DisplayRenderer walks.
static inline uint16_t ring_slot(const RtcHistory *h, uint16_t i)
{
  uint16_t start = (h->hourly_count < HOURLY_HISTORY_SIZE) ? 0 : h->hourly_idx;
  return (uint16_t)((start + i) % HOURLY_HISTORY_SIZE);
}

// Seed the 24h sparkline from the hourly ring for hours it does not already
// cover. Hourly resolution rather than per-refresh, but a coarse chart beats
// the empty one a restore used to produce.
//
// The sparkline is never journaled, so it is only ever as fresh as the base
// snapshot — and since it is a 24h window, a snapshot a day old restored a
// chart whose every point had already aged out. Backfilling from the ring
// closes exactly that gap, and it is the only way to show anything at all when
// the ring itself came from the journal with no snapshot behind it.
//
// Goes through temp_history_record() rather than writing the buffer directly,
// so ordering and Visvalingam eviction stay the real implementation's problem.
static void sparkline_backfill(RtcHistory *out)
{
  if (out->hourly_count == 0) return;

  const time_t newest_spark =
      out->temp_count ? (time_t)out->temp[out->temp_count - 1].timestamp : 0;

  uint16_t n = out->hourly_count < 24 ? out->hourly_count : 24;
  int added = 0;
  for (uint16_t k = n; k >= 1; k--)
  {
    const time_t t = out->hourly_latest_time - (time_t)(k - 1) * 3600;
    if (t <= newest_spark) continue;   // real per-refresh points win
    const HourlyEntry &e = out->hourly[ring_slot(out, out->hourly_count - k)];
    if (e.min_x10 == HOURLY_NO_DATA) continue;   // device was off; leave the gap
    temp_history_record(out->temp, &out->temp_count, t, e.avg_x10);
    added++;
  }
  if (added)
    LOGI("HistoryStore: sparkline backfilled with %d hourly points", added);
}

// Rebuild the hourly ring from the journal alone, for when no base snapshot
// validates. Every record carries its own hour and CRC, so the ring is fully
// reconstructible without a snapshot — the snapshot is a fast path, not the
// only copy. Without this, losing both ping-ponged base slots stranded an
// archive that was still perfectly readable, which is a poor way for something
// meant to hold years to fail.
//
// Two passes: the newest hour has to be known before the window can be placed,
// and a wrapped ring puts address order out of step with time order. Scans slot
// by slot rather than walking records, since without a base there is no cursor
// hint to walk from; the 16-bit CRC is what makes that safe, and the only
// non-record slots it can land on are the second halves of REC_DRIFT entries
// (~1/day), so false positives are far below one per archive lifetime.
//
// ~3.8MB of reads (~1.6s, ~50mC). Only ever on a cold boot that found no base,
// so it never runs in normal operation.
static bool journal_rebuild_hourly(RtcHistory *out)
{
  if (!journal_locate()) return false;

  uint8_t raw[HS_REC];
  time_t newest = 0, oldest = 0;
  for (uint32_t off = 0; off + HS_REC <= s_jrn_size; off += HS_REC)
  {
    if (!part_read(jrn_abs(off), raw, HS_REC)) continue;
    if (raw[0] != REC_HOURLY || !rec_crc_ok(raw, REC_HOURLY)) continue;
    const time_t t = (time_t)((const HsRec *)raw)->time;
    if (!time_is_plausible(t)) continue;
    if (t > newest) newest = t;
    if (oldest == 0 || t < oldest) oldest = t;
  }
  if (newest == 0) return false;

  // Window: the newest HOURLY_HISTORY_SIZE hours that actually exist, so a
  // young archive does not claim a ring full of gaps it never lived through.
  if (newest - oldest >= (time_t)HOURLY_HISTORY_SIZE * 3600)
    oldest = newest - (time_t)(HOURLY_HISTORY_SIZE - 1) * 3600;
  const uint16_t n = (uint16_t)((newest - oldest) / 3600) + 1;

  for (uint16_t i = 0; i < HOURLY_HISTORY_SIZE; i++)
    out->hourly[i] = { HOURLY_NO_DATA, HOURLY_NO_DATA, HOURLY_NO_DATA };

  int found = 0;
  for (uint32_t off = 0; off + HS_REC <= s_jrn_size; off += HS_REC)
  {
    if (!part_read(jrn_abs(off), raw, HS_REC)) continue;
    if (raw[0] != REC_HOURLY || !rec_crc_ok(raw, REC_HOURLY)) continue;
    const HsRec *r = (const HsRec *)raw;
    const time_t t = (time_t)r->time;
    if (t < oldest || t > newest) continue;
    // Filled linearly from index 0, so hourly_idx below is the write head and
    // ring_slot() resolves entry 0 to the oldest hour.
    out->hourly[(uint16_t)((t - oldest) / 3600)] = { r->a, r->b, r->c };
    found++;
  }

  out->hourly_count = n;
  out->hourly_idx = (uint16_t)(n % HOURLY_HISTORY_SIZE);
  out->hourly_latest_time = newest;
  LOGI("HistoryStore: no base — rebuilt %u hours from %d journal records",
       (unsigned)n, found);
  return true;
}

bool history_store_available(void) { return store_init(); }
uint8_t history_store_fault(void) { return s_fault; }
uint16_t history_store_flash_format(void) { return s_flash_format; }

bool history_store_restore(RtcHistory *out, HistoryDriftState *drift)
{
  if (!store_init()) return false;

  HsBaseHeader h;
  uint32_t off = base_find(&h);
  if (off == UINT32_MAX)
  {
    // No snapshot, but the journal may still hold years of timestamped,
    // CRC-checked hours. Rebuild from it rather than declaring the archive
    // lost. The drift block and the per-refresh sparkline live only in the
    // snapshot, so they do not come back — the ring does, and it is what the
    // partition exists for.
    LOGI("HistoryStore: no valid base snapshot — trying the journal");
    if (!out || !store_init()) return false;
    memset(out, 0, sizeof(*out));
    out->version = RTC_HISTORY_VERSION;
    if (!journal_rebuild_hourly(out)) return false;
    sparkline_backfill(out);
    return true;
  }

  if (drift)
  {
    memset(drift, 0, sizeof(*drift));
    if (!part_read(off + sizeof(HsBaseHeader) + h.sizeof_rtc_history, drift,
                   h.sizeof_drift_state))
      return false;
  }
  if (!out)
    return true;  // drift-only load; no 6.3KB read, no replay

  // Shorter stored payloads zero-fill; base_read_header() already rejected
  // longer ones and any geometry change.
  memset(out, 0, sizeof(*out));
  if (!part_read(off + sizeof(HsBaseHeader), out, h.sizeof_rtc_history))
    return false;
  out->version = RTC_HISTORY_VERSION;

  // Clamp the counts. The CRC proves these are the bytes that were written, not
  // that they were sane when written, and the geometry descriptors say nothing
  // about the values inside the payload. Everything downstream indexes the
  // arrays off them without a bound of its own — DisplayRenderer walks
  // temp_history[0..history_count) and window_mean_ambient_x10() walks back
  // from hourly_idx — so an out-of-range count reads far past RTC slow memory
  // and faults on the render path. A bad snapshot is re-restored on every cold
  // boot, so that would be a panic loop no reflash could clear.
  if (out->temp_count > TEMP_HISTORY_SIZE)
  {
    LOGI("HistoryStore: temp_count %u > %u — clamped",
         (unsigned)out->temp_count, (unsigned)TEMP_HISTORY_SIZE);
    out->temp_count = TEMP_HISTORY_SIZE;
  }
  if (out->hourly_count > HOURLY_HISTORY_SIZE)
  {
    LOGI("HistoryStore: hourly_count %u > %u — clamped",
         (unsigned)out->hourly_count, (unsigned)HOURLY_HISTORY_SIZE);
    out->hourly_count = HOURLY_HISTORY_SIZE;
  }
  if (out->hourly_idx >= HOURLY_HISTORY_SIZE)
  {
    LOGI("HistoryStore: hourly_idx %u out of range — reset",
         (unsigned)out->hourly_idx);
    out->hourly_idx = 0;
  }

  s_base_seq = h.seq;
  s_base_hourly = h.hourly_count;
  s_base_cursor = h.journal_cursor < s_jrn_size ? h.journal_cursor : 0;
  s_base_off = off;
  s_cursor = UINT32_MAX;
  if (!journal_locate()) return true;  // base alone is still a valid restore

  // Replay everything written after the base. base_seq is redundant with the
  // cursor range but cheap, and it catches a stale hint.
  int hourly = 0;
  uint8_t raw[2 * HS_REC];
  uint32_t pos = s_base_cursor;
  const uint16_t want = (uint16_t)(h.seq & 0xFFFF);
  // Bounded: a corrupt hint must not spin forever on a battery device.
  for (uint32_t steps = s_jrn_size / HS_REC; pos != s_cursor && steps; steps--)
  {
    if (!part_read(jrn_abs(pos), raw, HS_REC)) break;
    uint8_t type = raw[0];
    if (type == REC_FREE) break;
    uint8_t n = rec_slots(type);
    if (pos + (uint32_t)n * HS_REC > s_jrn_size) { pos = 0; continue; }
    if (n == 2 && !part_read(jrn_abs(pos), raw, 2 * HS_REC)) break;

    if (rec_crc_ok(raw, type))
    {
      const HsRec *r = (const HsRec *)raw;
      if (r->base_seq == want)
      {
        if (type == REC_HOURLY)
        {
          out->hourly[out->hourly_idx].min_x10 = r->a;
          out->hourly[out->hourly_idx].max_x10 = r->b;
          out->hourly[out->hourly_idx].avg_x10 = r->c;
          out->hourly_idx = (uint16_t)((out->hourly_idx + 1) % HOURLY_HISTORY_SIZE);
          if (out->hourly_count < HOURLY_HISTORY_SIZE) out->hourly_count++;
          out->hourly_latest_time = (time_t)r->time;
          hourly++;
        }
        // REC_DRIFT carries no RtcHistory state; the host tool decodes it.
      }
    }
    pos = jrn_next(pos, (uint32_t)n * HS_REC);
  }

  // The sparkline is not journaled, so what came out of the snapshot is as old
  // as the snapshot. Top it up from the hours replayed above, which covers the
  // window between the two at hourly resolution.
  sparkline_backfill(out);

  LOGI("History restored: %u hourly (+%d replayed), %u sparkline, base seq %u",
       (unsigned)out->hourly_count, hourly, (unsigned)out->temp_count,
       (unsigned)h.seq);
  return true;
}

void history_store_append_hourly(time_t hour_start, const HourlyEntry *entry)
{
  if (!store_init()) return;
  HsRec r;
  memset(&r, 0, sizeof(r));
  r.type = REC_HOURLY;
  r.base_seq = (uint16_t)(s_base_seq & 0xFFFF);
  r.time = (uint32_t)hour_start;
  r.a = entry->min_x10;
  r.b = entry->max_x10;
  r.c = entry->avg_x10;
  r.crc16 = crc16_of(&r, offsetof(HsRec, crc16));
  journal_append(&r, 1);
}

void history_store_append_drift(const HistoryDriftSample *s)
{
  if (!store_init()) return;
  HsDriftRec r;
  memset(&r, 0, sizeof(r));
  r.type = REC_DRIFT;
  r.base_seq = (uint16_t)(s_base_seq & 0xFFFF);
  r.time = (uint32_t)s->sync_time;
  r.drift_ms = s->drift_ms;
  r.window_s = s->window_s;
  r.ppm = s->ppm;
  r.ambient_mean_x10 = s->ambient_mean_x10;
  r.boot_count = s->boot_count;
  r.refresh_count = s->refresh_count;
  r.ambient_hours = s->ambient_hours;
  r.crc16 = crc16_of(&r, offsetof(HsDriftRec, crc16));
  journal_append(&r, 2);
}

void history_store_mark_base_dirty(void) { s_base_dirty = true; }

void history_store_flush(const RtcHistory *hist, const HistoryDriftState *drift,
                        time_t now)
{
  if (!s_base_dirty) return;
  s_base_dirty = false;
  if (!store_init() || !journal_locate()) return;

  // Never overwrite a good base with an emptier ring. The base write happens
  // many wakes after the restore, so a "restore succeeded" flag would have to
  // live in RTC; hourly_count only ever grows (saturating at
  // HOURLY_HISTORY_SIZE), which makes the same guarantee statelessly. This is
  // also what stops the >25h-backwards-jump reset from destroying the archive.
  if (s_base_seq != 0 && hist->hourly_count < s_base_hourly)
  {
    LOGI("HistoryStore: base write refused (%u hourly in RTC < %u stored)",
         (unsigned)hist->hourly_count, (unsigned)s_base_hourly);
    return;
  }

  // Ping-pong: write to whichever slot is not currently active, so a power loss
  // mid-write leaves the previous snapshot intact.
  uint32_t slot = (s_base_off == HS_BASE_A_OFF) ? HS_BASE_B_OFF : HS_BASE_A_OFF;

  HsBaseHeader h;
  memset(&h, 0, sizeof(h));
  h.magic = HS_MAGIC;
  h.format = HS_FORMAT;
  h.hdr_size = sizeof(HsBaseHeader);
  h.seq = s_base_seq + 1;
  h.payload_len = sizeof(RtcHistory) + sizeof(HistoryDriftState);
  h.written_at = (int64_t)now;
  h.journal_cursor = s_cursor;
  h.hourly_count = hist->hourly_count;
  h.temp_count = hist->temp_count;
  h.temp_history_size = TEMP_HISTORY_SIZE;
  h.hourly_history_size = HOURLY_HISTORY_SIZE;
  h.sizeof_temp_reading = sizeof(TempReading);
  h.sizeof_hourly_entry = sizeof(HourlyEntry);
  h.sizeof_time_t = sizeof(time_t);
  h.sizeof_rtc_history = sizeof(RtcHistory);
  h.sizeof_drift_state = sizeof(HistoryDriftState);
  h.drift_ppm_hist_size = DRIFT_PPM_HIST_SIZE;

  uint32_t crc = crc32_up(crc32_begin(), &h, offsetof(HsBaseHeader, crc32));
  crc = crc32_up(crc, hist, sizeof(*hist));
  crc = crc32_up(crc, drift, sizeof(*drift));
  h.crc32 = crc32_end(crc);

  // Timed because the cadence is an energy decision and the cost is dominated
  // by the flash part's internal erase time, not by anything the firmware
  // controls. Multiply by the active-phase current (~40mA: ~15mA flash +
  // ~25mA CPU at 80MHz, which spins with the cache disabled) for the charge.
  uint32_t t0 = ms_now();
  if (!part_erase(slot, HS_BASE_SIZE)) return;
  uint32_t t_erase = ms_now();

  // One page-aligned write, not three. Splitting it made the middle (6.3KB)
  // write start mid-page, so nearly every 256-byte page took an extra program
  // cycle — measured on an ESP32-E: 66ms across three writes versus 25ms this
  // way, which is 21% off the whole snapshot. The buffer is transient and DRAM
  // is ~85% free; fall back to the split writes if the allocation ever fails.
  const size_t total = sizeof(h) + sizeof(*hist) + sizeof(*drift);
  uint8_t *buf = (uint8_t *)malloc(total);
  bool ok;
  if (buf)
  {
    memcpy(buf, &h, sizeof(h));
    memcpy(buf + sizeof(h), hist, sizeof(*hist));
    memcpy(buf + sizeof(h) + sizeof(*hist), drift, sizeof(*drift));
    ok = part_write(slot, buf, total);
    free(buf);
  }
  else
  {
    ok = part_write(slot, &h, sizeof(h)) &&
         part_write(slot + sizeof(h), hist, sizeof(*hist)) &&
         part_write(slot + sizeof(h) + sizeof(*hist), drift, sizeof(*drift));
  }
  if (!ok) return;
  uint32_t t_prog = ms_now();

  // Verify before adopting the new seq: records appended earlier in THIS wake
  // are already inside the snapshot and carry the old seq, so they are
  // correctly skipped on replay. Bumping only after a verified write also
  // avoids orphaning a day of records if the write failed.
  HsBaseHeader check;
  if (!base_read_header(slot, &check) || !base_verify(slot, &check))
  {
    LOGI("HistoryStore: base snapshot failed verify, keeping seq %u",
         (unsigned)s_base_seq);
    return;
  }
  s_base_seq = check.seq;
  s_base_hourly = check.hourly_count;
  s_base_cursor = check.journal_cursor;
  s_base_off = slot;
  LOGI("HistoryStore: base snapshot seq %u (%u hourly, %u sparkline, cursor 0x%06x)"
       " — erase %ums, program %ums, verify %ums",
       (unsigned)s_base_seq, (unsigned)h.hourly_count, (unsigned)h.temp_count,
       (unsigned)s_cursor, (unsigned)(t_erase - t0), (unsigned)(t_prog - t_erase),
       (unsigned)(ms_now() - t_prog));
}

#endif  // MOCK_DISPLAY_DATA
