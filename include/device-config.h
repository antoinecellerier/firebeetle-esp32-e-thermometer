#pragma once
// Everything the build needs to know about this particular device, in one place.
//
// Two sources, deliberately separate: the rig describes the wired hardware and
// is tracked in git, while local-secrets.h holds credentials and is not. They
// used to be one hand-edited file, which is why flashing the wrong panel or
// sensor config was a per-flash hazard rather than a build error.
//
// Both includes are angle-bracketed so they resolve purely by include path.
// A quoted include would resolve against this file's own directory first and
// always find include/, which the host harnesses cannot override — tools/sim
// pins its own rig (and needs no credentials) by putting stubs/ ahead of
// include/ on the search path.

#include <generated/rig_config.h>  // panel / sensor / power gate / LEDs + RIG_NAME
                                   // written by scripts/gen_rig_config.py from
                                   // custom_rig (platformio.ini) or RIG=<name>
#include <local-secrets.h>         // MY_WIFI_SSID / MY_WIFI_PASSWORD / MY_TZ
                                   // gitignored; see local-secrets-example.h
