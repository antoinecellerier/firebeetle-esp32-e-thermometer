#pragma once
// Shadows include/app_common.h, which pulls in the whole IDF. HistoryStore.cpp
// only needs LOGI from it.
#include <stdio.h>
#include <stdint.h>
#define LOGI(str, ...) printf(str "\n", ##__VA_ARGS__)
