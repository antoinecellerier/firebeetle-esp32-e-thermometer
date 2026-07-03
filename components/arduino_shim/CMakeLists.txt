idf_component_register(
    SRCS "arduino_shim.cpp" "spi_shim.cpp"
    INCLUDE_DIRS "include"
    REQUIRES driver esp_timer
)
