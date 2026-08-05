#pragma once
// Pins the simulator's rig, shadowing include/generated/rig_config.h because
// -Istubs precedes -Iinclude and device-config.h resolves this by include path.
//
// The sim renders every panel size from one binary, so it compiles exactly one
// DISPLAY_HAS_RED. Left to follow whichever rig was last built for a device,
// that flag silently went bi-color and the committed screenshots lost their red
// — while docs/sim-fidelity-todo.md still recorded the path as covered. Pin the
// only tri-color rig so the _hot and _lowbat scenarios keep exercising it.
//
// The Makefile defines ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E, which is what this
// rig's cross-check asserts.
#define RIG_NAME "sim"
#include <rigs/firebeetle.h>
