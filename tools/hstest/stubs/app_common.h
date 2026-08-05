#pragma once
// Shadows include/app_common.h, which pulls in the whole IDF. HistoryStore.cpp
// only needs LOGI from it.
#include <stdio.h>
#include <stdint.h>
#define LOGI(str, ...) printf(str "\n", ##__VA_ARGS__)

// Stamped into every drift record. A host build is not a device running a bench
// arm, so this is 0 unless a test overrides it on the command line to exercise
// the round-trip: make CXXFLAGS='-DEXPERIMENT_ARM=7'
#ifndef EXPERIMENT_ARM
#define EXPERIMENT_ARM 0
#endif

// HistoryStore times its flash writes; the host harness has no real clock cost.
static inline uint32_t ms_now(void) { return 0; }
// vTaskDelay on device; nothing to yield to here.
static inline void sleep_ms(uint32_t) {}
