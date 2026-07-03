# HULP drives the ESP32 ULP FSM only — register as an empty component on
# LP-core targets (all components/ dirs enter the build graph regardless).
if(NOT IDF_TARGET STREQUAL "esp32")
    idf_component_register()
    return()
endif()

set(include_dirs
    "src"
)

# Only the core + regwr sources — touch/uart/debug helpers are unused by this
# project and pull in peripherals that IDF 6 removed or deprecated.
set(srcs
    "src/hulp.c"
    "src/hulp_regwr.c"
)

set(requires
    ulp
    driver
    soc
    hal
)
if(IDF_VERSION_MAJOR GREATER_EQUAL 6)
    # rtc_io_periph.h moved out of soc into esp_hal_gpio
    list(APPEND requires esp_hal_gpio esp_driver_gpio)
endif()

idf_component_register(
    INCLUDE_DIRS "${include_dirs}"
    SRCS "${srcs}"
    REQUIRES "${requires}"
)

# Vendored code — tolerate new-toolchain deprecation warnings
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
