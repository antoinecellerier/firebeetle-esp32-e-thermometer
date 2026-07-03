#include "SPI.h"

#include "sdkconfig.h"
#include "esp_err.h"

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
    ESP_ERROR_CHECK(spi_bus_initialize(SPI_HOST_USED, &buscfg, SPI_DMA_CH_AUTO));
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
}

void SPIClass::endTransaction()
{
    if (_dev)
        spi_device_release_bus(_dev);
}

uint8_t SPIClass::transfer(uint8_t data)
{
    spi_transaction_t t = {};
    t.length = 8;
    t.flags = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA;
    t.tx_data[0] = data;
    spi_device_polling_transmit(_dev, &t);
    return t.rx_data[0];
}

void SPIClass::transfer(void *buf, size_t count)
{
    if (!count)
        return;
    spi_transaction_t t = {};
    t.length = count * 8;
    t.tx_buffer = buf;
    t.rx_buffer = buf;
    spi_device_polling_transmit(_dev, &t);
}
