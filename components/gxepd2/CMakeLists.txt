# Vendored GxEPD2 (fork antoinecellerier/GxEPD2#add-gdeh0576t81-support, minus
# demo bitmaps). All panel headers ship (GxEPD2_BW.h includes every one), but
# only the base driver + the panels selectable in local-secrets.h compile —
# add the matching .cpp here when enabling a new USE_* panel.
set(srcs
    "src/GxEPD2_EPD.cpp"
    "src/epd/GxEPD2_154_M09.cpp"
    "src/epd/GxEPD2_213_M21.cpp"
    "src/epd/GxEPD2_290_I6FD.cpp"
    "src/epd3c/GxEPD2_154_Z90c.cpp"
    "src/gdey/GxEPD2_154_GDEY0154D67.cpp"
    "src/gdem/GxEPD2_576_GDEH0576T81.cpp"
)

idf_component_register(
    SRCS ${srcs}
    INCLUDE_DIRS "src"
    REQUIRES arduino_shim adafruit_gfx
)

# Vendored code — don't let new-toolchain warnings (IDF 6 defaults to
# warnings-as-errors) break the build
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
