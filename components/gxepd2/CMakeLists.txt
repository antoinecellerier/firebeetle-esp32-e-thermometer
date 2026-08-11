# GxEPD2 from the pinned upstream submodule (no local copy). All panel headers
# ship (GxEPD2_BW.h includes every one), but
# only the base driver + the panels selectable in local-secrets.h compile —
# add the matching .cpp here when enabling a new USE_* panel.
if(NOT EXISTS ${COMPONENT_DIR}/upstream/src/GxEPD2_EPD.cpp)
    message(FATAL_ERROR "Missing components/gxepd2/upstream — run: git submodule update --init")
endif()

set(srcs
    "upstream/src/GxEPD2_EPD.cpp"
    "upstream/src/epd/GxEPD2_154_M09.cpp"
    "upstream/src/epd/GxEPD2_213_M21.cpp"
    "upstream/src/epd/GxEPD2_290_I6FD.cpp"
    "upstream/src/epd3c/GxEPD2_154_Z90c.cpp"
    "upstream/src/gdey/GxEPD2_154_GDEY0154D67.cpp"
    "upstream/src/gdeh/GxEPD2_576_GDEH0576T81.cpp"
)

idf_component_register(
    SRCS ${srcs}
    INCLUDE_DIRS "upstream/src"
    REQUIRES arduino_shim adafruit_gfx
)

# Third-party code — don't let new-toolchain warnings (IDF 6 defaults to
# warnings-as-errors) break the build
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
