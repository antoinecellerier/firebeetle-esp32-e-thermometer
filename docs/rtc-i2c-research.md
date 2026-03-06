# ESP32 RTC I2C + ULP Coprocessor: Hardware Research

Research document for debugging ULP I2C communication with BMP390L sensor.
All findings sourced from manufacturer datasheets, SDK headers, and reference
implementations. Sources cited inline.

## 1. ESP32 RTC I2C Controller

### 1.1 What the RTC I2C controller is

The ESP32 contains a dedicated I2C controller in the RTC domain, separate from
the two main I2C peripherals. It exists specifically for ULP coprocessor use.
From the ESP-IDF register header (`soc/esp32/include/soc/rtc_i2c_reg.h`):

> This file lists peripheral registers of an I2C controller which is part of
> the RTC. ULP coprocessor uses this controller to implement I2C_RD and I2C_WR
> instructions.
>
> Part of the functionality of this controller (such as slave mode, and
> multi-byte transfers) is not wired to the ULP, and is such, is not available
> to the ULP programs.

Key limitation: single-byte reads/writes only. Each `I2C_RD`/`I2C_WR`
instruction performs one complete I2C transaction: START → addr+R/W → sub_addr
→ data byte → STOP. This matches the BMP390L's register access protocol.

### 1.2 Register map (ESP32, from SDK header)

All offsets from `DR_REG_RTC_I2C_BASE`:

| Offset | Register                    | Key fields |
|--------|-----------------------------|------------|
| 0x000  | `RTC_I2C_SCL_LOW_PERIOD`    | [19:0] SCL low time in RTC_FAST_CLK cycles |
| 0x004  | `RTC_I2C_CTRL`              | See §1.3 |
| 0x008  | `RTC_I2C_DEBUG_STATUS`      | [4] BUS_BUSY, [3] ARB_LOST, [2] TIMED_OUT, [0] ACK_VAL |
| 0x00c  | `RTC_I2C_TIMEOUT`           | [19:0] max FAST_CLK cycles per transaction |
| 0x010  | `RTC_I2C_SLAVE_ADDR`        | Local slave address (unused in master mode) |
| 0x01c  | `RTC_I2C_DATA`              | Last read result (also returned in R0) |
| 0x020  | `RTC_I2C_INT_RAW`           | Raw interrupt status |
| 0x024  | `RTC_I2C_INT_CLR`           | Interrupt clear |
| 0x028  | `RTC_I2C_INT_EN`            | Interrupt enable |
| 0x02c  | `RTC_I2C_INT_ST`            | Masked interrupt status |
| 0x030  | `RTC_I2C_SDA_DUTY`          | [19:0] SDA switch delay after SCL falling edge |
| 0x038  | `RTC_I2C_SCL_HIGH_PERIOD`   | [19:0] SCL high time |
| 0x040  | `RTC_I2C_SCL_START_PERIOD`  | [19:0] wait after START |
| 0x044  | `RTC_I2C_SCL_STOP_PERIOD`   | [19:0] wait before STOP |

Source: `~/.platformio/.../soc/esp32/include/soc/rtc_i2c_reg.h`

### 1.3 CTRL register bit layout (ESP32 ONLY)

**⚠️ Different ESP32 variants have DIFFERENT bit positions.** The ESP32-S2/S3
headers place MS_MODE at bit 2, CLK_EN at bit 31, etc. Our ESP32 header:

| Bit | Field             | Default | Description |
|-----|-------------------|---------|-------------|
| 7   | RX_LSB_FIRST      | 0       | Receive LSB first (0=MSB first) |
| 6   | TX_LSB_FIRST      | 0       | Transit LSB first (0=MSB first) |
| 5   | TRANS_START        | 0       | Force start condition |
| 4   | **MS_MODE**        | 0       | **1=master, 0=slave** |
| 3:2 | (unused)           |         | |
| 1   | SCL_FORCE_OUT      | 0       | 1=push-pull, **0=open-drain** |
| 0   | SDA_FORCE_OUT      | 0       | 1=push-pull, **0=open-drain** |

Source: `soc/esp32/include/soc/rtc_i2c_reg.h`, `RTC_I2C_MS_MODE_S = 4`

**Critical:** Open-drain (default 0) is correct for standard I2C. Push-pull
would prevent the slave from pulling SDA low for ACK.

### 1.4 Pin selection

The RTC I2C controller supports two pin pairs, selected via
`RTC_IO_SAR_I2C_IO_REG`:

| Selection | SCL pin | SDA pin |
|-----------|---------|---------|
| 0         | GPIO4 (TOUCH_PAD0 / RTC_GPIO10) | GPIO0 (TOUCH_PAD1 / RTC_GPIO11) |
| 1         | GPIO2 (TOUCH_PAD2 / RTC_GPIO12) | GPIO15 (TOUCH_PAD3 / RTC_GPIO13) |

We use Selection 0: `SDA_SEL=0, SCL_SEL=0`.

Source: ESP-IDF ULP instruction set docs, `soc/rtc_io_reg.h`

### 1.5 Slave address registers

Slave addresses are stored in `SENS_SAR_SLAVE_ADDRx_REG` registers:

| Register               | ADDR0 (bits [21:11]) | ADDR1 (bits [10:0]) |
|------------------------|----------------------|---------------------|
| SENS_SAR_SLAVE_ADDR1   | Slot 0               | Slot 1              |
| SENS_SAR_SLAVE_ADDR2   | Slot 2               | Slot 3              |
| ...                    | Slot 4-7             | ...                 |

Each field is 11 bits wide. The official ULP instruction set documentation
states:

> Slave address **(in 7-bit format)** has to be set in advance into
> `SENS_I2C_SLAVE_ADDRx` register field.

Source: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/ulp_instruction_set.html

**The HULP library (`hulp.c:hulp_register_i2c_slave()`) does NOT shift the
address — it passes the 7-bit value directly.** Our address 0x77 should be
written as-is.


## 2. ULP I2C Instructions

### 2.1 I2C_RD instruction

Assembly syntax: `I2C_RD sub_addr, high_bit, low_bit, slave_sel`

C macro: `I_I2C_RW(sub_addr, val, low_bit, high_bit, slave_sel, SUB_OPCODE_I2C_RD)`

The instruction:
1. Sends START condition
2. Sends slave address (from selected SENS register) + WRITE bit
3. Sends sub_addr (register address)
4. Sends repeated START
5. Sends slave address + READ bit
6. Reads one byte
7. Sends STOP condition
8. Stores bits [high_bit:low_bit] of the read byte into R0

### 2.2 CONFIRMED BUG: `I_I2C_READ` macro

From `ulp/include/esp32/ulp.h` line 1032:

```c
#define I_I2C_READ(slave_sel, sub_addr) \
    I_I2C_RW(sub_addr, 0, 0, 0, slave_sel, SUB_OPCODE_I2C_RD)
//                          ^  ^
//                    low=0, high=0 → reads ONLY bit 0!
```

Compare with `I_I2C_WRITE` which correctly uses `high_bit=7`:

```c
#define I_I2C_WRITE(slave_sel, sub_addr, val) \
    I_I2C_RW(sub_addr, val, 0, 7, slave_sel, SUB_OPCODE_I2C_WR)
```

**Fix (already in our code):**
```c
#define I_I2C_READ_BYTE(slave_sel, sub_addr) \
    I_I2C_RW(sub_addr, 0, 0, 7, slave_sel, SUB_OPCODE_I2C_RD)
```

Source: ESP-IDF SDK header, confirmed by ULP instruction set docs which show
`I2C_RD 0x10, 7, 0, 0` for full byte reads.

### 2.3 ULP clock and I_DELAY timing

From the official ULP docs:

> ULP coprocessor is clocked from `RTC_FAST_CLK`, which is normally derived
> from the internal **8 MHz** oscillator.

The `I_DELAY(cycles)` / `WAIT` instruction takes `(2 + cycles)` clock cycles
at RTC_FAST_CLK frequency.

**⚠️ Our current delay is WRONG:**
```
I_DELAY(750) at 8 MHz = 752 / 8,000,000 = 94 µs
```

We wrote "750 cycles ≈ 5ms" assuming RTC_SLOW_CLK at 150 kHz. The ULP runs
on RTC_FAST_CLK at 8 MHz. For a 5ms delay:

```
5ms × 8 MHz = 40,000 cycles → I_DELAY(40000)
```

The `cycles` field is 16 bits (max 65535 ≈ 8.2ms), so 40000 fits.

**This doesn't explain the I2C hang** (the hang occurs on the first I2C
instruction, before the delay), but it would cause wrong temperature readings.

Source: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/ulp_instruction_set.html

### 2.4 WAKE instruction requires readiness check

From the official ULP docs:

> Before using WAKE instruction, ULP program may need to wait until RTC
> controller is ready to wake up the main CPU. This is indicated using
> `RTC_CNTL_RDY_FOR_WAKEUP` bit of `RTC_CNTL_LOW_POWER_ST_REG` register.
> If WAKE instruction is executed while `RTC_CNTL_RDY_FOR_WAKEUP` is zero,
> **it has no effect** (wake up does not occur).

The wardjm reference implementation includes this check; we don't. This isn't
the hang cause, but could explain unreliable wakes.


## 3. Pin Configuration: Comparison of Approaches

### 3.1 wardjm example (KNOWN WORKING — uses assembly)

From `wardjm/esp32-ulp-i2c`, the Arduino-side init:

```c
// Uses pin pair 1 (GPIO2/GPIO15)
SET_PERI_REG_BITS(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SDA_SEL, 1, ...);
SET_PERI_REG_BITS(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SCL_SEL, 1, ...);

// Initialize ALL FOUR I2C pins as RTC GPIO
rtc_gpio_init(GPIO_NUM_0);
rtc_gpio_init(GPIO_NUM_4);
rtc_gpio_init(GPIO_NUM_2);
rtc_gpio_init(GPIO_NUM_15);

// Direction: INPUT_OUTPUT (standard push-pull, NOT OD)
rtc_gpio_set_direction(GPIO_NUM_15, RTC_GPIO_MODE_INPUT_OUTPUT);
rtc_gpio_set_direction(GPIO_NUM_4, RTC_GPIO_MODE_INPUT_OUTPUT);
rtc_gpio_set_direction(GPIO_NUM_2, RTC_GPIO_MODE_INPUT_OUTPUT);
rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_OUTPUT);

// Standard timing + master mode + address
WRITE_PERI_REG(RTC_I2C_SCL_LOW_PERIOD_REG, 40);
// ... (same timing values as ours)
SET_PERI_REG_BITS(RTC_I2C_CTRL_REG, RTC_I2C_MS_MODE, 1, RTC_I2C_MS_MODE_S);
SET_PERI_REG_BITS(SENS_SAR_SLAVE_ADDR1_REG, SENS_I2C_SLAVE_ADDR0, 0x5a, ...);
```

**Key observations:**
- **NO FUN_SEL=3.** Pins left at FUN_SEL=0 (default RTC function after `rtc_gpio_init`).
- **INPUT_OUTPUT direction** (not INPUT_ONLY, not OD).
- **No pullup/pulldown configuration** (relies on external or default).
- Uses `WRITE_PERI_REG` (writes entire register, not just a field).
- I2C config is also repeated FROM WITHIN the ULP assembly program.
- Includes `RDY_FOR_WAKEUP` check before WAKE.

Source: https://github.com/wardjm/esp32-ulp-i2c

### 3.2 HULP library (KNOWN WORKING — C API)

From `boarchuz/HULP` `hulp.c`:

```c
#define RTCIO_FUNC_RTC_I2C 0x3

esp_err_t hulp_configure_i2c_pins(gpio_num_t scl_pin, gpio_num_t sda_pin, ...) {
    // For each pin:
    hulp_configure_pin(pin, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0);
    //   internally does:
    //     rtc_gpio_set_direction(pin, DISABLED)
    //     rtc_gpio_init(pin)              ← sets FUN_SEL=0
    //     gpio_set_pull_mode(pin, PULLUP)
    //     rtc_gpio_set_level(pin, 0)
    //     rtc_gpio_set_direction(pin, INPUT_ONLY)

    // THEN set FUN_SEL=3 (overriding the 0 from rtc_gpio_init):
    SET_PERI_REG_BITS(rtc_io_desc[rtcio_num].reg,
                      RTC_IO_TOUCH_PAD1_FUN_SEL_V,
                      RTCIO_FUNC_RTC_I2C,
                      rtc_io_desc[rtcio_num].func);

    // Pin pair selection
    REG_SET_FIELD(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SCL_SEL, ...);
    REG_SET_FIELD(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SDA_SEL, ...);
}
```

Controller config (`hulp_configure_i2c_controller`):
```c
// Defaults: open-drain, MSB-first, master, timeout=200
REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_SCL_FORCE_OUT, 0);  // open-drain
REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_SDA_FORCE_OUT, 0);  // open-drain
REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_MS_MODE, 1);        // master
// + timing registers same as ours
// Default timeout: 200 (vs our 10000)
```

Slave address (`hulp_register_i2c_slave`):
```c
// NO SHIFT — passes 7-bit address directly
SET_PERI_REG_BITS(SENS_SAR_SLAVE_ADDR1_REG + ...,
                  SENS_I2C_SLAVE_ADDR0, address, ...);
```

**Key observations:**
- **FUN_SEL=3** explicitly set AFTER `rtc_gpio_init()` (which resets to 0).
- **INPUT_ONLY direction** — I2C peripheral handles output driving.
- **Pullups enabled** via `gpio_set_pull_mode()`.
- **Explicitly configures FORCE_OUT bits** (open-drain).
- Timeout = 200 (much shorter than our 10000).
- Address NOT shifted.

Source: https://github.com/boarchuz/HULP/blob/master/src/hulp.c

### 3.3 Our current code (NOT WORKING)

```c
rtc_gpio_init(GPIO_NUM_0);
rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_OUTPUT_OD);
rtc_gpio_pullup_en(GPIO_NUM_0);
rtc_gpio_pulldown_dis(GPIO_NUM_0);
REG_SET_BIT(RTC_IO_TOUCH_PAD1_REG, RTC_IO_TOUCH_PAD1_MUX_SEL);
REG_SET_FIELD(RTC_IO_TOUCH_PAD1_REG, RTC_IO_TOUCH_PAD1_FUN_SEL, 3);
// (same for GPIO4)

SET_PERI_REG_BITS(RTC_I2C_CTRL_REG, RTC_I2C_MS_MODE, 1, RTC_I2C_MS_MODE_S);
// timing via REG_SET_FIELD
// address 0x77, no shift
```

**Differences from both working implementations:**
- Uses `INPUT_OUTPUT_OD` (neither implementation uses this)
- Doesn't explicitly set `SCL_FORCE_OUT`/`SDA_FORCE_OUT`
- Digital I2C (Wire/TwoWire) not released before RTC I2C config
- `MUX_SEL` redundantly set (already done by `rtc_gpio_init`)


## 4. Critical Differences Analysis

### 4.1 FUN_SEL: 0 vs 3

This is the biggest discrepancy between the two working implementations:

| Implementation | FUN_SEL | Works? |
|---------------|---------|--------|
| wardjm        | 0 (default from rtc_gpio_init) | ✅ Yes |
| HULP          | 3 (explicitly set)             | ✅ Yes |
| Our code      | 3 (explicitly set)             | ❌ Hangs |

From the ESP32 SDK header (`hal/rtc_io_ll.h`):
```c
#define RTCIO_LL_PIN_FUNC  0  // used by rtc_gpio_init
// Comment: "0:RTC FUNCTION 1,2,3:Reserved"
```

The SDK considers FUN_SEL values 1-3 as "Reserved". The HULP library
defines `RTCIO_FUNC_RTC_I2C = 0x3` as a custom constant not present in the
SDK.

**Hypothesis:** The RTC I2C controller may have a dedicated internal connection
to the GPIO pins that's independent of FUN_SEL. The `SAR_I2C_IO_REG` pin
selection register directly routes the I2C signals, and FUN_SEL=0 (basic RTC
function) might be sufficient. FUN_SEL=3 might even conflict.

**Action: Try FUN_SEL=0 (remove our FUN_SEL=3 override).**

### 4.2 Pin direction

| Implementation | Direction          |
|---------------|-------------------|
| wardjm        | INPUT_OUTPUT       |
| HULP          | INPUT_ONLY         |
| Our code      | INPUT_OUTPUT_OD    |

All three are different, yet wardjm and HULP both work. `INPUT_OUTPUT_OD` is
used by neither. When FUN_SEL routes the pin to the I2C peripheral, the
direction setting may be irrelevant — the I2C controller drives the output.

**Action: Try INPUT_OUTPUT (matching wardjm) with FUN_SEL=0.**

### 4.3 Digital I2C not released

Our code flow on first boot:
1. Sensor init → `TwoWire.begin(GPIO0, GPIO4)` — digital I2C active on pins
2. Read temperature
3. `initialize_ulp()` → reads calibration via same TwoWire → reconfigures pins

At step 3, `rtc_gpio_init()` should disconnect from the digital domain. But
the digital I2C peripheral (I2C0) may still be actively driving the bus. There
could be internal contention until the I2C peripheral is properly stopped.

**Action: Call `sensor.GetWire().end()` before `ulp_configure_rtc_i2c()`.**

### 4.4 Missing FORCE_OUT configuration

HULP explicitly sets `RTC_I2C_SCL_FORCE_OUT=0` and
`RTC_I2C_SDA_FORCE_OUT=0` (open-drain). While the defaults are 0, if any
prior code has modified the CTRL register, these might not be 0.

**Action: Explicitly write the full CTRL register value matching HULP.**


## 5. BMP390L I2C Protocol

### 5.1 Device identity

| Parameter    | Value |
|-------------|-------|
| Manufacturer | Bosch Sensortec |
| I2C address  | 0x77 (SDO=VDD) or 0x76 (SDO=GND) |
| Chip ID reg  | 0x00, expected value: **0x60** |
| I2C modes    | Standard (100 kHz), Fast (400 kHz), High-speed (3.4 MHz) |

Source: BST-BMP390L-DS001 datasheet

### 5.2 Register map (relevant subset)

| Addr | Name        | R/W | Description |
|------|-------------|-----|-------------|
| 0x00 | chip_id     | R   | Returns 0x60 |
| 0x07 | DATA_0      | R   | Temperature [7:0] |
| 0x08 | DATA_1      | R   | Temperature [15:8] |
| 0x09 | DATA_2      | R   | Temperature [23:16] |
| 0x1B | PWR_CTRL    | R/W | Mode and sensor enable |
| 0x31-0x45 | NVM/calib | R | Calibration data |

### 5.3 PWR_CTRL register (0x1B)

| Bits  | Field     | Description |
|-------|-----------|-------------|
| [5:4] | mode      | 00=sleep, 01/10=forced, 11=normal |
| [1]   | temp_en   | Temperature measurement enable |
| [0]   | press_en  | Pressure measurement enable |

Our forced mode value: `0x13 = 0b00_01_0011`
- mode = 01 (forced) ✓
- temp_en = 1 ✓
- press_en = 1 ✓

### 5.4 Forced mode timing

After writing forced mode to PWR_CTRL, the sensor performs one measurement
then returns to sleep. Measurement time depends on oversampling:

| Config           | Typical time |
|-----------------|-------------|
| 1× temp only    | ~3.4 ms     |
| 1× temp+press   | ~6.8 ms     |
| 2× oversampling | ~13.3 ms    |
| Higher OS       | up to ~40 ms |

With default 1× oversampling for both temp and pressure, we need at least
~7ms delay. With our corrected delay calculation:

```
7ms × 8 MHz = 56,000 cycles
```

This exceeds the 16-bit max of I_DELAY (65535). Use 56000, or reduce to
temp-only (press_en=0, `0x12`) for a ~3.4ms / 27200-cycle delay.

### 5.5 I2C protocol specifics

The BMP390L uses standard I2C protocol with sub-address byte. A register read:

```
START → [addr|W] → [ACK] → [reg_addr] → [ACK] →
  rSTART → [addr|R] → [ACK] → [data] → [NACK] → STOP
```

This matches exactly what the ESP32 RTC I2C `I2C_RD` instruction performs.
No special initialization sequence is required — the chip ID register (0x00)
can be read immediately after power-up.


## 6. Recommended Fix Sequence

Based on the analysis, try these changes in order. Each builds on the previous:

### Step 1: Match wardjm (minimal config, no FUN_SEL)

```c
void ulp_configure_rtc_i2c() {
    // Release digital I2C first
    sensor.GetWire().end();  // or Wire.end() if applicable

    // Initialize as basic RTC GPIOs (FUN_SEL stays at 0)
    rtc_gpio_init(GPIO_NUM_0);
    rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_OUTPUT);
    rtc_gpio_init(GPIO_NUM_4);
    rtc_gpio_set_direction(GPIO_NUM_4, RTC_GPIO_MODE_INPUT_OUTPUT);

    // Pin pair 0
    SET_PERI_REG_BITS(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SDA_SEL, 0, RTC_IO_SAR_I2C_SDA_SEL_S);
    SET_PERI_REG_BITS(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SCL_SEL, 0, RTC_IO_SAR_I2C_SCL_SEL_S);

    // Use WRITE_PERI_REG (writes full register, matching wardjm)
    WRITE_PERI_REG(RTC_I2C_SCL_LOW_PERIOD_REG, 40);
    WRITE_PERI_REG(RTC_I2C_SCL_HIGH_PERIOD_REG, 40);
    WRITE_PERI_REG(RTC_I2C_SDA_DUTY_REG, 16);
    WRITE_PERI_REG(RTC_I2C_SCL_START_PERIOD_REG, 30);
    WRITE_PERI_REG(RTC_I2C_SCL_STOP_PERIOD_REG, 44);
    WRITE_PERI_REG(RTC_I2C_TIMEOUT_REG, 10000);
    SET_PERI_REG_BITS(RTC_I2C_CTRL_REG, RTC_I2C_MS_MODE, 1, RTC_I2C_MS_MODE_S);

    SET_PERI_REG_BITS(SENS_SAR_SLAVE_ADDR1_REG, SENS_I2C_SLAVE_ADDR0,
                      0x77, SENS_I2C_SLAVE_ADDR0_S);
}
```

### Step 2: If Step 1 doesn't work, try HULP style

```c
void ulp_configure_rtc_i2c() {
    sensor.GetWire().end();

    // HULP-style: INPUT_ONLY + FUN_SEL=3 + pullups
    rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_DISABLED);
    rtc_gpio_init(GPIO_NUM_0);
    gpio_set_pull_mode(GPIO_NUM_0, GPIO_PULLUP_ONLY);
    rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_ONLY);
    SET_PERI_REG_BITS(RTC_IO_TOUCH_PAD1_REG, RTC_IO_TOUCH_PAD1_FUN_SEL_V,
                      3, RTC_IO_TOUCH_PAD1_FUN_SEL_S);

    rtc_gpio_set_direction(GPIO_NUM_4, RTC_GPIO_MODE_DISABLED);
    rtc_gpio_init(GPIO_NUM_4);
    gpio_set_pull_mode(GPIO_NUM_4, GPIO_PULLUP_ONLY);
    rtc_gpio_set_direction(GPIO_NUM_4, RTC_GPIO_MODE_INPUT_ONLY);
    SET_PERI_REG_BITS(RTC_IO_TOUCH_PAD0_REG, RTC_IO_TOUCH_PAD0_FUN_SEL_V,
                      3, RTC_IO_TOUCH_PAD0_FUN_SEL_S);

    // Pin pair 0
    REG_SET_FIELD(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SDA_SEL, 0);
    REG_SET_FIELD(RTC_IO_SAR_I2C_IO_REG, RTC_IO_SAR_I2C_SCL_SEL, 0);

    // Full CTRL register config (matching HULP defaults)
    REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_RX_LSB_FIRST, 0);
    REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_TX_LSB_FIRST, 0);
    REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_SCL_FORCE_OUT, 0);
    REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_SDA_FORCE_OUT, 0);
    REG_SET_FIELD(RTC_I2C_CTRL_REG, RTC_I2C_MS_MODE, 1);

    REG_SET_FIELD(RTC_I2C_SCL_LOW_PERIOD_REG, RTC_I2C_SCL_LOW_PERIOD, 40);
    REG_SET_FIELD(RTC_I2C_SCL_HIGH_PERIOD_REG, RTC_I2C_SCL_HIGH_PERIOD, 40);
    REG_SET_FIELD(RTC_I2C_SDA_DUTY_REG, RTC_I2C_SDA_DUTY, 16);
    REG_SET_FIELD(RTC_I2C_SCL_START_PERIOD_REG, RTC_I2C_SCL_START_PERIOD, 30);
    REG_SET_FIELD(RTC_I2C_SCL_STOP_PERIOD_REG, RTC_I2C_SCL_STOP_PERIOD, 44);
    REG_SET_FIELD(RTC_I2C_TIMEOUT_REG, RTC_I2C_TIMEOUT, 200);  // HULP default

    SET_PERI_REG_BITS(SENS_SAR_SLAVE_ADDR1_REG, SENS_I2C_SLAVE_ADDR0,
                      0x77, SENS_I2C_SLAVE_ADDR0_S);
}
```

### Step 3: If both fail, add HULP as lib_dep

```ini
# platformio.ini
lib_deps =
    ...
    https://github.com/boarchuz/HULP.git
```

Then use directly:
```c
hulp_configure_i2c_pins(GPIO_NUM_4, GPIO_NUM_0, true, true);
hulp_i2c_controller_config_t cfg = HULP_I2C_CONTROLLER_CONFIG_DEFAULT();
hulp_configure_i2c_controller(&cfg);
hulp_register_i2c_slave(0, 0x77);
hulp_peripherals_on();
```

### Step 4: Fix I_DELAY and add RDY_FOR_WAKEUP check

Regardless of which step fixes I2C, also fix:

```c
// Fix delay: 7ms at 8 MHz = 56000 cycles
I_DELAY(56000),

// Or use temp-only (0x12): 3.5ms = 28000 cycles
I_I2C_WRITE(BMP390L_SLAVE_SEL, 0x1B, 0x12),  // temp only, forced mode
I_DELAY(28000),
```

Add RDY_FOR_WAKEUP check before WAKE in the ULP program (assembly-style
using C macros):

```c
// Before I_WAKE():
I_RD_REG(RTC_CNTL_LOW_POWER_ST_REG, RTC_CNTL_RDY_FOR_WAKEUP_S, RTC_CNTL_RDY_FOR_WAKEUP_S),
I_ANDI(R0, R0, 1),
M_BL(LABEL_RDY_WAIT, 1),  // if 0, loop back to re-check
```

### Step 5: Fallback — ULP bit-bang I2C

If hardware RTC I2C cannot be made to work, the HULP library provides a
complete **bit-bang I2C** implementation (`hulp_i2cbb.h`) that works on ANY
RTC GPIO pins. It uses `I_GPIO_OUTPUT_EN`/`I_GPIO_OUTPUT_DIS`/`I_GPIO_READ`
instructions to manually clock out I2C signals. This is ~76 ULP instructions
and runs at ~150 kHz.

Advantages: works on any RTC-capable pins, no hardware I2C peripheral quirks.
Disadvantage: larger ULP program, fixed ~150 kHz speed.


## 7. Diagnostic Steps (with hardware)

### 7.1 Read DEBUG_STATUS register after a failed I2C attempt

Add diagnostic code in the main CPU after ULP wake to read
`RTC_I2C_DEBUG_STATUS_REG`:

```c
uint32_t status = READ_PERI_REG(RTC_I2C_DEBUG_STATUS_REG);
Serial.printf("I2C debug: bus_busy=%d arb_lost=%d timed_out=%d ack=%d\n",
    (status >> 4) & 1, (status >> 3) & 1,
    (status >> 2) & 1, (status >> 0) & 1);
```

### 7.2 Logic analyzer on SDA/SCL

Connect logic analyzer to GPIO0 (SDA) and GPIO4 (SCL) to see:
- Are there any transitions at all? (If no: pin routing/FUN_SEL issue)
- Is there a START condition? (If no: I2C controller not starting)
- Is there a clock? (If yes but no ACK: address wrong or device not responding)
- Is there a NACK? (Wrong address or device in wrong state)

### 7.3 Verify pin electrical state

With the ULP NOT running, measure GPIO0 and GPIO4 with a multimeter:
- Both should be HIGH (~3.3V) if pullups are working
- If either is LOW, the bus may be stuck
- Try manual bus recovery: toggle SCL 9 times from main CPU before entering
  deep sleep


## 8. Summary of Issues Found

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | FUN_SEL=3 may be wrong — wardjm works without it | **HIGH** | See §9 |
| 2 | Digital I2C not released before RTC I2C config | **HIGH** | Fixed (Wire.end) |
| 3 | Wrong pin direction (OD vs INPUT_OUTPUT vs INPUT_ONLY) | MEDIUM | See §9 |
| 4 | Missing explicit FORCE_OUT config in CTRL register | MEDIUM | See §9 |
| 5 | I_DELAY(750) = 94µs not 5ms (wrong clock assumption) | **HIGH** | Fixed (56000) |
| 6 | Missing RDY_FOR_WAKEUP check before WAKE | LOW | Not needed (bit-bang) |
| 7 | I_I2C_READ bug (high_bit=0) | FIXED | Not needed (bit-bang) |


## 9. Resolution: HULP Bit-Bang I2C

**The hardware RTC I2C peripheral could not be made to work reliably.** After
extensive debugging (FUN_SEL=0 vs 3, INPUT_ONLY vs INPUT_OUTPUT, peripheral
reset, interrupt clear, timeout tuning), the peripheral's DEBUG_STATUS register
consistently showed BUS_BUSY=1 when FUN_SEL=3 was set, or NACK with no timeout
when FUN_SEL was left at 0. The ULP I2C instruction would block indefinitely.

### Root cause analysis

The ESP32 RTC I2C peripheral has undocumented state-machine behavior:
- With FUN_SEL=3 (routing pads to the I2C peripheral), the peripheral latches
  a BUS_BUSY state on connection, even when SDA and SCL are both HIGH. Clearing
  CTRL, INT_CLR, and reordering init did not help.
- Without FUN_SEL=3 (peripheral not connected to pads), the ULP I2C instruction
  sends data into the void (NACK, no timeout) and blocks forever.
- The HULP default timeout of 200 RTC_FAST_CLK cycles (25µs) is too short for
  100 kHz I2C. wardjm uses 10000 (1.25ms). Even with the correct timeout, the
  peripheral remained stuck.

### Working solution

HULP's bit-bang I2C (`hulp_i2cbb.h`) bypasses the hardware peripheral entirely.
It uses ULP GPIO instructions (`I_GPIO_READ`, `I_GPIO_OUTPUT_EN/DIS`) to manually
toggle SDA/SCL, implementing a software I2C master at ~150 kHz.

Pin configuration:
```c
hulp_configure_pin(GPIO_NUM_4, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0); // SCL
hulp_configure_pin(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_ONLY, GPIO_PULLUP_ONLY, 0); // SDA
hulp_peripherals_on();
```

The bit-bang subroutine expands to ~76 ULP instructions and is included in the
program via `M_INCLUDE_I2CBB()`. It supports 8-bit read, 16-bit read, and 8-bit
write, with NACK and arbitration-loss error callbacks.

### Additional finding: M_MOVL label addressing

When the bit-bang subroutine (~76 instructions) is included in the program,
ESP-IDF's `M_MOVL(reg, label)` macro produces incorrect addresses for labels
defined after the subroutine. The workaround is to use `I_MOVI(reg, constant)`
with a fixed `ULP_DATA_BASE` address (200) instead of label-relative data areas.

### Verified working configuration

- **I2C method**: HULP bit-bang (`hulp_i2cbb.h`), NOT hardware RTC I2C
- **Bus recovery**: 9 SCL clocks + STOP after `Wire.end()`, before pin reconfig
- **Pin mode**: `RTC_GPIO_MODE_INPUT_ONLY` with `GPIO_PULLUP_ONLY`
- **Data area**: Fixed at `RTC_SLOW_MEM[200]`, not label-based
- **Temperature**: BMP390L chip_id=0x60 confirmed, compensated temp matches sensor
- **Delta wake**: ULP compares DATA_1 byte, wakes CPU on ≥1 count change (~0.005°C)
