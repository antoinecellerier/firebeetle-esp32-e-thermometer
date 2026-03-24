# Shelved feature branches

## `feature/dpp-provisioning` — Wi-Fi Easy Connect (DPP)

QR-code-based WiFi provisioning: on first boot with no credentials, the device
displays a QR code on the e-paper. Scanning it with an Android 10+ phone pushes
WiFi credentials to the device via DPP (Device Provisioning Protocol). Credentials
are stored in NVS for subsequent power cycles.

**Status**: Fully working on the ESP32 side. Shelved due to Android UX limitation.

**Why shelved**: Android's Easy Connect requires the phone to be on 2.4GHz WiFi
when scanning (ESP32 doesn't support 5GHz). On dual-band routers with a single
SSID, there's no easy way to force the phone to 2.4GHz — the scan fails with
"Couldn't add device". This makes DPP impractical without router reconfiguration.

**What works**:
- pioarduino lib recompile with `custom_sdkconfig` to enable `CONFIG_ESP_WIFI_DPP_SUPPORT`
- BT and SPIRAM disabled via sdkconfig to recover ~55KB DRAM + remove PSRAM overhead
- QR code rendered on e-paper via `esp_qrcode` APIs
- DPP enrollment flow (init, bootstrap gen, listen, credential receive)
- NVS credential storage and 3-step fallback (hardcoded → NVS → DPP)
- Platform fork fixes for lib recompile (skip flash/SPIRAM auto-detection,
  delete stale per-env sdkconfig, ROM memset linker script)

**Build requirements** (documented in commit message):
- Platform fork `feature/lp-core-ulp-arduino` with lib recompile fixes
- `sdkconfig.custom` with BT/SPIRAM disabled + DPP enabled
- `-Wl,-Tesp32.rom.libc-funcs.ld` in build_flags (ROM memset for recompiled spi_flash)
- `huge_app.csv` partition table (WiFi + DPP exceeds default OTA partition)
- `custom_component_remove` for esp_insights/esp_rainmaker (fail during lib recompile)
- `SOC_LP_CORE_SUPPORTED` guard in `ulp/lp_core_main.c` (lib recompile compiles ULP for all targets)

**Alternatives considered**: WiFiManager (SoftAP + captive portal) would avoid the
band issue and work on iOS, but adds a web server dependency. SmartConfig requires
the Espressif app. Could revisit if Android fixes DPP cross-band support or if the
router is reconfigured with separate 2.4/5GHz SSIDs.
