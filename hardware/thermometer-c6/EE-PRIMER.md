# EE primer — reading the thermometer-c6 schematic

A field guide to the symbols and the electrical idioms on this board,
keyed to actual reference designators so you can follow along in the PDF.

## Reading the sheet

- **Wires** connect only where a **junction dot** (filled circle) sits, or
  where a wire ends exactly on a pin. Two wires *crossing without a dot are
  not connected* — that's the standard convention (this sheet currently has
  zero crossings anyway).
- **Global labels** (the flag-shaped tags like `EPD_SCK`) connect every
  point carrying the same name, sheet-wide. They're how the MCU zone talks
  to the FPC zone without 20cm of drawn wire. Click one in KiCad to
  highlight the whole net.
- **Power symbols**: the up-arrow/bar (`+3V3`, `VBUS`) and the three-line
  triangle (`GND`) are just global labels in disguise — every `GND` symbol
  is the same net.
- **PWR_FLAG (the small diamond)**: an ERC-only marker saying "trust me,
  this net is powered". ERC classifies pins (power input, output, passive);
  a net that reaches power-input pins only through passives (GND arrives
  via a connector; VSYS via a FET) would flag an error without it. Zero
  electrical meaning.
- **X on a pin** (small blue cross): deliberate no-connect. **Big red X
  over a part**: DNP — footprint on the board, part not fitted (U6, D7,
  R9, the headers).
- **Solder jumpers** (two pads with a dumbbell): bridged = filled link,
  open = gap. Config switches you operate with an iron; effectively 0Ω.
- **Test point** (circle on a stub): a bare copper pad for a probe.

## Component symbols

- **R / C / L**: zigzag-less EU-style rectangle = resistor; two parallel
  plates = capacitor; humps = inductor. Values: `4.7k`, `100nF`, `10uH`.
  `1%` = tolerance (matters on dividers), `/25V` = voltage rating (matters
  on the ±20V EPD rails).
- **Diode** (triangle + bar): current flows the way the triangle points,
  anode (A) → cathode (K, the bar side), dropping ~0.3V for Schottkys
  (MBR0530, SS14) and blocking in reverse. **TVS** (D7): a Zener-like
  clamp that shorts overvoltage spikes to GND.
- **LED**: diode + arrows. Current direction is the same A→K story;
  brightness set by the series resistor (R4, R8: I ≈ (V−Vf)/R).
- **MOSFET** (circle, three pins G/S/D): a voltage-controlled switch.
  Gate voltage *relative to source* (V_GS) turns the channel on:
  - **N-FET** (Q3, Q5, 2N7002): on when gate is a few volts *above*
    source. Source usually sits at GND → drive gate high to switch.
  - **P-FET** (Q1, Q2, Q4, Q6, AO3401A): on when gate is a few volts
    *below* source. Source sits at the supply → pull gate low to switch.
  - The **body diode** (drawn inside the symbol) is intrinsic: current can
    always sneak from drain→source (P-FET) regardless of the gate. Every
    P-FET on this board is oriented so that diode either helps (Q1 load
    share) or blocks the fault (Q6 reverse battery).

## The idioms in each zone

- **Pull-up / pull-down** (R6, R7, R12, R13, R19…): a high-value resistor
  that defines a node's voltage when nothing drives it. Costs current only
  when the node is held at the opposite rail (V/R — 3.3V/10k = 330µA while
  active, zero when idle). R12 pulls the EPD gate to 3V3 so the panel is
  OFF whenever the MCU is in reset/deep-sleep and the pin floats.
- **Decoupling capacitor** (the 100nF+10µF pairs at every IC): a local
  energy reservoir. Chips draw current in nanosecond spikes that the
  battery, centimetres away through inductive traces, cannot deliver; the
  cap next to the pin can. That's why C12/C13 must sit *at* U5's pins and
  why C26/C27 duplicate them at U6 — decoupling is positional.
- **Voltage divider** (R20/R21, R22/R23): two resistors make
  Vout = Vin·R2/(R1+R2). Halves the battery voltage into the ADC's range.
  The trick here: the divider leaks V/(R1+R2) continuously, so Q4/Q5
  disconnect it — and from the *high side*, because a low-side switch
  leaves the middle node pulled up to VBAT, where the ADC pin's internal
  ESD protection diode would leak into the 3V3 rail.
- **High-side switch** (Q2, Q4): a P-FET between supply and load — the
  load's GND stays honest and the rail is truly dead when off. Q2 gates
  the entire EPD booster because that booster leaks ~534µA when left
  powered (measured — the reason this board exists).
- **Load sharing** (D2 + Q1): with USB plugged, VBUS feeds VSYS through
  the Schottky and Q1's gate (=VBUS) turns the P-FET off, so the system
  runs from USB while the charger sees only the battery. Unplug: gate
  falls, Q1's body diode conducts for a microsecond, then the channel
  turns fully on and shorts the diode out. Zero standing current either way.
- **Reverse protection** (Q6): P-FET wired "backwards" in the battery
  feed. Correct polarity: body diode conducts first, then V_GS = −VBAT
  enhances the channel (mΩ loss, unlike a series diode's 0.3V). Reversed
  battery: the diode blocks and V_GS is positive → FET stays off. A
  polarity fuse with no fuse to replace.
- **LDO vs buck** (U2): a linear regulator is a smart series resistor —
  quiet, tiny idle current, output degrades *gracefully* as the battery
  sags. A buck is a switcher — more efficient mid-load, but the XIAO's
  buck has a hard cliff at 3.545V that cost 12–15% of pack capacity. At
  20µA sleep currents, LDO losses are irrelevant; graceful wins.
- **Boost converter** (zone G): L1 + Q3 + D4. The panel's controller
  pulses Q3 via GDR: switch closes → current ramps in the inductor (energy
  = ½LI²); switch opens → the inductor *insists* on keeping current
  flowing, so its voltage flies up and dumps through D4 into C17,
  producing ~+22V (PREVGH) from 3.3V. **Charge pump** (C16/D5/D6): the
  same switching node AC-couples through C16; D5/D6 rectify the negative
  excursion into −22V (PREVGL). E-paper needs both polarities to drive
  ink particles up and down.
- **Current sense** (RESE, R14–16): the panel regulates its boost by
  watching the voltage across this fraction-of-an-ohm resistor
  (I = V/R). Its value sets the peak inductor current — which is why it's
  panel-family-specific and why a mechanical switch (tens of mΩ of
  contact resistance) was ruled out in favour of solder jumpers.
- **RC time constants** (R6/C9, R24/C28): a resistor charging a capacitor
  reaches ~63% in τ = R·C. R6/C9 delay the MCU's enable ~10ms so the rail
  is stable before boot. R24/C28 slow Q2's gate so EPD_VCC ramps in ~100µs
  instead of instantly — an instant turn-on would yank charge out of the
  3V3 caps faster than the LDO can respond and brown out the MCU.
- **Crystal load caps** (C10/C11): a 32.768kHz crystal oscillates at spec
  only against its rated load capacitance, C_L = 12.5pF ≈ series
  combination of the two 20pF caps plus board strays. Wrong caps = wrong
  frequency or no start (cold, especially). R9 (DNP 10MΩ) is a bias
  helper if a batch won't start.
- **Flow-through ESD** (U3): the USB data lines enter pin 1/3 and leave
  pin 6/4 so the layout physically routes *through* the protection chip —
  a spike meets the clamp before it meets the MCU.

## Units cheat-sheet

µA = 10⁻⁶A. The sleep budget here is ~15–20µA total; a single always-on
divider (~10µA) or an ungated booster (~534µA) dwarfs it. mC = millicoulomb
= charge per event: 100mC per refresh, hourly, averages 100mC/3600s ≈ 28µA
— which is why refresh energy and sleep floor matter equally.
