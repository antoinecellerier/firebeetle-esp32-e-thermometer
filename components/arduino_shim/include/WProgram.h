#pragma once
// Pre-1.0 Arduino header name. Adafruit_GFX.h falls back to this when the
// ARDUINO macro isn't defined at preprocessing time (ours is defined inside
// Arduino.h, not by the build system) — providing it here keeps the vendored
// upstream unpatched.
#include "Arduino.h"
#include "Print.h"
