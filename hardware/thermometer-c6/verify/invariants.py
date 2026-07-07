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

from check_netlist import load_netlist  # noqa: E402

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

    def N(ref, pin):
        return net_of(nets, ref, pin)

    # --- power tree -----------------------------------------------------
    check("PPK2 break: JST+ reaches system VBAT only through JP1/J2 (nets differ)",
          N("J1", 1) != N("JP1", 2) and N("J1", 1) == N("JP1", 1) == N("J2", 1))
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

    # --- USB ------------------------------------------------------------
    check("CC1/CC2 each have their own 5.1k to GND",
          N("J3", "A5") == N("R1", 1) and N("J3", "B5") == N("R2", 1)
          and N("R1", 2) == "GND" and N("R2", 2) == "GND"
          and N("J3", "A5") != N("J3", "B5"))
    check("USB D- goes to GPIO12 (module pin 17) through ESD pins 1/6",
          N("J3", "A7") == N("U3", 1) == N("U3", 6) == N("U1", 17))
    check("USB D+ goes to GPIO13 (module pin 18) through ESD pins 3/4",
          N("J3", "A6") == N("U3", 3) == N("U3", 4) == N("U1", 18))
    check("Charge LED powered from VBUS (not battery)",
          N("R4", 1) == N("J3", "A4") and N("D1", 1) == N("U4", 1))

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
          nets.get(N("U1", 22), set()) == {("U1", "22"), ("J5", "9")})

    # --- sensor ---------------------------------------------------------
    check("BMP581 on LP I2C: SDA=GPIO6 (pin 15), SCL=GPIO7 (pin 16)",
          N("U5", 4) == N("U1", 15) and N("U5", 2) == N("U1", 16))
    check("Exactly one 4.7k pull-up to 3V3 on each of SDA/SCL",
          N("R10", 2) == N("U5", 4) and N("R11", 2) == N("U5", 2)
          and N("R10", 1) == "+3V3" and N("R11", 1) == "+3V3")
    check("BMP581 addr 0x47 strapping: SDO and CSB tied to VDDIO rail (3V3)",
          N("U5", 5) == "+3V3" and N("U5", 6) == "+3V3")
    check("BMP581 INT tied to GND (datasheet: don't float)",
          N("U5", 7) == "GND")
    check("BMP581 supplies on always-on 3V3 (LP core reads during deep sleep)",
          N("U5", 1) == "+3V3" and N("U5", 10) == "+3V3")

    # --- battery sense (high-side switched) ------------------------------
    check("Divider is high-side switched: P-FET source on VBAT, drain feeds top 100k",
          N("Q4", 2) == N("U4", 3) and N("Q4", 3) == N("R20", 1))
    check("Sense node: top 100k + bottom 100k + GPIO2 (pin 5) + test point, nothing else",
          nets.get(N("U1", 5), set()) ==
          {("U1", "5"), ("R20", "2"), ("R21", "1"), ("TP11", "1")})
    check("Bottom 100k grounds the divider directly (pin at 0V when off)",
          N("R21", 2) == "GND")
    check("P-gate pulled to VBAT (off) and pulled low by 2N7002 drain",
          N("R18", 1) == N("Q4", 2) and N("R18", 2) == N("Q4", 1) == N("Q5", 3))
    check("VDIV_EN = GPIO3 (pin 6) with 100k pull-down (off in deep sleep)",
          N("Q5", 1) == N("U1", 6) == N("R19", 1) and N("R19", 2) == "GND"
          and N("Q5", 2) == "GND")

    # --- EPD gate + booster ----------------------------------------------
    check("EPD gate P-FET: source 3V3, drain EPD_VCC, gate GPIO14 (pin 19)",
          N("Q2", 2) == "+3V3" and N("Q2", 3) == N("L1", 1)
          and N("Q2", 1) == N("U1", 19))
    check("Gate pull-up 10k to 3V3 -> panel OFF at reset/deep-sleep",
          N("R12", 2) == N("Q2", 1) and N("R12", 1) == "+3V3")
    check("Panel RST pull-up goes to EPD_VCC, NOT 3V3",
          N("R17", 1) == N("Q2", 3) and N("R17", 2) == N("J4", 10)
          and N("R17", 1) != "+3V3")
    check("Booster runs from gated EPD_VCC: inductor + panel VDDIO/VCI",
          N("L1", 1) == N("J4", 15) == N("J4", 16) == N("Q2", 3))
    check("Boost switch: FET drain on SW node with inductor, D4 anode, pump cap",
          N("Q3", 3) == N("L1", 2) == N("D4", 2) == N("C16", 1))
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
    def unconnected(ref, pin):
        n = N(ref, pin)
        return n is None or n.startswith("unconnected-")

    check("Panel VSS (17) on GND; pins 1,6,7 unconnected",
          N("J4", 17) == "GND" and unconnected("J4", 1)
          and unconnected("J4", 6) and unconnected("J4", 7))

    # --- debug header -----------------------------------------------------
    check("Debug header carries VBAT,3V3,GND,EN,TXD0,RXD0,IO4,IO5,IO8,GND",
          N("J5", 1) == N("U4", 3) and N("J5", 2) == "+3V3" and N("J5", 3) == "GND"
          and N("J5", 4) == N("U1", 8) and N("J5", 5) == N("U1", 31)
          and N("J5", 6) == N("U1", 30) and N("J5", 7) == N("U1", 9)
          and N("J5", 8) == N("U1", 10) and N("J5", 9) == N("U1", 22)
          and N("J5", 10) == "GND")

    print()
    if FAIL:
        print(f"invariants: {len(FAIL)} FAILURES")
        sys.exit(1)
    print("invariants: all passed")


if __name__ == "__main__":
    main()
