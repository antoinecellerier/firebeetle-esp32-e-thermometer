# HULP (ESP32 ULP FSM helper) from the pinned upstream submodule (no local
# copy). Registers as an empty component on LP-core targets — all components/
# dirs enter the build graph regardless of target.
if(NOT IDF_TARGET STREQUAL "esp32")
    idf_component_register()
    return()
endif()

if(NOT EXISTS ${COMPONENT_DIR}/upstream/src/hulp.c)
    message(FATAL_ERROR "Missing components/hulp/upstream — run: git submodule update --init")
endif()

# Only the core + regwr sources — touch/uart/debug helpers are unused by this
# project and pull in peripherals that IDF 6 removed or deprecated.
# compat/ shadows soc/rtc_io_periph.h, which IDF 6 moved to esp_hal_gpio,
# keeping upstream unpatched.
set(requires ulp driver soc hal)
if(IDF_VERSION_MAJOR GREATER_EQUAL 6)
    list(APPEND requires esp_hal_gpio esp_driver_gpio)
endif()

idf_component_register(
    SRCS "upstream/src/hulp.c" "upstream/src/hulp_regwr.c"
    INCLUDE_DIRS "compat" "upstream/src"
    REQUIRES ${requires}
)

# Third-party code — tolerate new-toolchain deprecation warnings
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
