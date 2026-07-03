# HULP drives the ESP32 ULP FSM only — register as an empty component on
# LP-core targets (all components/ dirs enter the build graph regardless).
if(NOT IDF_TARGET STREQUAL "esp32")
    idf_component_register()
    return()
endif()

set(include_dirs
    "src"
)

set(srcs
    "src/hulp.c"
    "src/hulp_touch.c"
    "src/hulp_uart.c"
    "src/hulp_regwr.c"
    "src/hulp_debug.c"
)

set(requires
    ulp
    driver
    soc
    hal
)

idf_component_register(
    INCLUDE_DIRS "${include_dirs}"
    SRCS "${srcs}"
    REQUIRES "${requires}"
)
