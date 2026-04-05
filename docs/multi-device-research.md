# Multi-device temperature reporting — research notes

Goal: multiple ESP32 sensor nodes in different rooms / outside, reporting to the
FireBeetle ESP32-E (with EPD) as central display.

## Protocol comparison

All numbers assume 60s reporting interval, 500mAh LiPo, 15µA deep sleep baseline.

### ESP-NOW

- **TX**: ~120mA for ~3ms (connectionless, no handshake)
- **Daily cost**: ~0.5 mAh (0.14 TX + 0.36 sleep)
- **Battery life**: ~2-3 years
- **Boards**: both ESP32-E and C6 (uses WiFi radio)
- **Range**: ~200m line-of-sight, ~30-50m indoors
- **Payload**: 250 bytes per frame (plenty for temp + humidity + battery + device ID)
- **Pros**: lowest latency, simplest code, no infrastructure, broadcast or unicast
- **Cons**: ESP-specific (no phone/tablet interop), no mesh (but can relay manually)

### BLE advertising

- **TX**: ~40mA for ~10ms (extended advertising on BLE 5)
- **Daily cost**: ~0.5 mAh (similar to ESP-NOW for sender)
- **Battery life**: ~2-3 years
- **Boards**: both (BLE 4.2 on ESP32-E, BLE 5 on C6)
- **Pros**: standard protocol, phones can scan directly, BLE 5 long range mode on C6
- **Cons**: receiver must actively scan (higher RX power budget), more code complexity

### Thread / 802.15.4

- **TX**: ~50mA for ~15ms per poll cycle
- **Daily cost**: ~2-5 mAh (Sleepy End Device must poll parent periodically)
- **Battery life**: ~100-250 days
- **Boards**: C6 only (has 802.15.4 radio)
- **Pros**: IP-native mesh, Matter/Home Assistant integration path
- **Cons**: 5-10x worse power than ESP-NOW, needs border router, heavy stack, C6 only

### WiFi + MQTT

- **TX**: ~160mA for ~500ms-2s (association + DHCP + TLS + publish)
- **Daily cost**: ~5-15 mAh
- **Battery life**: ~30-100 days
- **Boards**: both
- **Pros**: standard infrastructure, easy cloud/HA integration, longest range with AP
- **Cons**: worst battery life by far, needs WiFi AP + MQTT broker

### Summary table

| Protocol    | Per-send    | Daily (60s) | Battery life | Both boards | Infrastructure |
|-------------|-------------|-------------|-------------|-------------|----------------|
| ESP-NOW     | ~0.1 µAh   | ~0.5 mAh   | ~2-3 yr     | yes         | none           |
| BLE adv     | ~0.11 µAh  | ~0.5 mAh   | ~2-3 yr     | yes         | none           |
| Thread SED  | ~0.21 µAh  | ~2-5 mAh   | 100-250 d   | C6 only     | border router  |
| WiFi+MQTT   | ~10-80 µAh | ~5-15 mAh  | 30-100 d    | yes         | AP + broker    |


## Master device listening strategies

The fundamental problem: ESP32 cannot monitor its radio during deep sleep. The radio
is completely powered down. Options for the master:

### 1. Wall-powered (simplest)

Master plugs into USB. Always-on WiFi or continuous ESP-NOW/BLE scanning.
No power constraints. Can also bridge to WiFi/MQTT/Home Assistant.

- **Power**: unlimited (USB)
- **Complexity**: lowest
- **Latency**: immediate

### 2. RTC-synced rendezvous windows

Both master and remotes have NTP-calibrated RTCs (project already has adaptive drift
tracking). Remotes send at predictable times. Master wakes ~200ms before expected
transmission, listens for ~500ms, sleeps.

- **Master daily cost**: ~1-2 mAh (short RX windows only)
- **Master battery life**: 250-500 days on 500mAh
- **Complexity**: moderate (clock sync, retry logic for missed windows)
- **Latency**: up to one reporting interval

### 3. Light sleep with radio (C6 best)

ESP32-C6 supports auto light sleep with WiFi or BLE maintained. Chip wakes on
incoming frames automatically.

- **C6 light sleep + BLE**: ~0.5-1 mA → ~20-40 days on 500mAh
- **C6 light sleep + WiFi**: ~0.8-2 mA → ~10-25 days on 500mAh
- **ESP32-E light sleep + WiFi**: ~2-5 mA → ~4-10 days (older silicon)
- **Complexity**: low-moderate
- **Latency**: near-immediate

### 4. External wake-on-radio (WOR) chip

Add a dedicated sub-GHz radio with hardware WOR capability:

| Chip          | WOR current | Range       | Cost |
|---------------|-------------|-------------|------|
| SX1262 (LoRa) | ~1.5 µA    | 1-5 km      | ~$3  |
| CC1101        | ~1 µA       | 100-500 m   | ~$2  |

Radio listens at ~1µA, detects preamble, asserts GPIO interrupt, ESP32 wakes from
deep sleep, receives data via ESP-NOW or SPI from the sub-GHz radio.

- **Master sleep**: ~16 µA total (ESP32 deep sleep + radio WOR)
- **Master battery life**: ~3 years on 500mAh
- **Complexity**: high (extra hardware on both sides, second protocol, PCB work)
- **Latency**: near-immediate


## ESP32-C6 vs ESP32-E for this use case

| Feature                | ESP32-E         | ESP32-C6              |
|------------------------|-----------------|-----------------------|
| WiFi                   | 802.11 b/g/n    | 802.11 b/g/n (+ 6)   |
| BLE                    | 4.2              | 5.0 (long range, ext adv) |
| 802.15.4               | no               | yes (Thread/Zigbee)   |
| LP core                | ULP FSM          | RISC-V LP core + HW I2C |
| Deep sleep             | ~10-15 µA        | ~7-15 µA              |
| Light sleep + BLE      | ~2-5 mA          | ~0.5-1 mA             |
| Light sleep + WiFi     | ~2-5 mA          | ~0.8-2 mA             |

C6 is significantly better for any "listening" role due to lower light sleep current.
For send-only remotes, the difference is marginal since deep sleep dominates.

C6 BLE 5.0 long range mode (coded PHY, 125kbps) can reach ~400m+ LOS vs ~100m for
BLE 4.2 — useful for outdoor sensors.


## What's already in place

- **WiFi + NTP**: working, with adaptive drift tracking (1-28 day resync interval)
- **BLE stack**: compiled into firmware (Bluedroid, GATT server/client) but no app code
- **Deep sleep flow**: wake → read sensor → update display → sleep, with ULP monitoring
- **RTC persistence**: 24h sparkline + 30-day hourly history survives deep sleep
- **Clock drift tracking**: `drift_ppm` calculated from NTP resync — can inform rendezvous accuracy


## Recommendation

**Start with ESP-NOW + wall-powered master.** Reasons:

1. ESP-NOW has the best sender power budget and works on both boards
2. Wall power for the master eliminates the hardest problem (listening efficiently)
3. No infrastructure needed (no router, no broker, no border router)
4. Simple to prototype — ~50 lines of code on each side
5. Can add BLE or WiFi bridging on the master later without changing remotes
6. The master already lives next to the e-paper display in a fixed location

If wall power is truly impossible for the master, the RTC rendezvous approach is the
next best option — the project already has the clock drift infrastructure for it.
