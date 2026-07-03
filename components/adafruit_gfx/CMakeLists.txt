# Vendored Adafruit GFX core (pinned from the former Arduino lib_deps checkout).
# Only the GFX base + fonts — no SPITFT/BusIO (unused by this project).
idf_component_register(
    SRCS "Adafruit_GFX.cpp"
    INCLUDE_DIRS "."
    REQUIRES arduino_shim
)
