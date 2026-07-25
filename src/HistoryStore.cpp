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
bool history_store_restore(RtcHistory *, HistoryDriftState *) { return false; }
void history_store_append_hourly(time_t, const HourlyEntry *) {}
void history_store_append_sample(time_t, int16_t) {}
void history_store_append_drift(const HistoryDriftSample *) {}
void history_store_mark_base_dirty(void) {}
void history_store_flush(const RtcHistory *, const HistoryDriftState *, time_t) {}
#else

#include "esp_chip_info.h"
#include "esp_mac.h"
#include "esp_partition.h"
#include "TempHistory.h"  // temp_history_record() — replay reuses the real eviction

// --- geometry ---------------------------------------------------------------

#define HS_MAGIC        0x54534948u  // "HIST"
#define HS_FORMAT       1
#define HS_SECTOR       4096u
#define HS_HDR_OFF      0u
#define HS_BASE_A_OFF   0x1000u
#define HS_BASE_B_OFF   0x3000u
#define HS_BASE_SIZE    0x2000u
#define HS_JOURNAL_OFF  0x5000u
#define HS_REC          16u          // journal slot size

#define REC_FREE    0xFF
#define REC_HOURLY  1
#define REC_SAMPLE  2
#define REC_DRIFT   3   // occupies two consecutive slots

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
  char     board[16];
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
  uint32_t time;       // hour start (HOURLY) or sample timestamp (SAMPLE)
  int16_t  a, b, c;    // HOURLY: min,max,avg | SAMPLE: temp_x10,-,-
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

// Erase everything and stamp a fresh header. Only ever reached when no valid
// header is present — i.e. a virgin partition, or the ~1MB of old app image
// left behind by the partition-table move. Costs ~480 sector erases (~24s,
// ~1C) exactly once, on the flashing bench.
static bool store_format(void)
{
  LOGI("HistoryStore: no valid header — formatting %u KB (one-time, ~%us)",
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
    // or foreign content). Reclaim one sector rather than the whole archive.
    uint32_t s = (s_base_cursor / HS_SECTOR) * HS_SECTOR;
    if (s >= s_jrn_size) s = 0;
    LOGI("HistoryStore: no free slot found — reclaiming sector 0x%06x", (unsigned)s);
    if (!part_erase(jrn_abs(s), HS_SECTOR)) return false;
    c = s;
  }
  s_cursor = c;
  return true;
}

static void journal_append(const void *rec, uint8_t slots)
{
  if (!s_ready || !journal_locate()) return;

  uint32_t len = (uint32_t)slots * HS_REC;
  if (s_cursor + len > s_jrn_size) s_cursor = 0;  // never straddle the ring end

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
    // Old partition table. Degrade silently rather than panic a battery device.
    LOGI("HistoryStore: no 'history' partition — archive disabled");
    return false;
  }

  HsStoreHeader h;
  if (part_read(HS_HDR_OFF, &h, sizeof(h)) && header_valid(&h))
  {
    s_jrn_size = h.journal_size;
  }
  else if (!store_format())
  {
    return false;
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
  s_ready = true;
  return true;
}

bool history_store_available(void) { return store_init(); }

bool history_store_restore(RtcHistory *out, HistoryDriftState *drift)
{
  if (!store_init()) return false;

  HsBaseHeader h;
  uint32_t off = base_find(&h);
  if (off == UINT32_MAX)
  {
    LOGI("HistoryStore: no valid base snapshot");
    return false;
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

  s_base_seq = h.seq;
  s_base_hourly = h.hourly_count;
  s_base_cursor = h.journal_cursor < s_jrn_size ? h.journal_cursor : 0;
  s_base_off = off;
  s_cursor = UINT32_MAX;
  if (!journal_locate()) return true;  // base alone is still a valid restore

  // Replay everything written after the base. base_seq is redundant with the
  // cursor range but cheap, and it catches a stale hint.
  int hourly = 0, samples = 0;
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
        else if (type == REC_SAMPLE)
        {
          // Through the real recorder, so smart eviction reproduces exactly.
          temp_history_record(out->temp, &out->temp_count, (time_t)r->time, r->a);
          samples++;
        }
      }
    }
    pos = jrn_next(pos, (uint32_t)n * HS_REC);
  }

  LOGI("History restored: %u hourly, %u sparkline (base seq %u, +%d/%d replayed)",
       (unsigned)out->hourly_count, (unsigned)out->temp_count,
       (unsigned)h.seq, hourly, samples);
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

void history_store_append_sample(time_t ts, int16_t temp_x10)
{
  if (!store_init()) return;
  HsRec r;
  memset(&r, 0, sizeof(r));
  r.type = REC_SAMPLE;
  r.base_seq = (uint16_t)(s_base_seq & 0xFFFF);
  r.time = (uint32_t)ts;
  r.a = temp_x10;
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

  if (!part_erase(slot, HS_BASE_SIZE)) return;
  if (!part_write(slot, &h, sizeof(h))) return;
  if (!part_write(slot + sizeof(h), hist, sizeof(*hist))) return;
  if (!part_write(slot + sizeof(h) + sizeof(*hist), drift, sizeof(*drift))) return;

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
  LOGI("HistoryStore: base snapshot seq %u (%u hourly, %u sparkline, cursor 0x%06x)",
       (unsigned)s_base_seq, (unsigned)h.hourly_count, (unsigned)h.temp_count,
       (unsigned)s_cursor);
}

#endif  // MOCK_DISPLAY_DATA
