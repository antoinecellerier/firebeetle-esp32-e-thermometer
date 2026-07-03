FILE(GLOB_RECURSE app_sources ${CMAKE_CURRENT_SOURCE_DIR}/*.cpp)

idf_component_register(
    SRCS ${app_sources}
    INCLUDE_DIRS "." "../include"
    PRIV_REQUIRES driver esp_adc esp_wifi esp_netif esp_event nvs_flash lwip
                  esp_timer ulp esp_hw_support esp_system
)

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
