// Copy this sample to local-secrets.h to set values

// WiFi configuration
#define MY_WIFI_SSID ""
#define MY_WIFI_PASSWORD ""
// Uncomment to disable wifi at compile time which significantly reduces binary size
// #define DISABLE_WIFI

// Example TZ formats are available at https://github.com/esp8266/Arduino/blob/master/cores/esp8266/TZ.h
// The default value is set for Paris time zone with day light saving time
#define MY_TZ "CET-1CEST,M3.5.0,M10.5.0/3"

// Uncomment to disable serial logging
// #define DISABLE_SERIAL

// Uncomment to disable onboard leds
// #define DISABLE_LEDS

// Uncomment to disable display
// #define DISABLE_DISPLAY

// Select active display
//#define USE_154_Z90 // Tri-Color 200x200 1.54" with 15s full refresh
//#define USE_154_M09 // Bi-Color 200x200 1.54" with partial updates and 0.83s full refresh
#define USE_213_M21 // Bi-Color 212x104 2.13" DES with 3s full refresh

// Select active sensor
//#define USE_DS18B20_PAR
#define USE_BMP390L
// Uncomment to provide current altitude in meters for better calibration of BMP390L chip
//#define CURRENT_ALTITUDE_M 8849 /* example value for top of Everest */