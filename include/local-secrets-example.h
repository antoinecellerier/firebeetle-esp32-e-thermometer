// Copy this sample to local-secrets.h to set values. Credentials only —
// they are the same on every rig, and this file is gitignored.
//
// The hardware description (panel, sensor, power gate, LEDs) lives in a tracked
// rig header instead: see include/rigs/_template.h for the list of options, and
// platformio.ini's custom_rig for how one is selected.

// WiFi configuration
#define MY_WIFI_SSID ""
#define MY_WIFI_PASSWORD ""

// Example TZ formats are available at https://github.com/esp8266/Arduino/blob/master/cores/esp8266/TZ.h
// The default value is set for Paris time zone with day light saving time
#define MY_TZ "CET-1CEST,M3.5.0,M10.5.0/3"

// Bench knobs are build flags, not config — pass them through the environment:
//   PLATFORMIO_BUILD_FLAGS="-DDISABLE_WIFI -DNO_ULP" pio run -e <env>
// DISABLE_SERIAL is already set by [release] in platformio.ini.
