# Host test for src/HistoryStore.cpp. Same idea as tools/sim: compile the real
# firmware source natively so the fastest feedback loop doesn't need hardware.
#
#   make            build + run the checks
#   make sample     also emit sample.bin and assert tools/history.py decodes it
#                   to exactly what the C writer produced — this is the gate
#                   that keeps the two implementations on one on-flash format,
#                   so every step below must be able to fail the build

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

# No `>/dev/null` (it hid every FAIL line the CHECK macro prints) and no pipes
# (a pipeline takes its exit status from the last stage, so a traceback in the
# decoder left this target green).
sample: hstest check_sample.py ../history.py
	./hstest sample.bin
	python3 ../history.py dump sample.bin
	@echo
	python3 ../history.py dump sample.bin --drift
	@echo
	python3 check_sample.py sample.bin sample.bin.expect

clean:
	rm -f hstest sample.bin sample.bin.expect
