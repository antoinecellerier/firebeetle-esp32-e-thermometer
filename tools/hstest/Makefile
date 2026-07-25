# Host test for src/HistoryStore.cpp. Same idea as tools/sim: compile the real
# firmware source natively so the fastest feedback loop doesn't need hardware.
#
#   make            build + run the checks
#   make sample     also emit sample.bin and decode it with tools/history.py
#                   (cross-checks the C writer against the Python reader)

CXXFLAGS := -std=c++17 -g -O1 -Wall -Wextra -Wno-unused-parameter \
            -Istubs -I../../include \
            -DARDUINO_DFROBOT_FIREBEETLE_2_ESP32E -DUSE_BMP390L -DUSE_154_Z90 \
            -DGIT_HASH='"hstest"'

.PHONY: all sample clean
all: hstest
	./hstest

hstest: hstest.cpp ../../src/HistoryStore.cpp ../../include/HistoryStore.h \
        ../../include/RtcHistory.h ../../include/TempHistory.h
	$(CXX) $(CXXFLAGS) -o $@ hstest.cpp

sample: hstest
	./hstest sample.bin >/dev/null
	python3 ../history.py dump sample.bin
	@echo
	python3 ../history.py dump sample.bin --drift | tail -2

clean:
	rm -f hstest sample.bin
