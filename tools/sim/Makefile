PROJECT_ROOT := $(shell git -C $(dir $(lastword $(MAKEFILE_LIST))) rev-parse --show-toplevel)
GFX_LIB := $(PROJECT_ROOT)/.pio/libdeps/dfrobot_firebeetle2_esp32e_debug/Adafruit GFX Library

CXX := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wno-unused-parameter -DARDUINO=200

# Include paths: stubs first (to override Arduino.h), then project headers, then GFX lib
INCLUDES := \
	-I$(CURDIR)/stubs \
	-I$(PROJECT_ROOT)/include \
	-I"$(GFX_LIB)" \
	-I"$(GFX_LIB)/Fonts"

TARGET := render_display

.PHONY: all clean render

all: $(TARGET)

$(TARGET): sim_main.cpp $(PROJECT_ROOT)/src/DisplayRenderer.cpp \
           $(wildcard $(PROJECT_ROOT)/include/*.h) $(wildcard stubs/*.h)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ \
		sim_main.cpp \
		$(PROJECT_ROOT)/src/DisplayRenderer.cpp \
		"$(GFX_LIB)/Adafruit_GFX.cpp"

render: $(TARGET)
	cd $(PROJECT_ROOT) && tools/sim/$(TARGET) $(SIZES)

screenshots: $(TARGET)
	cd $(PROJECT_ROOT) && tools/sim/$(TARGET)

clean:
	rm -f $(TARGET)
