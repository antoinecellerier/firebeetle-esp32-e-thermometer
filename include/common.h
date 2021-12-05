#pragma once

// See local-secrets-example.h for a sample file if local-secrets.h is missing
#include "local-secrets.h"

// TODO: Figure out how to get proper logging facilities working (probably after switching to platformio)
#ifndef DISABLE_SERIAL
#define LOGI(str, ...) Serial.printf(str "\n", ##__VA_ARGS__)
#else
#define LOGI(...)
#endif
