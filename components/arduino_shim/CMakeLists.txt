# esp_driver_* named explicitly: works on IDF 5.5 and 6.0 (the legacy `driver`
# umbrella no longer pulls the split driver components in on 6.0)
idf_component_register(
    SRCS "arduino_shim.cpp" "spi_shim.cpp"
    INCLUDE_DIRS "include"
    REQUIRES esp_driver_gpio esp_driver_spi esp_timer
)
