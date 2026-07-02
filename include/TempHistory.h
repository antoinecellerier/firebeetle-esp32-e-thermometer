#pragma once

// 24h sparkline history: append + smart eviction.
//
// The buffer is a linear array ordered oldest→newest. Points are recorded
// delta-triggered (see DISPLAY_TEMP_DELTA in Thermometer.cpp), so density
// varies: sparse when stable, up to one point per ULP poll when noisy. A
// plain drop-oldest ring exhausts 24h coverage during noisy periods (192
// points × 60s ≈ 3.2h), truncating the chart. Instead, when the buffer is
// full:
//   - drop the front point if the window no longer needs it (the next point
//     still provides the pre-window carry-in anchor) — the only path taken
//     in stable periods, identical to drop-oldest;
//   - otherwise drop the interior point with the smallest Visvalingam
//     triangle area (least visual significance), so noisy stretches lose
//     redundant wiggle detail while the chart keeps spanning 24h.
//
// Header-only so the host simulator exercises the exact same code path
// (same pattern as MockData.h).

#include "Display.h"
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

inline void temp_history_remove(TempReading *buf, uint16_t *count, int i)
{
  memmove(&buf[i], &buf[i + 1], (size_t)(*count - 1 - i) * sizeof(TempReading));
  (*count)--;
}

// Make room for one append when the buffer is full.
// Timestamp math stays in the time_t (int64) domain: stored uint32 values are
// promoted, never `now` truncated — pre-NTP `now` can be smaller than 86400.
inline void temp_history_evict(TempReading *buf, uint16_t *count, time_t now)
{
  if (*count < 3)  // defensive; unreachable with TEMP_HISTORY_SIZE >= 3
  {
    temp_history_remove(buf, count, 0);
    return;
  }

  // Front point is expendable if the next one still anchors the chart's
  // left-edge carry-in (i.e. it is itself at or before the window start).
  time_t window_start = now - 86400;
  if ((time_t)buf[1].timestamp <= window_start)
  {
    temp_history_remove(buf, count, 0);
    return;
  }

  // Visvalingam: drop the interior point forming the smallest triangle with
  // its neighbours. Raw units (seconds × temp_x10) — per-axis scaling
  // multiplies every candidate area uniformly, so the ranking is invariant
  // and no normalization is needed. Index 0 (carry-in anchor) and the newest
  // point are never dropped. Ties go to the leftmost (oldest) candidate.
  int best = 1;
  int64_t best_area = INT64_MAX;
  for (int i = 1; i <= *count - 2; i++)
  {
    int64_t dt1 = (int64_t)buf[i].timestamp     - (int64_t)buf[i - 1].timestamp;
    int64_t dt2 = (int64_t)buf[i + 1].timestamp - (int64_t)buf[i - 1].timestamp;
    int64_t dy1 = buf[i].temp_x10     - buf[i - 1].temp_x10;
    int64_t dy2 = buf[i + 1].temp_x10 - buf[i - 1].temp_x10;
    int64_t area = dt1 * dy2 - dt2 * dy1;  // 2× signed triangle area
    if (area < 0) area = -area;
    if (area < best_area)
    {
      best_area = area;
      best = i;
    }
  }
  temp_history_remove(buf, count, best);
}

inline void temp_history_push(TempReading *buf, uint16_t *count, time_t now,
                              uint32_t ts, int16_t temp_x10)
{
  if (*count >= TEMP_HISTORY_SIZE)
    temp_history_evict(buf, count, now);
  buf[(*count)++] = { ts, temp_x10 };
}

// Record a new reading, backfilling on a long gap *and* a meaningful jump:
// anchor the prior flat region so the spline doesn't ramp-interpolate across
// it. Skip when the delta is ≤0.1°C — that's our sampling resolution, not a
// real step, and anchoring it produces a staircase on slow monotonic drift.
inline void temp_history_record(TempReading *buf, uint16_t *count,
                                time_t now, int16_t new_x10)
{
  if (*count > 0)
  {
    const TempReading &prev = buf[*count - 1];
    if (now - (time_t)prev.timestamp > 3600 && abs(new_x10 - prev.temp_x10) >= 2)
      temp_history_push(buf, count, now, (uint32_t)(now - 1), prev.temp_x10);
  }
  temp_history_push(buf, count, now, (uint32_t)now, new_x10);
}
