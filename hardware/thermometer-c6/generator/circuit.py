"""thermometer-c6 design definition — single source of truth.

Every component, net, and no-connect on the board. generate.py renders this
into the .kicad_sch; verify/ scripts check the exported netlist against it.

Conventions:
- Diodes: KiCad Diode:* symbols use pin 1 = K (cathode), pin 2 = A (anode).
- FETs (AO3401A/AO3400A/2N7002/Si1308EDL): pin 1 = G, 2 = S, 3 = D.
- LEDs (Device:LED): pin 1 = K, 2 = A.
- ESP32-C6-MINI-1: module pin numbers (IO0=12, IO1=13, IO2=5, IO3=6, IO4=9,
  IO5=10, IO6=15, IO7=16, IO8=22, IO9=23, IO12=17, IO13=18, IO14=19, IO15=20,
  IO18..23=24..29, RXD0(GPIO17)=30, TXD0(GPIO16)=31, EN=8, 3V3=3).

LCSC C-numbers verified against JLCPCB stock 2026-07-07 unless marked
verified (all jellybean passives re-confirmed via JLCPCB API 2026-07-07;
C25744 10k was transiently 0 stock — fallback YAGEO C60490).
"""

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
TP = "TestPoint:TestPoint_Pad_D1.5mm"

COMPONENTS = [
    # ---- A: Battery input + PPK2 measurement break ----
    dict(ref="J1", lib_id="Connector_Generic:Conn_01x02", value="JST-PH-2 BAT",
         footprint="Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
         lcsc="C295747", zone="A: Battery + PPK2 break"),
    dict(ref="Q6", lib_id="Transistor_FET:AO3401A", value="AO3401A", footprint=SOT23,
         lcsc="C15127", zone="A: Battery + PPK2 break"),  # reverse-battery protect
    dict(ref="JP1", lib_id="Jumper:SolderJumper_2_Bridged", value="MEAS",
         footprint="Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
         lcsc="", zone="A: Battery + PPK2 break"),
    dict(ref="J2", lib_id="Connector_Generic:Conn_01x02", value="MEAS_HDR",
         footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
         lcsc="", dnp=True, zone="A: Battery + PPK2 break"),
    dict(ref="TP1", lib_id="Connector:TestPoint", value="VBAT", footprint=TP,
         lcsc="", zone="A: Battery + PPK2 break"),
    dict(ref="TP2", lib_id="Connector:TestPoint", value="GND", footprint=TP,
         lcsc="", zone="A: Battery + PPK2 break"),
    dict(ref="TP3", lib_id="Connector:TestPoint", value="GND", footprint=TP,
         lcsc="", zone="A: Battery + PPK2 break"),

    # ---- B: LDO ----
    dict(ref="U2", lib_id="local:RT9080-33", value="RT9080-33GJ5",
         footprint="Package_TO_SOT_SMD:TSOT-23-5", lcsc="C841192",
         zone="B: 3V3 LDO"),
    dict(ref="C1", lib_id="Device:C", value="10uF", footprint=C0603,
         lcsc="C19702", zone="B: 3V3 LDO"),
    dict(ref="C2", lib_id="Device:C", value="22uF/25V", footprint=C0805,
         lcsc="C45783", zone="B: 3V3 LDO"),
    dict(ref="C3", lib_id="Device:C", value="10uF", footprint=C0603,
         lcsc="C19702", zone="B: 3V3 LDO"),
    dict(ref="C4", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", zone="B: 3V3 LDO"),
    dict(ref="TP4", lib_id="Connector:TestPoint", value="3V3", footprint=TP,
         lcsc="", zone="B: 3V3 LDO"),

    # ---- C: USB-C + charger + load sharing ----
    dict(ref="J3", lib_id="Connector:USB_C_Receptacle_USB2.0_16P", value="USB-C",
         footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
         lcsc="C165948", zone="C: USB-C + charger"),
    dict(ref="R1", lib_id="Device:R", value="5.1k", footprint=R0402,
         lcsc="C25905", zone="C: USB-C + charger"),
    dict(ref="R2", lib_id="Device:R", value="5.1k", footprint=R0402,
         lcsc="C25905", zone="C: USB-C + charger"),
    dict(ref="U3", lib_id="Power_Protection:USBLC6-2SC6", value="USBLC6-2SC6",
         footprint="Package_TO_SOT_SMD:SOT-23-6", lcsc="C7519",
         zone="C: USB-C + charger"),
    dict(ref="C5", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="C: USB-C + charger"),
    dict(ref="U4", lib_id="Battery_Management:MCP73831-2-OT", value="MCP73831-2",
         footprint="Package_TO_SOT_SMD:SOT-23-5", lcsc="C424093",
         zone="C: USB-C + charger"),
    dict(ref="R3", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="C: USB-C + charger"),  # PROG: 100mA
    dict(ref="C6", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="C: USB-C + charger"),
    dict(ref="R4", lib_id="Device:R", value="1k", footprint=R0402,
         lcsc="C11702", zone="C: USB-C + charger"),
    dict(ref="D1", lib_id="Device:LED", value="CHG red", footprint=LED0603,
         lcsc="C2286", zone="C: USB-C + charger"),
    dict(ref="D2", lib_id="Diode:SS14", value="SS14", footprint="Diode_SMD:D_SMA",
         lcsc="C2480", zone="C: USB-C + charger"),
    dict(ref="Q1", lib_id="Transistor_FET:AO3401A", value="AO3401A", footprint=SOT23,
         lcsc="C15127", zone="C: USB-C + charger"),
    dict(ref="R5", lib_id="Device:R", value="100k", footprint=R0402,
         lcsc="C25741", zone="C: USB-C + charger"),
    dict(ref="R22", lib_id="Device:R", value="100k", footprint=R0402,
         lcsc="C25741", zone="C: USB-C + charger"),  # VBUS sense top
    dict(ref="R23", lib_id="Device:R", value="100k", footprint=R0402,
         lcsc="C25741", zone="C: USB-C + charger"),  # VBUS sense bottom
    dict(ref="D7", lib_id="Device:D_TVS", value="SMF5.0A",
         footprint="Diode_SMD:D_SOD-123F", lcsc="", dnp=True,
         zone="C: USB-C + charger"),  # VBUS surge clamp, populate if hot-plug ring proves real

    # ---- D: MCU ----
    dict(ref="U1", lib_id="RF_Module:ESP32-C6-MINI-1", value="ESP32-C6-MINI-1-N4",
         footprint="RF_Module:ESP32-C6-MINI-1", lcsc="C5736265", zone="D: ESP32-C6"),
    dict(ref="C7", lib_id="Device:C", value="10uF", footprint=C0603,
         lcsc="C19702", zone="D: ESP32-C6"),
    dict(ref="C8", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", zone="D: ESP32-C6"),
    dict(ref="R6", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="D: ESP32-C6"),  # EN pull-up
    dict(ref="C9", lib_id="Device:C", value="1uF", footprint=C0402,
         lcsc="C52923", zone="D: ESP32-C6"),  # EN RC
    dict(ref="SW1", lib_id="Switch:SW_Push", value="RESET",
         footprint="local:SW_TS-1187A", lcsc="C318884", zone="D: ESP32-C6"),
    dict(ref="SW2", lib_id="Switch:SW_Push", value="BOOT",
         footprint="local:SW_TS-1187A", lcsc="C318884", zone="D: ESP32-C6"),
    dict(ref="R7", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="D: ESP32-C6"),  # GPIO9 pull-up
    dict(ref="D3", lib_id="Device:LED", value="STATUS green", footprint=LED0603,
         lcsc="C12624", zone="D: ESP32-C6"),
    dict(ref="R8", lib_id="Device:R", value="1k", footprint=R0402,
         lcsc="C11702", zone="D: ESP32-C6"),
    # 32.768 kHz crystal (GPIO0/1 = XTAL_32K_P/N)
    dict(ref="Y1", lib_id="Device:Crystal", value="32.768kHz FC-135",
         footprint="Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", lcsc="C32346",
         zone="D: ESP32-C6"),
    dict(ref="C10", lib_id="Device:C", value="20pF", footprint=C0402,
         lcsc="C1554", zone="D: ESP32-C6"),  # CL=12.5pF -> 2*(CL-Cstray)
    dict(ref="C11", lib_id="Device:C", value="20pF", footprint=C0402,
         lcsc="C1554", zone="D: ESP32-C6"),
    dict(ref="R9", lib_id="Device:R", value="10M", footprint=R0402,
         lcsc="", dnp=True, zone="D: ESP32-C6"),  # crystal bias, populate if startup issues

    # ---- E: BMP581 (LP I2C, sleep-time reads by LP core) ----
    dict(ref="U5", lib_id="local:BMP581", value="BMP581",
         footprint="local:Bosch_LGA-10_2x2mm", lcsc="C5362283",
         zone="E: BMP581"),
    dict(ref="R10", lib_id="Device:R", value="4.7k", footprint=R0402,
         lcsc="C25900", zone="E: BMP581"),  # SDA pull-up
    dict(ref="R11", lib_id="Device:R", value="4.7k", footprint=R0402,
         lcsc="C25900", zone="E: BMP581"),  # SCL pull-up
    dict(ref="C12", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", zone="E: BMP581"),  # VDD
    dict(ref="C13", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", zone="E: BMP581"),  # VDDIO
    # Alternate sensor: BMP585 (media-resistant, LGA-9 3.25mm). Same LP I2C
    # bus, same addr 0x47 strapping, same register map (chip-ID differs;
    # firmware BMP58x driver handles both). POPULATE EXACTLY ONE of U5/U6 —
    # both strap SDO high, so populating both collides at 0x47.
    dict(ref="U6", lib_id="local:BMP585", value="BMP585",
         footprint="local:Bosch_LGA-9_3.25x3.25mm", lcsc="C18184976",
         dnp=True, zone="E: BMP581"),
    dict(ref="C26", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", dnp=True, zone="E: BMP581"),  # U6 VDD
    dict(ref="C27", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", dnp=True, zone="E: BMP581"),  # U6 VDDIO

    # ---- F: EPD power gate ----
    dict(ref="Q2", lib_id="Transistor_FET:AO3401A", value="AO3401A", footprint=SOT23,
         lcsc="C15127", zone="F: EPD power gate"),
    dict(ref="R12", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="F: EPD power gate"),  # gate pull-up: default OFF
    dict(ref="R24", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="F: EPD power gate"),  # gate series: ~100us EPD_VCC ramp
    dict(ref="C28", lib_id="Device:C", value="10nF", footprint=C0402,
         lcsc="C15195", zone="F: EPD power gate"),  # gate-source, sets the ramp
    dict(ref="C14", lib_id="Device:C", value="10uF", footprint=C0603,
         lcsc="C19702", zone="F: EPD power gate"),
    dict(ref="C15", lib_id="Device:C", value="100nF", footprint=C0402,
         lcsc="C1525", zone="F: EPD power gate"),
    dict(ref="TP5", lib_id="Connector:TestPoint", value="EPD_VCC", footprint=TP,
         lcsc="", zone="F: EPD power gate"),

    # ---- G: EPD booster (DESPI-C02 reference, on gated EPD_VCC) ----
    dict(ref="L1", lib_id="Device:L", value="10uH SWPA4030S",
         footprint="Inductor_SMD:L_Sunlord_SWPA4030S", lcsc="C38117",
         zone="G: EPD booster"),
    dict(ref="L2", lib_id="Device:L", value="47uH SWPA4030S",
         footprint="Inductor_SMD:L_Sunlord_SWPA4030S", lcsc="C54731",
         zone="G: EPD booster"),  # GDEH0576T81 datasheet pairing (with 2.2R RESE)
    dict(ref="JP5", lib_id="Jumper:SolderJumper_2_Bridged", value="L 10uH",
         footprint="Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
         lcsc="", zone="G: EPD booster"),
    dict(ref="JP6", lib_id="Jumper:SolderJumper_2_Open", value="L 47uH",
         footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
         lcsc="", zone="G: EPD booster"),
    dict(ref="Q3", lib_id="local:Si1308EDL", value="Si1308EDL",
         footprint="Package_TO_SOT_SMD:SOT-323_SC-70", lcsc="C469327",
         zone="G: EPD booster"),
    dict(ref="R13", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="G: EPD booster"),  # GDR bleed
    dict(ref="R14", lib_id="Device:R", value="0.47R 1%", footprint=R0805,
         lcsc="C2930220", zone="G: EPD booster"),
    dict(ref="R15", lib_id="Device:R", value="2.2R 1%", footprint=R0805,
         lcsc="C17521", zone="G: EPD booster"),
    dict(ref="R16", lib_id="Device:R", value="3.0R 1%", footprint=R0805,
         lcsc="C17660", zone="G: EPD booster"),
    dict(ref="JP2", lib_id="Jumper:SolderJumper_2_Bridged", value="0.47R",
         footprint="Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
         lcsc="", zone="G: EPD booster"),
    dict(ref="JP3", lib_id="Jumper:SolderJumper_2_Open", value="2.2R",
         footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
         lcsc="", zone="G: EPD booster"),
    dict(ref="JP4", lib_id="Jumper:SolderJumper_2_Open", value="3R",
         footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
         lcsc="", zone="G: EPD booster"),
    dict(ref="D4", lib_id="Diode:MBR0530", value="MBR0530",
         footprint="Diode_SMD:D_SOD-123", lcsc="C5204746", zone="G: EPD booster"),
    dict(ref="D5", lib_id="Diode:MBR0530", value="MBR0530",
         footprint="Diode_SMD:D_SOD-123", lcsc="C5204746", zone="G: EPD booster"),
    dict(ref="D6", lib_id="Diode:MBR0530", value="MBR0530",
         footprint="Diode_SMD:D_SOD-123", lcsc="C5204746", zone="G: EPD booster"),
    dict(ref="C16", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="G: EPD booster"),  # pump cap (DESPI C3)
    dict(ref="C17", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="G: EPD booster"),  # PREVGH
    dict(ref="C18", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="G: EPD booster"),  # PREVGL
    dict(ref="TP6", lib_id="Connector:TestPoint", value="PREVGH", footprint=TP,
         lcsc="", zone="G: EPD booster"),
    dict(ref="TP7", lib_id="Connector:TestPoint", value="PREVGL", footprint=TP,
         lcsc="", zone="G: EPD booster"),
    dict(ref="TP8", lib_id="Connector:TestPoint", value="GDR", footprint=TP,
         lcsc="", zone="G: EPD booster"),
    dict(ref="TP9", lib_id="Connector:TestPoint", value="RESE", footprint=TP,
         lcsc="", zone="G: EPD booster"),

    # ---- H: FPC connector + panel-side caps (DESPI C1/C2/C6..C12 roles) ----
    dict(ref="J4", lib_id="Connector_Generic:Conn_01x24", value="EPD FPC24 0.5mm",
         footprint="Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal",
         lcsc="C2856831", zone="H: EPD FPC"),  # XUNPU FPC-05FB-24PH20 (dual contact); footprint verify at layout
    dict(ref="C19", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="H: EPD FPC"),  # VGL
    dict(ref="C20", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="H: EPD FPC"),  # VGH
    dict(ref="C21", lib_id="Device:C", value="1uF/50V", footprint=C0805,
         lcsc="C28323", zone="H: EPD FPC"),  # VDD
    dict(ref="C22", lib_id="Device:C", value="1uF/50V", footprint=C0805,
         lcsc="C28323", zone="H: EPD FPC"),  # VPP
    dict(ref="C23", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="H: EPD FPC"),  # VSH
    dict(ref="C24", lib_id="Device:C", value="4.7uF/25V", footprint=C0805,
         lcsc="C1779", zone="H: EPD FPC"),  # VSL
    dict(ref="C25", lib_id="Device:C", value="1uF/50V", footprint=C0805,
         lcsc="C28323", zone="H: EPD FPC"),  # VCOM
    dict(ref="R17", lib_id="Device:R", value="10k", footprint=R0402,
         lcsc="C25744", zone="H: EPD FPC"),  # panel RST pull-up to EPD_VCC
    dict(ref="TP10", lib_id="Connector:TestPoint", value="VCOM", footprint=TP,
         lcsc="", zone="H: EPD FPC"),

    # ---- I: Battery sense (high-side switched divider) ----
    dict(ref="Q4", lib_id="Transistor_FET:AO3401A", value="AO3401A", footprint=SOT23,
         lcsc="C15127", zone="I: Battery sense"),
    dict(ref="Q5", lib_id="Transistor_FET:2N7002", value="2N7002", footprint=SOT23,
         lcsc="C8545", zone="I: Battery sense"),
    dict(ref="R18", lib_id="Device:R", value="100k", footprint=R0402,
         lcsc="C25741", zone="I: Battery sense"),  # P-gate pull-up to VBAT
    dict(ref="R19", lib_id="Device:R", value="100k", footprint=R0402,
         lcsc="C25741", zone="I: Battery sense"),  # VDIV_EN pull-down
    dict(ref="R20", lib_id="Device:R", value="100k 1%", footprint=R0402,
         lcsc="C25741", zone="I: Battery sense"),  # divider top
    dict(ref="R21", lib_id="Device:R", value="100k 1%", footprint=R0402,
         lcsc="C25741", zone="I: Battery sense"),  # divider bottom
    dict(ref="C29", lib_id="Device:C", value="10nF", footprint=C0402,
         lcsc="", dnp=True, zone="I: Battery sense"),  # ADC reservoir; enable divider ~5ms before reading if fitted
    dict(ref="TP11", lib_id="Connector:TestPoint", value="VBAT_ADC", footprint=TP,
         lcsc="", zone="I: Battery sense"),

    # ---- J: Debug header ----
    dict(ref="J5", lib_id="Connector_Generic:Conn_01x10", value="DEBUG",
         footprint="Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical",
         lcsc="", dnp=True, zone="J: Debug"),
]

# ---------------------------------------------------------------------------

_MINI_GND_PINS = [1, 2, 11, 14] + list(range(36, 54))

NETS = {
    # power tree
    # reverse battery: body diode blocks, Vgs goes positive -> FET off
    "~BAT_IN": [("J1", 1), ("Q6", 3)],
    "~VBAT_RAW": [("Q6", 2), ("JP1", 1), ("J2", 1)],
    "VBAT": [("JP1", 2), ("J2", 2), ("U4", 3), ("C6", 1), ("Q1", 3),
             ("Q4", 2), ("R18", 1), ("TP1", 1)],
    "VSYS": [("D2", 1), ("Q1", 2), ("U2", 1), ("U2", 3), ("C1", 1), ("C2", 1)],
    "+3V3": [("U2", 5), ("C3", 1), ("C4", 1), ("TP4", 1),
             ("U1", 3), ("C7", 1), ("C8", 1), ("R6", 1), ("R7", 1),
             ("U5", 1), ("U5", 10), ("U5", 5), ("U5", 6),
             ("U6", 3), ("U6", 4), ("U6", 7), ("U6", 8),
             ("R10", 1), ("R11", 1), ("C12", 1), ("C13", 1),
             ("C26", 1), ("C27", 1),
             ("Q2", 2), ("R12", 1), ("C28", 1), ("J5", 2)],
    "VBUS": [("J3", "A4"), ("J3", "B4"), ("J3", "A9"), ("J3", "B9"),
             ("U3", 5), ("U4", 4), ("C5", 1), ("R4", 1), ("D2", 2),
             ("Q1", 1), ("R5", 1), ("R22", 1), ("D7", 1)],
    "GND": ([("J1", 2), ("TP2", 1), ("TP3", 1),
             ("U2", 2), ("C1", 2), ("C2", 2), ("C3", 2), ("C4", 2),
             ("J3", "A1"), ("J3", "B1"), ("J3", "A12"), ("J3", "B12"), ("J3", "SH"),
             ("R1", 2), ("R2", 2), ("U3", 2), ("C5", 2), ("U4", 2), ("C6", 2),
             ("R3", 2), ("R5", 2),
             ("C7", 2), ("C8", 2), ("C9", 2), ("SW1", 2), ("SW2", 2),
             ("C10", 2), ("C11", 2), ("D3", 1),
             ("U5", 3), ("U5", 8), ("U5", 9), ("C12", 2), ("C13", 2),
             ("U6", 6), ("C26", 2), ("C27", 2),
             ("C14", 2), ("C15", 2),
             ("R13", 2), ("JP2", 2), ("JP3", 2), ("JP4", 2), ("D5", 1),
             ("C17", 2), ("C18", 2),
             ("J4", 8), ("J4", 17),
             ("C19", 2), ("C20", 2), ("C21", 2), ("C22", 2), ("C23", 2),
             ("C24", 2), ("C25", 2),
             ("Q5", 2), ("R19", 2), ("R21", 2), ("Q6", 1), ("R23", 2),
             ("C29", 2), ("D7", 2),
             ("J5", 1), ("J5", 9), ("J5", 10)]
            + [("U1", n) for n in _MINI_GND_PINS]),

    # USB
    "~USB_CC1": [("J3", "A5"), ("R1", 1)],
    "~USB_CC2": [("J3", "B5"), ("R2", 1)],
    # USBLC6 flow-through: the symbol does not join its two I/O1 (or I/O2)
    # pins, so connector side and MCU side are distinct nets that meet
    # inside the chip — mirrors the recommended flow-through PCB routing.
    "~USB_DM_CONN": [("J3", "A7"), ("J3", "B7"), ("U3", 1)],
    "~USB_DP_CONN": [("J3", "A6"), ("J3", "B6"), ("U3", 3)],
    "USB_D-": [("U3", 6), ("U1", 17)],
    "USB_D+": [("U3", 4), ("U1", 18)],

    # charger
    "CHG_STAT": [("U4", 1), ("D1", 1)],
    "~CHG_LED_A": [("R4", 2), ("D1", 2)],
    "~CHG_PROG": [("U4", 5), ("R3", 1)],

    # MCU support
    "EN": [("U1", 8), ("R6", 2), ("C9", 1), ("SW1", 1), ("J5", 3)],
    "BOOT": [("U1", 23), ("R7", 2), ("SW2", 1)],
    "XTAL_32K_P": [("U1", 12), ("Y1", 1), ("C10", 1), ("R9", 1)],
    "XTAL_32K_N": [("U1", 13), ("Y1", 2), ("C11", 1), ("R9", 2)],
    "LED_STATUS": [("U1", 20), ("R8", 1)],
    "~LED_A": [("R8", 2), ("D3", 2)],

    # sensor (LP I2C — GPIO6/7 fixed by silicon)
    "SDA": [("U1", 15), ("U5", 4), ("U6", 2), ("R10", 2)],
    "SCL": [("U1", 16), ("U5", 2), ("U6", 1), ("R11", 2)],

    # battery sense
    "VBAT_ADC": [("U1", 5), ("R20", 2), ("R21", 1), ("TP11", 1), ("C29", 1)],
    "VDIV_EN": [("U1", 6), ("Q5", 1), ("R19", 1)],
    "~VDIV_TOP": [("Q4", 3), ("R20", 1)],
    "~VDIV_PGATE": [("Q4", 1), ("R18", 2), ("Q5", 3)],

    # debug header spares + UART
    "DBG_TX": [("U1", 31), ("J5", 4)],
    "DBG_RX": [("U1", 30), ("J5", 5)],
    "VBUS_SENSE": [("U1", 9), ("R22", 2), ("R23", 1), ("J5", 6)],
    "DBG_IO5": [("U1", 10), ("J5", 7)],
    "DBG_IO8": [("U1", 22), ("J5", 8)],

    # EPD power gate
    "EPD_PWR_EN": [("U1", 19), ("R24", 2)],
    "~EPD_GATE": [("Q2", 1), ("R12", 2), ("C28", 2), ("R24", 1)],
    "EPD_VCC": [("Q2", 3), ("C14", 1), ("C15", 1), ("TP5", 1),
                ("L1", 1), ("L2", 1), ("J4", 15), ("J4", 16), ("R17", 1)],

    # EPD booster (DESPI-C02 topology)
    # jumpers on the switch-node side: the unselected coil idles on the DC
    # rail instead of dangling from the switching node
    "~SW_10U": [("L1", 2), ("JP5", 1)],
    "~SW_47U": [("L2", 2), ("JP6", 1)],
    "EPD_SW": [("JP5", 2), ("JP6", 2), ("Q3", 3), ("D4", 2), ("C16", 1)],
    "EPD_GDR": [("Q3", 1), ("R13", 1), ("J4", 2), ("TP8", 1)],
    "EPD_RESE": [("Q3", 2), ("J4", 3), ("R14", 1), ("R15", 1), ("R16", 1),
                 ("TP9", 1)],
    "~RESE_A": [("R14", 2), ("JP2", 1)],
    "~RESE_B": [("R15", 2), ("JP3", 1)],
    "~RESE_C": [("R16", 2), ("JP4", 1)],
    "~EPD_PUMP": [("C16", 2), ("D5", 2), ("D6", 1)],
    "EPD_PREVGH": [("D4", 1), ("C17", 1), ("J4", 21), ("TP6", 1)],
    "EPD_PREVGL": [("D6", 2), ("C18", 1), ("J4", 23), ("TP7", 1)],

    # EPD control (SPI pins are in the C6 SDIO strap group: they idle on weak
    # pull-ups at reset and may toggle until firmware claims them — panel is
    # unpowered then, gate defaults off via R12)
    "EPD_BUSY": [("U1", 29), ("J4", 9)],
    "EPD_RST": [("U1", 28), ("J4", 10), ("R17", 2)],
    "EPD_DC": [("U1", 27), ("J4", 11)],
    "EPD_CS": [("U1", 26), ("J4", 12)],
    "EPD_SCK": [("U1", 25), ("J4", 13)],
    "EPD_MOSI": [("U1", 24), ("J4", 14)],

    # panel-side storage caps
    "~EPD_VGL": [("J4", 4), ("C19", 1)],
    "~EPD_VGH": [("J4", 5), ("C20", 1)],
    "~EPD_VDD": [("J4", 18), ("C21", 1)],
    "~EPD_VPP": [("J4", 19), ("C22", 1)],
    "~EPD_VSH": [("J4", 20), ("C23", 1)],
    "~EPD_VSL": [("J4", 22), ("C24", 1)],
    "~EPD_VCOM": [("J4", 24), ("C25", 1), ("TP10", 1)],
}

NC = [
    # MINI-1 NC pins
    ("U1", 4), ("U1", 7), ("U1", 21), ("U1", 32), ("U1", 33), ("U1", 34), ("U1", 35),
    # BMP58x INT pins unconnected: firmware must set int_en=1, int_od=0,
    # pad_int_drv=0 per datasheet (protects against future int_en=push-pull
    # into a hard short that a grounded pad would have been)
    ("U5", 7), ("U6", 5),
    # BMP585 laser-mark pad (solder-resist covered, no connection possible)
    ("U6", 9),
    # LDO pin 4
    ("U2", 4),
    # USB SBU
    ("J3", "A8"), ("J3", "B8"),
    # FPC: pin 1 NC, pins 6/7 TSCL/TSDA (touch-panel variant only)
    ("J4", 1), ("J4", 6), ("J4", 7),
]

# Nets rendered as power symbols (everything else gets global labels)
POWER_SYMBOLS = {
    "GND": "power:GND",
    "+3V3": "power:+3V3",
    "VBUS": "power:VBUS",
}

# Power-input pins exist on nets driven only by passives -> need PWR_FLAG
# (VBAT needs none: the charger's V_BAT pin is a power output)
PWR_FLAG_NETS = {"GND", "VBUS", "VSYS"}
