#pragma once

// The host builds (tools/sim, tools/hstest) pass -DGIT_HASH themselves, so
// theirs wins. Firmware builds read the generated header, which a fresh
// checkout does not have until a generator has run — include/generated/ is
// gitignored.
#if !defined(GIT_HASH) && __has_include("generated/git_hash.h")
#include "generated/git_hash.h"
#endif

#ifndef GIT_HASH
#define GIT_HASH "0000000"
#endif
