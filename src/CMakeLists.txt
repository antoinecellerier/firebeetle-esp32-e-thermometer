FILE(GLOB_RECURSE app_sources ${CMAKE_CURRENT_SOURCE_DIR}/*.cpp)

# esp_driver_* named explicitly for IDF 5.5/6.0 compatibility (see arduino_shim)
set(priv_reqs esp_driver_gpio esp_driver_i2c esp_adc esp_wifi esp_netif
              esp_event nvs_flash lwip esp_timer ulp esp_hw_support esp_system
              espcoredump arduino_shim adafruit_gfx gxepd2)
if(IDF_TARGET STREQUAL "esp32")
    list(APPEND priv_reqs hulp) # ULP FSM helper, ESP32-E only
endif()

idf_component_register(
    SRCS ${app_sources}
    INCLUDE_DIRS "." "../include"
    PRIV_REQUIRES ${priv_reqs}
)

# Board identity macro, derived from the IDF target (one board per target).
# Legacy Arduino-variant names kept so the #if sites across include/ and src/
# stay unchanged.
if(IDF_TARGET STREQUAL "esp32")
    target_compile_definitions(${COMPONENT_LIB} PUBLIC ARDUINO_DFROBOT_FIREBEETLE_2_ESP32E)
elseif(IDF_TARGET STREQUAL "esp32c6")
    target_compile_definitions(${COMPONENT_LIB} PUBLIC ARDUINO_XIAO_ESP32C6)
else()
    message(FATAL_ERROR "No board mapped to IDF target '${IDF_TARGET}'")
endif()

# Generated fonts: PlatformIO builds refresh these every run via
# scripts/pre_build_fonts.py (which also injects GIT_HASH); for plain idf.py
# builds, generate them once here if missing.
if(NOT EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/../include/generated/font_config.h)
    execute_process(
        COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/../scripts/generate_font.py --all
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/..
    )
endif()

# LP core (ESP32-C6): compile + embed the ULP binary; generates ulp_main.h and
# the _binary_ulp_main_bin_start/end symbols the sensor code consumes.
# ESP32-E uses ULP FSM via HULP (program built at runtime) — no ULP toolchain.
if(CONFIG_ULP_COPROC_TYPE_LP_CORE)
    set(ulp_app_name ulp_main)
    set(ulp_sources "${CMAKE_CURRENT_SOURCE_DIR}/../ulp/lp_core_main.c")
    set(ulp_exp_dep_srcs "sensors/BMP58xSensor.cpp" "sensors/BMP390LSensor.cpp"
                         "sensors/DummySensor.cpp" "Thermometer.cpp")
    ulp_embed_binary(${ulp_app_name} "${ulp_sources}" "${ulp_exp_dep_srcs}")
endif()
