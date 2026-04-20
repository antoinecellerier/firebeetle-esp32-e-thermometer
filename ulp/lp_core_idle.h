// LP core idle mode: no I2C, wakes main CPU every N loops.
// Used for power measurement testing without sensor hardware.

#define WAKE_EVERY 6

int main(void)
{
    sample_count++;
    lp_wake_count++;

    // Simulate sensor read time (~7ms like BMP390L)
    ulp_lp_core_delay_us(7000);

    // Wake main CPU every N loops
    if ((sample_count % WAKE_EVERY) == 0) {
        // Alternate fake temperature to trigger delta detection
        temp_raw_1 = (sample_count / WAKE_EVERY) & 1 ? 0x80 : 0x60;
        wake_reason = 1;
        ulp_lp_core_wakeup_main_processor();
    }

    return 0;
}
