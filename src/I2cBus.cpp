#include "I2cBus.h"

#include "driver/gpio.h"
#include "esp_rom_sys.h"

#define I2C_TIMEOUT_MS 50

bool I2cBus::begin(int sda, int scl, uint32_t hz)
{
    if (_bus)
        return true;
    _hz = hz;
    i2c_master_bus_config_t cfg = {};
    cfg.i2c_port = -1; // auto-select
    cfg.sda_io_num = (gpio_num_t)sda;
    cfg.scl_io_num = (gpio_num_t)scl;
    cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    cfg.glitch_ignore_cnt = 7;
    cfg.flags.enable_internal_pullup = true;
    return i2c_new_master_bus(&cfg, &_bus) == ESP_OK;
}

void I2cBus::end()
{
    if (_dev)
    {
        i2c_master_bus_rm_device(_dev);
        _dev = nullptr;
        _devAddr = 0;
    }
    if (_bus)
    {
        i2c_del_master_bus(_bus);
        _bus = nullptr;
    }
}

i2c_master_dev_handle_t I2cBus::dev(uint8_t addr)
{
    if (!_bus)
        return nullptr;
    if (_dev && _devAddr == addr)
        return _dev;
    if (_dev)
    {
        i2c_master_bus_rm_device(_dev);
        _dev = nullptr;
    }
    i2c_device_config_t dcfg = {};
    dcfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dcfg.device_address = addr;
    dcfg.scl_speed_hz = _hz;
    if (i2c_master_bus_add_device(_bus, &dcfg, &_dev) != ESP_OK)
    {
        _dev = nullptr;
        return nullptr;
    }
    _devAddr = addr;
    return _dev;
}

bool I2cBus::writeReg(uint8_t addr, uint8_t reg, uint8_t value)
{
    i2c_master_dev_handle_t d = dev(addr);
    if (!d)
        return false;
    uint8_t buf[2] = {reg, value};
    return i2c_master_transmit(d, buf, sizeof(buf), I2C_TIMEOUT_MS) == ESP_OK;
}

bool I2cBus::readReg(uint8_t addr, uint8_t reg, uint8_t *buf, size_t len)
{
    i2c_master_dev_handle_t d = dev(addr);
    if (!d)
        return false;
    return i2c_master_transmit_receive(d, &reg, 1, buf, len, I2C_TIMEOUT_MS) == ESP_OK;
}

void i2c_bus_recover(int sda_pin, int scl_pin)
{
    gpio_num_t sda = (gpio_num_t)sda_pin;
    gpio_num_t scl = (gpio_num_t)scl_pin;

    gpio_reset_pin(scl);
    gpio_set_direction(scl, GPIO_MODE_OUTPUT);
    gpio_reset_pin(sda);
    gpio_set_direction(sda, GPIO_MODE_INPUT);
    gpio_set_pull_mode(sda, GPIO_PULLUP_ONLY);

    for (int i = 0; i < 9; i++)
    {
        gpio_set_level(scl, 0);
        esp_rom_delay_us(5);
        gpio_set_level(scl, 1);
        esp_rom_delay_us(5);
        if (gpio_get_level(sda))
            break;
    }
    // Generate STOP condition (SDA low→high while SCL high)
    gpio_set_direction(sda, GPIO_MODE_OUTPUT);
    gpio_set_level(sda, 0);
    esp_rom_delay_us(5);
    gpio_set_level(scl, 1);
    esp_rom_delay_us(5);
    gpio_set_level(sda, 1);
    esp_rom_delay_us(5);
}
