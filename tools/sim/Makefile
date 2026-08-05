PROJECT_ROOT := $(shell git -C $(dir $(lastword $(MAKEFILE_LIST))) rev-parse --show-toplevel)
GFX_LIB := $(PROJECT_ROOT)/components/adafruit_gfx/upstream

CXX := g++
# Same command scripts/gen_git_hash.py stamps the firmware with, so the
# indicator line renders at its real width instead of the 0000000 fallback.
# Passed as -D: include/git_hash.h yields to a value already defined, so the
# simulator never picks up a device build's stamp.
GIT_HASH := $(shell git -C $(PROJECT_ROOT) describe --always --dirty 2>/dev/null || echo unknown)
CXXFLAGS := -std=c++17 -O2 -Wall -Wno-unused-parameter -DARDUINO=200 -DSLEEP_INTERVAL_S=5 -DARDUINO_DFROBOT_FIREBEETLE_2_ESP32E -DGIT_HASH='"$(GIT_HASH)"'

INCLUDES := \
	-I$(CURDIR)/stubs \
	-I$(PROJECT_ROOT)/include \
	-I"$(GFX_LIB)" \
	-I"$(GFX_LIB)/Fonts"

TARGET := render_display
FONT_SCRIPT := $(PROJECT_ROOT)/scripts/generate_font.py
FONT_STAMP := $(PROJECT_ROOT)/include/generated/.stamp
FONT_CONFIG := $(PROJECT_ROOT)/include/generated/font_config.h

.PHONY: all clean render screenshots

all: $(TARGET)

# Generate fonts when the script changes, stamp is missing, or PIO
# overwrote font_config.h (single-display mode clobbers --all output)
$(FONT_STAMP): $(FONT_SCRIPT) $(FONT_CONFIG)
	python3 $(FONT_SCRIPT) --all
	touch $@

# Both extensions: include/ carries .h and .hpp, and a glob that misses one lets
# `make screenshots` render PNGs from a binary built against the older header.
$(TARGET): $(FONT_STAMP) sim_main.cpp $(PROJECT_ROOT)/src/DisplayRenderer.cpp \
           $(wildcard $(PROJECT_ROOT)/include/*.h) $(wildcard $(PROJECT_ROOT)/include/*.hpp) \
           $(wildcard $(PROJECT_ROOT)/include/sensors/*.hpp) \
           $(wildcard $(PROJECT_ROOT)/include/generated/*.h) \
           $(wildcard stubs/*.h) $(wildcard stubs/*.hpp)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ \
		sim_main.cpp \
		$(PROJECT_ROOT)/src/DisplayRenderer.cpp \
		"$(GFX_LIB)/Adafruit_GFX.cpp"

render: $(TARGET)
	cd $(PROJECT_ROOT) && tools/sim/$(TARGET) $(SIZES)

screenshots: $(TARGET)
	cd $(PROJECT_ROOT) && tools/sim/$(TARGET)

clean:
	rm -f $(TARGET) $(FONT_STAMP)
