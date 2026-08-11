# Schematic verification record — rev A pre-order sign-off

**Date:** 2026-07-20. **Scope:** schematic only (PCB/DRC covered by the
`make fab` gate, see ORDERING.md). **Verdict: no order-blocking error found.**

Method: `make check` (mechanical gate) plus four independent review passes
(power chain / MCU+sensors / EPD interface / meta cross-check), each working
from the exported netlist and **primary sources only** — device datasheets,
the DESPI-C02 reference schematic, Espressif documentation, LCSC part pages —
never from README tables, code comments, or `verify/` scripts. Every symbol
pin-number→function mapping used by the netlist was re-derived from its
device datasheet (a wrong symbol passes every automated check at once).

## Mechanical gate

- ERC clean at `--severity-all` (0 violations); netlist golden match
  (35 named + 25 anonymous nets, 298 pin connections); all invariants pass;
  all footprints resolve.
- Regenerating from `generator/` produced a **byte-identical**
  `thermometer-c6.kicad_sch` to the committed file.

## Requirements — all PROVEN

| Req | Proof (primary sources) |
|---|---|
| R1 MCU boots/runs | All 22 module GND pins + pin 3=3V3 pin-by-pin vs ESP32-C6-MINI-1 datasheet Table 3-1 (verified independently twice); EN RC 10k/1µF = Espressif HDG exact; BOOT pulls GPIO9 low (SPI boot needs high, Table 4-3); strap audit GPIO4/5/8/9/15; USB D+/D− traced unswapped J3 A6/B6→USBLC6 3↔4→GPIO13, A7/B7→1↔6→GPIO12 (ST USBLC6 p.2 + C6 datasheet); UART0 on module pins 31/30 |
| R2 EPD drive | 24/24 J4 pin functions match the DESPI-C02 reference transcription (rendered PDF); BUSY/RES/DC/CS/SCLK/SDI → module pins 29–24 = GPIO23–18; booster topology + all three MBR0530 orientations verified against the reference AND first principles (per-diode reverse stress ~20V vs 30V rating); Si1308EDL G/S/D per SC-70 datasheet; all panel power on gated EPD_VCC — no J4 pin touches always-on 3V3; RES pull-up to EPD_VCC; BS→GND = 4-wire SPI per SSD1677; XUNPU FPC-05FB rated 50V between adjacent terminals (VGH/VGL on pins 4/5 span ~40V — inside rating), 0.5A/contact |
| R3 BMP58x @0x47, LP core | LP_I2C fixed to GPIO6/7 (C6 datasheet) = U1.15/16 = firmware pins (`include/app_common.h`, `ulp/lp_core_bmp58x.h`); BMP581 symbol == Bosch Table 28, BMP585 == Table 26 (pinouts differ, checked separately); CSB→VDDIO = I2C, SDO→VDDIO = 0x47 per both datasheets; INT-floating sanctioned by Bosch §6.2 |
| R4 Battery/charging/measurement | MCP73831 PROG 10k → 100mA (DS20001984H §5.1.2 + EC table); -2ACI = 4.20V; load-share proven by Vgs analysis (USB present → Q1 off → charger terminates on true cell current); Q6 reverse-battery blocks by body-diode analysis (AO3401A); divider level-shift GPIO3→2N7002→Q4 correct; VBAT/2 ≤2.1V on ADC1_CH2, VBUS/2 on ADC1_CH4 (channel map per C6 datasheet) |
| R5 Sleep leakage | Every VBAT/VBUS/3V3→GND path walked in the sleep state: divider dead (Q4 Vgs=0), VBUS nets dead unplugged, STAT floats, no pull-up carries standing current (I2C idles high), EPD gate held off by R12. Floor = RT9080 Iq (2µA typ) + MCP73831 reverse drain (≤2µA max) — consistent with the measured ~15.8µA C6 rig floor |
| R6 Bench/debug | JP1/J2 series-break correct (default bridged); TP1–TP11 nets confirmed; debug header order asserted 1–10, GND-first, no VBAT beside 3V3; TP4 probe-only per RT9080 active-discharge spec |

## Key facts verified (source)

- RT9080-33GJ5: pinout, EN polarity, 600mA/ILIM 610mA min, Iq 2µA, output-cap
  requirement (DS9080-09 p.1/4/6). MCP73831: pinout, tri-state STAT, PROG
  formula (DS20001984H). SS14 Vf 0.5V typ (Vishay 88746). AO3401A 30V P-ch,
  1=G/2=S/3=D, all four instances by function. USBLC6-2SC6 1/6=I/O1, 3/4=I/O2,
  2=GND, 5=VBUS (ST p.2). FC-135 CL=12.5pF → 2×20pF (Epson/LCSC C32346).
- BOM == circuit.py == netlist across all 75 populated lines; DNP flags
  consistent; jumpers/TPs/holes correctly absent from the BOM.
- LCSC C-numbers spot-checked against product pages: C5736265 (MINI-1-N4,
  4MB, PCB antenna), C5362283, C18184976, C32346, C98192 (4.7µF **50V**),
  C28323 (1µF **50V**), C424093, C841192, C15127, C8545, C2480, C165948,
  C7519, C2856831 (FPC-05FB dual-contact), C2930220 (FOJAN FRL0805FR470TS =
  0.47Ω 1% 0805 current-sense).

## Findings and dispositions

1. **GPIO8 has no pull-up** — BOOT-button serial download relies on floating
   GPIO8 reading high (Espressif: unreliable). USB-Serial-JTAG download works
   regardless; README documents "header only" as the intent. **Accepted for
   rev A** (rev B candidate: 10k pull-up mirroring R7).
2. **EPD control pins (GPIO18–23, always-on domain) can back-power the
   gated-off panel** through its ESD diodes unless firmware tri-states them
   before sleep. Matches DESPI (no series resistors, README open item 4).
   **Firmware obligation** — float EPD pins before deep sleep.
3. **LDO dropout at EOL battery**: worst-case RT9080 needs VIN ≥~3.71V to
   hold 3.3V at the 465mA EPD peak — right at the 3.7V cutoff.
   **First-article bench item**: measure 3V3 sag at 3.7V supply during
   refresh (feeds the planned cutoff re-derivation).
   **Closed 2026-07-31**: BOD probe measured ~300mV droop at the peak; cutoff
   re-derived to 3550/3500mV (`1e1048e`).
4. **Boost transient vs 610mA ILIM**: pulsed inductor current could brush
   the LDO limit. **First-article bench item** (PPK2 peak capture).
5. **Physical FPC cable pin-1 orientation** — logically proven pin-for-pin;
   dual-contact part removes the flip failure mode; end-for-end cable fold
   is only checkable against the real panel. **Closed on hardware**: BRINGUP
   Phase 0 continuity, all 24 nets to the right adapter pins, then board 1's
   first render.
6. **Crystal 20pF load assumes ~2.5pF stray** — correct nominal; cold-start
   already a first-article item (7pF FC-135 variant is the fallback).
7. **`datasheets/XUNPU_FPC-05FB-NPH20.pdf` was corrupted** (circular xref)
   — replaced 2026-07-20 with the ghostscript-repaired LCSC copy
   (C2856831 datasheet = the same FPC-05FB-NPH20 manufacture drawing;
   confirms pads 0.30×1.20 @0.5mm, tabs 2.0×1.8 at 14.6mm c-t-c, body 5.40,
   rear-flip dual contact).
8. **Verification-harness coverage gaps** — closed 2026-07-20:
   `check_netlist.py` now also verifies component value/footprint/LCSC/dnp/
   exclude_from_bom against circuit.py and that every declared-NC pin is
   really unconnected on the sheet (NC is now bidirectional); `invariants.py`
   now asserts the charger PROG node + 10k value, LDO VOUT + output caps,
   and the datasheet-derived critical values (EN RC, 32k load caps, I2C
   pull-ups, CC Rd, divider pair, RESE ladder, inductors, 50V boost caps,
   DNP roster / populate-exactly-one). Fault-injection tested (wrong value,
   wrong LCSC, wrongly-NC'd pin all fail the gate).
9. **FPC anchor tabs are netless** — common practice, left as-is.

Remaining independent-coverage note: the BOM shares circuit.py as its source,
so a wrong-but-self-consistent circuit.py value can only be caught by
invariants.py's hand-written value list (keep it in sync with datasheet
reasoning, per the three-files rule in CLAUDE.md).
