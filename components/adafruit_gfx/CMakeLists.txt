# Adafruit GFX core from the pinned upstream submodule (no local copy).
# Only the GFX base + fonts — no SPITFT/BusIO (unused; stub headers in
# arduino_shim satisfy the includes). WProgram.h in arduino_shim covers the
# pre-ARDUINO-macro include fallback, so upstream stays unpatched.
if(NOT EXISTS ${COMPONENT_DIR}/upstream/Adafruit_GFX.cpp)
    message(FATAL_ERROR "Missing components/adafruit_gfx/upstream — run: git submodule update --init")
endif()

idf_component_register(
    SRCS "upstream/Adafruit_GFX.cpp"
    INCLUDE_DIRS "upstream"
    REQUIRES arduino_shim
)

# Third-party code — don't let new-toolchain warnings (IDF 6 defaults to
# warnings-as-errors) break the build
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
