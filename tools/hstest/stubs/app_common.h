#pragma once
// Shadows include/app_common.h, which pulls in the whole IDF. HistoryStore.cpp
// only needs LOGI from it.
#include <stdio.h>
#include <stdint.h>
#define LOGI(str, ...) printf(str "\n", ##__VA_ARGS__)

// HistoryStore times its flash writes; the host harness has no real clock cost.
static inline uint32_t ms_now(void) { return 0; }
// vTaskDelay on device; nothing to yield to here.
static inline void sleep_ms(uint32_t) {}
