#pragma once

#include <stdint.h>
#include <stdbool.h>

struct DppResult {
    bool success;
    char ssid[33];
    char password[65];
};

// Run DPP (Wi-Fi Easy Connect) enrollment as an enrollee.
// Generates a bootstrap QR code URI, calls display_cb so the caller can
// render it, then listens for a configurator to push WiFi credentials.
// Blocks until connected, failed, or timeout_ms expires.
// WiFi must be initialized in STA mode before calling this.
DppResult run_dpp_provisioning(uint32_t timeout_ms,
                               void (*display_cb)(const char *uri));
