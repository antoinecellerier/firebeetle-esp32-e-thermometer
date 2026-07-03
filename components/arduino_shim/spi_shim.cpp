#include "SPI.h"

#include "sdkconfig.h"
#include "esp_err.h"
// IDF 6 no longer includes FreeRTOS headers from driver headers
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

SPIClass SPI;

// Board default pins for no-arg begin() (GxEPD2 calls SPI.begin() itself).
// Keyed on the IDF target; matches the pins previously used under Arduino.
#if CONFIG_IDF_TARGET_ESP32
#define SPI_DEFAULT_SCK  18 // FireBeetle 2 ESP32-E: Arduino VSPI defaults
#define SPI_DEFAULT_MOSI 23
#elif CONFIG_IDF_TARGET_ESP32C6
#define SPI_DEFAULT_SCK  19 // XIAO ESP32-C6: D8=SCK, D10=MOSI
#define SPI_DEFAULT_MOSI 18
#else
#error "SPI default pins not defined for this target"
#endif

#define SPI_HOST_USED SPI2_HOST

void SPIClass::begin(int sck, int miso, int mosi, int ss)
{
    (void)miso;
    (void)ss; // e-paper is write-only, CS driven as plain GPIO by GxEPD2
    if (_busInited)
        return;

    spi_bus_config_t buscfg = {};
    buscfg.sclk_io_num = (sck >= 0) ? sck : SPI_DEFAULT_SCK;
    buscfg.mosi_io_num = (mosi >= 0) ? mosi : SPI_DEFAULT_MOSI;
    buscfg.miso_io_num = -1;
    buscfg.quadwp_io_num = -1;
    buscfg.quadhd_io_num = -1;
    // No DMA: transfers are 1-64 bytes (GxEPD2 is byte-wise), and skipping the
    // per-transaction DMA descriptor setup makes small polling transfers faster
    ESP_ERROR_CHECK(spi_bus_initialize(SPI_HOST_USED, &buscfg, SPI_DMA_DISABLED));
    _busInited = true;
}

void SPIClass::end()
{
    if (_dev)
    {
        spi_bus_remove_device(_dev);
        _dev = nullptr;
        _devMode = 0xFF;
        _devClock = 0;
    }
    if (_busInited)
    {
        spi_bus_free(SPI_HOST_USED);
        _busInited = false;
    }
}

void SPIClass::ensureDevice(const SPISettings &settings)
{
    if (_dev && _devClock == settings.clock && _devMode == settings.dataMode)
        return;
    if (_dev)
    {
        spi_bus_remove_device(_dev);
        _dev = nullptr;
    }
    spi_device_interface_config_t devcfg = {};
    devcfg.clock_speed_hz = (int)settings.clock;
    devcfg.mode = settings.dataMode;
    devcfg.spics_io_num = -1; // CS managed by GxEPD2 via digitalWrite
    devcfg.queue_size = 1;
    devcfg.flags = SPI_DEVICE_NO_DUMMY;
    ESP_ERROR_CHECK(spi_bus_add_device(SPI_HOST_USED, &devcfg, &_dev));
    _devClock = settings.clock;
    _devMode = settings.dataMode;
}

void SPIClass::beginTransaction(const SPISettings &settings)
{
    if (!_busInited)
        begin();
    ensureDevice(settings);
    // Hold the bus for the whole transaction — cuts per-byte overhead
    ESP_ERROR_CHECK(spi_device_acquire_bus(_dev, portMAX_DELAY));
    _bytesSinceYield = 0;
}

// GxEPD2 pushes whole framebuffers (~78KB on the 5.76" panel) through here in
// a tight loop from the main task, which starves IDLE and trips the task WDT.
// Briefly block every 16KB so IDLE runs; costs ~10ms per full-panel push.
void SPIClass::maybeYield(size_t bytes)
{
    _bytesSinceYield += bytes;
    if (_bytesSinceYield >= 16384)
    {
        _bytesSinceYield = 0;
        vTaskDelay(1);
    }
}

void SPIClass::endTransaction()
{
    flushPending();
    if (_dev)
        spi_device_release_bus(_dev);
}

void SPIClass::rawTransmit(const uint8_t *data, size_t count)
{
    spi_transaction_t t = {};
    t.length = count * 8;
    t.tx_buffer = data;
    spi_device_polling_transmit(_dev, &t);
    maybeYield(count);
}

void SPIClass::flushPending()
{
    if (_pendingLen == 0)
        return;
    size_t n = _pendingLen;
    _pendingLen = 0;
    rawTransmit(_pending, n);
}

uint8_t SPIClass::transfer(uint8_t data)
{
    _pending[_pendingLen++] = data;
    if (_pendingLen == sizeof(_pending))
        flushPending();
    return 0; // write-only bus, nothing to read back
}

void SPIClass::transfer(void *buf, size_t count)
{
    flushPending();
    // Chunk to the non-DMA FIFO limit (64 bytes)
    const uint8_t *p = (const uint8_t *)buf;
    while (count > 0)
    {
        size_t n = count > 64 ? 64 : count;
        rawTransmit(p, n);
        p += n;
        count -= n;
    }
}
