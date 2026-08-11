#include "app_common.h"
#include "git_hash.h"

// needed for setenv and tzset :-/
#undef __STRICT_ANSI__
#include "time.h"
#include "stdlib.h"

#include "esp_sleep.h"
#include "esp_log.h"
#include "esp_system.h"  // esp_reset_reason
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include <math.h>
#include <string.h>
#ifdef CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH
#include "esp_core_dump.h"
#endif
#ifndef DISABLE_WIFI
#include "esp_wifi.h"
#include "esp_mac.h"   // esp_efuse_mac_get_default, for the DHCP hostname
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "freertos/event_groups.h"
#endif

#include "Display.h"
#include "TempHistory.h"
#include "RtcHistory.h"
#include "HistoryStore.h"

// Used for JTAG. Avoid for other purposes if possible
// Firebeetle Pin | JTAG PIN
//            12  |  TDI
//            13  |  TCK
//            14  |  TMS
//            15  |  TDO
// JTAG init and deep sleep don't seem to play well together
// openocd errors when trying to init JTAG during deep sleep:
//   Error: JTAG scan chain interrogation failed: all ones
//   Error: Check JTAG interface, timings, target power, etc.
//   Error: Trying to use configured scan chain anyway...
//   Error: esp32.cpu0: IR capture error; saw 0x1f not 0x01
// when that error is hit you might need to kill the openocd process even if debugging is stopped in VS code
// Repro cmd
// ~/.platformio/packages/tool-openocd-esp32/bin/openocd -s ~/.platformio/packages/tool-openocd-esp32 -c "gdb_port pipe; tcl_port disabled; telnet_port disabled" -s ~/.platformio/packages/tool-openocd-esp32/share/openocd/scripts -f interface/ftdi/esp32_devkitj_v1.cfg -f board/esp-wroom-32.cfg -c "adapter_khz 5000"

#if defined(USE_DS18B20_PAR)
  #include "sensors/DS18B20Sensor.hpp"
  DS18B20Sensor sensor;
#elif defined(USE_BMP390L)
  #include "sensors/BMP390LSensor.hpp"
  BMP390LSensor sensor;
#elif defined(USE_BMP58x)
  #include "sensors/BMP58xSensor.hpp"
  BMP58xSensor sensor;
#elif defined(USE_DUMMY_SENSOR)
  #include "sensors/DummySensor.hpp"
  DummySensor sensor;
#else
  #error "Unknown sensor type"
#endif

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
void ulp_check_data_overlap();
#endif

#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
#include "ulp_main.h"  // exposes ulp_lp_wake_count and other LP-core globals
#endif

// The wake cycle lives next to setup(), where the sequence reads in the order a
// boot performs it.
static void begin_wake_cycle(void);
static void run_wake_cycle(bool ulp_sample_available);
bool vbus_present();

#ifdef HAS_USB_SERVICE_WINDOW
#include "driver/usb_serial_jtag.h"  // usb_serial_jtag_is_connected()
static void usb_service_window(void);
#endif

// --- RTC memory layout ---
// RTC memory survives deep sleep but NOT power-on reset (firmware upload,
// battery swap, reset button). More precisely: the bootloader reloads
// .rtc.data and startup zeroes .rtc.bss on ANY reset that isn't a deep-sleep
// wake (esp_image_format.c / cpu_start.c) — so RTC_DATA_ATTR state, including
// boot_count and all history, does not survive a panic/WDT/brownout reset
// either. .rtc_noinit is exempt from both, which is what CrashLog (below)
// relies on; it dies only with the RTC power domain (battery swap, or the
// FireBeetle's reset button, whose circuit power-cycles RTC).
//
// The history itself outlives all of that: HistoryStore mirrors it to the
// `history` flash partition, which an upload does not touch. What lands here on
// a cold boot is a restore from flash, not an empty buffer.
//
// RtcHistory, RTC_HISTORY_VERSION and the self_addr scheme live in
// include/RtcHistory.h so HistoryStore.cpp can serialize the same layout.
// Bump RTC_STATE_VERSION when changing operational state variables below.
#define RTC_STATE_VERSION   0xDA050009

// Initial min/max temperature sentinels (float).
// Any real reading will replace these on first comparison.
#define TEMP_INIT_MIN  999.0f
#define TEMP_INIT_MAX (-999.0f)

// Minimum temperature change (C) to trigger a display refresh.
// Overridable so a bench build can decouple the refresh cadence from the room:
// set it past any real swing and REFRESH_EVERY_N_WAKES becomes the only
// temperature-independent repaint source.
#ifdef DISPLAY_TEMP_DELTA
// Already defined means a build override is in force. Flagged so the panel can
// say so: refresh cadence is the dominant term in the power budget, and a build
// that decouples it from the room renders identically to production.
#define DISPLAY_TEMP_DELTA_OVERRIDDEN 1
#else
#define DISPLAY_TEMP_DELTA 0.1f
#endif

RTC_DATA_ATTR RtcHistory historical_data;

// Operational state — changes here are caught by self_addr if the linker
// shifts historical_data, and by RTC_STATE_VERSION for format changes.
RTC_DATA_ATTR uint32_t rtc_state_version = 0;

RTC_DATA_ATTR int boot_count = 0;
RTC_DATA_ATTR int display_refresh_count = 0;

// InitializeUlp() calls this power cycle. Healthy value is exactly 1 (first
// boot); anything higher means ULP/LP state (wake counters, delta reference)
// is being wiped in the field — rendered as "uN" in the footer when > 1.
RTC_DATA_ATTR uint32_t ulp_reinit_count = 0;

// Wakeup cause, cached before anything can light-sleep: esp_sleep reports the
// cause of the MOST RECENT sleep, and the EPD busy-wait light sleep
// (epd_busy_light_sleep) replaces the deep-sleep cause with its GPIO wake.
// Querying live after a display refresh misread every refresh boot as a fresh
// boot and reloaded the LP core each time (wiping its counters and delta
// reference). Always use these, never app_wakeup_cause(), past setup() entry.
static esp_sleep_wakeup_cause_t s_wake_cause = ESP_SLEEP_WAKEUP_UNDEFINED;
static uint32_t s_wake_causes_raw = 0;

// --- Crash forensics -------------------------------------------------------
// Lives in .rtc_noinit: the only RTC storage that survives panic/WDT/brownout
// resets (see RTC memory layout comment above). Breadcrumbs (stage,
// cur_boot_count, cur_time) are stamped while running; the first boot after
// an abnormal reset copies them into the last_* fields and, when a flash
// coredump is present, harvests the exception PC + task name. Garbage after a
// true power-on — guarded by the magic word. Rendered by the "! <reason>"
// status indicator until the next RTC power cycle.
#define CRASH_LOG_MAGIC 0xC0DEB008  // bump when CrashLog layout changes
struct CrashLog {
  uint32_t magic;
  // Live breadcrumbs, stamped as the current wake progresses
  uint8_t  stage;            // CrashStage checkpoint (Display.h)
  uint8_t  unused0;
  uint16_t unused1;
  int32_t  cur_boot_count;
  uint32_t cur_time;         // epoch, stamped once wall clock is known
  // Harvested on the first boot after an abnormal reset
  uint8_t  crash_count;      // abnormal resets since RTC power-on
  uint8_t  last_reason;      // esp_reset_reason_t
  uint8_t  last_stage;
  uint8_t  unused2;
  int32_t  last_boot_count;
  uint32_t last_time;
  uint32_t pc;               // coredump exception PC (0 = none)
  char     task[16];         // coredump crashed task name
  char     elf_sha[9];       // first 8 hex chars of the crashing app's ELF
                             // SHA256 — identifies which build to addr2line
};
RTC_NOINIT_ATTR static CrashLog crash_log;

static const char *reset_reason_str(uint8_t r)
{
  switch (r)
  {
    case ESP_RST_SW:         return "SW";
    case ESP_RST_PANIC:      return "PANIC";
    case ESP_RST_INT_WDT:    return "IWDT";
    case ESP_RST_TASK_WDT:   return "TWDT";
    case ESP_RST_WDT:        return "WDT";
    case ESP_RST_BROWNOUT:   return "BROWN";
    case ESP_RST_EFUSE:      return "EFUSE";
    case ESP_RST_PWR_GLITCH: return "GLITCH";
    case ESP_RST_CPU_LOCKUP: return "LOCKUP";
    default:                 return "RST";
  }
}

// Copy PC + task name out of a flash coredump into crash_log, then erase the
// dump so a stale one is never re-harvested after a later dump-less reset
// (e.g. RTC WDT, where the panic handler never ran).
static void harvest_coredump_summary()
{
  crash_log.pc = 0;
  crash_log.task[0] = '\0';
  crash_log.elf_sha[0] = '\0';
#ifdef CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH
  esp_core_dump_summary_t *sum =
      (esp_core_dump_summary_t *)calloc(1, sizeof(*sum));
  if (sum == NULL)
    return;
  if (esp_core_dump_get_summary(sum) == ESP_OK)
  {
    crash_log.pc = sum->exc_pc;
    memcpy(crash_log.task, sum->exc_task, sizeof(crash_log.task));
    crash_log.task[sizeof(crash_log.task) - 1] = '\0';
    // Already a hex string in the summary; keep the first 8 chars
    size_t sha_n = strnlen((const char *)sum->app_elf_sha256,
                           sizeof(crash_log.elf_sha) - 1);
    memcpy(crash_log.elf_sha, sum->app_elf_sha256, sha_n);
    crash_log.elf_sha[sha_n] = '\0';
    esp_core_dump_image_erase();
  }
  free(sum);
#endif
}

// Detect and record an abnormal reset. Must run before RTC state is used in
// anger, but after setup_serial() so the LOGI is visible.
static void crash_forensics_on_boot()
{
  esp_reset_reason_t rr = esp_reset_reason();
  if (crash_log.magic != CRASH_LOG_MAGIC)
  {
    // True power-on (or first firmware with CrashLog): noinit RAM is garbage
    memset(&crash_log, 0, sizeof(crash_log));
    crash_log.magic = CRASH_LOG_MAGIC;
  }
  else if (rr != ESP_RST_DEEPSLEEP && rr != ESP_RST_POWERON &&
           rr != ESP_RST_USB && rr != ESP_RST_JTAG && rr != ESP_RST_SDIO)
  {
    // USB/JTAG/SDIO excluded: flash-tool resets, not field crashes
    if (crash_log.crash_count < 255)
      crash_log.crash_count++;
    crash_log.last_reason     = (uint8_t)rr;
    crash_log.last_stage      = crash_log.stage;
    crash_log.last_boot_count = crash_log.cur_boot_count;
    crash_log.last_time       = crash_log.cur_time;
    harvest_coredump_summary();
    LOGI("Abnormal reset #%u: %s at boot %d stage %d pc 0x%x %s",
         (unsigned)crash_log.crash_count, reset_reason_str(crash_log.last_reason),
         (int)crash_log.last_boot_count, (int)crash_log.last_stage,
         (unsigned)crash_log.pc, crash_log.task);
  }
  crash_log.stage = STAGE_BOOT;
}

RTC_DATA_ATTR time_t first_boot_time = 0;
RTC_DATA_ATTR time_t next_clear_time = 0;
const time_t one_day = 86400;

// The last temperature actually measured, and the reference the sensor drivers
// compare a suspicious coprocessor reading against (a jump past TEMP_REREAD_DELTA
// triggers a direct I2C re-read). They skip that check when it holds the sentinel,
// so this must never be blanked: doing so switches the verification off for
// exactly the wakes following a fault, which is when it is needed most.
RTC_DATA_ATTR float previous_temp = TEMP_NO_PREVIOUS;
// What the panel is showing, which is a different question — a rejected reading
// blanks it to "--.-" while previous_temp keeps the last real value — so the two
// cannot share one variable. Costs 4 bytes of the RTC area the ULP data segment
// sits above; the build prints the remaining headroom on every ESP32-E build.
RTC_DATA_ATTR bool panel_shows_reading = false;
RTC_DATA_ATTR int previous_boot_count = -1;
// While the panel is blanked nothing changes, so nothing redraws and the counters
// on screen freeze — leaving a wedged device indistinguishable from a quiet one.
// Repaint occasionally so the fault stays legible, counted in wakes because that
// is what the fault itself drives.
#define FAULT_REPAINT_WAKES 30

// Latched DisplayFault from the last refresh that ran. A panel that did not
// answer will not answer faster next wake, and each doomed attempt burns a full
// GxEPD2 busy timeout per wait (10s, 20s on the Z90) — so once this is set the
// refresh is skipped and epd_fault_blink() carries the news instead. Cleared by
// any reset that wipes RTC, which is what reseating a panel at the bench
// involves anyway; the retry below covers a panel that came back on its own.
RTC_DATA_ATTR uint8_t epd_fault = DISPLAY_FAULT_NONE;
#define EPD_FAULT_RETRY_WAKES 30

RTC_DATA_ATTR uint32_t max_battery_mv = 0;

RTC_DATA_ATTR uint32_t bad_pin27_count = 0;

// Min/max temperature since boot
RTC_DATA_ATTR float min_temp_since_boot = TEMP_INIT_MIN;
RTC_DATA_ATTR float max_temp_since_boot = TEMP_INIT_MAX;

// Bootstrap budget for the very first sync (see ntp_bootstrap_sync).
#define NTP_BOOTSTRAP_ASSOC_TRIES     3
#define NTP_BOOTSTRAP_SNTP_TRIES      3
#define NTP_BOOTSTRAP_SNTP_TIMEOUT_MS 10000U
// Wakes between bootstrap retries, doubling to 8x this on repeated failure.
#define NTP_BOOTSTRAP_FIRST_WAKES     8

// Minimum resync interval (1 day) — floor to avoid hammering WiFi.
// Overridable so a bench build can force attempts on a short cadence: measuring
// the charge of a resync (successful or timed out) otherwise means waiting a day
// for each sample. Never ship an override — see the revert list in CLAUDE.md.
#ifdef RESYNC_INTERVAL_MIN
// Already defined means a build override is in force. Flagged so the adaptive
// rule can be pinned (it would otherwise double the interval away from the
// cadence the override exists to create) and so the panel can say so.
#define RESYNC_INTERVAL_OVERRIDDEN 1
#else
#define RESYNC_INTERVAL_MIN  (86400)
#endif
// Maximum resync interval (4 weeks)
#define RESYNC_INTERVAL_MAX  (28 * 86400)

// Periodic NTP resync state
RTC_DATA_ATTR time_t next_resync_time = 0;           // when to next attempt NTP resync
// Starts at the floor: the first resync is the only measurement the device has
// for a fortnight otherwise, and a healthy clock climbs back out fast (each
// negligible-drift resync doubles the interval, so 1d → 28d in five wakes).
RTC_DATA_ATTR int32_t resync_interval_s = RESYNC_INTERVAL_MIN;
RTC_DATA_ATTR int32_t last_drift_ms = 0;             // drift measured at last resync (positive = clock ahead)
RTC_DATA_ATTR int32_t last_drift_window_s = 0;       // measured span the drift accumulated over (NOT the interval setting: failed attempts stretch it)
RTC_DATA_ATTR time_t last_sync_time = 0;             // wall-clock of last successful NTP sync (0 = never)
RTC_DATA_ATTR uint16_t resync_fail_count = 0;        // failed resync attempts since the last success
// Rate history, newest last. One measurement says how far the clock ran off;
// several say whether the RC oscillator's error is a stable constant (which is
// what drift compensation would need) or wanders with temperature.
RTC_DATA_ATTR int16_t drift_ppm_hist[DRIFT_PPM_HIST_SIZE] = {};
RTC_DATA_ATTR uint16_t drift_win_min[DRIFT_PPM_HIST_SIZE] = {};  // window per rate, for weighting
RTC_DATA_ATTR uint8_t drift_ppm_count = 0;

// Status flags for display error indicators
RTC_DATA_ATTR bool wifi_ok = false;
RTC_DATA_ATTR bool ntp_synced = false;
RTC_DATA_ATTR bool last_sensor_ok = true;

// Which configured network worked last, so a resync can go straight at it and
// skip the scan — 2501ms of radio at the IDF default dwell, measured on board 2
// (2026-08-09), against a ~300ms association. Deliberately not a BSSID or a
// channel: pinning either measured no faster than letting the driver find the
// SSID, and leaving them free lets it pick a better AP in a multi-AP network.
// A hint, not state: losing it to a panic or a reflash costs one extra scan,
// which is why it is not mirrored to the flash archive.
#define WIFI_NET_NONE 0xFF
RTC_DATA_ATTR uint8_t wifi_last_net = WIFI_NET_NONE;
// This wake only, so deliberately not RTC state: "the coprocessor handed up a
// reading we could not use". It is the sole trigger for the recovery reload
// below — every route to a coprocessor problem sets it, and a stale RTC flag in
// that condition would reload the program on wakes where nothing went wrong.
static bool s_ulp_read_failed = false;
// Also this boot only: the coprocessor program has been loaded, so the
// fresh-boot reload condition is satisfied and must not fire again. Only matters
// while the USB service window runs several cycles inside one boot — without it,
// a cold boot with a host attached would reload the program every cycle.
static bool s_lp_loaded_this_boot = false;

#ifdef HAS_USB_SERVICE_WINDOW
// Whether the USB flash-service window is currently holding the CPU awake, and
// whether the frame on the panel says so. Both this boot only: every reset that
// loses them also forces a first frame (previous_boot_count < 0), which repaints
// whatever is true then.
static bool s_usb_window_active = false;
static bool s_panel_has_usb_badge = false;
#endif

// Gather/scatter the drift block for the flash archive. Keeping it in one place
// means the on-flash layout (HistoryDriftState) and these RTC variables can
// only drift apart in one file.
static void drift_state_save(HistoryDriftState *d)
{
  d->resync_interval_s = resync_interval_s;
  d->last_drift_ms = last_drift_ms;
  d->last_drift_window_s = last_drift_window_s;
  d->last_sync_time = (int64_t)last_sync_time;
  d->resync_fail_count = resync_fail_count;
  d->drift_ppm_count = drift_ppm_count;
  d->rsvd = 0;
  memcpy(d->drift_ppm_hist, drift_ppm_hist, sizeof(drift_ppm_hist));
  memcpy(d->drift_win_min, drift_win_min, sizeof(drift_win_min));
  // Zero first: snprintf leaves the bytes past the terminator untouched, and
  // this struct is persisted.
  memset(d->git_hash, 0, sizeof(d->git_hash));
  snprintf(d->git_hash, sizeof(d->git_hash), "%s", GIT_HASH);
}

// `trust_clock` gates only last_sync_time: it is the reference maybe_ntp_resync()
// measures the next drift window against, so restoring it under a clock that
// has not been set yet would produce a nonsense window on the first resync
// after a power-cycle. The rates themselves are timeless and always restored.
static void drift_state_load(const HistoryDriftState *d, bool trust_clock)
{
  // Everything here is sanitized, not trusted. Flash content can be stale,
  // truncated, or injected by tools/history.py, and this block feeds the WiFi
  // scheduler — an out-of-range interval is a battery problem, not a cosmetic
  // one. A restored resync_interval_s of 0 would make next_resync_time land on
  // `now`, so every subsequent wake would bring up WiFi (1.5-4.5C per failed
  // attempt, docs/clock-drift.md).
  resync_interval_s = d->resync_interval_s;
  if (resync_interval_s < RESYNC_INTERVAL_MIN) resync_interval_s = RESYNC_INTERVAL_MIN;
  if (resync_interval_s > RESYNC_INTERVAL_MAX) resync_interval_s = RESYNC_INTERVAL_MAX;

  last_drift_ms = d->last_drift_ms;
  last_drift_window_s = d->last_drift_window_s;
  resync_fail_count = d->resync_fail_count;

  // Keep only samples with a real measurement window. maybe_ntp_resync() never
  // records one below DRIFT_MIN_WINDOW_S, so a zero window means corrupt or
  // synthetic data; it contributes nothing to the window-weighted mean but
  // would still inflate the "nN" sample count on screen.
  drift_ppm_count = 0;
  memset(drift_ppm_hist, 0, sizeof(drift_ppm_hist));
  memset(drift_win_min, 0, sizeof(drift_win_min));
  uint8_t n = d->drift_ppm_count;
  if (n > DRIFT_PPM_HIST_SIZE) n = DRIFT_PPM_HIST_SIZE;
  for (uint8_t i = 0; i < n; i++)
  {
    if (d->drift_win_min[i] == 0) continue;
    drift_win_min[drift_ppm_count] = d->drift_win_min[i];
    drift_ppm_hist[drift_ppm_count++] = d->drift_ppm_hist[i];
  }

  if (trust_clock)
    last_sync_time = (time_t)d->last_sync_time;
}

// Longest gap still attributed to a missed safety-net wake rather than to the
// device being off. The safety net fires hourly, so this allows exactly one
// miss; beyond it, skipped hours are marked HOURLY_NO_DATA instead of repeating
// the last reading.
#define HOURLY_REPEAT_FILL_MAX 2

// Write one finalized entry into the ring and mirror it to the flash archive.
// Every ring write goes through here so the two can never diverge.
static void hourly_append(time_t hour_start, const HourlyEntry &entry)
{
  historical_data.hourly[historical_data.hourly_idx] = entry;
  historical_data.hourly_idx = (historical_data.hourly_idx + 1) % HOURLY_HISTORY_SIZE;
  if (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
    historical_data.hourly_count++;
  history_store_append_hourly(hour_start, &entry);
}

// Update the hourly history buffer with a new temperature reading.
// Called on every main CPU wake (both delta-triggered and safety-net timer).
// When the clock hour changes, the accumulated entry is finalized and appended
// to the circular buffer. Any skipped hours (shouldn't happen normally since
// the safety net wakes every hour) are filled with sentinel entries.
// Called on every wake, including those whose reading was rejected: has_reading
// false still advances the hour bookkeeping, it only skips the accumulation. If
// it were skipped entirely the hour anchor would freeze for the whole outage,
// and the eventual recovery would look like one long gap to the fill logic below
// — which would repeat the last good hour across hours that measured nothing.
static void update_hourly_history(time_t now, const struct tm *nowtm, float temp,
                                  bool has_reading)
{
  // Nothing here is meaningful without a wall clock: entries are filed by clock
  // hour, and a 1970 timestamp would file them ~54 years before everything
  // already stored. Recording nothing (and letting the `! NOSYNC` badge explain
  // the stall) beats recording lies — before this guard an unsynced device
  // wrote 1970-stamped entries, and the eventual forward step filled the whole
  // ring with one repeated value.
  if (!time_is_plausible(now))
    return;

  // Compute wall-clock start-of-hour for current local time
  struct tm hour_tm = *nowtm;
  hour_tm.tm_min = 0;
  hour_tm.tm_sec = 0;
  time_t hour_start = mktime(&hour_tm);

  // Finalize only when the clock has moved into a genuinely later hour than
  // anything already stored. An NTP resync correcting a slow RTC steps the
  // clock BACKWARDS (−9559s on the ESP32-E, docs/clock-drift.md): the negative
  // hours_elapsed below already skips the fill, but a plain "hour changed"
  // test would still advance hourly_idx while moving hourly_latest_time
  // backwards, permanently offsetting the index→time mapping in Display.h that
  // every later entry inherits. Re-lived hours therefore keep accumulating
  // into the current entry and produce exactly one entry once the clock passes
  // the newest stored hour again — no duplicate, no gap.
  bool hour_advanced = historical_data.current_hour_start != 0 &&
                       hour_start > historical_data.current_hour_start;
  bool extends_history = (hour_start - 3600) > historical_data.hourly_latest_time;
  if (hour_advanced && extends_history)
  {
    // Clock hour changed — finalize the completed hour's entry. An hour that
    // accepted no readings is recorded as measured-nothing rather than with the
    // accumulator's init values, which are sentinels, not temperatures.
    HourlyEntry entry;
    if (historical_data.current_hour_sample_count > 0)
    {
      entry.min_x10 = historical_data.current_hour_min_x10;
      entry.max_x10 = historical_data.current_hour_max_x10;
      entry.avg_x10 = (int16_t)(historical_data.current_hour_sum_x10 /
                                historical_data.current_hour_sample_count);
    }
    else
    {
      entry.min_x10 = entry.max_x10 = entry.avg_x10 = HOURLY_NO_DATA;
    }

    hourly_append(historical_data.current_hour_start, entry);

    // Fill any skipped hours.
    // Uses time_t difference (UTC-based) so DST transitions are handled
    // correctly — a "spring forward" skip produces one fill, a "fall back"
    // repeat produces hours_elapsed=0 (no fill needed).
    int hours_elapsed = (int)((hour_start - historical_data.current_hour_start) / 3600);
    if (hours_elapsed > HOURLY_HISTORY_SIZE)
      hours_elapsed = HOURLY_HISTORY_SIZE;

    // A short gap means the ULP safety-net woke but no delta was detected, so
    // temperature was stable and the last known value is the best estimate. A
    // long one means the device was not running at all — a battery swap, a
    // reflash, or a restore from flash — and repeating the last value there
    // would draw a flat line across days the device never measured. The safety
    // net fires hourly, so anything past one missed wake is the second case.
    HourlyEntry gap = entry;
    if (hours_elapsed > HOURLY_REPEAT_FILL_MAX)
      gap.min_x10 = gap.max_x10 = gap.avg_x10 = HOURLY_NO_DATA;

    for (int i = 1; i < hours_elapsed; i++)
      hourly_append(historical_data.current_hour_start + (time_t)i * 3600, gap);

    // Update reference time: the last written entry's start-of-hour
    historical_data.hourly_latest_time = hour_start - 3600;

    // Reset accumulator for the new hour
    historical_data.current_hour_sum_x10 = 0;
    historical_data.current_hour_sample_count = 0;
    historical_data.current_hour_min_x10 = TEMP_INIT_MIN_X10;
    historical_data.current_hour_max_x10 = TEMP_INIT_MAX_X10;
  }

  // First reading after boot.
  if (historical_data.current_hour_start == 0)
  {
    if (historical_data.hourly_count == 0)
    {
      // Nothing stored. The anchor names the newest *finalized* entry and there
      // are none yet, so it sits one hour before the in-progress hour; the first
      // finalize then lands on the boot hour and extends_history is satisfied.
      historical_data.hourly_latest_time = hour_start - 3600;
    }
    else if (hour_start > historical_data.hourly_latest_time + 3600)
    {
      // History came back from flash. hourly_latest_time dates the ENTIRE ring —
      // Display.h derives every entry's hour by counting back from it — so
      // overwriting it with this boot's hour would silently re-date 30 days of
      // archived readings and land the derived daily columns on the wrong days.
      // Keep it, and mark the hours the device was off. The finalize path above
      // cannot do this: by the time it next runs, current_hour_start is only one
      // hour back, so hours_elapsed is 1 and no fill happens.
      int gap = (int)((hour_start - historical_data.hourly_latest_time) / 3600) - 1;
      if (gap > HOURLY_HISTORY_SIZE)
        gap = HOURLY_HISTORY_SIZE;
      // Counting back from hour_start rather than forward from the anchor keeps
      // the newest fill adjacent to the in-progress hour even when the outage
      // outran the ring, which is what the anchor must name.
      HourlyEntry nodata = { HOURLY_NO_DATA, HOURLY_NO_DATA, HOURLY_NO_DATA };
      for (int i = gap; i >= 1; i--)
        hourly_append(hour_start - (time_t)i * 3600, nodata);
      historical_data.hourly_latest_time = hour_start - 3600;
    }
    // Otherwise the clock has not passed the newest stored hour (a restored
    // future-dated archive, or drift): leave the anchor alone and let the
    // extends_history guard absorb the re-lived hours.
  }

  historical_data.current_hour_start = hour_start;

  if (!has_reading)
    return;

  // Accumulate reading into current hour's stats
  int16_t temp_x10 = (int16_t)(temp * 10);
  historical_data.current_hour_sample_count++;
  historical_data.current_hour_sum_x10 += temp_x10;
  if (temp_x10 < historical_data.current_hour_min_x10)
    historical_data.current_hour_min_x10 = temp_x10;
  if (temp_x10 > historical_data.current_hour_max_x10)
    historical_data.current_hour_max_x10 = temp_x10;
}

static void update_temp_extremes(float temp)
{
  if (temp < min_temp_since_boot)
    min_temp_since_boot = temp;
  if (temp > max_temp_since_boot)
    max_temp_since_boot = temp;
}

// Do any deferred flash work now. Every path into deep sleep goes through here
// — the normal one and the permanent shutdown — so the two can't diverge.
// Appends already happened inline (a page program is ~0.04mC); this is the
// ~4.5mC base snapshot, and it only fires when marked dirty.
//
// Deliberately a single point so it is trivial to isolate on a PPK2 trace: it
// is the last thing in the active phase, right before PPK2_CPU_ACTIVE_LOW().
// Build with -DHISTORY_BASE_EVERY_WAKE to force one per wake and measure the
// delta against a normal wake.
//
// That flag is for a capture, not for a session. Normally the snapshot rate is
// wall-clock-bound — roughly one a day, alternating between the two base slots,
// so the partition outlives the product. Forced per wake it becomes rate-bound
// instead: parked in the USB service window at a 5s interval that is ~8,600
// erases per slot per day, and at the usual 100k-cycle NOR figure a base slot is
// spent in under a fortnight of continuous running. Derived, not measured, and
// the flash part is not identified anywhere in this repo — but the margin is
// four orders of magnitude smaller than normal operation, so treat it as real.
// Flash it, take the trace, flash it back out.
static void history_store_persist_now()
{
  HistoryDriftState drift;
  drift_state_save(&drift);
  time_t now;
  time(&now);
#ifdef HISTORY_BASE_EVERY_WAKE
  history_store_mark_base_dirty();
#endif
  // Reuses the display marker (D11/GPIO16 → PPK2 D1): rendering is finished by
  // the time this runs, so the two can never overlap in a trace, and the flash
  // write gets a crisp bracket instead of being an unlabelled plateau at the
  // tail of the active phase.
  //
  // Three 50ms pulses first, as a signature. The pin is not held across deep
  // sleep (no gpio_hold_en), so it floats while asleep and its idle level on a
  // PPK2 input is whatever the input does — which makes a lone edge ambiguous
  // to read. A triple blip immediately before the write is unmistakable at any
  // polarity, and the flash write is the excursion right after it.
  //
  // 50ms, not 2ms: at the 3s window needed to see a whole wake, 2ms pulses are
  // ~1px each and invisible. 300ms of preamble is ~10% of that width, so it can
  // be found zoomed out and then zoomed into.
  //
  // The #ifdef is load-bearing, not decoration: PPK2_DISPLAY_HIGH/LOW compile to
  // nothing without PPK2_DEBUG but sleep_ms() does not, so leaving the loop
  // unguarded put 300ms of awake time on EVERY wake of a normal build — ~0.6C/day
  // against a ~7.1C/day budget, and silently, since the markers it existed to
  // emit were no-ops.
#ifdef PPK2_DEBUG
  for (int i = 0; i < 3; i++)
  {
    PPK2_DISPLAY_HIGH();
    sleep_ms(50);
    PPK2_DISPLAY_LOW();
    sleep_ms(50);
  }
#endif
  PPK2_DISPLAY_HIGH();
  history_store_flush(&historical_data, &drift, now);
  PPK2_DISPLAY_LOW();
}

// Mean of the hourly averages over the last `window_s`, for the drift record's
// temperature correlate — docs/clock-drift.md wants to know whether the RC
// oscillator's rate tracks ambient. Reports how many hours actually contributed
// so a window longer than the ring's 30-day reach shows up as clipped rather
// than as a quietly shorter average.
static int16_t window_mean_ambient_x10(int32_t window_s, uint16_t *hours_out)
{
  int32_t want = window_s / 3600;
  if (want < 1) want = 1;
  if (want > (int32_t)historical_data.hourly_count)
    want = historical_data.hourly_count;

  int32_t sum = 0;
  uint16_t n = 0;
  for (int32_t i = 0; i < want; i++)
  {
    int idx = (int)historical_data.hourly_idx - 1 - (int)i;
    while (idx < 0) idx += HOURLY_HISTORY_SIZE;
    const HourlyEntry &e = historical_data.hourly[idx];
    if (e.min_x10 == HOURLY_NO_DATA) continue;  // device was off for that hour
    sum += e.avg_x10;
    n++;
  }
  *hours_out = n;
  return n ? (int16_t)(sum / n) : (int16_t)HOURLY_NO_DATA;
}

#ifdef MOCK_DISPLAY_DATA
#include "MockData.h"

static void fill_mock_data(time_t now)
{
  mock_fill_sparkline(now, historical_data.temp, &historical_data.temp_count);
  mock_fill_hourly(now, historical_data.hourly, &historical_data.hourly_count, &historical_data.hourly_idx,
                   &historical_data.hourly_latest_time);

  min_temp_since_boot = 18.5f;
  max_temp_since_boot = 22.8f;
  previous_temp = 22.1f;

  // Set up in-progress hour accumulator with mock values
  struct tm now_tm;
  localtime_r(&now, &now_tm);
  now_tm.tm_min = 0;
  now_tm.tm_sec = 0;
  historical_data.current_hour_start = mktime(&now_tm);
  historical_data.current_hour_sample_count = 3;
  historical_data.current_hour_sum_x10 = 223 * 3;  // 22.3°C × 3 readings
  historical_data.current_hour_min_x10 = 219;      // 21.9°C
  historical_data.current_hour_max_x10 = 228;      // 22.8°C
}
#endif

DisplayStats make_display_stats()
{
  // Compute circular buffer start index (oldest entry)
  uint16_t hourly_start = (historical_data.hourly_count < HOURLY_HISTORY_SIZE)
    ? 0
    : historical_data.hourly_idx;

  // Map ESP-IDF wake cause to a portable int for display
  int wake = (s_wake_cause == ESP_SLEEP_WAKEUP_ULP) ? 1 :
             (s_wake_cause == ESP_SLEEP_WAKEUP_TIMER) ? 2 :
             (s_wake_cause == ESP_SLEEP_WAKEUP_GPIO) ? 3 : 0;

  // Compute in-progress hour entry from accumulator
  bool has_current = (historical_data.current_hour_sample_count > 0);
  HourlyEntry current_entry = {};
  if (has_current)
  {
    current_entry.min_x10 = historical_data.current_hour_min_x10;
    current_entry.max_x10 = historical_data.current_hour_max_x10;
    current_entry.avg_x10 = (int16_t)(historical_data.current_hour_sum_x10 / historical_data.current_hour_sample_count);
  }

  uint32_t lp_wakes = 0;
  uint32_t lp_errors = 0;
  int32_t  lp_last_err = 0;
  uint32_t lp_last_op = 0;
#if defined(HAS_ULP_SUPPORT) && defined(SOC_LP_CORE_SUPPORTED) && SOC_LP_CORE_SUPPORTED
  // These counters live in the LP core's .bss, which ulp_lp_core_load_binary()
  // zeroes along with the rest of the reserve region — InitializeUlp() carries
  // them across a reload by hand. On a cold boot that runs *after* this render,
  // so the symbols still hold uninitialised SRAM — leave the stats at 0 until an
  // LP/timer wake proves the LP core has run this power cycle. Avoids a phantom
  // "! LP" indicator on the first frame.
  if (wake != 0)
  {
    lp_wakes    = ulp_lp_wake_count;
    lp_errors   = ulp_lp_error_count;
    lp_last_err = (int32_t)ulp_last_lp_error;
    lp_last_op  = ulp_last_lp_op;
  }
#endif

  // Sequenced before the aggregate below: history_store_fault() is what sets
  // the format the next field reads back. List-initialization does evaluate
  // left to right, but nothing about the two calls says they are ordered.
  const uint8_t archive_fault = history_store_fault();

  DisplayStats s = {
    boot_count, previous_boot_count, display_refresh_count,
    lp_wakes, lp_errors, lp_last_err, lp_last_op,
    first_boot_time, next_clear_time, max_battery_mv, bad_pin27_count,
    sensor.SupportsUlp(), wake, wifi_ok, ntp_synced, last_sensor_ok,
#ifdef USE_DUMMY_SENSOR
    true,
#else
    false,
#endif
#ifdef MOCK_DISPLAY_DATA
    true,
#else
    false,
#endif
    // power_efficient: true only when serial is off, sleep interval is
    // production-length, and no debug instrumentation. Overrides that move a
    // large power term count, because without them here the panel renders
    // identically to production — so a photo or a harvested capture could not
    // tell the two apart. A resync override can spend 1.5-4.5 C per attempt on
    // a minutes-long cadence; the refresh-cadence pair is larger still, since a
    // refresh is the dominant event on a typical day.
#if defined(DISABLE_SERIAL) && SLEEP_INTERVAL_S >= 60 && !defined(PPK2_DEBUG) \
    && !defined(RESYNC_INTERVAL_OVERRIDDEN) \
    && !defined(REFRESH_EVERY_N_WAKES) && !defined(DISPLAY_TEMP_DELTA_OVERRIDDEN)
    true,
#else
    false,
#endif
#ifdef PPK2_DEBUG
    true,
#else
    false,
#endif
#ifdef RESYNC_INTERVAL_OVERRIDDEN
    true,
#else
    false,
#endif
#if defined(REFRESH_EVERY_N_WAKES) || defined(DISPLAY_TEMP_DELTA_OVERRIDDEN)
    true,
#else
    false,
#endif
    EXPERIMENT_ARM,  // 0 in a field build; nonzero raises the ! EXP badge
#ifdef HAS_USB_SERVICE_WINDOW
    s_usb_window_active,
#else
    false,
#endif
    last_drift_ms, last_drift_window_s, last_sync_time, resync_fail_count,
    archive_fault, history_store_flash_format(),
    drift_ppm_hist, drift_win_min, drift_ppm_count,
    previous_temp, min_temp_since_boot, max_temp_since_boot,
    historical_data.temp, historical_data.temp_count,
    historical_data.hourly, historical_data.hourly_count, hourly_start,
    historical_data.hourly_latest_time, current_entry, has_current,
    ulp_reinit_count, s_wake_causes_raw,
    0, 0, "", 0, 0, 0, "", ""  // crash fields, assigned below
  };
  s.crash_count = crash_log.crash_count;
  s.crash_stage = crash_log.last_stage;
  snprintf(s.crash_reason, sizeof(s.crash_reason), "%s",
           reset_reason_str(crash_log.last_reason));
  s.crash_boot_count = crash_log.last_boot_count;
  s.crash_time = crash_log.last_time;
  s.crash_pc = crash_log.pc;
  memcpy(s.crash_task, crash_log.task, sizeof(s.crash_task));
  memcpy(s.crash_elf_sha, crash_log.elf_sha, sizeof(s.crash_elf_sha));
  return s;
}

void setup_serial()
{
#ifndef DISABLE_SERIAL
  // The IDF console (UART on the FireBeetle, USB-Serial-JTAG on the C6, per
  // sdkconfig) is ready before app_main — nothing to set up.
  LOGI("Logging to log facilities - info");
#else
  // TODO: update our own logging levels when using JTAG debugging
  esp_log_level_set("*", ESP_LOG_ERROR);
#endif
}

void start_deep_sleep()
{
  history_store_persist_now();

#ifdef HAS_USB_SERVICE_WINDOW
  // After the archive is safe, so losing power inside the window costs nothing
  // already earned, and before PPK2_CPU_ACTIVE_LOW() below, so time spent held
  // awake reads as awake time on a power trace instead of a raised sleep floor.
  usb_service_window();
#endif

  if (sensor.SupportsUlp())
  {
    // ULP is polling the sensor — it will wake us when temperature changes
    esp_sleep_enable_ulp_wakeup();
    // Timer safety net for periodic housekeeping (display clear, battery check)
    uint64_t safety_net_us = ULP_SAFETY_NET_US;
#ifdef HAS_USB_SERVICE_WINDOW
    // Sleeping with the cable in means no window opened: a charger, a host that
    // went away, or an observe cycle. The bus can come back with VBUS never
    // transitioning — replugging into a different port, or the host resuming —
    // and the level wake armed below cannot fire against a level already high,
    // so looking again is the only way back. An hour is the wrong "soon": it is
    // how long the port would stay missing, and USB_WINDOW_OBSERVE_CYCLES=2
    // would put a bench reflash two hours out. Costs nothing but wakes, and
    // those are on USB power by definition.
    if (vbus_present())
      safety_net_us = (uint64_t)SLEEP_INTERVAL_S * 1000000ULL;
#endif
    esp_sleep_enable_timer_wakeup(safety_net_us);
    LOGI("Sleeping with ULP wakeup (timer safety net: %d s)", (int)(safety_net_us / 1000000ULL));
  }
  else
  {
    esp_sleep_enable_timer_wakeup((uint64_t)SLEEP_INTERVAL_S * 1000000ULL);
    LOGI("Sleeping for %d seconds", SLEEP_INTERVAL_S);
  }
#ifdef HAS_USB_SERVICE_WINDOW
  // Wake the instant USB is plugged in, so a reflash never has to wait out a
  // sleep interval. Only meaningful while VBUS reads low — a wake-on-high armed
  // against a level that is already high fires immediately and forever. The
  // cable-already-in case is covered by the shortened safety net above instead.
  if (!vbus_present())
    app_enable_gpio_high_wakeup(VBUS_SENSE_GPIO);
#endif
  fflush(stdout);
  PPK2_CPU_ACTIVE_LOW();
  crash_log.stage = STAGE_SLEEP;
  esp_deep_sleep_start();
}

void get_time(time_t *now, struct tm *nowtm)
{
  setenv("TZ", MY_TZ, 1);
  tzset();
  time(now);
  localtime_r(now, nowtm);
}

#ifndef DISABLE_WIFI
// Connect to WiFi with timeout. Returns true on success.
//
// Two tiers, because a scan is expensive and an association is not (measured on
// board 2, 2026-08-09): a scan is 2501ms of radio at the IDF default dwell,
// while associating to a named SSID is ~300ms whether or not the channel and
// BSSID are pinned. So the cheap path is not a cleverer association — it is not
// scanning at all. wifi_last_net remembers which network worked, and only a
// miss pays for a scan.
//
// What this must never become is a loop over the credential list: each failed
// association is a full WIFI_TIMEOUT_MS of radio (~1.5C, docs/notes.md), so N
// networks tried blindly is N times that. The scan exists to make sure exactly
// one association is attempted.
static const uint32_t WIFI_TIMEOUT_MS = 15000;
// A hint that no longer holds should cost little before falling through to the
// scan. Generous against a measured ~300ms association + ~3-4s DHCP.
static const uint32_t WIFI_HINT_TIMEOUT_MS = 8000;
// Enough for a dense band: 14 APs was the busiest scan seen on the bench. The
// driver reports how many it found regardless, so an overflow is visible in the
// log rather than silent.
#define WIFI_SCAN_MAX_AP 32

struct WifiNetwork { const char *ssid; const char *pass; };
#define WIFI_NET_ENTRY(s, p) { s, p },
static const WifiNetwork s_wifi_networks[] = { MY_WIFI_NETWORKS(WIFI_NET_ENTRY) };
#undef WIFI_NET_ENTRY
static const uint8_t s_wifi_net_count =
    (uint8_t)(sizeof(s_wifi_networks) / sizeof(s_wifi_networks[0]));

// An entry with an empty SSID is a placeholder, not a network — that is how
// local-secrets-example.h ships, and how "no WiFi here" is expressed.
static bool wifi_is_configured()
{
  for (uint8_t i = 0; i < s_wifi_net_count; i++)
    if (s_wifi_networks[i].ssid[0])
      return true;
  return false;
}

static EventGroupHandle_t s_wifi_events;
static esp_event_handler_instance_t s_wifi_handler, s_ip_handler;
static volatile bool s_wifi_stopping = false;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAILED_BIT    BIT1

// Why the disconnect happened, so the caller can tell "that AP is not here"
// from "those credentials are wrong" — retrying the second burns radio and can
// never succeed.
static volatile int s_wifi_reason;

// Was any configured network demonstrably present during this attempt — either
// associated with, or seen in the scan? It separates "out of range" from "in
// range but the link failed", and those want opposite retry policies: the first
// should become rare, the second must keep trying. Per-wake, not RTC state: it
// is evidence about now, not history.
static bool s_wifi_net_seen;

static bool wifi_reason_is_terminal(int reason)
{
  switch (reason)
  {
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_NO_AP_FOUND:
    case WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY:
    case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
    case WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD:
      return true;
    default:
      return false;  // transient: worth the retry the caller's budget allows
  }
}

// No esp_wifi_connect() on STA_START: nothing is configured yet at that point,
// and a station that is connecting makes esp_wifi_scan_start() return
// ESP_ERR_WIFI_STATE, which would break the scan tier outright.
static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED)
  {
    s_wifi_reason = ((wifi_event_sta_disconnected_t *)data)->reason;
    if (!s_wifi_stopping)
      xEventGroupSetBits(s_wifi_events, WIFI_FAILED_BIT);
  }
  else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP)
    xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
}

// Radio fully off before deep sleep (matches former WiFi.disconnect(true, true)).
// Handlers unregister before deinit and the stopping flag stays set throughout,
// so a late STA_DISCONNECTED can't call esp_wifi_connect() on a dead driver.
static void wifi_disconnect()
{
  s_wifi_stopping = true;
  esp_wifi_stop();
  if (s_wifi_handler)
  {
    esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, s_wifi_handler);
    s_wifi_handler = nullptr;
  }
  if (s_ip_handler)
  {
    esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, s_ip_handler);
    s_ip_handler = nullptr;
  }
  esp_wifi_deinit();
  s_wifi_stopping = false;
}

// Bring the driver up without choosing a network: the credential goes in later,
// once a tier has decided which one.
static bool wifi_driver_start()
{
  esp_err_t err = nvs_flash_init(); // esp_wifi_init() requires NVS
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
  {
    nvs_flash_erase();
    err = nvs_flash_init();
  }
  if (err != ESP_OK)
  {
    LOGI("NVS init failed: 0x%x", err);
    return false;
  }

  // Degrade to "NO WIFI" on any init failure (the Arduino path never aborted);
  // a panic here would boot-loop a battery device instead of rendering a frame.
#define WIFI_TRY(x)                                        \
  do {                                                     \
    esp_err_t _e = (x);                                    \
    if (_e != ESP_OK)                                      \
    {                                                      \
      LOGI("WiFi setup failed (%s): " #x, esp_err_to_name(_e)); \
      wifi_disconnect();                                   \
      return false;                                        \
    }                                                      \
  } while (0)

  WIFI_TRY(esp_netif_init());
  err = esp_event_loop_create_default();
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) // INVALID_STATE = already created
  {
    LOGI("Event loop creation failed: 0x%x", err);
    return false;
  }
  static esp_netif_t *sta_netif = nullptr;
  if (!sta_netif)
    sta_netif = esp_netif_create_default_wifi_sta();
  if (sta_netif)
  {
    // Every ESP-IDF device ships DHCP hostname "espressif"
    // (CONFIG_LWIP_LOCAL_HOSTNAME), so a household with several becomes
    // espressif, espressif1, espressif2... in the router's device list and no
    // row identifies anything. The MAC is the one identifier that is per-board,
    // needs no configuration, and survives a rig change or a reflash.
    // Set before the DHCP client starts, which is at association.
    static char hostname[32];
    uint8_t mac[6] = {};
    // The STA MAC, not esp_efuse_mac_get_default(): the latter returns the
    // EUI-64 base whose last three bytes are the ff:fe padding plus one shared
    // OUI byte, so every board here would answer to the same name — measured,
    // it produced "thermometer-c6-fffe75" on a board whose STA MAC ends 75:48:10.
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(hostname, sizeof(hostname), "%s-%02x%02x%02x",
             history_store_board_name(), mac[3], mac[4], mac[5]);
    // Underscores are legal in the archive header but not in a hostname
    // (RFC 1123 allows letters, digits and hyphens), and resolvers differ on
    // how forgiving they are.
    for (char *p = hostname; *p; p++)
      if (*p == '_') *p = '-';
    esp_netif_set_hostname(sta_netif, hostname);
    LOGI("WiFi: DHCP hostname %s", hostname);
  }
  if (!sta_netif)
  {
    LOGI("WiFi setup failed: no STA netif");
    return false;
  }

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  WIFI_TRY(esp_wifi_init(&cfg));

  if (!s_wifi_events)
    s_wifi_events = xEventGroupCreate();
  xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
  WIFI_TRY(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                               &wifi_event_handler, nullptr, &s_wifi_handler));
  WIFI_TRY(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                               &wifi_event_handler, nullptr, &s_ip_handler));

  WIFI_TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM)); // reconfigured every boot; skip NVS writes
  WIFI_TRY(esp_wifi_set_mode(WIFI_MODE_STA));
  WIFI_TRY(esp_wifi_start());
#undef WIFI_TRY
  return true;
}

// One network, to GOT_IP. Leaves the station idle on failure, so a scan can
// follow — esp_wifi_scan_start() refuses while the station is connecting.
static bool wifi_try_net(uint8_t idx, uint32_t timeout_ms)
{
  const WifiNetwork &net = s_wifi_networks[idx];
  wifi_config_t wcfg = {};
  strncpy((char *)wcfg.sta.ssid, net.ssid, sizeof(wcfg.sta.ssid) - 1);
  strncpy((char *)wcfg.sta.password, net.pass, sizeof(wcfg.sta.password) - 1);
  if (esp_wifi_set_config(WIFI_IF_STA, &wcfg) != ESP_OK)
    return false;

  const uint32_t deadline = ms_now() + timeout_ms;
  for (;;)
  {
    xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT | WIFI_FAILED_BIT);
    s_wifi_reason = 0;
    esp_wifi_connect();  // attempts once; retrying is on us (esp_wifi.h)

    const uint32_t now = ms_now();
    const uint32_t left = (now < deadline) ? (deadline - now) : 0;
    EventBits_t bits = xEventGroupWaitBits(s_wifi_events,
                                           WIFI_CONNECTED_BIT | WIFI_FAILED_BIT,
                                           pdFALSE, pdFALSE, pdMS_TO_TICKS(left));
    if (bits & WIFI_CONNECTED_BIT)
    {
      wifi_last_net = idx;
      s_wifi_net_seen = true;
      LOGI("WiFi: connected to '%s'", net.ssid);
      return true;
    }
    if (!(bits & WIFI_FAILED_BIT))
    {
      LOGI("WiFi: '%s' timed out after %ums", net.ssid, (unsigned)timeout_ms);
      break;
    }
    if (wifi_reason_is_terminal(s_wifi_reason))
    {
      // Worth shouting about: wrong credentials look exactly like a missing AP
      // on the panel, and no amount of retrying fixes them.
      LOGI("WiFi: '%s' refused us (reason %d)%s", net.ssid, s_wifi_reason,
           (s_wifi_reason == WIFI_REASON_AUTH_FAIL ||
            s_wifi_reason == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT)
               ? " — check the password in local-secrets.h" : "");
      break;
    }
    if (ms_now() >= deadline)
    {
      LOGI("WiFi: '%s' gave up after %ums (last reason %d)", net.ssid,
           (unsigned)timeout_ms, s_wifi_reason);
      break;
    }
    LOGI("WiFi: '%s' disconnected (reason %d), retrying", net.ssid, s_wifi_reason);
  }

  esp_wifi_disconnect();
  return false;
}

// One scan, then the strongest configured network in it. WIFI_NET_NONE if none
// of ours showed up.
static uint8_t wifi_scan_pick()
{
  wifi_scan_config_t sc = {};
  sc.scan_type = WIFI_SCAN_TYPE_ACTIVE;

  const uint32_t t0 = ms_now();
  esp_err_t err = esp_wifi_scan_start(&sc, true);
  const uint32_t scan_ms = ms_now() - t0;
  if (err != ESP_OK)
  {
    LOGI("WiFi: scan failed after %ums (%s)", (unsigned)scan_ms, esp_err_to_name(err));
    return WIFI_NET_NONE;
  }

  uint16_t found = 0;
  esp_wifi_scan_get_ap_num(&found);
  uint16_t take = (found > WIFI_SCAN_MAX_AP) ? WIFI_SCAN_MAX_AP : found;
  static wifi_ap_record_t recs[WIFI_SCAN_MAX_AP];
  // These records are heap-allocated by the driver and only these two calls
  // free them — a scan whose results go unread leaks until the next deinit.
  if (take)
    esp_wifi_scan_get_ap_records(&take, recs);
  else
    esp_wifi_clear_ap_list();

  uint8_t best = WIFI_NET_NONE;
  int8_t best_rssi = INT8_MIN;
  for (uint16_t i = 0; i < take; i++)
    for (uint8_t n = 0; n < s_wifi_net_count; n++)
    {
      if (!s_wifi_networks[n].ssid[0]) continue;
      if (strcmp((const char *)recs[i].ssid, s_wifi_networks[n].ssid) != 0) continue;
      if (recs[i].rssi > best_rssi) { best_rssi = recs[i].rssi; best = n; }
    }

  if (best != WIFI_NET_NONE)
    s_wifi_net_seen = true;

  if (best == WIFI_NET_NONE)
    LOGI("WiFi: scan %ums, %u APs, none of ours", (unsigned)scan_ms, (unsigned)take);
  else
    LOGI("WiFi: scan %ums, %u APs, best '%s' at %d dBm", (unsigned)scan_ms,
         (unsigned)take, s_wifi_networks[best].ssid, (int)best_rssi);
  return best;
}

static bool wifi_connect()
{
  s_wifi_net_seen = false;
  if (!wifi_is_configured())
    return false;
  if (!wifi_driver_start())
    return false;

  const uint32_t started = ms_now();

  // Tier 0: whatever worked last, no scan.
  if (wifi_last_net < s_wifi_net_count && s_wifi_networks[wifi_last_net].ssid[0])
  {
    if (wifi_try_net(wifi_last_net, WIFI_HINT_TIMEOUT_MS))
      return true;
    LOGI("WiFi: '%s' did not answer; falling back to a scan",
         s_wifi_networks[wifi_last_net].ssid);
  }

  // Tier 1: one scan, one association.
  uint8_t pick = wifi_scan_pick();

  // Tier 2: nothing of ours in the scan. Scans are noisy here — consecutive
  // identical scans returned between 5 and 14 APs (2026-08-09) — so an empty
  // result is not proof a network is gone. With a single network configured,
  // try it anyway: that is exactly what the firmware did before this change, so
  // it cannot regress, and it costs one association rather than N. With several,
  // guessing is the expensive pattern this design exists to avoid; leave
  // wifi_last_net alone so the next wake still opens with tier 0.
  if (pick == WIFI_NET_NONE)
  {
    if (s_wifi_net_count != 1 || wifi_last_net == 0)
    {
      wifi_disconnect();
      return false;
    }
    LOGI("WiFi: scan found nothing; trying the only configured network anyway");
    pick = 0;
  }

  const uint32_t elapsed = ms_now() - started;
  const uint32_t left = (elapsed < WIFI_TIMEOUT_MS) ? (WIFI_TIMEOUT_MS - elapsed) : 1000;
  if (wifi_try_net(pick, left))
    return true;

  wifi_disconnect();
  return false;
}

// One-shot SNTP sync: fresh instance, wait for a genuinely new time response.
static bool sntp_sync_once(uint32_t timeout_ms)
{
  esp_sntp_config_t scfg = {};
  scfg.start = true;
  scfg.wait_for_sync = true;
  scfg.num_of_servers = 1;
  scfg.servers[0] = "pool.ntp.org";
#if CONFIG_LWIP_SNTP_MAX_SERVERS >= 2
  scfg.num_of_servers = 2;
  scfg.servers[1] = "time.google.com";
#endif
  if (esp_netif_sntp_init(&scfg) != ESP_OK)
    return false;
  bool ok = (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(timeout_ms)) == ESP_OK);
  esp_netif_sntp_deinit();
  return ok;
}

// Bring the clock up when it has never been set, retrying inside a single WiFi
// session.
//
// The two failure modes cost very differently, so they get different budgets.
// A failed association is ~15s of radio (~1.5C); a failed SNTP with the
// association already up is just more waiting on a radio that is already
// powered, and it is the mode most likely to clear on a second ask. So retry
// SNTP hard and association gently.
//
// Worth real energy because the alternative is worse than a slow clock: with no
// wall clock the device records nothing at all (see update_hourly_history), so
// a permanently unsynced device collects nothing.
// `assoc_tries` is the caller's budget, not a constant: the burst on the very
// first boot and the retries on later wakes are different problems. The burst
// pays for itself once, while the device is usually on USB being flashed. A
// device that can never reach the AP would otherwise repeat that burst forever
// — 3 x 15s of association timeouts is ~4.5C, and at the ~1/day the backoff
// settles to that is most of a ~7.1C/day budget. Retries therefore get one
// association, which is what a failing resync already costs.
static bool ntp_bootstrap_sync(int assoc_tries)
{
  for (int assoc = 0; assoc < assoc_tries; assoc++)
  {
    if (!wifi_connect())
    {
      LOGI("NTP bootstrap: WiFi attempt %d/%d failed", assoc + 1, assoc_tries);
      continue;
    }
    LOGI("Connected to WiFi");
    wifi_ok = true;
    for (int s = 0; s < NTP_BOOTSTRAP_SNTP_TRIES; s++)
    {
      if (sntp_sync_once(NTP_BOOTSTRAP_SNTP_TIMEOUT_MS))
      {
        wifi_disconnect();
        LOGI("WiFi disconnected");
        return true;
      }
      LOGI("NTP bootstrap: SNTP attempt %d/%d timed out (association held)",
           s + 1, NTP_BOOTSTRAP_SNTP_TRIES);
    }
    wifi_disconnect();
    LOGI("WiFi disconnected");
    return false;  // network is up but NTP isn't; re-associating won't help
  }
  return false;
}

// Is a bootstrap retry due on this wake?
//
// Counted in wakes, not wall time: next_resync_time arithmetic is useless when
// the clock is the broken thing (with now ~ 0, now + resync_interval_s lands a
// simulated day away). Escalates from one attempt per 8 wakes to one per 64,
// which at the observed rate (~48 refresh wakes + 24 safety-net wakes/day)
// settles near one attempt per day. Each retry is one association (~15s, ~1.5C)
// — the same cost a failing resync already carries — so a device that never
// reaches its AP settles at ~1.5C/day, not the ~36-108C/day that retrying on
// every safety-net wake would cost.
static bool ntp_bootstrap_due(void)
{
  uint32_t shift = resync_fail_count < 3 ? resync_fail_count : 3;
  uint32_t period = (uint32_t)NTP_BOOTSTRAP_FIRST_WAKES << shift;
  return boot_count > 0 && ((uint32_t)boot_count % period) == 0;
}

// When to try again after a failed resync.
//
// Failures re-arm; without escalation a board that cannot reach its AP retries
// forever at the interval floor, which is what a basement deployment does today.
// But escalation must not touch a board that is *in range and failing* — the
// XIAO rigs see periodic association/SNTP failures on their ceramic chip antenna
// (docs/notes.md) and are recovering, so deferring them would be exactly wrong.
// Hence the caller passes what it observed rather than just "it failed".
//
// resync_fail_count already exists for the badge; this is its second consumer,
// and success clears it, so recovery needs no separate state.
//
// Two limits, binding on different devices rather than stacking. The shift
// governs short-interval boards, the only ones that retry often enough to cost
// anything: at the 1-day floor it gives 1, 2, 4, 8 days and stops. The absolute
// ceiling only bites once resync_interval_s has adapted past ~3.5 days, where
// escalation buys nothing anyway — it exists so a board that had reached the
// 28-day interval before losing its AP defers 28 days, not the 224 the shift
// alone would give. Collapsing them into one ceiling would *shorten* a 28-day
// board's retry, making it try harder after a failure than when healthy.
static time_t resync_retry_at(time_t now, bool network_absent)
{
  uint32_t shift = 0;
  if (network_absent)
    shift = resync_fail_count < 3 ? resync_fail_count : 3;
  int64_t backed_off = (int64_t)resync_interval_s << shift;
  if (backed_off > RESYNC_INTERVAL_MAX)
    backed_off = RESYNC_INTERVAL_MAX;
  return now + (time_t)backed_off;
}

// Attempt NTP resync if due. Measures clock drift and adjusts next interval.
static void maybe_ntp_resync(time_t now)
{
  if (!ntp_synced)
  {
    // The clock was never set — on_first_boot() ran once and failed. Without
    // this the device stayed on a 1970 clock until someone reset it, because
    // on_first_boot() only runs at boot_count == 1.
    if (!ntp_bootstrap_due())
      return;
    LOGI("NTP bootstrap: retrying first sync (%u failures so far)",
         (unsigned)resync_fail_count);
    if (!ntp_bootstrap_sync(1))
    {
      resync_fail_count++;
      return;
    }
    time(&last_sync_time);
    ntp_synced = true;
    resync_fail_count = 0;
    if (first_boot_time == 0)
      first_boot_time = last_sync_time;
    next_resync_time = last_sync_time + resync_interval_s;
    LOGI("NTP bootstrap: clock set, resuming normal resyncs");
    // No drift to measure: the clock was wrong by an unknown amount, not
    // drifting from a known reference.
    return;
  }
  if (next_resync_time == 0)
  {
    // First call after boot — schedule initial resync
    next_resync_time = now + resync_interval_s;
    return;
  }
  if (now < next_resync_time)
    return;

  LOGI("NTP resync: connecting to WiFi");
  if (!wifi_connect())
  {
    resync_fail_count++;
    const bool absent = !s_wifi_net_seen;
    next_resync_time = resync_retry_at(now, absent);
    LOGI("NTP resync: WiFi failed (%u in a row, network %s), retrying in %d s",
         (unsigned)resync_fail_count, absent ? "absent" : "present but unusable",
         (int)(next_resync_time - now));
    return;
  }

  // Capture pre-sync time for drift measurement
  time_t before_sync;
  time(&before_sync);

  // Fresh SNTP instance waits for a genuinely new time response. The clock is
  // already set (just drifted), so anything that returns early on a valid-
  // looking clock would measure ~0 drift and never actually correct it.
  if (!sntp_sync_once(30000U))
  {
    resync_fail_count++;
    LOGI("NTP resync: sync failed (%u in a row), deferring to next scheduled resync",
         (unsigned)resync_fail_count);
    wifi_disconnect();
    // No escalation: we associated, so the network is demonstrably there and a
    // retry has a real chance. Only absence earns a longer wait.
    next_resync_time = resync_retry_at(now, false);
    return;
  }

  time_t after_sync;
  time(&after_sync);

  // Window the drift accumulated over: since the clock was last *set* (boot
  // sync or a previous successful resync), not since the last attempt. Failed
  // attempts re-arm at +resync_interval_s, so the interval setting understates
  // the span by a whole multiple after every failure.
  time_t last_set = (last_sync_time > 0) ? last_sync_time : first_boot_time;
  last_drift_window_s = (int32_t)(before_sync - last_set);
  last_sync_time = after_sync;

  // Drift = what the clock said before sync minus what NTP says now.
  // Positive = clock was ahead, negative = clock was behind.
  // after_sync is the corrected time; before_sync was the drifted time.
  last_drift_ms = (int32_t)(before_sync - after_sync) * 1000;
  // Rate in ppm, kept with its window as a short history so the screen can
  // show whether the oscillator error is a stable constant. Short windows are
  // dropped rather than averaged in — see DRIFT_MIN_WINDOW_S.
  if (last_drift_window_s >= DRIFT_MIN_WINDOW_S)
  {
    int32_t ppm = (int32_t)((last_drift_ms * 1000LL) / last_drift_window_s);
    ppm = (ppm > 32767) ? 32767 : (ppm < -32768 ? -32768 : ppm);
    int32_t win_min = last_drift_window_s / 60;
    if (win_min > 65535) win_min = 65535;  // saturates at 45 days
    if (drift_ppm_count == DRIFT_PPM_HIST_SIZE)
    {
      memmove(drift_ppm_hist, drift_ppm_hist + 1,
              sizeof(drift_ppm_hist) - sizeof(drift_ppm_hist[0]));
      memmove(drift_win_min, drift_win_min + 1,
              sizeof(drift_win_min) - sizeof(drift_win_min[0]));
      drift_ppm_count--;
    }
    drift_win_min[drift_ppm_count] = (uint16_t)win_min;
    drift_ppm_hist[drift_ppm_count++] = (int16_t)ppm;
    LOGI("NTP resync: rate %d ppm over %d min (%u samples retained)",
         (int)ppm, (int)win_min, (unsigned)drift_ppm_count);
  }

  LOGI("NTP resync: drift was %d ms over %d s (%u attempts failed since last sync)",
       (int)last_drift_ms, (int)last_drift_window_s, (unsigned)resync_fail_count);

  // Journal the observation before clearing resync_fail_count, and snapshot the
  // drift block at the next sleep. Between them this is what docs/clock-drift.md
  // asks to be transcribed off the screen daily: the retained ppm ring holds
  // only DRIFT_PPM_HIST_SIZE (6) samples and dies on any reflash, whereas the
  // archive keeps every one of them with its correlates.
  {
    HistoryDriftSample s = {};
    s.sync_time = last_sync_time;
    s.drift_ms = last_drift_ms;
    s.window_s = last_drift_window_s;
    s.ppm = (last_drift_window_s >= DRIFT_MIN_WINDOW_S && drift_ppm_count > 0)
                ? drift_ppm_hist[drift_ppm_count - 1] : 0;
    // Absolute, not deltas: the host differences consecutive records, so no RTC
    // variable has to remember the previous values.
    s.boot_count = (uint32_t)boot_count;
    s.refresh_count = (uint32_t)display_refresh_count;
    s.ambient_mean_x10 = window_mean_ambient_x10(last_drift_window_s, &s.ambient_hours);
    history_store_append_drift(&s);
  }
  history_store_mark_base_dirty();

  resync_fail_count = 0;

#ifdef RESYNC_INTERVAL_OVERRIDDEN
  // Pinned. The override exists to sample resyncs on a fixed short cadence, and
  // the adaptive rule below would defeat that: a bench rig that was just synced
  // shows negligible drift, so the interval doubles after every success —
  // 300s, 600, 1200, 2400, 4800 — and is back over four hours within five
  // wall-clock hours, yielding a handful of geometrically-spaced samples instead
  // of the steady cadence that was asked for.
  resync_interval_s = RESYNC_INTERVAL_MIN;
  LOGI("NTP resync: interval pinned at %d s by build override (adaptation off)",
       (int)resync_interval_s);
#else
  // Only shorten the interval if drift is significant (>= 1 minute).
  // For a low-fidelity EPD thermometer display, sub-minute drift is invisible.
  int32_t abs_drift = abs(last_drift_ms);
  if (abs_drift >= 60000)
  {
    // Aim for <60s drift at next resync. The rate is drift over the measured
    // window, not over the interval setting — using the setting after a run of
    // failed attempts overstates the rate and shortens the interval too far.
    int32_t target = (int32_t)((60LL * last_drift_window_s * 1000) / abs_drift);
    if (target < RESYNC_INTERVAL_MIN)
      target = RESYNC_INTERVAL_MIN;
    if (target > RESYNC_INTERVAL_MAX)
      target = RESYNC_INTERVAL_MAX;
    resync_interval_s = target;
    LOGI("NTP resync: significant drift, interval adjusted to %d s (%d h)",
         (int)resync_interval_s, (int)(resync_interval_s / 3600));
  }
  else
  {
    // Drift < 1 minute — double the interval (capped)
    if (resync_interval_s < RESYNC_INTERVAL_MAX / 2)
      resync_interval_s *= 2;
    else
      resync_interval_s = RESYNC_INTERVAL_MAX;
    LOGI("NTP resync: drift negligible, extending interval to %d s (%d h)",
         (int)resync_interval_s, (int)(resync_interval_s / 3600));
  }
#endif // RESYNC_INTERVAL_OVERRIDDEN

  wifi_disconnect();
  next_resync_time = after_sync + resync_interval_s;
}
#endif // DISABLE_WIFI

// Battery thresholds (mV).
#if defined(THERMOMETER_C6_BOARD)
// RT9080 LDO tree, measured on board 1 (docs/notes.md 2026-07-30): total
// droop at the ~425mA refresh peak is ~300mV (BOD probe), the fresh-boot
// cliff 3317-3320mV, the sleep-floor knee 3.34V. At 3500mV the rail still
// holds ~3.2V through the peak on a stiff source; the ~200mV over the C6's
// 3.0V spec floor is what cold dropout and real-cell ESR spend from, and
// the shutdown itself is a render + persist that must complete. Hold the
// conservative end until the cold and real-cell BOD-probe runs report;
// they decide between here and 3450 (~5-8% more pack, OCV estimate).
const uint32_t low_battery_mv = 3550;
const uint32_t no_battery_mv = 3500;
#elif defined(ARDUINO_XIAO_ESP32C6)
// The XIAO's 3V3 rail is a pure buck (SGM6029C): at VBAT ≤3.6V it enters a
// bootstrap-starvation sag band (rail sags ~VTH below VIN; wakes collapse it
// into 0.5-0.9A brownout-restart storms; 30Hz sawtooth at 3.3V). Fine sweep
// 2026-07-05 (docs/notes.md): 3.7V is the lowest verified-healthy point,
// 3.6V is already inside the sag band — so shut down at the electrical
// cliff, not the battery's own limit (~12-15% SoC abandoned per OCV curve).
const uint32_t low_battery_mv = 3800;
const uint32_t no_battery_mv = 3700;
#else
// https://dlnmh9ip6v2uc.cloudfront.net/datasheets/Prototyping/TP4056.pdf
// https://www.best-microcontroller-projects.com/tp4056.html
const uint32_t low_battery_mv = 3200;
const uint32_t no_battery_mv = 3000; // Controller stops delivering current at 2.9V
#endif

uint32_t read_battery_level()
{
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // https://dfimg.dfrobot.com/nobody/wiki/fd28d987619c16281bdc4f40990e5a1c.PDF => looks like 1M/1M divider == x2 ratio
  // GPIO34 (A2) = ADC1 channel 6
  // On ADC failure return a value in the low-battery band: visible on the
  // display as a warning, but above no_battery_mv so a transient ADC error
  // can never trigger the permanent shutdown in handle_permanent_shutdown().
  const uint32_t adc_fail_mv = 3100;

  adc_oneshot_unit_handle_t unit;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &unit) != ESP_OK)
  {
    LOGI("ERROR: ADC unit init failed");
    return adc_fail_mv;
  }
  adc_oneshot_chan_cfg_t ccfg = {};
  ccfg.atten = ADC_ATTEN_DB_12;
  ccfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_oneshot_config_channel(unit, ADC_CHANNEL_6, &ccfg);

  adc_cali_handle_t cali = nullptr;
  adc_cali_line_fitting_config_t lcfg = {};
  lcfg.unit_id = ADC_UNIT_1;
  lcfg.atten = ADC_ATTEN_DB_12;
  lcfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_cali_create_scheme_line_fitting(&lcfg, &cali);

  int raw = 0, mv = 0;
  bool read_ok = (adc_oneshot_read(unit, ADC_CHANNEL_6, &raw) == ESP_OK);
  if (cali)
  {
    adc_cali_raw_to_voltage(cali, raw, &mv);
    adc_cali_delete_scheme_line_fitting(cali);
  }
  else
  {
    mv = raw * 3100 / 4095; // uncalibrated fallback, 12dB full scale ~3.1V
  }
  adc_oneshot_del_unit(unit);

  if (!read_ok)
  {
    LOGI("ERROR: ADC read failed");
    return adc_fail_mv;
  }

  uint32_t battery_mv = (uint32_t)mv * 2;
  LOGI("Battery level: %d mV", (int)battery_mv);
  return battery_mv;
#elif defined(THERMOMETER_C6_BOARD)
  // Custom thermometer-c6 board: high-side switched 100k/100k divider
  // (R20/R21). VDIV_EN (GPIO3) high → Q5 NFET → Q4 P-FET connects VBAT;
  // the external 100k pull-down keeps it hard-off in deep sleep. C29 10nF
  // reservoir on the ADC node charges through 100k — give it a few ms.
  // VBAT_ADC = GPIO2 = ADC1_CH2. While VBUS is present this node reads the
  // charger CV output, not battery SoC — see vbus_present().
  // ADC-failure fallback sits between no_battery_mv and low_battery_mv:
  // visible as a warning, can never trigger permanent shutdown.
  const uint32_t adc_fail_mv = 3525;

  gpio_out_init(3 /* VDIV_EN */);
  gpio_set_level(GPIO_NUM_3, 1);
  sleep_ms(5);

  adc_oneshot_unit_handle_t unit;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &unit) != ESP_OK)
  {
    gpio_set_level(GPIO_NUM_3, 0);
    LOGI("ERROR: ADC unit init failed");
    return adc_fail_mv;
  }
  adc_oneshot_chan_cfg_t ccfg = {};
  ccfg.atten = ADC_ATTEN_DB_12;
  ccfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_oneshot_config_channel(unit, ADC_CHANNEL_2, &ccfg);

  adc_cali_handle_t cali = nullptr;
  adc_cali_curve_fitting_config_t cfcfg = {};
  cfcfg.unit_id = ADC_UNIT_1;
  cfcfg.chan = ADC_CHANNEL_2;
  cfcfg.atten = ADC_ATTEN_DB_12;
  cfcfg.bitwidth = ADC_BITWIDTH_DEFAULT;
  adc_cali_create_scheme_curve_fitting(&cfcfg, &cali);

  int raw = 0, mv = 0;
  bool read_ok = (adc_oneshot_read(unit, ADC_CHANNEL_2, &raw) == ESP_OK);
  if (cali)
  {
    adc_cali_raw_to_voltage(cali, raw, &mv);
    adc_cali_delete_scheme_curve_fitting(cali);
  }
  else
  {
    mv = raw * 3300 / 4095; // uncalibrated fallback, 12dB full scale ~3.3V
  }
  adc_oneshot_del_unit(unit);
  gpio_set_level(GPIO_NUM_3, 0); // divider off; external pull-down holds it in sleep

  if (!read_ok)
  {
    LOGI("ERROR: ADC read failed");
    return adc_fail_mv;
  }

  uint32_t battery_mv = (uint32_t)mv * 2;
  LOGI("Battery level: %d mV", (int)battery_mv);
  return battery_mv;
#elif defined(ARDUINO_XIAO_ESP32C6)
  // https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/#reading-battery-voltage
  // Requires wiring A0/GPIO0 to VBAT see https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/#check-the-battery-voltage
  return 4321; // TODO: remove this once proper circuit has been soldered
#else
  #error "Unknown board type"
#endif
}

// USB presence. With VBUS attached, VBAT_ADC reads the charger CV node, so
// SoC-based decisions (especially permanent shutdown) must be suppressed.
bool vbus_present()
{
#if defined(THERMOMETER_C6_BOARD)
  // R22/R23 100k/100k from VBUS → ~2.5V at GPIO4 with USB attached; the
  // divider is dead (0V, zero drain) with USB unplugged.
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << 4;
  cfg.mode = GPIO_MODE_INPUT;
  cfg.pull_up_en = GPIO_PULLUP_DISABLE;
  cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
  gpio_config(&cfg);
  return gpio_get_level(GPIO_NUM_4) != 0;
#else
  return false;
#endif
}

// Outside the DISABLE_LEDS gate on purpose: epd_fault_blink() needs the pin even
// on the rigs that keep the LED dark. GPIO15 is LED_BUILTIN on the XIAO (yellow)
// and the status LED on the custom board (white 0603 through R8 1k); both are
// active-high.
#if defined(ARDUINO_XIAO_ESP32C6)
#define STATUS_LED_PIN 15
#endif

#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  #include "Adafruit_NeoPixel.h"
  Adafruit_NeoPixel status_led(1, 5 /*data pin*/, NEO_GRB + NEO_KHZ800);
#elif !defined(ARDUINO_XIAO_ESP32C6)
  #error "Unknown board type"
#endif
#endif

static uint32_t rgb(uint8_t r, uint8_t g, uint8_t b)
{
  return ((uint32_t)r << 16) | ((uint32_t)g << 8) | b;
}

void initialize_status_led()
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  status_led.begin();
  status_led.setBrightness(128);
#elif defined(ARDUINO_XIAO_ESP32C6)
  gpio_out_init(STATUS_LED_PIN);
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0);
#else
  #error "Unknown board type"
#endif
#endif
}

void set_status_led(uint32_t color)
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  // Looks like Red is a greenish tint
  // Green and Blue both show up correct
  status_led.setPixelColor(0, color);
  status_led.show();
#elif defined(ARDUINO_XIAO_ESP32C6)
  // Single-color yellow LED
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, color != 0 ? 1 : 0);
#else
  #error "Unknown board type"
#endif
#endif
}

void clear_status_led()
{
#ifndef DISABLE_LEDS
#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
  status_led.clear();
  status_led.show();
#elif defined(ARDUINO_XIAO_ESP32C6)
  gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0);
#else
  #error "Unknown board type"
#endif
#endif
}

// The panel-fault signal, and the only one this fault has.
//
// Deliberately NOT gated on DISABLE_LEDS. Every rig turns the LED off to save
// power, but a board whose panel is dead cannot put a badge on the thing that
// broke, and DISABLE_SERIAL removes the console from every release build — so
// without this a misconfigured or unplugged panel is completely silent. Power
// does not enter into it: this only runs on a board that is already not doing
// its job, and it suspends the refreshes that dominate the budget.
//
// The ESP32-E is excluded rather than gated: its LED is a NeoPixel and
// Adafruit_NeoPixel is not vendored under components/, so that board does not
// link with LEDs enabled at all (include/rigs/firebeetle.h). Driving its WS2812
// needs RMT or bit-banging — worth doing, not worth blocking this on.
//
// Three short and one long, repeated: a rhythm nothing else on this board
// produces, so it reads as deliberate rather than as a flicker. ~5s per wake.
#define EPD_FAULT_BLINK_GROUPS 3
static void epd_fault_blink(uint8_t fault)
{
  LOGI("*** EPD FAULT: %s — panel not responding, refreshes suspended ***",
       fault == DISPLAY_FAULT_BUSY_IDLE ? "BUSY never asserted (no panel?)"
                                        : "BUSY stuck (panel absent, or rail off?)");
#if defined(STATUS_LED_PIN)
  gpio_out_init(STATUS_LED_PIN);
  for (int group = 0; group < EPD_FAULT_BLINK_GROUPS; group++)
  {
    for (int i = 0; i < 3; i++)
    {
      gpio_set_level((gpio_num_t)STATUS_LED_PIN, 1); sleep_ms(120);
      gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0); sleep_ms(120);
    }
    gpio_set_level((gpio_num_t)STATUS_LED_PIN, 1); sleep_ms(600);
    gpio_set_level((gpio_num_t)STATUS_LED_PIN, 0); sleep_ms(400);
  }
#endif
}

float read_temperature()
{
  LOGI("Getting temperature");
  float temp = sensor.GetTemperatureC();
  LOGI("temp: %f °C", temp);
  // The single gate for the whole system. Sensor drivers only have to return the
  // sentinel (or anything outside the range) when they cannot produce a reading;
  // the policy for what to do about it lives here, on the CPU that can afford it.
  if (!temp_is_plausible(temp))
  {
    // Returning the sentinel rather than the value: every recording site skips it,
    // and the renderer shows "--.-" instead of a number a reader would believe.
    LOGI("Reading %.2f outside %.0f..%.0f — reporting no reading", temp,
         TEMP_PLAUSIBLE_MIN_C, TEMP_PLAUSIBLE_MAX_C);
    last_sensor_ok = false;
    return TEMP_NO_PREVIOUS;
  }
  // A direct read that rescued the wake produces a good number, but it does not
  // make the sensor subsystem healthy: the coprocessor that failed is still being
  // reloaded every wake. Clearing the badge here would render a frame that looks
  // entirely normal while that continues, which is the silent degradation the
  // project forbids. Only a wake with nothing wrong clears it.
  if (!s_ulp_read_failed)
    last_sensor_ok = true;
  return temp;
}

uint16_t buttonRead(uint8_t pin)
{
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = 1ULL << pin;
  cfg.mode = GPIO_MODE_INPUT;
  cfg.pull_up_en = GPIO_PULLUP_ENABLE;
  gpio_config(&cfg);
  return gpio_get_level((gpio_num_t)pin); // return 0 when pressed
}

#if defined(ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
#define SHUTDOWN_BUTTON_PIN 27
#elif defined(ARDUINO_XIAO_ESP32C6)
#define SHUTDOWN_BUTTON_PIN 9
#else
  #error "Unknown board type"
#endif

void handle_permanent_shutdown(uint32_t battery_mv)
{
  uint16_t pin27 = buttonRead(SHUTDOWN_BUTTON_PIN);
  LOGI("Button read %d: %d", SHUTDOWN_BUTTON_PIN, pin27);
#if defined(THERMOMETER_C6_BOARD)
  // The button shares GPIO9 with the BOOT strap, which a host asserts through
  // DTR when it opens the port — so a console attach can hold the "button" down
  // for as long as it likes, and a wake landing in that window reads a confirmed
  // press and clears the panel into permanent shutdown. Requiring USB to be
  // detached costs nothing real: storing the device is an unplugged act, and the
  // dead-battery arm below is already VBUS-suppressed.
  const bool button_pressed = (pin27 == 0) && !vbus_present();
  if (pin27 == 0 && !button_pressed)
    LOGI("Shutdown button reads pressed, but USB is attached — ignoring. "
         "Unplug, then hold it through a wake.");
#else
  const bool button_pressed = (pin27 == 0);
#endif
#ifdef BATTERY_SHUTDOWN_DISABLED
  // Bench sweep builds only (tools/ppk2.py sweep): never latch off on voltage.
  // A stock build below no_battery_mv renders the empty-battery panel, persists
  // history to flash and powers down on every fresh boot — flash and panel wear
  // on every sweep step, and indistinguishable from a dead board on the PPK2.
  // The button path stays live. Must never ship: CLAUDE.md revert list.
  const bool battery_dead = false;
  if (battery_mv < no_battery_mv)
    LOGI("BATTERY_SHUTDOWN_DISABLED: ignoring %d mV < %d mV",
         (int)battery_mv, (int)no_battery_mv);
#else
  // On USB power the measured voltage is the charger CV node, not battery
  // SoC — never let it trigger the permanent shutdown while charging.
  const bool battery_dead = battery_mv < no_battery_mv && !vbus_present();
#endif
  if (button_pressed || battery_dead)
  {
    // If button is pressed or battery is dead, powerdown
    if (button_pressed)
    {
      // Looks like we might be getting extremely rare spurious reads of 0
      // Double check after a delay ...
      sleep_ms(1000);
      pin27 = buttonRead(SHUTDOWN_BUTTON_PIN);
      LOGI("Button read %d confirmation: %d", SHUTDOWN_BUTTON_PIN, pin27);
      if (pin27 != 0)
      {
        bad_pin27_count++;
        return;
      }

      display_clear();

      // ... and add somethign on screen for diagnostics purposes in case the delay isn't sufficient
      // TODO remove this later
      display_show_pin27_diagnostic(boot_count);
    }
    else //  battery_mv < no_battery_mv
    {
      time_t now;
      struct tm nowtm;
      get_time(&now, &nowtm);
      display_show_empty_battery(battery_mv, now, make_display_stats());
    }

    // This path bypasses start_deep_sleep(), so flush explicitly — it is the
    // one moment the archive most needs to be current, since the device is
    // about to be off indefinitely. Hourly entries were journaled as they were
    // finalized and are already safe; what would otherwise be lost is the base
    // snapshot, and with it the sparkline and the drift block.
    history_store_persist_now();

    for (int domain = 0; domain < ESP_PD_DOMAIN_MAX; domain++)
      esp_sleep_pd_config((esp_sleep_pd_domain_t)domain, ESP_PD_OPTION_OFF);
    LOGI("Shutting down until reset. All sleep pd domains have been shutdown.");
    esp_deep_sleep_start();
  }
}

void on_first_boot()
{
#ifdef DISABLE_WIFI
  LOGI("WiFi has been disabled at build time with DISABLE_WIFI. See local-secrets.h to fix.");
  // Not an error — suppress "! NO WIFI" indicator on display
  wifi_ok = true;
  set_status_led(rgb(255, 255, 0));
  sleep_ms(100);
#else
  #if !defined(MY_WIFI_NETWORKS)
    #error "MY_WIFI_NETWORKS is not defined. See local-secrets.h (and local-secrets-example.h) to fix."
  #endif
  if (!wifi_is_configured())
  {
    LOGI("No WiFi network configured. Will assume network connectivity isn't possible. See local-secrets.h to fix.");
    return;
  }

  // Connect to WiFi with timeout (avoids hanging forever if network is down)
  LOGI("Connecting to WiFi and synchronizing time");
  set_status_led(rgb(0, 0, 255));

  // Retries inside one session, and handles its own WiFi teardown. Getting the
  // clock on the first boot matters more than it used to: without one the
  // device records no history at all, and a failure here used to be permanent.
  const bool synced = ntp_bootstrap_sync(NTP_BOOTSTRAP_ASSOC_TRIES);
  if (!synced)
    resync_fail_count++;   // wifi_ok separately reflects the association
  set_status_led(synced ? rgb(0, 255, 0) : rgb(255, 0, 0));

  // Judge the clock on its own merits either way. A failed sync does not mean
  // there is no time: a panic or WDT reset reloads .rtc.data — so boot_count is
  // back to 1 and this runs again — while the RTC timer keeps counting
  // correctly across it. Returning early instead left first_boot_time at 0,
  // which renders as a ~20601d uptime, hides the boot date, shows a permanent
  // NO-NTP badge against a correct clock, and keeps maybe_ntp_resync() on the
  // WiFi-burning bootstrap path indefinitely.
  time(&first_boot_time);
  ntp_synced = time_is_plausible(first_boot_time);
  if (ntp_synced && last_sync_time == 0)
    last_sync_time = first_boot_time;   // a value restored from flash wins
  if (!synced)
    LOGI("NTP sync failed — %s", ntp_synced
             ? "RTC clock is still plausible, keeping it"
             : "time is unreliable, will retry on later wakes");
#endif
}


bool periodic_display_clear(const time_t now, struct tm nowtm)
{
  // Trigger screen clear daily
  if (next_clear_time == 0)
  {
    if (now < one_day)
    {
      // We don't seem to have a synchronized clock, clear screen periodically from first boot
      next_clear_time = now + one_day;
    }
    else
    {
      // We have a synchronzied clock, clear screen periodically when it's likely to be least disruptive
      // Let's pick the next time it's 04h00
      time_t offset = 0;
      if (4 <= nowtm.tm_hour)
      {
        offset = one_day;
      }
      nowtm.tm_hour = 4;
      nowtm.tm_min = 0;
      nowtm.tm_sec = 0;
      next_clear_time = mktime(&nowtm) + offset;
    }
  }

  if (now < next_clear_time)
  {
    return false;
  }

  display_clear();
  next_clear_time += one_day; // Schedule next clear in a day
  return true;
}

// Everything a trip does once it has a reading: resync, record, decide whether
// to redraw, redraw. Separate from the sleep that normally follows, because a
// parked session runs it repeatedly without sleeping between passes — and a hold
// that skipped it would freeze the hour accumulator and leave a stale frame on
// the panel, which is how the first attempt at that hold failed.
static void wake_work(uint32_t battery_mv, float temp)
{
  time_t now;
  struct tm nowtm;
  get_time(&now, &nowtm);

#ifndef DISABLE_WIFI
  crash_log.stage = STAGE_NTP;
  maybe_ntp_resync(now);
  // Re-read time after potential resync correction
  get_time(&now, &nowtm);
#endif
  crash_log.cur_time = (uint32_t)now;

#ifdef MOCK_DISPLAY_DATA
  // Override the sensor reading to match the mock data range so it doesn't
  // distort the chart Y-axis (DummySensor returns a constant 12.3°C). Applied
  // before validity is decided, so the substitute is treated as the reading for
  // every purpose below rather than being rendered as a number the same frame
  // calls invalid.
  temp = 22.3f;
#endif

  // One decision, used for recording and display alike, so the two can never
  // disagree about what was believed. A rejected reading must reach neither: it
  // would be a fabricated point in the sparkline, the hourly ring and the min/max,
  // none of which can be undone once mirrored to flash.
  //
  // A reading that arrives over the CPU's own bus carries the sensor's identity
  // with it, because Initialize() rechecks the chip ID. One from the coprocessor
  // does not — see setup() for why recovery on the C6 has to accept it anyway.
  const bool temp_trusted = (temp != TEMP_NO_PREVIOUS);

  if (temp_trusted)
    update_temp_extremes(temp);
  // Called either way: the hour bookkeeping has to keep moving so the outage is
  // recorded as hours that measured nothing.
  update_hourly_history(now, &nowtm, temp, temp_trusted);

  LOGI("now: %ld. next clear time: %ld. first boot time: %ld. prev_temp: %.1f",
       (long)now, (long)next_clear_time, (long)first_boot_time, previous_temp);
  // RENDER covers both the periodic clear and the refresh below — either can
  // die mid-EPD-write (SPI, busy-wait light sleep, panel power)
  crash_log.stage = STAGE_RENDER;

#ifdef CRASH_TEST_BOOT
  // Deliberate crash to exercise the forensics path on hardware — flash with
  //   PLATFORMIO_BUILD_FLAGS="-DCRASH_TEST_BOOT=3" pio run -e <env> -t upload
  // (add -DCRASH_TEST_HANG to test the task-WDT→panic path instead of a null
  // deref). Fires on the first wake at/after that boot count, once per RTC
  // power cycle: the crash_count guard stops a crash loop, and also means a
  // second test needs a power cycle (which clears the CrashLog) first.
  if (boot_count >= CRASH_TEST_BOOT && crash_log.crash_count == 0)
  {
    LOGI("CRASH_TEST_BOOT: deliberately crashing at boot %d", boot_count);
    fflush(stdout);
#ifdef CRASH_TEST_HANG
    while (true) {}                    // starve idle task → TWDT → panic
#else
    *(volatile uint32_t *)0 = 0xdead;  // store to NULL → panic + coredump
#endif
  }
#endif
  // Reasons to redraw. Gaining or losing a reading is tested against the panel
  // rather than against previous_temp, since the delta is meaningless when either
  // side is not a measurement; and a persistent fault redraws only on the
  // heartbeat, so it cannot churn the panel.
  const bool fault_heartbeat = !temp_trusted && !panel_shows_reading &&
                               previous_boot_count >= 0 &&
                               (boot_count - previous_boot_count) >= FAULT_REPAINT_WAKES;
#ifdef REFRESH_EVERY_N_WAKES
  // Bench builds only: repaint on a wake count rather than on temperature, so
  // the refresh cadence stops tracking the room. Same shape as the fault
  // heartbeat but unconditional — paired with a DISPLAY_TEMP_DELTA past any real
  // swing, this becomes the sole repaint source and the cadence is exact.
  const bool cadence_repaint = previous_boot_count >= 0 &&
                               (boot_count - previous_boot_count) >= REFRESH_EVERY_N_WAKES;
#else
  const bool cadence_repaint = false;
#endif
  // Named rather than inlined into the expression below: whether the panel was
  // driven at all decides whether display_fault() has anything to say this wake.
  // Left running even while a fault is latched — it is once a day, and its own
  // attempt to drive the panel doubles as a retry.
  const bool cleared = periodic_display_clear(now, nowtm);
  bool should_refresh = cleared ||
                        previous_boot_count < 0 ||   // nothing rendered yet this RTC epoch
                        temp_trusted != panel_shows_reading ||
                        fault_heartbeat ||
                        cadence_repaint ||
                        (temp_trusted && fabsf(temp - previous_temp) >= DISPLAY_TEMP_DELTA);
#ifdef HAS_USB_SERVICE_WINDOW
  // The window badge is a claim about right now — the port is held open, and the
  // reading carries the CPU's self-heating — so gaining or losing it repaints
  // even when the temperature has not moved.
  should_refresh = should_refresh || (s_usb_window_active != s_panel_has_usb_badge);
#endif

  // A panel that is not answering costs a full GxEPD2 busy timeout per wait on
  // every attempt, and there is nothing to put a frame on anyway. Retry on a slow
  // cadence so a panel that came back — reseated FFC, rail restored — recovers
  // without needing a reset.
  const bool panel_retry_due = (boot_count % EPD_FAULT_RETRY_WAKES) == 0;
  if (epd_fault != DISPLAY_FAULT_NONE && !panel_retry_due)
    should_refresh = false;

  if (!should_refresh)
  {
    LOGI("temperature hasn't changed significantly, no need to refresh display");
  }
  else
  {
    display_refresh_count++;
    if (max_battery_mv < battery_mv)
      max_battery_mv = battery_mv;

    // Same plausibility gate as update_hourly_history(): a 1970 timestamp here
    // would sit ~54 years before every stored point and never leave the window.
    // Not journaled — the sparkline rides along in the base snapshot instead.
    if (time_is_plausible(now) && temp_trusted)
      temp_history_record(historical_data.temp, &historical_data.temp_count,
                          now, (int16_t)(temp * 10));

    // The badge describes the frame about to be drawn, so fold in the trust
    // decision without discarding what the read path already reported: a wake
    // rescued by a direct read after the coprocessor failed still gets a badge.
    last_sensor_ok = last_sensor_ok && temp_trusted;

    PPK2_DISPLAY_HIGH();
    display_show_temperature(temp_trusted ? temp : TEMP_NO_PREVIOUS,
                             battery_mv, battery_mv < low_battery_mv,
                             now, &nowtm, make_display_stats());
    PPK2_DISPLAY_LOW();

    if (temp_trusted)
      previous_temp = temp;
    panel_shows_reading = temp_trusted;
    previous_boot_count = boot_count;
#ifdef HAS_USB_SERVICE_WINDOW
    s_panel_has_usb_badge = s_usb_window_active;
#endif
  }

  // Only a wake that actually drove the panel has evidence about it; one that
  // skipped the refresh must leave the latch as it found it, or the fault would
  // clear itself on the first quiet wake and the blink would stutter.
  if (cleared || should_refresh)
    epd_fault = display_fault();

  // Reload the coprocessor program on a fresh boot, and on any wake whose
  // coprocessor reading could not be used. InitializeUlp() is the only thing that
  // writes OSR_CONFIG and loads the program, so a sensor that lost power comes
  // back at its reset defaults and stays misconfigured until something reloads it;
  // doing it here is what a manual power cycle would otherwise be needed for. An
  // ordinary wake must not reload — the coprocessor is running and configured.
  //
  // The cause tested must be the CACHED one: the EPD busy-wait light sleeps have
  // replaced the live wakeup cause with their own GPIO wake by this point, so
  // reading it here reports a fresh boot on every refresh.
  //
  // Deliberately unbounded. A sensor that NACKs makes the LP core wake the CPU on
  // every failed read (both error paths in ulp/lp_core_*.h wake unconditionally), so
  // the program reloads once per SLEEP_INTERVAL_S for as long as the fault lasts.
  // Accepted rather than bounded: the mode is rare, and it either clears on the next
  // reading or the device is unusable anyway. Note the "uN" footer count climbs but
  // is only re-rendered when something else triggers a refresh, so a persistent fault
  // sits on the panel as "! SENSOR" beside a stale count, not a visibly rising one.
  // The fresh-boot term is spent once per boot; the recovery terms are not, so a
  // fault still reloads on every cycle it persists.
  const bool cold_boot_reload =
      (s_wake_cause == ESP_SLEEP_WAKEUP_UNDEFINED) && !s_lp_loaded_this_boot;
  if (sensor.SupportsUlp() && (cold_boot_reload || s_ulp_read_failed || !temp_trusted))
  {
    crash_log.stage = STAGE_LP_INIT;
    ulp_reinit_count++;
    // Only a genuine power cycle leaves the coprocessor's shared state
    // uninitialised; a recovery reload must keep the counters and delta reference
    // it already has.
    sensor.InitializeUlp(cold_boot_reload);
    s_lp_loaded_this_boot = true;
  }

  // Genuinely last: every measurement, record and reload above happens on its
  // normal schedule first, so a board signalling a dead panel is still archiving
  // temperature the whole time it blinks.
  if (epd_fault != DISPLAY_FAULT_NONE)
    epd_fault_blink(epd_fault);
}

#ifdef HAS_USB_SERVICE_WINDOW
// --- USB flash-service window ---
//
// The USB Serial/JTAG controller is unpowered in deep sleep, so a sleeping board
// presents no USB device at all and esptool's download-mode reset — what stands
// in for the BOOT button on this chip — has nothing to talk to. Holding the CPU
// awake while a host is attached keeps the port enumerated, which is what makes a
// reflash hands-free.
//
// The predecessor of this code was deleted for two reasons, and both shape it:
// it detected the host from the USB SOF interrupt bit at sleep entry, which is
// not set that early after a wake (enumeration takes longer than the wake's
// active phase); and it then spun in place, so the board stopped measuring,
// refreshing, resyncing and arming wake sources, silently. So: entry is decided
// by VBUS, which is a live voltage rather than a latched event, and the hold runs
// the ordinary cycle on the ordinary schedule — the wait replaces deep sleep, it
// does not replace the work.

// Sleeps still owed to real deep sleep before the window may open. Deep-sleep
// paths (wake stubs, RTC restore, boot chain) cannot be exercised while the
// window substitutes a delay for the sleep, so a bench build can ask for the
// first N to be genuine. Reloaded from its initialiser by every reset that is
// not a deep-sleep wake — including a reflash — so each flash buys N real
// cycles and then the port comes back unattended.
RTC_DATA_ATTR uint8_t usb_observe_left = USB_WINDOW_OBSERVE_CYCLES;

// Whether a host has answered on this cable session, and the geometric backoff
// for looking again when none has — see USB_WINDOW_PROBE_SHIFT_MAX. All three
// are cleared by any wake that finds VBUS absent, so a fresh plug is always
// judged on its own evidence.
RTC_DATA_ATTR bool usb_host_seen = false;
RTC_DATA_ATTR uint8_t usb_probe_skip = 0;
RTC_DATA_ATTR uint8_t usb_probe_shift = 0;

// One window pass: exactly what a timer wake does, minus the sleep. Nothing here
// but the two calls a real wake makes — the coprocessor keeps sampling on its own
// timer whether or not the CPU slept, so a parked cycle always has a sample
// waiting, the same one a timer wake would have come up to.
static void usb_window_cycle()
{
  begin_wake_cycle();
  run_wake_cycle(true);
  // What start_deep_sleep() does for a sleeping board, at the point a parked one
  // stops working: nothing in the archive is older than the last completed
  // cycle. It cannot live inside the cycle itself — the sleep path would then
  // reach it twice, which is free in a stock build but not under PPK2_DEBUG,
  // where each call adds a 300ms marker preamble, or HISTORY_BASE_EVERY_WAKE,
  // where the second call re-dirties and writes a whole second snapshot. Those
  // are the measurement builds; doubling their cost corrupts the instrument.
  history_store_persist_now();
}

static void usb_service_window(void)
{
  if (!vbus_present())
  {
    // Cable out. Forget what was learned about that session, so the next plug is
    // judged on its own evidence and probed at once.
    usb_host_seen = false;
    usb_probe_skip = 0;
    usb_probe_shift = 0;
    return;  // the battery case: one GPIO read, then sleep as usual
  }

  // A host, once it has answered, is assumed to still be there for as long as
  // the cable is. SOF stops whenever the OS suspends an idle port — 2s by
  // default on Linux, and nothing holds this port open between reflashes — but a
  // suspended device is still enumerated and still perfectly flashable. Reading
  // that silence as departure would shut the window on precisely the board
  // someone left plugged in so they could flash it later.
  bool host = usb_host_seen;

  if (!host)
  {
    if (usb_probe_skip > 0)
    {
      usb_probe_skip--;
      return;
    }

    // usb_serial_jtag_is_connected() tracks SOF frames, which only a live bus
    // sends, but it starts out optimistically "connected" and decays a few ticks
    // into the boot — so the first look is deliberately taken one poll interval
    // in, never immediately.
    for (uint32_t waited = 0; waited < USB_WINDOW_ENUM_GRACE_MS; waited += USB_WINDOW_POLL_MS)
    {
      sleep_ms(USB_WINDOW_POLL_MS);
      if (usb_serial_jtag_is_connected())
      {
        host = true;
        break;
      }
      if (!vbus_present())
      {
        usb_probe_skip = 0;
        usb_probe_shift = 0;
        return;  // plugged and unplugged inside the grace
      }
    }
    if (!host)
    {
      usb_probe_skip = (uint8_t)(1u << usb_probe_shift);
      if (usb_probe_shift < USB_WINDOW_PROBE_SHIFT_MAX)
        usb_probe_shift++;
      LOGI("VBUS with no host traffic — charger, not a bus; sleeping normally "
           "(next probe in %u wakes)", (unsigned)usb_probe_skip);
      return;
    }
    usb_host_seen = true;
    usb_probe_skip = 0;
    usb_probe_shift = 0;
  }

  // Spent only on sleeps a host would actually have held open, so docking on a
  // charger cannot quietly consume the bench budget.
  if (usb_observe_left > 0)
  {
    usb_observe_left--;
    LOGI("USB host attached, but this sleep is an observe cycle (%u more after it)"
         " — sleeping for real", (unsigned)usb_observe_left);
    return;
  }

  LOGI("USB host attached — flash-service window open, port stays enumerated");
  s_usb_window_active = true;
  // A refresh must not light-sleep from here on: light sleep gates the USB PHY
  // clock, and the port may not come back without replugging the cable. The
  // energy that costs is irrelevant — the window only ever runs on USB power.
  display_set_busy_wait_plain(true);

  // VBUS is the only thing that closes this. SOF silence cannot: an idle port is
  // suspended within seconds and stays that way until something opens it, which
  // is the normal state of a board left plugged in waiting to be flashed. The
  // case that leaves is a host that powers down while still supplying 5V — the
  // board then stays awake on that supply, which the "! USB" badge says out loud.
  bool leaving = false;
  while (!leaving)
  {
    // Park where deep sleep would have been. sleep_ms() is vTaskDelay, so the
    // idle task still runs and the task watchdog stays fed however long this is.
    crash_log.stage = STAGE_USB_WINDOW;
    uint32_t vbus_low = 0;
    for (uint32_t parked = 0; parked < (uint32_t)SLEEP_INTERVAL_S * 1000u;
         parked += USB_WINDOW_POLL_MS)
    {
      sleep_ms(USB_WINDOW_POLL_MS);

      if (vbus_present())
      {
        vbus_low = 0;
      }
      else if (++vbus_low >= USB_WINDOW_VBUS_DEBOUNCE_N)
      {
        LOGI("USB unplugged — closing the window");
        leaving = true;
        break;
      }
    }
    if (leaving)
      break;

    usb_window_cycle();
  }

  s_usb_window_active = false;
  // Restored before the last frame, so a board that just went back on battery
  // pays the light-sleep-free busy wait for none of it. Still plain while the
  // cable is in, matching the rule setup() applies: light sleep and an
  // enumerated port do not coexist.
  display_set_busy_wait_plain(vbus_present());
  // The panel must not keep claiming the port is held open.
  if (s_panel_has_usb_badge)
    usb_window_cycle();
  LOGI("flash-service window closed");
}
#endif  // HAS_USB_SERVICE_WINDOW


// Reset history buffers (sparkline + hourly).
// Called when the history data format changes (struct layout, buffer sizes).
static void reset_rtc_history()
{
  memset(&historical_data, 0, sizeof(historical_data));
  historical_data.current_hour_min_x10 = TEMP_INIT_MIN_X10;
  historical_data.current_hour_max_x10 = TEMP_INIT_MAX_X10;
  historical_data.version = RTC_HISTORY_VERSION;
  historical_data.self_addr = (uint32_t)&historical_data;
}

// Reset operational state (counters, flags, thresholds).
// Called when non-history RTC variables change. Preserves history.
static void reset_rtc_state()
{
  boot_count = 0;
  display_refresh_count = 0;
  ulp_reinit_count = 0;
  first_boot_time = 0;
  next_clear_time = 0;
  previous_temp = TEMP_NO_PREVIOUS;
  panel_shows_reading = false;
  previous_boot_count = -1;
  max_battery_mv = 0;
  bad_pin27_count = 0;
  min_temp_since_boot = TEMP_INIT_MIN;
  max_temp_since_boot = TEMP_INIT_MAX;
  next_resync_time = 0;
  resync_interval_s = RESYNC_INTERVAL_MIN;
  last_drift_ms = 0;
  last_drift_window_s = 0;
  last_sync_time = 0;
  resync_fail_count = 0;
  memset(drift_ppm_hist, 0, sizeof(drift_ppm_hist));
  memset(drift_win_min, 0, sizeof(drift_win_min));
  drift_ppm_count = 0;
  wifi_ok = false;
  ntp_synced = false;
  last_sensor_ok = true;
  wifi_last_net = WIFI_NET_NONE;
#ifdef HAS_USB_SERVICE_WINDOW
  usb_observe_left = USB_WINDOW_OBSERVE_CYCLES;
  usb_host_seen = false;
  usb_probe_skip = 0;
  usb_probe_shift = 0;
#endif
  rtc_state_version = RTC_STATE_VERSION;
}

// Pull the history and drift block back out of the flash archive.
//
// Deliberately NOT gated on a plausible clock. A first-boot NTP failure is
// permanent today (on_first_boot() runs only at boot_count==1, and
// maybe_ntp_resync() returns early while !ntp_synced), and it is common on the
// XIAO boards — so waiting for a good clock would often mean never restoring at
// all, leaving 30 days of readable history invisible. The snapshot is
// internally consistent on its own; the clock is only needed to place *new*
// readings against it, which update_hourly_history() already refuses to do
// without one.
//
// current_hour_start is left at 0 (reset_rtc_history() zeroed it), which is the
// existing "first reading after boot" sentinel: no finalize can fire until a
// reading with a real clock arrives, and the gap between the snapshot and now
// is then filled with HOURLY_NO_DATA by the normal path.
static void restore_history_from_flash()
{
  HistoryDriftState drift;
  if (!history_store_restore(&historical_data, &drift))
  {
    reset_rtc_history();  // partial reads may have touched it
    return;
  }
  historical_data.self_addr = (uint32_t)&historical_data;
  historical_data.current_hour_start = 0;
  historical_data.current_hour_sum_x10 = 0;
  historical_data.current_hour_sample_count = 0;
  historical_data.current_hour_min_x10 = TEMP_INIT_MIN_X10;
  historical_data.current_hour_max_x10 = TEMP_INIT_MAX_X10;

  time_t now;
  time(&now);
  drift_state_load(&drift, time_is_plausible(now) &&
                               now >= (time_t)drift.last_sync_time);
}

// Same, for the branch where RTC history survived but the state block was
// reset. The archive's copy is at least as fresh as the one just cleared.
static void restore_drift_from_flash()
{
  HistoryDriftState drift;
  if (!history_store_restore(nullptr, &drift))
    return;
  time_t now;
  time(&now);
  drift_state_load(&drift, time_is_plausible(now) &&
                               now >= (time_t)drift.last_sync_time);
}

#ifdef PPK2_DEBUG
// Marker fingerprint, emitted on every wake so PPK2 wiring can be confirmed
// against the capture it actually produced rather than against a boot that may
// not be in frame. The pattern differs in BOTH count and width per lane — 2x10ms
// on CPU-active, 5x4ms on display/flash — so a lane is still identifiable when a
// pulse is clipped at a capture boundary. It also reads the pads back, which
// separates "the firmware isn't driving the pin" from "the lead is on the wrong
// pin"; a flat channel with a passing read-back is a wiring fault.
//
// 80ms total, down from the 400ms this used to cost. That earlier version was
// gated to the first boot to keep it off the energy budget, which silently
// removed crossed-lead detection from every capture that did not start with an
// RTC-wiped boot — the leads were in fact crossed on this rig and the fingerprint
// is what caught it. 80ms per wake (~1.4 mC) buys the check back on every wake.
//
// Pulses this short do not survive decimation — analyse marker captures with
// --decimate 1. Marker captures are short and want that anyway, and long
// production captures carry no markers at all.
// Kept in sync with check_selftest() in tools/ppk2.py, which pattern-matches
// these exact counts and widths to tell the lanes apart.
#define PPK2_FP_CPU_PULSES   2
#define PPK2_FP_CPU_MS      10
#define PPK2_FP_DISP_PULSES  5
#define PPK2_FP_DISP_MS      4

static void ppk2_selftest()
{
  // INPUT_OUTPUT, not OUTPUT: gpio_config() with GPIO_MODE_OUTPUT disables the
  // input buffer on ESP32, so gpio_get_level() would always read 0.
  gpio_config_t cfg = {};
  cfg.pin_bit_mask = (1ULL << PPK2_PIN_CPU_ACTIVE) | (1ULL << PPK2_PIN_DISPLAY);
  cfg.mode = GPIO_MODE_INPUT_OUTPUT;
  gpio_config(&cfg);

  gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 1);
  gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 1);
  int d0_hi = gpio_get_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE);
  int d1_hi = gpio_get_level((gpio_num_t)PPK2_PIN_DISPLAY);
  gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 0);
  gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 0);
  int d0_lo = gpio_get_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE);
  int d1_lo = gpio_get_level((gpio_num_t)PPK2_PIN_DISPLAY);
  LOGI("PPK2 selftest: D0=GPIO%d %d->%d, D1=GPIO%d %d->%d — pads %s",
       PPK2_PIN_CPU_ACTIVE, d0_hi, d0_lo, PPK2_PIN_DISPLAY, d1_hi, d1_lo,
       (d0_hi && !d0_lo && d1_hi && !d1_lo) ? "follow (firmware OK)"
                                            : "DO NOT follow (firmware fault)");

  for (int i = 0; i < PPK2_FP_CPU_PULSES; i++)
  {
    gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 1); sleep_ms(PPK2_FP_CPU_MS);
    gpio_set_level((gpio_num_t)PPK2_PIN_CPU_ACTIVE, 0); sleep_ms(PPK2_FP_CPU_MS);
  }
  for (int i = 0; i < PPK2_FP_DISP_PULSES; i++)
  {
    gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 1); sleep_ms(PPK2_FP_DISP_MS);
    gpio_set_level((gpio_num_t)PPK2_PIN_DISPLAY, 0); sleep_ms(PPK2_FP_DISP_MS);
  }
}
#endif

// What every trip through the high-power path opens with. A real wake inherits
// part of this from the boot — statics come up zeroed — but a parked cycle runs
// inside one boot and has to be explicit, so both paths call the same thing
// rather than each keeping its own idea of what starting a trip means.
static void begin_wake_cycle(void)
{
  // boot_count counts trips through this path, not power-ons: every deep-sleep
  // wake is a fresh boot, and ntp_bootstrap_due() already reads it as "wakes".
  // The fault heartbeat's repaint interval, that NTP throttle and the "#" the
  // panel reports all key off it.
  boot_count++;
  crash_log.cur_boot_count = boot_count;

  // Per-trip, not per-boot: "the coprocessor handed up a reading we could not
  // use". Latched across the cycles of a parked session it would reload the
  // coprocessor program on every one of them, on the strength of one stale
  // failure, and inflate the "uN" health counter while doing it.
  s_ulp_read_failed = false;
}

// One trip through the high-power path, from the battery reading to the flash
// mirror. The coprocessor's sample is used when this trip has one that can be
// trusted, and a direct read is the fallback — which rescues the wake on the
// ESP32-E and, today, cannot on the C6 (see below).
//
// Shared deliberately, and kept as wide as it can be: a board parked on USB runs
// this same function on the same cadence a sleeping one does, so what the bench
// observes is what the field executes. A second copy of the sequence would mean
// iterating against code the deployed device never runs. The only thing the
// window is allowed to differ in is window management itself — the park in place
// of the sleep, and the wake sources that go with it.
static void run_wake_cycle(bool ulp_sample_available)
{
  const uint32_t battery_mv = read_battery_level();

  // Shared even though it can only fire on battery: both of its arms require
  // VBUS to be absent, so inside a window it is a no-op by construction. Running
  // it anyway keeps the parked path honest rather than quietly shorter.
  handle_permanent_shutdown(battery_mv);

  // Reachable only on the very first trip, which is always a real boot — a
  // parked cycle cannot precede setup()'s own. Kept here so the order a first
  // boot runs in (battery, shutdown, first-boot, then measure) is the order this
  // function defines, not one split across two call sites.
  if (boot_count == 1)
  {
    initialize_status_led();
    on_first_boot();
    clear_status_led(); // TODO: double check that this stops drawing power
  }

#ifdef MOCK_DISPLAY_DATA
  // Fill mock data if history is empty (handles both first boot and stale RTC
  // memory after firmware upload without power-cycle)
  if (historical_data.temp_count == 0)
  {
    time_t mock_now;
    struct tm mock_nowtm;
    get_time(&mock_now, &mock_nowtm);
    fill_mock_data(mock_now);
    // Force display refresh by invalidating previous_temp
    previous_temp = TEMP_NO_PREVIOUS;
  }
#endif

  float temp;
  if (ulp_sample_available && sensor.SupportsUlp())
  {
    crash_log.stage = STAGE_ULP_READ;
    if (sensor.ReadUlpTemperature(&temp, previous_temp))
    {
      last_sensor_ok = true;
      wake_work(battery_mv, temp);
      return;
    }

    // ULP I2C error, or a reading the driver rejected — fall through to a direct
    // read, which rescues the wake on the ESP32-E, where release_i2c_pins_to_hp()
    // hands the bit-banged pins back.
    //
    // It does not rescue it on the C6 today. lp_core_i2c_master_init() calls
    // rtc_gpio_init() on the shared pins, which sets their LP_AON_GPIO_MUX_SEL bit
    // and routes the pads out of the digital GPIO domain, where the HP I2C driver
    // cannot reach them — measured, with the LP core reading the sensor on 28 of 30
    // cycles while every CPU-side read failed. ulp_lp_core_stop() is no help: it
    // halts the core and touches no GPIO or I2C register.
    //
    // rtc_gpio_deinit() on both pins clears that bit and hands the pads back, which
    // is the same call the FSM path above already makes. Not done here yet: it is
    // unverified on this board, and on the C6 rtc_gpio_deinit() also force-disables
    // the shared LP IO clock gate under an open IDF TODO (IDF-14951), which may
    // disturb other LP peripherals. Until that is tested, recovery runs through the
    // coprocessor, whose reading is accepted above — it reports an absent sensor as
    // a NACK, which is the failure that matters. The gap left is a bus that ACKs
    // without being the sensor.
    last_sensor_ok = false;
    sensor.StopUlp();
    s_ulp_read_failed = true;
  }

  crash_log.stage = STAGE_SENSOR;
  temp = read_temperature();
  wake_work(battery_mv, temp);
}

void setup()
{
  // Must run before anything that can light-sleep (see s_wake_cause).
  s_wake_causes_raw = app_wakeup_causes_raw();
  s_wake_cause = app_wakeup_cause();

#ifdef HAS_USB_SERVICE_WINDOW
  // Also before anything that can light-sleep, and for the same reason the EPD
  // busy-wait cannot use it while serving a host: light sleep gates the USB PHY
  // clock and the port may not come back without replugging the cable. This wake
  // may well render before start_deep_sleep() ever asks whether a host is there
  // — the first frame after a reflash always does — and a light sleep inside
  // that render would have killed the port before the question was put, on
  // exactly the boot the window exists to cover.
  if (vbus_present())
    display_set_busy_wait_plain(true);
#endif

  setup_serial();
  crash_forensics_on_boot();

#if defined(HAS_ULP_SUPPORT) && defined(SOC_ULP_FSM_SUPPORTED)
  ulp_check_data_overlap();  // abort immediately if ULP data overlaps RTC variables
#endif

#ifdef PPK2_DEBUG
  gpio_out_init(PPK2_PIN_CPU_ACTIVE);
  gpio_out_init(PPK2_PIN_DISPLAY);
#endif
  // Before the fingerprint, not after: a marker raised afterwards excludes the
  // fingerprint plus everything earlier in startup. Measured on the C6 ePaper rig,
  // raising it late hid ~450ms at 10-20mA (~5-9 mC) from every wake figure the
  // marker bounded.
  PPK2_CPU_ACTIVE_HIGH();
#ifdef PPK2_DEBUG
  ppk2_selftest();
  PPK2_CPU_ACTIVE_HIGH();     // the fingerprint leaves the pad low
#endif

  // Detect stale RTC memory from a different firmware version.
  // Three checks: version tag mismatch (format changed), address shift
  // (linker moved the struct due to other RTC variable changes), and
  // state version mismatch (non-history RTC variables changed).
  if (historical_data.version != RTC_HISTORY_VERSION ||
      historical_data.self_addr != (uint32_t)&historical_data)
  {
    if (historical_data.version != RTC_HISTORY_VERSION)
      LOGI("RTC history version mismatch — resetting history");
    else
      LOGI("RTC history address shifted (was 0x%08x, now 0x%08x) — resetting history",
           (unsigned)historical_data.self_addr, (unsigned)(uint32_t)&historical_data);
    reset_rtc_history();
    reset_rtc_state();
    restore_history_from_flash();  // must run last: reset_rtc_state() would
                                   // otherwise clobber the restored drift block
  }
  else if (rtc_state_version != RTC_STATE_VERSION)
  {
    LOGI("RTC state version mismatch — resetting state (history preserved)");
    reset_rtc_state();
    restore_drift_from_flash();  // history survived; the drift block did not
  }

  begin_wake_cycle();
  // CPU frequency is fixed at 80 MHz at build time (CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ)
  // — replaces the Arduino-era setCpuFrequencyMhz(80) on non-first boots.

  LOGI("Boot count: %d [%s] rig %s sizeof(TempReading)=%d sizeof(time_t)=%d",
       boot_count, GIT_HASH, RIG_NAME, (int)sizeof(TempReading), (int)sizeof(time_t));

  // Diagnostic: dump sparkline buffer to detect packed struct corruption
  if (historical_data.temp_count > 0)
  {
    LOGI("Sparkline: count=%d", historical_data.temp_count);
    for (int i = 0; i < historical_data.temp_count; i++)
    {
      LOGI("  [%d] ts=%lld temp_x10=%d",
           i,
           (long long)historical_data.temp[i].timestamp,
           (int)historical_data.temp[i].temp_x10);
    }
  }

  esp_sleep_wakeup_cause_t wakeup_cause = s_wake_cause;
  LOGI("Wakeup caused by %d (raw 0x%x)", (int)wakeup_cause, (unsigned)s_wake_causes_raw);

  // Which wakes come up to a coprocessor sample. A cold boot does not — nothing
  // has been sampling — and neither does a reset. A VBUS wake does, and takes
  // that path for the same reason a timer wake does: its sample is at most one
  // period old, and on the C6 a direct read cannot succeed while the LP core owns
  // the I2C pins, so falling through would paint "! SENSOR" on a wake where
  // nothing is wrong.
  const bool ulp_sample_available =
      (wakeup_cause == ESP_SLEEP_WAKEUP_ULP || wakeup_cause == ESP_SLEEP_WAKEUP_TIMER ||
       wakeup_cause == ESP_SLEEP_WAKEUP_GPIO);

  run_wake_cycle(ulp_sample_available);
  start_deep_sleep();
}

extern "C" void app_main(void)
{
  setup(); // deep-sleeps at the end; never returns
}
