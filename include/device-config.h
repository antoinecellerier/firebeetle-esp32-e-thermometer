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
#include <local-secrets.h>         // MY_WIFI_NETWORKS / MY_TZ
                                   // gitignored; see local-secrets-example.h

// local-secrets.h is untracked, so a rename cannot be applied to the copy on
// someone's disk. Keep the single-network form working by expressing it as a
// one-entry list.
#if !defined(MY_WIFI_NETWORKS) && defined(MY_WIFI_SSID)
#define MY_WIFI_NETWORKS(X) X(MY_WIFI_SSID, MY_WIFI_PASSWORD)
#endif
