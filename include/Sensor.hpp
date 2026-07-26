#pragma once

// Sentinel value meaning "no valid previous temperature available".
// Used by ReadUlpTemperature to skip plausibility checks on first reading.
#define TEMP_NO_PREVIOUS (-999.0f)

// Plausibility gate — the last of three defences, and the weakest. Identity comes
// first (the driver refuses to read a part that did not answer with its chip ID),
// then the raw-code test below, then this. Deliberately wide: the job is catching
// what the other two miss, not policing ambient.
//
// It cannot stand alone, and neither can the drivers' delta/re-read machinery: that
// compares two readings against each other, which says nothing about whether either
// came from a sensor. An undriven bus produces values inside this range.
//
// Bound is the operating range both BMP58x and BMP390L are specified over.
#define TEMP_PLAUSIBLE_MIN_C (-40.0f)
#define TEMP_PLAUSIBLE_MAX_C ( 85.0f)

static inline bool temp_is_plausible(float t)
{
  return t >= TEMP_PLAUSIBLE_MIN_C && t <= TEMP_PLAUSIBLE_MAX_C;
}

// An all-zero or all-ones 24-bit field is a bus artifact, not a measurement: the
// first is what a read returns from an unpowered device or a bus held low, the
// second from an absent device or one floating high. A live sensor does not report
// exactly 0.0000 C at 1/65536 resolution. Catches the 0.0 C case, which sits well
// inside the range gate above and would otherwise pass.
#define TEMP_RAW24_IS_BUS_ARTIFACT(raw) \
  (((raw) & 0xFFFFFFu) == 0x000000u || ((raw) & 0xFFFFFFu) == 0xFFFFFFu)

class Sensor
{
    public:
        virtual float GetTemperatureC() = 0;

        // ULP support — sensors override these if they support ULP polling.
        // Default: no ULP support.
        virtual bool SupportsUlp() { return false; }
        virtual void InitializeUlp(bool cold_boot = true) { (void)cold_boot; }
        // Halt the coprocessor so the CPU can use the shared I2C bus alone. The
        // sensor is wired to one pair of pins and both cores drive them, so a
        // direct read taken while the coprocessor is still polling is racing it.
        // Stopping implies reloading: InitializeUlp() is what restarts it.
        virtual void StopUlp() {}
        virtual bool ReadUlpTemperature(float *temp_out, float previous_temp = TEMP_NO_PREVIOUS) { return false; }
};
