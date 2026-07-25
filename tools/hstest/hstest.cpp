// Host-side test for src/HistoryStore.cpp.
//
// Compiles the REAL store against a simulated NOR flash, so the on-flash format,
// the journal cursor logic and the ring wrap are exercised natively instead of
// only on hardware. The wrap in particular is ~4.6 years out on a real device —
// this is the only practical way to reach it.
//
// The store's state is file-static, so this includes the .cpp directly: that is
// what lets a "reboot" be simulated by clearing those statics, which is exactly
// what the cursor-rediscovery path needs to be tested against.
//
// Writes model NOR semantics (program can only clear bits), so writing over a
// non-blank slot corrupts it here just as it would on the device.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <cstdint>
#include <vector>

#include "esp_chip_info.h"
#include "esp_mac.h"
#include "esp_partition.h"

// Small partition so the ring wraps in seconds rather than years.
#define FAKE_PART_SIZE (0x5000u + 8u * 4096u)

static std::vector<uint8_t> g_flash;
static esp_partition_t g_part;
static bool g_have_part = true;
static size_t g_erase_count, g_write_count;

const esp_partition_t *esp_partition_find_first(esp_partition_type_t,
                                                esp_partition_subtype_t,
                                                const char *)
{
  return g_have_part ? &g_part : nullptr;
}

esp_err_t esp_partition_read(const esp_partition_t *, size_t off, void *dst, size_t n)
{
  if (off + n > g_flash.size()) return -1;
  memcpy(dst, g_flash.data() + off, n);
  return ESP_OK;
}

esp_err_t esp_partition_write(const esp_partition_t *, size_t off, const void *src, size_t n)
{
  if (off + n > g_flash.size()) return -1;
  if (off % 4 || n % 4) { printf("FAIL: unaligned write off=%zu n=%zu\n", off, n); exit(1); }
  const uint8_t *s = (const uint8_t *)src;
  for (size_t i = 0; i < n; i++)
    g_flash[off + i] &= s[i];  // NOR: program only clears bits
  g_write_count++;
  return ESP_OK;
}

esp_err_t esp_partition_erase_range(const esp_partition_t *, size_t off, size_t n)
{
  if (off % 4096 || n % 4096) { printf("FAIL: unaligned erase off=%zu n=%zu\n", off, n); exit(1); }
  if (off + n > g_flash.size()) return -1;
  memset(g_flash.data() + off, 0xFF, n);
  g_erase_count += n / 4096;
  return ESP_OK;
}

// Overridable so --inject can stamp a real device's MAC and have it accept the
// image as its own.
static uint8_t g_mac[6] = { 0x24, 0x6f, 0x28, 0xab, 0xcd, 0xef };

int esp_efuse_mac_get_default(uint8_t *mac)
{
  memcpy(mac, g_mac, 6);
  return ESP_OK;
}

void esp_chip_info(esp_chip_info_t *out) { out->model = 1; out->revision = 3; }

#include "../../src/HistoryStore.cpp"
#include "MockData.h"

// --- harness ----------------------------------------------------------------

static int g_fail;
#define CHECK(cond, ...) do { if (!(cond)) { \
    printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); g_fail++; } } while (0)

// Clear the store's module state — the device equivalent of a cold boot.
static void reboot(void)
{
  s_part = nullptr;
  s_ready = s_probed = s_base_dirty = false;
  s_jrn_size = 0;
  s_cursor = UINT32_MAX;
  s_base_seq = 0;
  s_base_hourly = 0;
  s_base_cursor = 0;
  s_base_off = UINT32_MAX;
}

static void power_on(bool wipe)
{
  if (wipe) { g_flash.assign(FAKE_PART_SIZE, 0xFF); }
  g_part.size = FAKE_PART_SIZE;
  reboot();
}

static RtcHistory g_hist;
static HistoryDriftState g_drift;

static void reset_hist(void)
{
  memset(&g_hist, 0, sizeof(g_hist));
  g_hist.version = RTC_HISTORY_VERSION;
  g_hist.current_hour_min_x10 = 9990;
  g_hist.current_hour_max_x10 = -9990;
  memset(&g_drift, 0, sizeof(g_drift));
}

static void ring_push(time_t hour, int16_t mn, int16_t mx, int16_t av)
{
  HourlyEntry e = { mn, mx, av };
  g_hist.hourly[g_hist.hourly_idx] = e;
  g_hist.hourly_idx = (uint16_t)((g_hist.hourly_idx + 1) % HOURLY_HISTORY_SIZE);
  if (g_hist.hourly_count < HOURLY_HISTORY_SIZE) g_hist.hourly_count++;
  g_hist.hourly_latest_time = hour;
  history_store_append_hourly(hour, &e);
}

static const time_t T0 = 1750000000;  // 2025-06-15, comfortably "plausible"

int main(int argc, char **argv)
{
  // ---- 1. virgin partition formats and is usable ----
  power_on(true);
  reset_hist();
  CHECK(history_store_available(), "store should come up on a blank partition");
  CHECK(s_jrn_size == FAKE_PART_SIZE - HS_JOURNAL_OFF, "journal size %u",
        (unsigned)s_jrn_size);

  // ---- 2. append, snapshot, restore round-trip ----
  for (int i = 0; i < 50; i++)
    ring_push(T0 + i * 3600, (int16_t)(200 + i), (int16_t)(210 + i), (int16_t)(205 + i));
  g_hist.temp_count = 0;
  for (int i = 0; i < 20; i++)
    temp_history_record(g_hist.temp, &g_hist.temp_count, T0 + i * 600, (int16_t)(200 + i));

  g_drift.resync_interval_s = 86400;
  g_drift.last_drift_ms = -9559000;
  g_drift.last_drift_window_s = 1814400;
  g_drift.last_sync_time = T0;
  g_drift.drift_ppm_count = 2;
  g_drift.drift_ppm_hist[0] = -5265;
  g_drift.drift_ppm_hist[1] = -5100;

  history_store_mark_base_dirty();
  history_store_flush(&g_hist, &g_drift, T0 + 50 * 3600);
  CHECK(s_base_seq == 1, "first base should be seq 1, got %u", (unsigned)s_base_seq);

  RtcHistory saved = g_hist;
  reboot();
  RtcHistory got;
  HistoryDriftState gotd;
  CHECK(history_store_restore(&got, &gotd), "restore after snapshot");
  CHECK(got.hourly_count == saved.hourly_count, "hourly_count %u != %u",
        got.hourly_count, saved.hourly_count);
  CHECK(memcmp(got.hourly, saved.hourly, sizeof(got.hourly)) == 0, "hourly ring differs");
  CHECK(got.temp_count == saved.temp_count, "temp_count %u != %u",
        got.temp_count, saved.temp_count);
  CHECK(memcmp(got.temp, saved.temp, sizeof(got.temp)) == 0, "sparkline differs");
  CHECK(gotd.drift_ppm_hist[0] == -5265 && gotd.drift_ppm_count == 2, "drift block lost");
  CHECK(gotd.last_sync_time == T0, "last_sync_time lost");

  // ---- 3. records written after the base are replayed, not double-applied ----
  reboot();
  history_store_available();
  g_hist = saved;
  for (int i = 50; i < 60; i++)
    ring_push(T0 + i * 3600, (int16_t)(200 + i), (int16_t)(210 + i), (int16_t)(205 + i));
  RtcHistory saved2 = g_hist;
  reboot();
  CHECK(history_store_restore(&got, &gotd), "restore with journal tail");
  CHECK(got.hourly_count == saved2.hourly_count,
        "replayed hourly_count %u != %u (double-apply?)", got.hourly_count,
        saved2.hourly_count);
  CHECK(memcmp(got.hourly, saved2.hourly, sizeof(got.hourly)) == 0,
        "replayed ring differs from live ring");
  CHECK(got.hourly_latest_time == saved2.hourly_latest_time,
        "replayed anchor %lld != %lld", (long long)got.hourly_latest_time,
        (long long)saved2.hourly_latest_time);

  // ---- 4. base ping-pong: a second snapshot lands in the other slot ----
  uint32_t first_slot = s_base_off;
  reboot();
  history_store_available();
  g_hist = saved2;
  history_store_mark_base_dirty();
  history_store_flush(&g_hist, &g_drift, T0 + 60 * 3600);
  CHECK(s_base_off != first_slot, "second base reused slot 0x%x", (unsigned)first_slot);
  CHECK(s_base_seq == 2, "second base seq %u", (unsigned)s_base_seq);

  // ---- 5. the monotone guard refuses an emptier ring ----
  RtcHistory empty;
  memset(&empty, 0, sizeof(empty));
  empty.version = RTC_HISTORY_VERSION;
  uint32_t seq_before = s_base_seq;
  history_store_mark_base_dirty();
  history_store_flush(&empty, &g_drift, T0 + 61 * 3600);
  CHECK(s_base_seq == seq_before, "base write from an empty ring was allowed");
  reboot();
  CHECK(history_store_restore(&got, &gotd), "archive survives the refused write");
  CHECK(got.hourly_count == saved2.hourly_count, "archive damaged: %u != %u",
        got.hourly_count, saved2.hourly_count);

  // ---- 6. ring wrap: keep appending well past the journal size ----
  reboot();
  history_store_available();
  g_hist = saved2;
  size_t slots = s_jrn_size / HS_REC;
  size_t erases_before = g_erase_count;
  for (size_t i = 0; i < slots * 3; i++)
  {
    HourlyEntry we = { (int16_t)(i & 0x7F), 210, 205 };
    history_store_append_hourly(T0 + (time_t)i * 3600, &we);
    if ((i % 500) == 0)
    {
      // Rediscover the cursor from scratch, as a cold boot would.
      uint32_t seq = s_base_seq, hc = s_base_hourly, bc = s_base_cursor, bo = s_base_off;
      reboot();
      s_part = &g_part; s_ready = s_probed = true;
      s_jrn_size = FAKE_PART_SIZE - HS_JOURNAL_OFF;
      s_base_seq = seq; s_base_hourly = hc; s_base_cursor = bc; s_base_off = bo;
      CHECK(journal_locate(), "cursor lost after wrap at i=%zu", i);
      CHECK(s_cursor < s_jrn_size, "cursor 0x%x out of range at i=%zu",
            (unsigned)s_cursor, i);
    }
  }
  CHECK(g_erase_count > erases_before, "ring never erased a sector while wrapping");
  printf("wrap: %zu appends over %zu slots, %zu sector erases\n",
         slots * 3, slots, g_erase_count - erases_before);

  // ---- 7. a snapshot still works after wrapping, and restores ----
  history_store_mark_base_dirty();
  history_store_flush(&g_hist, &g_drift, T0 + 100 * 3600);
  reboot();
  CHECK(history_store_restore(&got, &gotd), "restore after wrap");
  CHECK(got.hourly_count == saved2.hourly_count, "post-wrap hourly %u != %u",
        got.hourly_count, saved2.hourly_count);

  // ---- 8. a base gets written without any NTP resync ever succeeding ----
  // Restore needs a base to anchor to, so appending alone must eventually
  // demand one; otherwise a device whose clock never syncs journals records it
  // could never restore.
  power_on(true);
  reset_hist();
  history_store_available();
  // store_init() asks for a base as soon as it finds none, so the sparkline
  // is persisted from the first sleep rather than the first hour boundary.
  CHECK(s_base_dirty, "a store with no base should request one at init");
  {
    HourlyEntry e = { 200, 210, 205 };
    history_store_append_hourly(T0, &e);
  }
  CHECK(s_base_dirty, "first append with no base must request one");
  g_hist.hourly_count = 1;
  history_store_flush(&g_hist, &g_drift, T0);
  CHECK(s_base_seq == 1, "base should exist after the first flush");
  // And again once a sector of records has gone by, so replay stays bounded.
  s_base_dirty = false;
  for (size_t i = 0; i < HS_SECTOR / HS_REC; i++)
  {
    HourlyEntry se = { 200, 210, 205 };
    history_store_append_hourly(T0 + (time_t)i * 3600, &se);
  }
  CHECK(s_base_dirty, "a sector of records must request a fresh base");

  // ---- 9. foreign content (old app image) is detected and formatted ----
  power_on(true);
  srand(1);
  for (auto &b : g_flash) b = (uint8_t)rand();
  reset_hist();
  CHECK(history_store_available(), "store should format over foreign content");
  CHECK(!history_store_restore(&got, &gotd), "nothing to restore after format");

  // ---- 10. a missing partition degrades instead of crashing ----
  g_have_part = false;
  reboot();
  CHECK(!history_store_available(), "should report unavailable with no partition");
  {
    HourlyEntry ne = { 200, 210, 205 };
    history_store_append_hourly(T0, &ne);   // must not crash
  }
  history_store_mark_base_dirty();
  history_store_flush(&g_hist, &g_drift, T0);
  g_have_part = true;

  // ---- optional: emit a full-size image to inject onto a real device ----
  // `--inject <file> <part-size> <mac-hex> <now-epoch>` writes an image that a
  // device will accept as its own, filled with MockData's 30-day profile — the
  // same data the simulator renders, so the on-screen result can be compared
  // against tools/mock_200x200.png. Beats waiting 30 days for a real chart.
  //
  // Built by the REAL store code, so the injected image cannot disagree with
  // what the firmware writes.
  if (argc > 5 && strcmp(argv[1], "--inject") == 0)
  {
    g_flash.assign((size_t)strtoul(argv[2], nullptr, 0), 0xFF);
    g_part.size = (uint32_t)g_flash.size();
    sscanf(argv[3], "%2hhx:%2hhx:%2hhx:%2hhx:%2hhx:%2hhx", &g_mac[0], &g_mac[1],
           &g_mac[2], &g_mac[3], &g_mac[4], &g_mac[5]);
    time_t now = (time_t)strtoll(argv[4], nullptr, 0);
    reboot();
    reset_hist();
    history_store_available();

    mock_fill_hourly(now, g_hist.hourly, &g_hist.hourly_count,
                     &g_hist.hourly_idx, &g_hist.hourly_latest_time);
    // argv[6] == "ramp" replaces the sparkline with a clean 10->30C diagonal at
    // a fixed 30min spacing. Nothing the room or MockData produces looks like
    // that, so seeing it on the 24h chart proves the flash path unambiguously.
    if (argc > 6 && strcmp(argv[6], "ramp") == 0)
    {
      g_hist.temp_count = 0;
      for (int i = 0; i < 48; i++)
        temp_history_record(g_hist.temp, &g_hist.temp_count,
                            now - (time_t)(47 - i) * 1800,
                            (int16_t)(100 + i * (300 - 100) / 47));
      printf("sparkline: 10.0-30.0C ramp, 48 points at 30min\n");
    }
    else
    {
      mock_fill_sparkline(now, g_hist.temp, &g_hist.temp_count);
    }
    // Journal the ring as well, so the archive (not just the base) is populated
    // and a restore exercises replay rather than only the snapshot.
    for (uint16_t k = 0; k < g_hist.hourly_count; k++)
    {
      uint16_t idx = (uint16_t)((g_hist.hourly_idx + HOURLY_HISTORY_SIZE - g_hist.hourly_count + k)
                                % HOURLY_HISTORY_SIZE);
      time_t hr = g_hist.hourly_latest_time -
                  (time_t)(g_hist.hourly_count - 1 - k) * 3600;
      history_store_append_hourly(hr, &g_hist.hourly[idx]);
    }
    // A self-consistent drift block: an interval the scheduler will accept,
    // and a ppm sample paired with the window it was measured over. Leaving
    // either unset is not harmless — a zero interval schedules a WiFi resync
    // on every wake, and a zero window makes the on-screen weighted mean
    // collapse to +0ppm.
    g_drift.resync_interval_s = 86400;
    g_drift.last_sync_time = now;
    g_drift.last_drift_ms = -9559000;
    g_drift.last_drift_window_s = 1814400;
    g_drift.drift_ppm_count = 1;
    g_drift.drift_ppm_hist[0] = -5265;
    g_drift.drift_win_min[0] = 1814400 / 60;
    history_store_mark_base_dirty();
    history_store_flush(&g_hist, &g_drift, now);

    FILE *f = fopen(argv[5], "wb");
    fwrite(g_flash.data(), 1, g_flash.size(), f);
    fclose(f);
    printf("injected image: %u hourly, %u sparkline, %zu bytes\n",
           g_hist.hourly_count, g_hist.temp_count, g_flash.size());
    return g_fail ? 1 : 0;
  }

  // ---- optional: emit an image for the Python decoder to cross-check ----
  if (argc > 1)
  {
    power_on(true);
    reset_hist();
    history_store_available();
    for (int i = 0; i < 40; i++)
      ring_push(T0 + i * 3600, (int16_t)(180 + i), (int16_t)(220 + i), (int16_t)(200 + i));
    for (int i = 0; i < 12; i++)
    {
      temp_history_record(g_hist.temp, &g_hist.temp_count, T0 + i * 900,
                          (int16_t)(195 + i));
    }
    g_drift.last_sync_time = T0;
    g_drift.drift_ppm_count = 1;
    g_drift.drift_ppm_hist[0] = -5265;
    history_store_mark_base_dirty();
    history_store_flush(&g_hist, &g_drift, T0 + 40 * 3600);
    HistoryDriftSample ds = {};
    ds.sync_time = T0 + 40 * 3600;
    ds.drift_ms = -9559000;
    ds.window_s = 1814400;
    ds.ppm = -5265;
    ds.ambient_mean_x10 = 213;
    ds.ambient_hours = 40;
    ds.boot_count = 847;
    ds.refresh_count = 203;
    history_store_append_drift(&ds);
    FILE *f = fopen(argv[1], "wb");
    fwrite(g_flash.data(), 1, g_flash.size(), f);
    fclose(f);
    printf("wrote sample image %s (%zu bytes)\n", argv[1], g_flash.size());
  }

  printf(g_fail ? "\n%d CHECK(s) FAILED\n" : "\nall checks passed (%d failures)\n",
         g_fail);
  return g_fail ? 1 : 0;
}
