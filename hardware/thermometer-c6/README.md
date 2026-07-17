# thermometer-c6 — custom ultra-low-power e-paper thermometer board

Custom PCB replacing the XIAO-C6/FireBeetle dev-board rigs. ESP32-C6-MINI-1 +
BMP581 + universal 24-pin EPD interface with on-board gated booster, USB-C
charging, LDO power tree. Design driven by the PPK2 measurement campaign in
`docs/notes.md` (repo root).

**Status: layout + routing complete** (48×35mm 2-layer, hand-routed,
DRC-clean at full severity), silkscreen done. Fab export is `make fab`
(gerbers/drill + CPL/BOM zip, git-hash+date stamped, gated by
`verify/check_fab.py`); order per `ORDERING.md`.

## Why these choices (measurement rationale)

| Decision | Measurement behind it |
|---|---|
| LDO (not buck) 3.3V rail | XIAO's SGM6029C buck: razor-sharp dropout cliff at 3.545V → 0.5–0.9A brownout storms; forces 3.70V firmware shutdown, wasting ~12–15% of pack (notes.md 2026-07-05) |
| P-FET-gated EPD booster | DESPI-C02 leaks ~534µA with panel asleep; FDN340P gate mod → ~18µA (notes.md) |
| Switched 100k/100k battery divider | Always-on 200k divider ≈ 10µA (~⅔ of the sleep floor); 1M/1M biases the C6 SAR ADC low (~300ns sample window) (wiring.md) |
| High-side divider switch | Low-side switch leaves the sense node at VBAT through the top 100k → pin ESD diode clamps into 3V3 above ~3.7V (~5µA at 4.2V) |
| Load-sharing USB path | Without it, no-battery USB operation is limited to the 100mA charge current — EPD refresh peaks at ~465mA |
| Reverse-battery P-FET (Q6) | JST vs Adafruit pigtail polarity is a real supply-chain trap; MCP73831 abs-max is −0.3V — one AO3401A makes it survivable |
| EPD gate soft-start (R24/C28) | GPIO14 slamming Q2 on charge-shares 10µF against the rail faster than the LDO loop — ~100µs ramp kills the brownout risk |
| VBUS sense (R22/R23 → GPIO4) | Firmware needs to know USB is present: VBAT_ADC reads the charger CV node while charging, and SoC logic must ignore it; zero draw with USB absent |
| Jumper-selected inductor (JP5/JP6) | 10µH proven on all panels; 47µH per the GDEH0576T81 datasheet (with 2.2Ω RESE) — jumpers sit on the switch-node side so the unselected coil idles on the DC rail |
| 32.768kHz crystal | C6 on internal RC runs hours fast over weeks (memory: project_c6_clock_drift) |

## Reference transcription: DESPI-C02 V1.0 (Good Display, 2018-07-06)

Transcribed from `hardware/DESPI-C02_SCH V1.0.pdf` (visual + embedded netlist),
2026-07-07. This is the booster we replicate (with EPD_VCC gating added).

### 24-pin 0.5mm FPC panel pinout (P1, "FPC24(0.5MM)")

| Pin | Name | DESPI connection | Pin | Name | DESPI connection |
|---|---|---|---|---|---|
| 1 | NC | — | 13 | SCLK | host SPI SCK |
| 2 | GDR | Q1 gate + R1 10k→GND | 14 | SDI | host SPI MOSI |
| 3 | RESE | Q1 source + Rsense→GND | 15 | VDDIO | 3.3V |
| 4 | VGL | C1 4.7µF/25V→GND | 16 | VCI | 3.3V |
| 5 | VGH | C2 4.7µF/25V→GND | 17 | VSS | GND |
| 6 | TSCL | — (touch variant only) | 18 | VDD | C7 1µF/50V→GND |
| 7 | TSDA | — (touch variant only) | 19 | VPP | C8 1µF/50V→GND |
| 8 | BS | R4 3Ω→GND (= tied low, 4-wire SPI) | 20 | VSH | C9 4.7µF/25V→GND |
| 9 | BUSY | host | 21 | PREVGH | C5 4.7µF/25V→GND + D3 cathode |
| 10 | RES | host + R5 10k→3.3V pull-up | 22 | VSL | C10 4.7µF/25V→GND |
| 11 | D/C | host | 23 | PREVGL | C11 4.7µF/25V→GND + D1 anode |
| 12 | CS | host | 24 | VCOM | C12 1µF/50V→GND |

### Booster topology (all diodes MBR0530; orientation by function, not pin #)

- L1 10µH/1A: 3.3V → SW node
- Q1 Si1308EDL N-FET: gate=GDR (R1 10k bleed to GND), drain=SW, source=RESE
- RESE → Rsense → GND. DESPI: slide switch selects R3 0.47Ω or R2 3Ω.
  **This board: three parallel legs, each Rsense in series with a solder
  jumper: 0.47Ω (default-bridged) / 2.2Ω / 3Ω.**
- D3: anode=SW, cathode=PREVGH (boost rectifier)
- Negative charge pump: SW → C3 4.7µF/25V → X node; D2 anode=X, cathode=GND;
  D1 anode=PREVGL, cathode=X
- 3.3V rail bulk: C4 4.7µF/25V. (On this board the whole block hangs off the
  gated EPD_VCC rail, and the RES pull-up goes to EPD_VCC — never 3V3.)
- There are **no** PREVGH↔PREVGL/VCOM bridge caps in the real reference
  (the abandoned draft in `hardware/kicad/` invented them).

## ESP32-C6 pin map

| GPIO | Function | Notes |
|---|---|---|
| 0 / 1 | XTAL_32K_P / N | FC-135 32.768kHz + 20pF; R9 10M bias DNP — the C6's 32k oscillator amplifier runs at very low gm, so startup margin depends on crystal ESR spread (≤70kΩ allowed, rises when cold) and stray C; the parallel bias resistor (Espressif HDG checklist) gives the inverter a DC feedback path if a given board/batch won't start |
| 2 | VBAT_ADC (ADC1_CH2) | sense node of switched divider; 0V when divider off |
| 3 | VDIV_EN | 100k pull-down → divider hard-off in deep sleep |
| 4 | VBUS_SENSE (100k/100k from VBUS) | USB-presence detect; divider is dead (0V, zero drain) with USB unplugged |
| 5 | spare → J5 debug header | strap-adjacent (SDIO clock-edge only at default eFuses) — keep high-Z |
| 6 / 7 | LP I2C SDA / SCL | fixed by silicon; BMP581; 4.7k pull-ups to 3V3 |
| 8 | spare → J5 | STRAP: must be free to pull high for download boot — header only |
| 9 | BOOT button | strap, its intended use; 10k pull-up |
| 12 / 13 | USB D− / D+ | native USB-Serial-JTAG via USBLC6-2SC6 |
| 14 | EPD_PWR_EN (P-FET gate) | chosen because it is NOT in the SDIO strap group (GPIO18–23 can toggle during early boot, esp-idf #11975); 10k pull-up → panel off at reset/sleep |
| 15 | Status LED | safe: JTAG_SEL strap ignored at default eFuses |
| 16 / 17 | UART0 TX / RX → J5 | module pins TXD0/RXD0 |
| 18–21 | EPD MOSI/SCK/CS/DC | SDIO-group boot toggles drive an unpowered panel — harmless |
| 22 | EPD RST | 10k pull-up to **EPD_VCC** (gated) |
| 23 | EPD BUSY (input) | |

## Debug header J5 (2×5, DNP — GND-first, no VBAT)

The silk carries only a `DBG` marker (no room for a per-pin legend at ≥0.8mm),
so the pinout lives here. Standard 2×5 numbering, pin 1 = the marked corner:

| Pin | Signal | | Pin | Signal |
|---|---|---|---|---|
| 1 | GND | | 2 | +3V3 |
| 3 | EN (reset) | | 4 | DBG_TX (UART0 TXD0, GPIO16) |
| 5 | DBG_RX (UART0 RXD0, GPIO17) | | 6 | VBUS_SENSE (GPIO4) |
| 7 | DBG_IO5 (spare GPIO5) | | 8 | DBG_IO8 (spare GPIO8, strap) |
| 9 | GND | | 10 | GND |

DNP by default — solder a header only if you need wired debug/UART. **BOOT is
not on J5** (it's the SW2 button only); only EN is exposed here.

## Charging rule (product decision, 2026-07-07)

**Charge indoors only (0–45°C).** The MCP73831 has no thermistor input;
charging LiPo below 0°C plates lithium. The board will get a silkscreen
note at layout. Related: don't leave USB permanently attached — the
charger float-cycles the cell between ~3.95V and 4.2V indefinitely.
Firmware should also refuse to advertise "charge OK" below 0°C using the
BMP58x temperature (belt and braces; it cannot stop the charger).

## Inductor solder jumpers (JP5/JP6) — bridge exactly one

| Bridge | L | Pair with |
|---|---|---|
| JP5 (default) | L1 10µH | RESE 0.47Ω or 3Ω — the proven DESPI-C02 config for all six panels |
| JP6 | L2 47µH | RESE 2.2Ω (JP3) — the GDEH0576T81 datasheet booster spec |

## RESE solder jumpers (JP2/JP3/JP4) — bridge exactly one

| Bridge | Rsense | Panel family |
|---|---|---|
| JP2 (default) | 0.47Ω | GDEW/GDEY (UC81xx): GDEW0154M09, GDEW0213M21, GDEW029I6FD, GDEM0154I61; proven with GDEH0576T81 too (DESPI-C02 heritage) |
| JP3 | 2.2Ω | GDEH0576T81 per its datasheet (bridge JP6 to select L2 47µH with it) |
| JP4 | 3Ω | GDEH/GDEM SSD16xx: GDEH0154Z90 (tri-color), GDEH0154D67, GDEH0213B73, GDEH029A1 |

## Bench procedures

- **IBAT break — battery-current (series) measurement**: wick JP1 and insert a
  PPK2 (or any ammeter) across J2 (the 2-pin header silk-labelled `IBAT`, DNP by
  default — solder one in). Battery in JST as usual.
- **PPK2 source-mode power**: feed J2 pin 2 (system side) + GND, JST empty,
  JP1 open. This powers the full deployment topology (LDO in circuit).
- **Do NOT back-feed the 3V3 test pad**: RT9080 abs-max forbids VOUT > VIN
  + 0.3V, and its EN=0 active-discharge (~80Ω) would fight the source.
  TP4 (3V3) is probe-only.
- Charge current: R3 10k → 100mA (0.25C for a 400–500mAh pouch). 4.99k →
  200mA if a bigger pack is fitted.
- C29 (10nF ADC reservoir on VBAT_ADC) is populated by default: enable the
  divider ~5ms before reading (τ = 50k × 10n = 0.5ms).
- BMP58x INT pins are unconnected: firmware must configure int_en=1,
  int_od=0, pad_int_drv=0 per the Bosch datasheets.
- The 3700mV shutdown threshold inherited from the XIAO buck rig should be
  re-derived (~3.4–3.5V defensible) after first-article PPK2 measurement —
  the LDO tree degrades gracefully where the buck cliffed.
- First-article PPK2 items: SS14 reverse leakage at temperature (swap to
  PMEG6010 class if the hot floor drifts), EPD_VCC ramp with the soft-start
  fitted, 32k crystal cold start (a 7pF FC-135 variant is the mitigation
  if marginal).
- While charging, the board self-heats slightly — BMP581 temperature reads
  high until it cools; log accordingly.

## BOM

Generated at `bom/thermometer-c6-bom.csv` (JLCPCB columns) from circuit.py.
Notable parts: ESP32-C6-MINI-1-N4 (C5736265), RT9080-33GJ5 (C841192),
MCP73831-2 (C424093), Si1308EDL (C469327, low stock — fallback Si1304BDL
clone C7419947), MBR0530 TWGMC (C5204746), FPC-05FB-24PH20 dual-contact
(C2856831), SWPA4030S100MT (C38117), FC-135 (C32346), BMP581 (C5362283 —
**out of stock at LCSC/JLCPCB as of 2026-07-07**: consign from
DigiKey/Mouser or hand-place from a Fermion breakout donor).

DESPI-C02 §4.5 requires an FPC socket with "contact at up side or both
side" — hence the dual-contact FPC-05FB (the bottom-contact-only
FPC-05F-24PH20 C2856805 must NOT be substituted). J4 uses the hand-drawn
`local:XUNPU_FPC-05FB-24PH20` footprint, transcribed from the XUNPU
FPC-05FB-NPH20 manufacture drawing (pads 0.3×1.2 @0.5mm, tabs 2.0×1.8 at
±7.3/+1.625 center-to-center) and cross-checked against the EasyEDA/JLC
C2856831 land pattern — the two agree exactly. Cable enters from the
pad-row side; the actuator flips up at the rear; pin 1 is on the left
viewed with cable entry pointing up (silk dot marks it). Pin-1 direction
is verified against the DESPI-C02 manual photos (P1 silk: "1" and "24"
end markers, "24" at the P1-refdes end) — with components up and the
cable exiting east, panel pin 1 is at the north end. Note the DESPI "P1"
silk next to the pin-24 marker is the connector refdes, not pin 1.

## Alternate sensor: BMP585 (U6, DNP by default)

The board carries footprints for BOTH BMP581 (U5, LGA-10 2×2) and BMP585
(U6, LGA-9 3.25×3.25, media-resistant — suitable for outdoor/weather-exposed
builds; gel-protected port under the metal lid, keep the Ø2.2mm opening
unobstructed in the enclosure). Same LP I2C bus, same 0x47 strapping
(CSB+SDO→VDDIO), same register map — the firmware BMP58x driver reads the
chip-ID (0x50=581, 0x51=585) and works with either unchanged.
**Populate exactly one**: both strap to address 0x47.
BMP585 = LCSC C18184976 (in stock, unlike the BMP581). Its datasheet
requires a 10Ω supply series resistor only for supply ramps <10µs — not
applicable here (always-on 3V3 rail, never GPIO-gated).

## Regenerating

```
make check   # generate + ERC + netlist golden check + invariants + footprints
make pdf     # out/thermometer-c6.pdf for review
```

The `.kicad_sch` is generated by `generator/generate.py` from
`generator/circuit.py` (nets/parts) + `generator/layout.py` (placement and
drawn wire routes) — edit those, never the .kicad_sch. Connectivity is
verified three ways: generator geometric checks (cross-net coincidence =
build error), `kicad-cli` ERC at zero tolerance, and exact netlist matching
against circuit.py (anonymous `~` nets matched by pin set).

## Open items (user sign-off)

1. **BMP581 sourcing** — out of stock at LCSC/JLCPCB (3 pcs). Mitigated:
   the BMP585 (in stock, C18184976) has its own footprint on the board as
   U6 — assemble with U6 populated and U5 empty if the 581 stays dry.
2. **Si1308EDL stock thin** (~1.4k) — order early; fallback Si1304BDL-clone
   C7419947 (Vgs(th) ≤1.2V, same SC-70, lower Id 0.9A — adequate).
3. **Reverse-polarity protection omitted** (keyed JST + clear silk) — veto?
4. **EPD SPI/control series resistors omitted** (DESPI omits them; firmware
   floats pins when the panel is gated off) — veto?
5. **JST-PH polarity**: silk will mark +; verify against your pigtails
   before first battery plug (JST vs Adafruit convention differs).
6. **FPC footprint**: done — hand-drawn `local:XUNPU_FPC-05FB-24PH20`
   (see BOM section). Pin-1 direction confirmed against the DESPI-C02
   manual photos (2026-07-08); numbering flipped accordingly.
7. **32k crystal populated by default** — ~0.1–0.5µA for real timekeeping;
   DNP it if vetoed (firmware falls back to internal RC).
8. Old `hardware/kicad/` Copilot draft: delete or archive — your call.

## Follow-up phases

- PCB layout (2-layer) — **DONE**: booster switch loop tight, RESE sense
  short, no-copper zone under BMP581, antenna keep-out per Espressif HDG,
  JLCPCB gerbers/drill + CPL/BOM via `make fab` (order per `ORDERING.md`).
- Firmware (not in this deliverable): new board define with this pin map
  (EPD on GPIO18–23, gate GPIO14, LED GPIO15, divider GPIO2/3, 32k crystal
  sdkconfig).
