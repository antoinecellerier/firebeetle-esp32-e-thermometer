#pragma once
// Arduino SPI API over ESP-IDF spi_master, write-only (MISO unused).
// Surface = what GxEPD2 uses: begin/end, beginTransaction(SPISettings)/
// endTransaction, byte transfer(). Per-byte polling transactions with the bus
// acquired for the whole transaction; EPD refresh time dominates the overhead.

#include <cstdint>
#include "driver/spi_master.h"

#define MSBFIRST 1
#define LSBFIRST 0
#define SPI_MODE0 0
#define SPI_MODE1 1
#define SPI_MODE2 2
#define SPI_MODE3 3

class SPISettings {
public:
  SPISettings() : clock(1000000), bitOrder(MSBFIRST), dataMode(SPI_MODE0) {}
  SPISettings(uint32_t clk, uint8_t order, uint8_t mode)
    : clock(clk), bitOrder(order), dataMode(mode) {}
  uint32_t clock;
  uint8_t bitOrder;
  uint8_t dataMode;
};

class SPIClass {
public:
  // No-arg form uses per-target board defaults (GxEPD2 calls begin() itself)
  void begin(int sck = -1, int miso = -1, int mosi = -1, int ss = -1);
  void end();
  void beginTransaction(const SPISettings &settings);
  void endTransaction();
  // Write-buffered: bytes accumulate up to the 64-byte FIFO and go out as one
  // transaction (per-byte transactions made a 78KB framebuffer push take
  // seconds). The bus is write-only here (no MISO), so this returns 0.
  // digitalWrite/digitalRead flush the buffer first — GxEPD2 toggles DC/CS
  // between transfer() calls, and no buffered byte may cross that edge.
  uint8_t transfer(uint8_t data);
  void transfer(void *buf, size_t count);
  void flushPending(); // called from the GPIO shim before any pin change/read

private:
  void ensureDevice(const SPISettings &settings);
  void rawTransmit(const uint8_t *data, size_t count);
  void maybeYield(size_t bytes);

  bool _busInited = false;
  spi_device_handle_t _dev = nullptr;
  uint32_t _devClock = 0;
  uint8_t _devMode = 0xFF;
  uint8_t _pending[64];
  size_t _pendingLen = 0;
  // GxEPD2 pushes whole framebuffers without yielding; count bytes per
  // transaction so IDLE gets scheduled (task WDT) on big pushes
  size_t _bytesSinceYield = 0;
};

extern SPIClass SPI;
