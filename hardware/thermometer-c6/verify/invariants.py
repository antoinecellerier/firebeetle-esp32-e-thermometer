#!/usr/bin/env python3
"""Independent design invariants, hand-written from the design doc (README /
plan) and checked against the EXPORTED netlist — not against circuit.py.
This closes the loop where a circuit.py mistake would satisfy its own golden
file: these assertions restate the design intent from first principles.
"""

import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "generator"))
sys.path.insert(0, HERE)

from check_netlist import load_netlist, load_components  # noqa: E402

FAIL = []


def net_of(nets, ref, pin):
    for name, pins in nets.items():
        if (ref, str(pin)) in pins:
            return name
    return None


def check(desc, cond):
    if cond:
        print(f"  ok: {desc}")
    else:
        print(f"FAIL: {desc}")
        FAIL.append(desc)


def main():
    nets = load_netlist(sys.argv[1])
    comps = load_components(sys.argv[1])

    def N(ref, pin):
        return net_of(nets, ref, pin)

    def V(ref):
        return comps.get(ref, {}).get("value", "<absent>")

    def dnp(ref):
        return comps.get(ref, {}).get("dnp", False)

    def unconnected(ref, pin):
        n = N(ref, pin)
        return n is None or n.startswith("unconnected-")

    # --- power tree -----------------------------------------------------
    check("Reverse-battery P-FET: JST+ on drain, system on source, gate grounded",
          N("J1", 1) == N("Q6", 3) and N("Q6", 2) == N("JP1", 1)
          and N("Q6", 1) == "GND" and N("J1", 1) != N("JP1", 1))
    check("PPK2 break: protected battery reaches system VBAT only through JP1/J2",
          N("Q6", 2) != N("JP1", 2) and N("Q6", 2) == N("JP1", 1) == N("J2", 1))
    check("LDO input is VSYS (load-share node), not raw battery",
          N("U2", 1) == N("Q1", 2) == N("D2", 1) and N("U2", 1) != N("J1", 1))
    check("LDO EN tied to VIN", N("U2", 3) == N("U2", 1))
    check("Load-share P-FET: drain on VBAT, source on VSYS, gate on VBUS",
          N("Q1", 3) == N("U4", 3) and N("Q1", 2) == N("U2", 1)
          and N("Q1", 1) == N("U4", 4))
    check("Load-share gate pull-down R5 between VBUS-gate net and GND",
          N("R5", 1) == N("Q1", 1) and N("R5", 2) == "GND")
    check("Schottky D2: anode on VBUS, cathode on VSYS",
          N("D2", 2) == N("U4", 4) and N("D2", 1) == N("U2", 1))
    check("Charger BAT pin and its 4.7uF sit on system-side VBAT with divider + TP",
          N("U4", 3) == N("C6", 1) == N("Q4", 2) == N("TP1", 1))
    check("Charger PROG: U4 pin 5 through R3 to GND, nothing else on the node",
          nets.get(N("U4", 5), set()) == {("U4", "5"), ("R3", "1")}
          and N("R3", 2) == "GND")
    check("Charge current 100mA: R3 = 10k (MCP73831 IREG = 1000V/R, 0.25C for "
          "a 400-500mAh pouch)",
          V("R3") == "10k")
    check("LDO output on +3V3 with 10uF + 100nF caps to GND",
          N("U2", 5) == "+3V3" and N("C3", 1) == "+3V3" and N("C4", 1) == "+3V3"
          and N("C3", 2) == "GND" and N("C4", 2) == "GND"
          and V("C3") == "10uF" and V("C4") == "100nF")

    # --- USB ------------------------------------------------------------
    check("CC1/CC2 each have their own 5.1k to GND",
          N("J3", "A5") == N("R1", 1) and N("J3", "B5") == N("R2", 1)
          and N("R1", 2) == "GND" and N("R2", 2) == "GND"
          and N("J3", "A5") != N("J3", "B5"))
    check("USB D-: connector pins A7/B7 into ESD pin 1; ESD pin 6 to GPIO12 "
          "(flow-through — the USBLC6 symbol joins the line internally)",
          N("J3", "A7") == N("J3", "B7") == N("U3", 1)
          and N("U3", 6) == N("U1", 17) and N("U3", 1) != N("U3", 6))
    check("USB D+: connector pins A6/B6 into ESD pin 3; ESD pin 4 to GPIO13",
          N("J3", "A6") == N("J3", "B6") == N("U3", 3)
          and N("U3", 4) == N("U1", 18) and N("U3", 3) != N("U3", 4))
    check("Charge LED powered from VBUS (not battery)",
          N("R4", 1) == N("J3", "A4") and N("D1", 1) == N("U4", 1))
    check("VBUS sense: 100k/100k from VBUS to GPIO4 (pin 9) and debug header, "
          "zero drain with USB absent",
          N("R22", 1) == N("J3", "A4") and N("R22", 2) == N("R23", 1) == N("U1", 9)
          and N("U1", 9) == N("J5", 6) and N("R23", 2) == "GND")
    check("VBUS TVS (DNP) clamps VBUS to GND",
          N("D7", 1) == N("J3", "A4") and N("D7", 2) == "GND")

    # --- MCU support ----------------------------------------------------
    check("EN has pull-up to 3V3, RC cap to GND, reset button to GND",
          N("R6", 2) == N("U1", 8) == N("C9", 1) == N("SW1", 1)
          and N("R6", 1) == "+3V3" and N("C9", 2) == "GND" and N("SW1", 2) == "GND")
    check("BOOT button on GPIO9 (pin 23) with 10k pull-up to 3V3",
          N("SW2", 1) == N("U1", 23) == N("R7", 2) and N("R7", 1) == "+3V3"
          and N("SW2", 2) == "GND")
    check("32k crystal on GPIO0/GPIO1 (module pins 12/13) with load caps to GND",
          N("Y1", 1) == N("U1", 12) == N("C10", 1)
          and N("Y1", 2) == N("U1", 13) == N("C11", 1)
          and N("C10", 2) == "GND" and N("C11", 2) == "GND")
    check("Status LED on GPIO15 (pin 20) — NOT on strap GPIO8/GPIO9 (pins 22/23)",
          N("R8", 1) == N("U1", 20) and N("D3", 2) == N("R8", 2)
          and N("D3", 1) == "GND")
    check("GPIO8 (pin 22) carries nothing but the high-Z debug header",
          nets.get(N("U1", 22), set()) == {("U1", "22"), ("J5", "8")})

    # --- sensor ---------------------------------------------------------
    check("BMP581 on LP I2C: SDA=GPIO6 (pin 15), SCL=GPIO7 (pin 16)",
          N("U5", 4) == N("U1", 15) and N("U5", 2) == N("U1", 16))
    check("Exactly one 4.7k pull-up to 3V3 on each of SDA/SCL",
          N("R10", 2) == N("U5", 4) and N("R11", 2) == N("U5", 2)
          and N("R10", 1) == "+3V3" and N("R11", 1) == "+3V3")
    check("BMP581 addr 0x47 strapping: SDO and CSB tied to VDDIO rail (3V3)",
          N("U5", 5) == "+3V3" and N("U5", 6) == "+3V3")
    check("BMP581 INT unconnected (firmware: int_en=1, int_od=0, drv=0)",
          unconnected("U5", 7))
    check("BMP581 supplies on always-on 3V3 (LP core reads during deep sleep)",
          N("U5", 1) == "+3V3" and N("U5", 10) == "+3V3")
    check("BMP585 alternate shares the LP I2C bus: SDX=GPIO6, SCX=GPIO7",
          N("U6", 2) == N("U1", 15) and N("U6", 1) == N("U1", 16))
    check("BMP585 straps for 0x47 like the 581: SDO and CSB to VDDIO rail",
          N("U6", 3) == "+3V3" and N("U6", 7) == "+3V3")
    check("BMP585 supplies on 3V3, VSS on GND, INT unconnected",
          N("U6", 4) == "+3V3" and N("U6", 8) == "+3V3"
          and unconnected("U6", 5) and N("U6", 6) == "GND")

    # --- battery sense (high-side switched) ------------------------------
    check("Divider is high-side switched: P-FET source on VBAT, drain feeds top 100k",
          N("Q4", 2) == N("U4", 3) and N("Q4", 3) == N("R20", 1))
    check("Sense node: top 100k + bottom 100k + GPIO2 (pin 5) + TP + "
          "sampling cap, nothing else",
          nets.get(N("U1", 5), set()) ==
          {("U1", "5"), ("R20", "2"), ("R21", "1"), ("TP11", "1"), ("C29", "1")})
    check("Bottom 100k grounds the divider directly (pin at 0V when off)",
          N("R21", 2) == "GND")
    check("P-gate pulled to VBAT (off) and pulled low by 2N7002 drain",
          N("R18", 1) == N("Q4", 2) and N("R18", 2) == N("Q4", 1) == N("Q5", 3))
    check("VDIV_EN = GPIO3 (pin 6) with 100k pull-down (off in deep sleep)",
          N("Q5", 1) == N("U1", 6) == N("R19", 1) and N("R19", 2) == "GND"
          and N("Q5", 2) == "GND")

    # --- EPD gate + booster ----------------------------------------------
    check("EPD gate P-FET: source 3V3, drain EPD_VCC; GPIO14 drives through "
          "the R24/C28 soft-start (~100us ramp)",
          N("Q2", 2) == "+3V3" and N("Q2", 3) == N("L1", 1)
          and N("Q2", 1) == N("R24", 1) == N("C28", 2)
          and N("R24", 2) == N("U1", 19) and N("C28", 1) == "+3V3"
          and N("Q2", 1) != N("U1", 19))
    check("Gate pull-up 10k to 3V3 -> panel OFF at reset/deep-sleep",
          N("R12", 2) == N("Q2", 1) and N("R12", 1) == "+3V3")
    check("Panel RST pull-up goes to EPD_VCC, NOT 3V3",
          N("R17", 1) == N("Q2", 3) and N("R17", 2) == N("J4", 10)
          and N("R17", 1) != "+3V3")
    check("Booster runs from gated EPD_VCC: both inductors + panel VDDIO/VCI",
          N("L1", 1) == N("L2", 1) == N("J4", 15) == N("J4", 16) == N("Q2", 3))
    check("Inductor select: each coil through its own solder jumper onto the "
          "switch node (10uH default-bridged, 47uH open)",
          N("L1", 2) == N("JP5", 1) and N("L2", 2) == N("JP6", 1)
          and N("JP5", 2) == N("JP6", 2) == N("Q3", 3))
    check("Boost switch: FET drain on SW node with jumpers, D4 anode, pump cap",
          N("Q3", 3) == N("D4", 2) == N("C16", 1))
    check("GDR drives boost FET gate, 10k bleed to GND, panel pin 2",
          N("Q3", 1) == N("J4", 2) == N("R13", 1) and N("R13", 2) == "GND")
    check("RESE: FET source to panel pin 3 and three jumpered legs",
          N("Q3", 2) == N("J4", 3) == N("R14", 1) == N("R15", 1) == N("R16", 1))
    check("Each RESE leg: resistor -> its own jumper -> GND",
          N("R14", 2) == N("JP2", 1) and N("R15", 2) == N("JP3", 1)
          and N("R16", 2) == N("JP4", 1)
          and N("JP2", 2) == "GND" and N("JP3", 2) == "GND" and N("JP4", 2) == "GND")
    check("PREVGH: D4 cathode + storage cap + panel pin 21",
          N("D4", 1) == N("C17", 1) == N("J4", 21) and N("C17", 2) == "GND")
    check("Negative pump: SW -> C16 -> node with D5 anode (clamp to GND) + D6 cathode",
          N("C16", 2) == N("D5", 2) == N("D6", 1) and N("D5", 1) == "GND")
    check("PREVGL: D6 anode + storage cap + panel pin 23",
          N("D6", 2) == N("C18", 1) == N("J4", 23) and N("C18", 2) == "GND")
    check("BS (panel pin 8) tied to GND -> 4-wire SPI",
          N("J4", 8) == "GND")

    # --- FPC pin map (transcribed from DESPI-C02) ------------------------
    check("FPC 9..14 = BUSY,RES,D/C,CS,SCLK,SDI to GPIO23,22,21,20,19,18",
          N("J4", 9) == N("U1", 29) and N("J4", 10) == N("U1", 28)
          and N("J4", 11) == N("U1", 27) and N("J4", 12) == N("U1", 26)
          and N("J4", 13) == N("U1", 25) and N("J4", 14) == N("U1", 24))
    check("Panel storage caps on 4,5,18,19,20,22,24 (VGL,VGH,VDD,VPP,VSH,VSL,VCOM)",
          N("J4", 4) == N("C19", 1) and N("J4", 5) == N("C20", 1)
          and N("J4", 18) == N("C21", 1) and N("J4", 19) == N("C22", 1)
          and N("J4", 20) == N("C23", 1) and N("J4", 22) == N("C24", 1)
          and N("J4", 24) == N("C25", 1))
    check("Panel VSS (17) on GND; pins 1,6,7 unconnected",
          N("J4", 17) == "GND" and unconnected("J4", 1)
          and unconnected("J4", 6) and unconnected("J4", 7))

    # --- debug header -----------------------------------------------------
    check("Debug header: GND,3V3,EN,TXD0,RXD0,IO4,IO5,IO8,GND,GND — no VBAT "
          "next to 3V3 (one-pin-offset plug must not back-drive the LDO)",
          N("J5", 1) == "GND" and N("J5", 2) == "+3V3"
          and N("J5", 3) == N("U1", 8) and N("J5", 4) == N("U1", 31)
          and N("J5", 5) == N("U1", 30) and N("J5", 6) == N("U1", 9)
          and N("J5", 7) == N("U1", 10) and N("J5", 8) == N("U1", 22)
          and N("J5", 9) == "GND" and N("J5", 10) == "GND")

    # --- component values (datasheet-derived, read from the exported -------
    # --- netlist's components section, not from circuit.py) ----------------
    check("EN reset RC = 10k + 1uF (Espressif C6 HDG CHIP_PU recommendation)",
          V("R6") == "10k" and V("C9") == "1uF")
    check("BOOT pull-up R7 = 10k", V("R7") == "10k")
    check("32k load caps = 20pF each (FC-135 CL 12.5pF, 2*(CL-~2.5pF stray))",
          V("C10") == "20pF" and V("C11") == "20pF")
    check("I2C pull-ups = 4.7k to the always-on rail",
          V("R10") == "4.7k" and V("R11") == "4.7k")
    check("USB-C CC pull-downs = 5.1k (UFP Rd)",
          V("R1") == "5.1k" and V("R2") == "5.1k")
    check("Battery divider = matched 100k 1% pair (VBAT/2 into the ADC)",
          V("R20") == "100k 1%" and V("R21") == "100k 1%")
    check("Divider switch + VBUS sense resistors all 100k (leak-bounded)",
          V("R18") == "100k" and V("R19") == "100k"
          and V("R22") == "100k" and V("R23") == "100k" and V("R5") == "100k")
    check("EPD gate: 10k pull-up, 10k series + 10nF soft-start (~100us ramp)",
          V("R12") == "10k" and V("R24") == "10k" and V("C28") == "10nF")
    check("RESE ladder = 0.47R / 2.2R / 3.0R at 1% (DESPI-C02 + GDEH0576T81 "
          "datasheet options)",
          V("R14") == "0.47R 1%" and V("R15") == "2.2R 1%"
          and V("R16") == "3.0R 1%")
    check("Boost inductors: L1 = 10uH (proven default), L2 = 47uH (T81 pairing)",
          V("L1").startswith("10uH") and V("L2").startswith("47uH"))
    check("Every cap that can see boost rails is 50V-rated "
          "(VGH/VGL reach ~±20V; DESPI reference used 25V)",
          all(V(r) == "4.7uF/50V" for r in
              ("C16", "C17", "C18", "C19", "C20", "C23", "C24"))
          and all(V(r) == "1uF/50V" for r in ("C21", "C22", "C25")))
    check("Populate-exactly-one sensor: U5 BMP581 fitted, U6 BMP585 (+ its "
          "caps) DNP — both strap I2C 0x47",
          not dnp("U5") and dnp("U6") and dnp("C26") and dnp("C27"))
    check("DNP roster: J2 MEAS header, J5 debug header, R9 crystal bias, "
          "D7 VBUS TVS — everything else populated",
          {r for r, c in comps.items() if c["dnp"]}
          == {"J2", "J5", "R9", "D7", "U6", "C26", "C27"})

    print()
    if FAIL:
        print(f"invariants: {len(FAIL)} FAILURES")
        sys.exit(1)
    print("invariants: all passed")


if __name__ == "__main__":
    main()
