#pragma once
// Include-path compat so the unpatched HULP submodule builds across IDF
// versions: IDF 6 moved this header (and the rtc_io_desc table) from soc/
// into esp_hal_gpio. This directory shadows the old path; on IDF < 6
// include_next falls through to the real soc header.
#if __has_include("hal/rtc_io_periph.h")
#include "hal/rtc_io_periph.h"
#else
#include_next "soc/rtc_io_periph.h"
#endif
