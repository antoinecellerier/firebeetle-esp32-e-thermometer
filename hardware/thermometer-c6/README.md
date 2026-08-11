# thermometer-c6 — custom ultra-low-power e-paper thermometer board

Custom PCB replacing the XIAO-C6/FireBeetle dev-board rigs. ESP32-C6-MINI-1 +
BMP581 + universal 24-pin EPD interface with on-board gated booster, USB-C
charging, LDO power tree. Design driven by the PPK2 measurement campaign in
[`docs/notes.md`](../../docs/notes.md) (repo root).

**Status: rev A built and working.** Ordered 2026-07-20
([`archive/order-2026-07-20/`](archive/order-2026-07-20/); landed €273.93 ≈
€68.50/assembled board, breakdown in [`ORDERING.md`](ORDERING.md)). Board 1
passed bring-up Phases 0–2 on 2026-07-29 ([`BRINGUP.md`](BRINGUP.md)): first
render, LP-core survival, and a measured 18.3µA @ 4.2V deployment-path sleep
floor over a full field interval (docs/notes.md 2026-07-29) — vs 21.7µA at
the same 4.2V on the XIAO buck rig, validating the LDO tree. Next hardware
phase: [`BRINGUP.md`](BRINGUP.md) Phase 3, gated on board 1 coming off its
battery soak (running since 2026-07-31; harvest before resetting it). Board 2
went straight to flash on the strength of board 1's pass, worked first time,
and is the bench board; boards 3–4 are still in the bag. The board is 48×35mm
2-layer, hand-routed, DRC-clean at full severity; fab export is `make fab`
(gerbers/drill + CPL/BOM zip, git-hash+date stamped, gated by
`verify/check_fab.py`); pre-order schematic sign-off (requirements proven
against primary sources, findings + dispositions):
[`SCHEMATIC-VERIFICATION.md`](SCHEMATIC-VERIFICATION.md).

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
charging LiPo below 0°C plates lithium. The board carries this on back silk
(`CHARGE INDOORS 0-45°C`). Related: don't leave USB permanently attached — the
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

- **PPK2 source-mode power, deployment path (used for all published board-1
  figures)**: feed J1 through a Dupont-into-JST harness, JP1 untouched. Q6
  and the MCP73831 VBAT-pin leakage are in the measurement by construction —
  true battery-terminal figures. `tools/ppk2.py` rail id: `reva-j1` (also
  what `ppk2.py sweep` sweeps for the battery-floor regime map).
- **IBAT break — battery-current (series) measurement**: cut JP1 open and
  insert a PPK2 (or any ammeter) across J2 (the 2-pin header silk-labelled
  `IBAT`, DNP by default — solder one in). Battery in JST as usual. JP1
  ships as a factory copper bridge: knife-cut it the first time, re-close
  with solder afterwards (wicking only applies to a soldered re-bridge).
- **PPK2 source-mode at J2**: feed J2 pin 2 + GND, JST empty, JP1 open.
  Pin 2 is VBAT — the charger output node, not VSYS (VSYS has no TP or
  header; probe D2's cathode pad). Powers the LDO tree + charger but
  excludes Q6. `tools/ppk2.py` rail id: `reva-j2`.
- **Do NOT back-feed the 3V3 test pad**: RT9080 abs-max forbids VOUT > VIN
  + 0.3V, and its EN=0 active-discharge (~80Ω) would fight the source.
  TP4 (3V3) is probe-only.
- Charge current: R3 10k → 100mA (0.25C for a 400–500mAh pouch). 4.99k →
  200mA if a bigger pack is fitted.
- C29 (10nF ADC reservoir on VBAT_ADC) is populated by default: enable the
  divider ~5ms before reading (τ = 50k × 10n = 0.5ms).
- BMP58x INT pins are unconnected: firmware must configure int_en=1,
  int_od=0, pad_int_drv=0 per the Bosch datasheets.
- Battery thresholds are board-scoped in Thermometer.cpp: **3550 warn /
  3500mV shutdown** (applied 2026-07-31 from the sweep + BOD-probe
  measurements, notes.md 2026-07-30 — droop at the refresh peak ≈300mV, so
  3500 keeps ~200mV of rail margin over the C6's 3.0V spec floor). That
  recovers most of the ~25% of pack capacity the buck-era 3700mV cutoff
  stranded; the cold and real-cell BOD-probe runs decide whether 3450
  (~5-8% more, OCV estimate) is safe.
- The first-article measurement list lives in [`BRINGUP.md`](BRINGUP.md)
  Phase 3 (VGH/VGL spec at refresh, EPD_VCC soft-start ramp, 3V3 sag →
  threshold re-derivation, boost ILIM transient, 32k crystal cold start,
  SS14 warm-floor leakage, VBAT_ADC sweep, charging self-heat). The 32k crystal
  is proven running warm on board 1 (no RTC fallback warning); cold start
  remains open.
- While charging, the board self-heats slightly — BMP581 temperature reads
  high until it cools; log accordingly.

## BOM

Generated at `bom/thermometer-c6-bom.csv` (JLCPCB columns) from circuit.py.
Notable parts: ESP32-C6-MINI-1-N4 (C5736265), RT9080-33GJ5 (C841192),
MCP73831-2 (C424093), Si1308EDL (C469327, low stock — fallback Si1304BDL
clone C7419947), MBR0530 TWGMC (C5204746), FPC-05FB-24PH20 dual-contact
(C2856831), SWPA4030S100MT (C38117), FC-135 (C32346), BMP581 (C5362283 —
**restocked at LCSC as of 2026-07-17** (3,675 pcs); the fab BOM populates
U5 by default. Re-verify stock at order time like everything else).

DESPI-C02 §4.5 requires an FPC socket with "contact at up side or both
side" — hence the dual-contact FPC-05FB (the bottom-contact-only
FPC-05F-24PH20 C2856805 must NOT be substituted). J4 uses the hand-drawn
`local:XUNPU_FPC-05FB-24PH20` footprint, transcribed from the XUNPU
FPC-05FB-NPH20 manufacture drawing (pads 0.3×1.2 @0.5mm, tabs 2.0×1.8 at
±7.3/+1.625 center-to-center) and cross-checked against the EasyEDA/JLC
C2856831 land pattern — the two agree exactly. The FPC-05FB is a rear-flip
connector: the SMT contact tails / pad row sit at the REAR (actuator) face,
and the mouth / cable entry is on the far side, 4.95mm from the pad centers
(body depth 5.40 = the XUNPU drawing; VERTEX_POINT-only STEP bbox,
`out/j3-land/` §7 2026-07-20 — the earlier 6.55 came from bounding-boxing
raw CARTESIAN_POINTs, which include LINE/AXIS2_PLACEMENT_3D entities that
own no geometry). On the board J4 is placed at rot 90 with the tail/pad
column WEST (x41.45) and the mouth EAST at x46.40, so the panel cable
approaches from the east edge. The mouth sits 1.60mm inboard of the edge
rather than flush — harmless for an FPC (the cable bottoms out inside the
housing either way) and it leaves the body fully supported. Pad 1 = panel circuit 1 sits at the NORTH end (the footprint pads are
numbered to keep pin 1 north despite the rear-flip geometry; the pin-1 silk
dot marks it). Pin-1 direction is verified against the DESPI-C02 manual
photos (P1 silk: "1" and "24" end markers, "24" at the P1-refdes end); note
the DESPI "P1" silk next to the pin-24 marker is the connector refdes, not
pin 1.

## Alternate sensor: BMP585 (U6, DNP by default)

The board carries footprints for BOTH BMP581 (U5, LGA-10 2×2) and BMP585
(U6, LGA-9 3.25×3.25, media-resistant — suitable for outdoor/weather-exposed
builds; gel-protected port under the metal lid, keep the Ø2.2mm opening
unobstructed in the enclosure). Same LP I2C bus, same 0x47 strapping
(CSB+SDO→VDDIO), same register map — the firmware BMP58x driver reads the
chip-ID (0x50=581, 0x51=585) and works with either unchanged.
**Populate exactly one**: both strap to address 0x47.
BMP585 = LCSC C18184976. Its datasheet
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

## Open items (user sign-off) — all dispositioned

1. **BMP581 sourcing** — RESOLVED 2026-07-17: restocked at LCSC (3,675
   pcs); the ordered boards populate U5 BMP581. The BMP585 (C18184976)
   remains the U6 populate-one alternate (outdoor/media-resistant builds,
   or if the 581 dries up again).
2. **Si1308EDL stock thin** — RESOLVED by the order: C469327 is on the
   boards; the fallback Si1304BDL-clone C7419947 was never needed.
3. **Reverse-polarity protection** — RESOLVED: Q6 AO3401A P-FET at the
   JST is fitted (see "Why these choices"); a reversed cell is blocked,
   MCP73831's −0.3V abs-max is respected. Proven on board 1: body diode
   0.4259V diode-mode pass ([`BRINGUP.md`](BRINGUP.md) Phase 0). Keyed JST
   + silk remain the first line of defense.
4. **EPD SPI/control series resistors omitted** — CLOSED by construction,
   no veto: boards fabbed without them, firmware floats the pins when the
   panel is gated off (src/Display.cpp), first render passed on board 1.
   Disposition recorded in [`SCHEMATIC-VERIFICATION.md`](SCHEMATIC-VERIFICATION.md).
5. **JST-PH polarity** — RESOLVED 2026-07-29 on hardware: DMM on the loose
   plug, red wire / + contact mates with J1's `+`-marked pad
   ([`BRINGUP.md`](BRINGUP.md) Phase 0). JST vs Adafruit convention still
   differs — re-check any new pigtail.
6. **FPC footprint** — DONE and hardware-verified: hand-drawn
   `local:XUNPU_FPC-05FB-24PH20` (see BOM section), respun 2026-07-19
   after a numeric STEP proof (`out/j4-proof/`), body depth corrected to
   5.40 on 2026-07-20. Placement verified pre-order (75/75 placements,
   [`archive/order-2026-07-20/`](archive/order-2026-07-20/)); J4 pin-1 north
   / mouth-east confirmed by continuity on board 1
   ([`BRINGUP.md`](BRINGUP.md) Phase 0).
7. **32k crystal populated by default** — CONFIRMED: on the ordered boards
   and proven oscillating on board 1 (no RTC fallback warning in the boot
   log); cold start remains a [`BRINGUP.md`](BRINGUP.md) Phase 3 item.
8. **Old Copilot draft** — MOOT as originally written: `hardware/kicad/`
   was never merged and exists only on the unmerged branch
   `hardware/custom-esp32c6-pcb`. Nothing in the tree to delete; the
   remaining call is whether to delete that branch.

## Follow-up phases

- PCB layout (2-layer) — **DONE**: booster switch loop tight, RESE sense
  short, no-copper zone under BMP581, antenna keep-out per Espressif HDG,
  JLCPCB gerbers/drill + CPL/BOM via `make fab` (order per
  [`ORDERING.md`](ORDERING.md)).
- Firmware — **DONE**: `THERMOMETER_C6_BOARD` variant (`thermometer_c6_*`
  envs in platformio.ini): EPD on GPIO18–23 + gate GPIO14 with float-on-off,
  battery divider GPIO2/3, VBUS sense GPIO4 (suppresses SoC shutdown on USB),
  LED GPIO15, 32k crystal via `sdkconfig.defaults.thermometer_c6`.
- Fab order — **DONE** (2026-07-20,
  [`archive/order-2026-07-20/`](archive/order-2026-07-20/); landed cost
  breakdown in [`ORDERING.md`](ORDERING.md) §8).
- Bring-up Phases 0–2 — **DONE** on board 1 (2026-07-29,
  [`BRINGUP.md`](BRINGUP.md)); measured numbers in the
  [`docs/notes.md`](../../docs/notes.md) power logbook.
- **NEXT** (hardware): [`BRINGUP.md`](BRINGUP.md) Phase 3 first-article
  measurements. Board 1 has been on battery soak since 2026-07-31 and most of
  Phase 3 waits on it. Boards 3–4 need bringing up, but not the full Phase 0–1
  checklist — board 2 skipped it and worked; only board 4's flagged U5 skew
  wants the Phase 2 sensor detect run early.

## Routed-copper census (rev A final vs the pre-connector-fix board)

`python3 verify/copper_stats.py --vs 9100758` — baseline `9100758` is the last
commit before the J4 mouth-east respin, the J3 datum/land fork and the R2.2
corners. Tracks and vias only; pours are regenerated fill, not authored copper.

```
segments   977 ->  906     -71  (-7.3%)
vias       189 ->  154     -35 (-18.5%)
F.Cu mm  756.1 -> 643.5  -112.5 (-14.9%)
B.Cu mm  840.6 -> 736.2  -104.4 (-12.4%)
total   1596.6 ->1379.7  -216.9 (-13.6%)
nets shorter 40   longer 2   ~unchanged 18   (of 60)

vias by region   FPC/east x>36  36 -> 27      USB/north y<9  51 -> 28
                 west x<20      84 -> 72
```

Putting both connectors on their true datums made the board measurably
simpler rather than merely correct: the USB/north region shed 45% of its vias
and CHG_STAT/EPD_SCK/VBUS/VBAT each lost 12–19mm. Routing style is
deliberately free-angle (≈48% of copper length off the 45/90 grid) — that is
a choice, not drift.

## Rev B candidates

Deliberately NOT taken for rev A — each is real but none justifies a respin
of a board that is otherwise order-ready.

- **Panel readback (SDO) — open, and per-controller.** Whether the panel can
  answer the host at all depends on its controller, not on this board, so there
  is no single answer to carry forward.
  **UC8151 works on the wiring as built**: probed 2026-08-05 on board 2 with a
  GDEY0213M21, `0x70` → `01 0e`, `0x71` → `13 13`, `0x40` → `d2 00`, each byte
  identical whether the input was pulled up or down (i.e. actively driven), while
  foreign SSD168x commands floated — that contrast is the control.
  **SSD2677 (the T81) is untested, and no longer "unlikely".** An earlier note
  here said it could not reply because the FPC carries no SDO. That was wrong:
  `SSD1677.pdf` names `SDI`/`SDO` as separate **chip** pins in 4-wire mode, but
  the T81 module bonds a single `SDA` to FPC pin 14 — exactly like every other
  panel here, none of which exposes an SDO either. Its module datasheet calls that
  pin an input and documents no read procedure, which was equally true of the M21
  before the M21 answered. **Probe a T81 before concluding anything.**
  Why it matters beyond diagnostics: `GxEPD2_576_GDEH0576T81::_Init_Full` reads
  the controller temperature to choose a waveform LUT, and today reads 0 — the
  coldest compensation on a room-temperature panel. If that is a wiring limit
  rather than a firmware one, the fixes are 3-wire mode (a 9-bit protocol GxEPD2's
  4-wire path does not implement) or an SDO on the FPC, and only then is this a
  board change. Firmware probe: `display_probe_readback()` behind `EPD_PROBE`.
  **What is readable is narrow, and per-controller.** On the UC8151 only three
  registers answer — `0x70` REV, `0x71` FLG, `0x40` temperature — and they answer
  identically before and after GxEPD2's init. `0x61` TRES and `0x00` PSR **float**,
  so resolution cannot be read back: the datasheet calls TRES a host-set override
  anyway, and probing before init confirmed it is not merely being overwritten.
  Resolution would in any case only ever **falsify** a match, never confirm one —
  two different 200x200 panels agree on it. The one panel-intrinsic value on offer
  is `0x70`'s `LUT_REV`, sourced from OTP address `0x001`, since a waveform LUT is
  tuned to its glass. Caveat before trusting it as an ID: our bytes (`01 0e`) do
  not match the datasheet's documented `CHIP_REV` of `1101b`, so the framing (a
  dummy first byte on OTP reads, or bit alignment) is unresolved — the values are
  stable and repeatable, so they serve as an opaque fingerprint, but should not be
  reported as "the chip revision" until that is settled. And nothing here
  transfers: an SSD168x command set floats entirely on a UC8151, so every panel
  family needs its own probe table.

- **Shrink the board east (48×35 → 47×35 or further).** J4's mouth is at
  x46.40, already 1.60mm inboard of the east edge, and there is no copper
  east of x46.0 (easternmost feature: the GND via at (45.60, 28.25)). The
  binding constraint on the 48.0 edge is **H1**, not J4: a ⌀2.2 hole at
  (45.8, 2.2) with the R2.2 corner arc concentric with it, giving a uniform
  1.100mm ring of FR4 around the corner. Shrinking means moving H1 west with
  the edge and re-centring both east corner arcs — the FR4 ring survives at
  1.100mm, but H1's ⌀4.993 screw-head keepout then overlaps Q1's courtyard
  by 0.806mm. No fab saving (1680 → 1645mm² is the same JLC tier), so this
  is only worth doing as part of a placement pass that gives Q1 somewhere to
  go. Study, scripts and renders: `out/east-shave/`.
- **Q1 clears H1's ⌀4.993 screw-head keepout by only 0.105mm** on the
  current board (nearest Q1 courtyard corner (43.345, 3.062) is 2.602mm from
  H1's centre). Independent of any shrink; worth a deliberate look in a rev B
  placement pass.
- **USB connector-segment symmetry.** `USB_D+`/`USB_D-` (U3→U1) are matched
  to 0.024mm, but the connector segment is not: D+ is daisy-chained *through*
  B6 to A6 (a series node, not a tap) while D- gets a balanced tee, so
  end-to-end skew is +2.31mm (B-row mated) or +5.21mm (A-row). 1.90mm of
  that is pure USBLC6 pinout — pins 1 and 3 sit 1.90mm apart on the same
  SOT-23-6 edge — and would vanish for free by swapping which (symmetric)
  channel carries which polarity. Irrelevant at the C6's 12 Mbps full speed
  (~31ps against an 83,333ps bit period, 4–20ns edges); it would start to
  matter only if this path ever carried High Speed.
- **Sensor placement against the board's heat sources — open, and not the swap
  it first looks like.** Edge-to-edge courtyard gaps:

  | heat source | → U5 (fitted) | → U6 (DNP alt) |
  |---|---|---|
  | U1 ESP32-C6 module | 2.25mm | 4.25mm |
  | U2 RT9080 LDO | 4.90mm | 3.00mm |
  | U4 MCP73831 charger | 36.8mm | 38.0mm |

  Populating U6 instead of U5 gains 2.0mm from the module and gives back 1.9mm
  to the LDO, so as a thermal move it is close to a wash — the obvious "put the
  default sensor at the far site" is not obviously an improvement.

  Which source matters depends on the mode, and duty cycle dominates the
  arithmetic (all figures below are calculated, none measured):
  - **Charging**: (5.0−3.7)V × 100mA ≈ **130mW continuous** at U4 for the whole
    CC phase — much the largest steady source, and 37mm from both sites, so it
    reaches the die as whole-board bulk warming through the pour rather than as
    a local gradient. **Sensor placement cannot fix this one**; a thermal moat,
    a lower charge current, or suppressing/flagging readings while charging are
    the levers.
  - **Deployed on battery**: the CPU is awake ~1s per wake, so ~100mW while
    awake time-averages to single-digit mW, and the LDO is sub-mW. Nothing here
    needs fixing — this is the mode the device actually lives in.
  - **Parked on USB** (the new service window, `docs` in `BRINGUP.md` Phase 3):
    the CPU is continuously awake, ~100mW at 2.25mm, plus ~50mW at the LDO
    (1.7V drop at ~30mA) 3–5mm away. This is the mode where local placement
    would actually pay, and it is a bench mode, not a deployment one.

  The no-pour keep-outs under both sensors already remove the plane coupling
  (Bosch thermal-fidelity guidance) but buy no distance.

  **There is no usable measurement yet.** Board 1's 33.9°C-vs-29.8°C is not
  evidence: it mixes bench sun, USB self-heat and the operator's fingers on the
  board (it decayed afterwards). Get a clean equilibrium delta per mode before
  anyone moves a footprint — `BRINGUP.md` Phase 3.

  If placement is revisited, the target is a site far from **both** U1 and U2 —
  the south/south-west edge — not U6's slot. Note a literal U5/U6 coordinate
  swap is infeasible anyway: U6's courtyard is 3.5mm square against U5's 2.2mm,
  and the northern slot has 0.45mm of headroom with the antenna keep-out and C12
  boxing it in, so it wants a re-flow of the sensor picket (U5/U6 +
  C12/C13/C26/C27), which is also what would let both move away from the LDO.
  Rev A can still bound the U1-proximity term on its own: the sites are
  populate-exactly-one and the driver reads the chip ID (0x50/0x51), so building
  one of boards 2–4 with U6 gives an A/B on the same rig (confounded by the
  different package and die-to-pad path). Needs a BMP585 (C18184976) in the next
  order.
- **No GND reference under the USB path.** Opposite-layer pour coverage is
  16.8% / 0.0% / 2.4% / 0.0% across the four USB nets against 28%/40%
  board-wide — the 0.5mm zone clearance starves the pour out in the dense
  x18–27, y6.7–15 window. The long D+ vertical crosses six foreign nets on
  B.Cu in 4.9mm and the two western signal vias have no GND stitch within
  4mm. Acceptable at full speed and the EPD boost switching nodes are not
  among the crossings, but it is the condition the path runs in.
- **Add key presses on silkscreen.** It would make it obvious how to recover.
  Especially: download mode, restarting firmware, as those are not softare
  defined. The shutdown sequence would be interesting as well but might not be
  a good idea as it could change.

### Cost reduction (researched 2026-07-22)

Baseline: the €204.94 qty 5 PCB / 4 assembled itemised quote in ORDERING.md
§8. The order landed at €273.93 (€211.93 JLC invoice 2026-07-27 + €62.00
DHL) ≈ €68.50/assembled board — breakdown in ORDERING.md; the per-unit
analysis below reasons from the quote. Three structural facts frame
everything: **Economy PCBA is unreachable
regardless of PCB options** (U1 and U5 are Standard-PCBA-only parts, both
locked; Economy is also single-sided-placement, ≤50pcs), **X-Ray is
mandatory** for U5's LGA and U1's shield (tiered per inspected piece —
$1.57/pc at 1–10; the €11.46 ≈ 2 parts × 4 boards — so it scales with
quantity, it is not a flat order fee), and **no wireless SoC or
environmental sensor exists in the JLC Basic tier at all** (verified
2026-07-23: Basic-filtered library probes for ESP32/ESP8266/nRF/BL602/
W800/CH57x/CC25xx/RTL87xx all return zero) — so feeder-fee optimisation is
small-bore and the real levers are POFV, quantity, and BOM-line count.
Tier/stock facts below re-verified 2026-07-23 against JLC's own part API
(`getComponentDetail`); fee-policy facts against jlcpcb.com's live
assembly-price page. The order dialog remains ground truth at order time.

- **Drop POFV in a rev B re-route: −€44.07/order, the single largest line.**
  Not a touch-up: a full via audit of the committed board found **81 vias in
  solderable pads** (independently reproduced 2026-07-23 with a pcbnew
  script: 84 via centres in mask-open SMD pads, 81 excluding the JP2/3/5
  copper-jumper pads) — via-in-pad is the board's core 2-layer escape
  strategy.
  ~50 have a legal dog-bone spot against today's copper (FPC-east fanout
  column, central EPD-driver discretes, all GND stitches); **26 are
  hard-boxed** with no clear spot within 1mm — dominated by 12 ESP32-C6 QFN
  pins (0.4mm pads narrower than the 0.6mm via), the 32k crystal pair, the
  sensor pins, and the USB-C VBUS/CC joints. J4 (0.5mm FPC) and U5 (LGA)
  are already via-in-pad-free, so nothing is geometrically impossible.
  Opportunity cost: days — grow the outline (free up to JLC's 100×100mm
  tier), re-place the west/QFN cluster, re-route essentially from scratch,
  full-severity DRC again, and a fresh first-article risk. Best bundled
  with the Q1/H1 placement pass above and the production-copper trim below
  (the freed bench-pad corridors are exactly where the dog-bones must go).
  Before committing to it, confirm POFV is a flat charge vs qty (quote at
  5/10/20) — if flat, large orders amortise it and weaken the case. The
  scaling is not documented anywhere public (checked 2026-07-23: JLC's
  extra-charges article doesn't list POFV; the only official pricing fact
  is that POFV is free on 6–20-layer boards, paid on 2/4-layer), so the
  quote calculator is the only oracle.
- **Panel-lock BOM collapse: −€3–9/order.** Locking the panel family to the
  proven 10µH/0.47Ω config deletes L2 (47µH, Extended), R15 (2.2Ω) and R16
  (3Ω) plus their placements; JP2–JP6 are copper-only and can stay.
  Opportunity cost: the board loses the GDEH0576T81-datasheet booster
  option (47µH + 2.2Ω RESE) and the 3Ω SSD16xx leg — fine iff the panel
  choice is final; the copper jumpers keep a hand-solder escape hatch.
- **MBR0530 → B5819W (C8598) confirmed-Basic swap: −~€2.75/order.** Same
  SOD-123 package, 40V/1A vs 30V/0.5A. Verified 2026-07-23 via the JLC
  part API: **Basic tier, 621k stock, $0.029** (MBR0530 C5204746 confirmed
  Extended). Vf 600mV@1A vs 500mV@500mA costs a hair of refresh
  efficiency; reverse leakage is irrelevant (the whole booster hangs off
  gated EPD_VCC). Caveat: the −€2.75 assumes the per-Extended-line feeder
  billing the 2026-07-20 quote exhibited — under JLC's *documented*
  Standard-PCBA policy ($1.50 × every unique line, Basic included) the
  swap is feeder-neutral and saves only pennies of part cost. Resolve the
  feeder question (ORDERING.md §3/§4) before counting this saving.
- **C98192 (4.7µF/50V, 9 placements, one Extended line) → C440198
  candidate Basic swap: −~€2.75/order, same caveat.** There is no Basic
  4.7µF ≥50V 0805 (verified 2026-07-23; the only Basic 4.7µF 0805 is
  25V), but **C440198 10µF 50V X5R 0805 is Basic** with 2.4M stock.
  Doubling the pump/reservoir caps (C16–C24) and the VBUS-side C5/C6
  needs booster re-validation (startup surge, pump timing) — try only
  with a bench board to compare against, and mind X5R DC-bias derating
  at the ~22V rails is similar for both parts.
- **Production-copper trim (dev board → production board): −~€1–6/order,
  but mainly routing room.** The board already carries its debug features
  as DNP/copper-only (J5, J2, JP1–6, all TPs, R9, U6), so they cost
  nothing at assembly. What a production variant can still cut: SW1/SW2 →
  tweezer-shortable pads (keeps the unbrick path — USB-Serial-JTAG download
  works but the device deep-sleeps ~99% of the time, so a physical
  BOOT-at-power-on path is worth keeping in some form) and D3 (status is
  the EPD's job). Keep D1: CHG_STAT reaches no GPIO, so it is the only
  charge indication. The real value is deleting TP/J5/J2/U6 copper in the
  same pass — TP7 alone pinches the B.Cu channel south of the booster to a
  0.30mm slot, and the bench pads impose 2.1mm HV keepout walls — which is
  exactly the room the POFV dog-bones need. Opportunity cost: the PPK2
  bench procedures above stop working on that variant; only strip after
  the rev-A first-article campaign is done.
- **Quantity is the dominant per-unit lever, no design change needed.**
  ~€78/order is fixed (setup 22.32, feeders 46.75, stencil 7.17, confirm
  fees 1.30); X-Ray (€11.46) is tiered per inspected piece so it shrinks
  per-board with volume but never disappears. At qty 4 assembled that is
  ~€20–23/board of pure overhead. Qty 15–20 takes unit cost from ~€51 to
  ~€20–25 with the design untouched (modulo how POFV scales — see above).

Ruled out, with reasons (don't re-research):

- **SoC alternatives — U1 stays.** Requirements bar (docs/notes.md): hold
  the 14–16µA system deep-sleep floor, sample I2C every 60s in deep sleep
  at ~50nA average without booting the HP core (LP core), 32.768kHz XTAL,
  WiFi. ESP32-C3/C2/ESP8685/ESP8266/BL602/W800 all fail the LP-sampling
  bar (no LP/ULP coprocessor; ESP8266 also ~20µA floor) and save ≤€1.
  Nordic nRF52x has best-in-class sleep and a CPU-off TWIM sampling path
  but is BLE-only — fails WiFi outright. Bare ESP32-C6FH4 saves ~$0.5 and
  costs antenna design + modular RF certification. No wireless part is
  Basic tier, so there is no feeder-fee escape either.
- **Sensor alternatives — U5 stays.** BMP581 is ~$1.44 at LCSC ($2.35–3.03
  through JLC assembly) — already the cheapest pressure-capable part that
  passes the power bar (~0.5µA standby, ~3µC/forced reading). BMP390L costs *more* (~$5) despite the
  existing driver; BMP280 saves pennies and is equally Standard-only.
  SHT40 is the standout if pressure were expendable (80nA, ~2.4µC, ±0.2°C,
  ~$1.3) but its Economy-capability is moot (U1 forces Standard) and it
  drops pressure. AHT20/21 fail per-reading energy (~80ms conversions);
  MCP9808 (~50µC/reading at 0.1°C res), STTS22H (1.75µA standby), LM75B
  (±2°C) all fail the bars. An NTC divider (~$0.01, GPIO-gated → zero
  standby, like the battery divider) passes the power bars trivially but
  is ±0.5–1°C uncalibrated (±0.2–0.3°C with single-point cal), needs C6
  SAR ADC characterisation to reach 0.1°C resolution, and drops pressure.
- **ENIG stays** (€14.84): the locked 0.5mm-pitch LGA and FPC sit at JLC's
  0.20mm HASL clearance floor, and dropping it cannot unlock Economy
  anyway. **X-Ray stays**: mandatory for LGA. **D1, USBLC6, Q6, Y1 stay**:
  charge indication, ESD, reverse-battery survival and timekeeping are
  functionality, and each saves pennies at best.

Net: cheap wins (panel lock + diode swap + production trim) ≈ €15–25/order
with rev-A-class effort; the POFV rev B adds ~€44/order more but is a real
re-layout; quantity halves unit cost on its own.
