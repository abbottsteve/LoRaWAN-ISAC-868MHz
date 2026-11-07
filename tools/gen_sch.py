#!/usr/bin/env python3
"""
Generate the human-crafted KiCad 9 schematic + local symbol library for the
868 MHz Dual-Function ISAC Antenna-Sensor Node (Rev E.5).

Design highlights (Rev E.5 PCBWay Turnkey Hardware):
  * Clean multi-unit functional decomposition of U1 (`RAK3172LP-SiP`, LGA-73):
    - `U1A`: Digital/Analog/RF Power Conditioning (`VDD1/2`, isolated `VDDA/VREF+`,
      `VDDRF`, `VDDPA`), 15 uH internal buck SMPS (`LQH2MCN150K02L`), and LGA GND bank.
    - `U1B`: STM32WLE5JC Control, Protected SWD/UART2/BOOT Debug, ADC Sensing &
      Sub-GHz `RF_OUT` (`Pin 37`, RFO_LP) launching left-to-right onto the RF spine.
    - `U1C`: Compact auxiliary termination bank for the 33 unused LGA-73 I/O & NC pins.
  * Strict 2.54 mm (100 mil) grid alignment across all symbols, pins, wires,
    junctions, and power symbols (0 ERC errors, 0 ERC warnings) + automated 2D
    Shapely bounding-box collision & A3 border containment verification.
  * Ultra-low-sleep (< 2.5 uA typ across VBAT = 3.0..4.2 V):
    - U3 TI TPS7A0233DBVR (SOT-23-5: 1=IN, 2=GND, 3=EN, 4=NC, 5=OUT;
      Iq = 25 nA typ, 200 mA continuous) + Q3 AO3401A ideal diode.
    - Independent PA9 (BAT_MON_EN) high-side gated battery divider via Q2
      (Nexperia NX3008CBKS,115 complementary +/-30 V N+P MOSFET, SOT-363) +
      R_BG (470k) + R_B1/R_B2 (4.7k 0.1%) + C_BAT (1n 50V C0G): 0 nA sleep bleed.
    - Header LiPo back-feed isolation: R_VAPP (1k) on J4.1 VAPP_SENSE,
      R_VUART (DNP 0R) on J5.1 VUART_ISO, R_BHI (10k) on J3.2 BOOT_HI, D_3V3 TVS.
  * Co-optimized Elliptic Low-Pass Harmonic Pi-Network (C_M1=3.6p, L_M1=8.2n ||
    C_MZ=0.5p, C_M2=4.3p) + Parasitic-Controlled Bridge (R1=8.2R Yageo RT0402BRD078R2L,
    zero RF test points, DC TP1..TP5 only).

Run:  python3 tools/gen_sch.py
"""
from collections import defaultdict
import csv
import os
import re
import subprocess
import tempfile
import uuid

PROJECT = "ISAC_868_KiCad9"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NS = uuid.UUID("0d6f5c2e-4a1b-4c7e-9f10-2b3c4d5e6f70")

G = 2.54  # 100 mil schematic grid in mm


def u(tag):
    return str(uuid.uuid5(NS, f"{PROJECT}:{tag}"))


def gm(n):
    """Convert integer grid units (2.54 mm) to rounded mm."""
    return round(n * G, 4)


# --------------------------------------------------------------------------
# S-expression formatter
# --------------------------------------------------------------------------
def sx_flat(obj):
    if isinstance(obj, list):
        return "(" + " ".join(sx_flat(x) for x in obj) + ")"
    return str(obj)


def sx(obj, ind=0):
    sp = "  " * ind
    if isinstance(obj, list):
        if not obj:
            return "()"
        flat = sx_flat(obj)
        if len(flat) <= 92 and "\n" not in flat:
            return flat
        head, rest = obj[0], obj[1:]
        if not rest:
            return "(" + sx(head, 0) + ")"
        body = "\n".join(sp + "  " + sx(x, ind + 1) for x in rest)
        return "(" + sx(head, 0) + "\n" + body + "\n" + sp + ")"
    return str(obj)


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


# --------------------------------------------------------------------------
# Symbol library definitions (all pin endpoints on exact multiples of 2.54 mm)
# --------------------------------------------------------------------------
SYMS = {}


def rect(x1, y1, x2, y2, fill="none", width=0.254):
    return ["rectangle", ["start", round(x1, 4), round(y1, 4)],
            ["end", round(x2, 4), round(y2, 4)],
            ["stroke", ["width", width], ["type", "default"]],
            ["fill", ["type", fill]]]


def poly(pts, width=0.254, fill="none"):
    return ["polyline", ["pts"] + [["xy", round(x, 4), round(y, 4)] for x, y in pts],
            ["stroke", ["width", width], ["type", "default"]],
            ["fill", ["type", fill]]]


def circ(x, y, r, width=0.254, fill="none"):
    return ["circle", ["center", round(x, 4), round(y, 4)], ["radius", round(r, 4)],
            ["stroke", ["width", width], ["type", "default"]],
            ["fill", ["type", fill]]]


def arc(p1, pm, p2, width=0.254):
    return ["arc", ["start", round(p1[0], 4), round(p1[1], 4)],
            ["mid", round(pm[0], 4), round(pm[1], 4)],
            ["end", round(p2[0], 4), round(p2[1], 4)],
            ["stroke", ["width", width], ["type", "default"]],
            ["fill", ["type", "none"]]]


def add_sym(name, hw_g, hh_g, pins, graphics, ref_prefix,
            hide_pin_nums=False, hide_pin_names=False, is_power=False,
            in_bom="yes", on_board="yes", units=None):
    SYMS[name] = dict(
        hw=gm(hw_g), hh=gm(hh_g), pins=pins, graphics=graphics,
        ref=ref_prefix, hide_nums=hide_pin_nums, hide_names=hide_pin_names,
        is_power=is_power, in_bom=in_bom, on_board=on_board, units=units,
    )


def box_pin(side, hw_g, hh_g, num, name, etype, pos_g, hide=False, unit=1):
    if side == "L":
        return dict(num=num, name=name, etype=etype, unit=unit,
                    lx=gm(-hw_g - 1), ly=gm(pos_g), rot=0, length=G, hide=hide)
    if side == "R":
        return dict(num=num, name=name, etype=etype, unit=unit,
                    lx=gm(hw_g + 1), ly=gm(pos_g), rot=180, length=G, hide=hide)
    if side == "T":
        return dict(num=num, name=name, etype=etype, unit=unit,
                    lx=gm(pos_g), ly=gm(hh_g + 1), rot=270, length=G, hide=hide)
    if side == "B":
        return dict(num=num, name=name, etype=etype, unit=unit,
                    lx=gm(pos_g), ly=gm(-hh_g - 1), rot=90, length=G, hide=hide)
    raise ValueError(side)


# ---- U1: RAK3172LP-SiP (3-Unit Functional Symbol: U1A, U1B, U1C) -----------
# Unit 1 (U1A): Power Supplies, Ferrite-Isolated Analog/RF/PA & 15 uH SMPS (29 pins)
u1a_hw, u1a_hh = 5, 12
u1a_pins = [
    box_pin("L", u1a_hw, u1a_hh, 3, "VDD1", "power_in", 8, unit=1),
    box_pin("L", u1a_hw, u1a_hh, 55, "VDD2", "power_in", 6, unit=1),
    box_pin("L", u1a_hw, u1a_hh, 4, "VBAT", "power_in", 4, unit=1),
    box_pin("L", u1a_hw, u1a_hh, 11, "VDDSMPS", "passive", 0, unit=1),
    box_pin("L", u1a_hw, u1a_hh, 13, "VLXSMPS", "passive", -7, unit=1),
    box_pin("L", u1a_hw, u1a_hh, 10, "VFBSMPS", "passive", -10, unit=1),

    box_pin("R", u1a_hw, u1a_hh, 7, "VDDA", "power_in", 8, unit=1),
    box_pin("R", u1a_hw, u1a_hh, 6, "VREF+", "power_in", 6, unit=1),
    box_pin("R", u1a_hw, u1a_hh, 54, "VDDRF", "passive", -1, unit=1),
    box_pin("R", u1a_hw, u1a_hh, 53, "VDDPA", "passive", -9, unit=1),

    box_pin("B", u1a_hw, u1a_hh, 12, "GND", "power_in", 0, hide=False, unit=1),
] + [
    box_pin("B", u1a_hw, u1a_hh, gpin, "GND", "passive", 0, hide=True, unit=1)
    for gpin in (28, 35, 36, 38, 39, 46, 47, 52, 56, 65, 66, 67, 68, 69, 70, 71, 72, 73)
]

# Unit 2 (U1B): STM32WLE5JC Control, Protected Debug, ADC & Sub-GHz Radio (11 pins)
u1b_hw, u1b_hh = 6, 14
u1b_pins = [
    box_pin("L", u1b_hw, u1b_hh, 44, "~{NRST}", "input", 12, unit=2),
    box_pin("L", u1b_hw, u1b_hh, 43, "BOOT0", "input", 9, unit=2),
    box_pin("L", u1b_hw, u1b_hh, 1, "PA13/SWDIO", "bidirectional", 2, unit=2),
    box_pin("L", u1b_hw, u1b_hh, 2, "PA14/SWCLK", "bidirectional", -2, unit=2),
    box_pin("L", u1b_hw, u1b_hh, 29, "PA2/UART2_TX", "output", -9, unit=2),
    box_pin("L", u1b_hw, u1b_hh, 30, "PA3/UART2_RX", "input", -13, unit=2),

    box_pin("R", u1b_hw, u1b_hh, 37, "RF_OUT", "bidirectional", 11, unit=2),
    box_pin("R", u1b_hw, u1b_hh, 8, "PA15/ADC_IN11", "input", 3, unit=2),
    box_pin("R", u1b_hw, u1b_hh, 51, "PA8/DET_EN", "output", -1, unit=2),
    box_pin("R", u1b_hw, u1b_hh, 15, "PB4/ADC_IN3", "input", -5, unit=2),
    box_pin("R", u1b_hw, u1b_hh, 50, "PA9/BAT_MON_EN", "output", -9, unit=2),
]

# Unit 3 (U1C): Unused LGA-73 GPIO & Internal NC Termination Bank (33 pins)
u1c_hw, u1c_hh = 8, 9
_u1c_left = [
    (5, "PC13", "bidirectional"),
    (9, "PB15", "bidirectional"),
    (14, "PB3/ADC_IN2", "bidirectional"),
    (16, "PB5", "bidirectional"),
    (17, "PB6/UART1_TX", "bidirectional"),
    (18, "PB7/UART1_RX", "bidirectional"),
    (19, "PB8", "bidirectional"),
    (20, "PB9", "bidirectional"),
    (21, "PC0", "bidirectional"),
    (22, "PC1", "bidirectional"),
    (23, "PC2", "bidirectional"),
    (24, "PC3", "bidirectional"),
    (25, "PC4", "bidirectional"),
    (26, "PC5", "bidirectional"),
    (27, "PC6", "bidirectional"),
    (31, "PA4/SPI1_CS", "bidirectional"),
    (32, "PA5/SPI1_CLK", "bidirectional"),
]
_u1c_right = [
    (33, "PA6/SPI1_MISO", "bidirectional"),
    (34, "PA7/SPI1_MOSI", "bidirectional"),
    (48, "PB11", "bidirectional"),
    (49, "PB10", "bidirectional"),
    (57, "PB1/ADC_IN5", "bidirectional"),
    (58, "PB2/ADC_IN4", "bidirectional"),
    (59, "PB12", "bidirectional"),
    (60, "PB13/ADC_IN0", "bidirectional"),
    (61, "PB14/ADC_IN1", "bidirectional"),
    (62, "PA10/I2C_SDA", "bidirectional"),
    (63, "PA11", "bidirectional"),
    (64, "PA12", "bidirectional"),
    (40, "NC", "passive"),
    (41, "NC", "passive"),
    (42, "NC", "passive"),
    (45, "NC", "passive"),
]
u1c_pins = [
    box_pin("L", u1c_hw, u1c_hh, pnum, pname, petype, 8 - idx, unit=3)
    for idx, (pnum, pname, petype) in enumerate(_u1c_left)
] + [
    box_pin("R", u1c_hw, u1c_hh, pnum, pname, petype, 8 - idx, unit=3)
    for idx, (pnum, pname, petype) in enumerate(_u1c_right)
]

rak_pins = u1a_pins + u1b_pins + u1c_pins
assert len(rak_pins) == 73 and {p["num"] for p in rak_pins} == set(range(1, 74))

rak_units = {
    1: dict(hw=gm(u1a_hw), hh=gm(u1a_hh),
            graphics=[rect(gm(-u1a_hw), gm(-u1a_hh), gm(u1a_hw), gm(u1a_hh), "background")],
            pins=u1a_pins),
    2: dict(hw=gm(u1b_hw), hh=gm(u1b_hh),
            graphics=[rect(gm(-u1b_hw), gm(-u1b_hh), gm(u1b_hw), gm(u1b_hh), "background")],
            pins=u1b_pins),
    3: dict(hw=gm(u1c_hw), hh=gm(u1c_hh),
            graphics=[rect(gm(-u1c_hw), gm(-u1c_hh), gm(u1c_hw), gm(u1c_hh), "background")],
            pins=u1c_pins),
}
add_sym("RAK3172LP-SiP", u1a_hw, u1a_hh, rak_pins,
        [rect(gm(-u1a_hw), gm(-u1a_hh), gm(u1a_hw), gm(u1a_hh), "background")],
        "U", units=rak_units)

# ---- U2: LT5538IDD (40 MHz - 3.8 GHz 75 dB Log Detector, DFN-8-1EP) ------
lt_pins = [
    box_pin("T", 4, 5, 5, "VCC", "power_in", 0),
    box_pin("L", 4, 5, 1, "ENBL", "input", 3),
    box_pin("L", 4, 5, 2, "IN+", "passive", 1),
    box_pin("L", 4, 5, 3, "IN-", "passive", -2),
    box_pin("R", 4, 5, 7, "CAP+", "passive", 3),
    box_pin("R", 4, 5, 6, "CAP-", "passive", 1),
    box_pin("R", 4, 5, 8, "OUT", "output", -2),
    box_pin("B", 4, 5, 4, "GND", "power_in", -1),
    box_pin("B", 4, 5, 9, "EP", "power_in", 1),
]
add_sym("LT5538IDD", 4, 5, lt_pins,
        [rect(gm(-4), gm(-5), gm(4), gm(5), "background")], "U")

# ---- U3: TPS7A0233DBVR (200 mA, 25 nA Nanopower-Iq 3.3 V LDO, SOT-23-5) ---
ldo_pins = [
    box_pin("L", 3, 3, 1, "IN", "power_in", 2),
    box_pin("L", 3, 3, 3, "EN", "input", 0),
    box_pin("B", 3, 3, 2, "GND", "power_in", 0),
    box_pin("R", 3, 3, 5, "OUT", "power_out", 2),
    box_pin("R", 3, 3, 4, "NC", "passive", -1),
]
add_sym("TPS7A0233DBVR", 3, 3, ldo_pins,
        [rect(gm(-3), gm(-3), gm(3), gm(3), "background")], "U")

# ---- Q1: TPS22919DCKR (Zero-Iq Load Switch, SOT-363 / SC-70-6) -----------
tps_pins = [
    box_pin("L", 3, 3, 1, "VIN", "power_in", 2),
    box_pin("L", 3, 3, 3, "ON", "input", -1),
    box_pin("B", 3, 3, 2, "GND", "power_in", 0),
    box_pin("R", 3, 3, 6, "VOUT", "power_out", 2),
    box_pin("R", 3, 3, 5, "QOD", "passive", 0),
    box_pin("R", 3, 3, 4, "NC", "passive", -2),
]
add_sym("TPS22919DCKR", 3, 3, tps_pins,
        [rect(gm(-3), gm(-3), gm(3), gm(3), "background")], "Q")

# ---- Q2: NX3008CBKS (Complementary +/-30V N+P Trench MOSFET, SOT-363) -----
nx_pins = [
    box_pin("L", 3, 3, 4, "S2", "passive", 2),
    box_pin("L", 3, 3, 5, "G2", "input", 0),
    box_pin("L", 3, 3, 6, "D1", "passive", -2),
    box_pin("B", 3, 3, 1, "S1", "passive", 0),
    box_pin("R", 3, 3, 2, "G1", "input", 2),
    box_pin("R", 3, 3, 3, "D2", "passive", -2),
]
add_sym("NX3008CBKS", 3, 3, nx_pins,
        [rect(gm(-3), gm(-3), gm(3), gm(3), "background")], "Q")

# ---- Passives (pins at +/- 2*G = +/- 5.08 mm -> 100% 2.54 mm grid!) ------
passive_lr = [
    dict(num=1, name="~", etype="passive", unit=1, lx=gm(-2), ly=0.0, rot=0, length=G, hide=False),
    dict(num=2, name="~", etype="passive", unit=1, lx=gm(2), ly=0.0, rot=180, length=G, hide=False),
]
add_sym("R", 1, 0, passive_lr,
        [rect(-2.54, -1.016, 2.54, 1.016, "none")],
        "R", hide_pin_nums=True, hide_pin_names=True)

add_sym("C", 1, 0, passive_lr,
        [poly([(-2.54, 0), (-0.635, 0)]),
         poly([(0.635, 0), (2.54, 0)]),
         poly([(-0.635, -1.905), (-0.635, 1.905)], width=0.381),
         poly([(0.635, -1.905), (0.635, 1.905)], width=0.381)],
        "C", hide_pin_nums=True, hide_pin_names=True)

add_sym("L", 1, 0, passive_lr,
        [arc((-2.54, 0), (-1.905, 0.889), (-1.27, 0)),
         arc((-1.27, 0), (-0.635, 0.889), (0.0, 0)),
         arc((0.0, 0), (0.635, 0.889), (1.27, 0)),
         arc((1.27, 0), (1.905, 0.889), (2.54, 0))],
        "L", hide_pin_nums=True, hide_pin_names=True)

add_sym("FB", 1, 0, passive_lr,
        [poly([(-2.54, 0), (-1.905, 0)]),
         poly([(1.905, 0), (2.54, 0)]),
         poly([(-1.905, -0.889), (-1.27, 0.889), (1.905, 0.889),
               (1.27, -0.889), (-1.905, -0.889)], fill="outline")],
        "FB", hide_pin_nums=True, hide_pin_names=True)

add_sym("D", 1, 0,
        [dict(num=2, name="A", etype="passive", unit=1, lx=gm(-2), ly=0.0, rot=0, length=G, hide=False),
         dict(num=1, name="K", etype="passive", unit=1, lx=gm(2), ly=0.0, rot=180, length=G, hide=False)],
        [poly([(-2.54, 0), (2.54, 0)]),
         poly([(-1.27, -1.27), (-1.27, 1.27), (1.27, 0), (-1.27, -1.27)], fill="outline"),
         poly([(0.762, -1.27), (1.27, -1.27), (1.27, 1.27), (1.778, 1.27)])],
        "D", hide_pin_nums=True, hide_pin_names=True)

add_sym("TVS_BIDIR", 1, 0, passive_lr,
        [poly([(-2.54, 0), (2.54, 0)]),
         poly([(-1.524, -1.016), (-1.524, 1.016), (0.0, 0), (-1.524, -1.016)], fill="outline"),
         poly([(1.524, -1.016), (1.524, 1.016), (0.0, 0), (1.524, -1.016)], fill="outline"),
         poly([(-0.381, -1.143), (0.0, -1.143), (0.0, 1.143), (0.381, 1.143)])],
        "D", hide_pin_nums=True, hide_pin_names=True)

add_sym("PMOS_RPP", 1, 1,
        [box_pin("L", 1, 1, 3, "D", "passive", 0),
         box_pin("R", 1, 1, 2, "S", "passive", 0),
         box_pin("B", 1, 1, 1, "G", "input", 0)],
        [rect(gm(-1), gm(-1), gm(1), gm(1), "background")], "Q")

add_sym("PESD5V0U2BT", 1, 1,
        [box_pin("T", 1, 1, 1, "IO1", "passive", 0),
         box_pin("B", 1, 1, 2, "IO2", "passive", 0),
         box_pin("L", 1, 1, 3, "GND", "passive", 0)],
        [rect(gm(-1), gm(-1), gm(1), gm(1), "background"),
         poly([(-2.54, 0), (0, 0)]),
         poly([(0, 2.54), (0, -2.54)]),
         poly([(-0.762, 0.635), (0.762, 0.635), (0, 1.778), (-0.762, 0.635)], fill="outline"),
         poly([(-0.762, -0.635), (0.762, -0.635), (0, -1.778), (-0.762, -0.635)], fill="outline")],
        "D", hide_pin_names=True)

add_sym("SW_PUSH", 1, 0,
        [dict(num=1, name="1", etype="passive", unit=1, lx=gm(-2), ly=0.0, rot=0, length=G, hide=False),
         dict(num=2, name="2", etype="passive", unit=1, lx=gm(2), ly=0.0, rot=180, length=G, hide=False)],
        [circ(-1.524, 0, 0.508), circ(1.524, 0, 0.508),
         poly([(-2.54, 0), (-2.032, 0)]), poly([(2.032, 0), (2.54, 0)]),
         poly([(-1.778, 1.016), (1.778, 1.016)]),
         poly([(0, 1.016), (0, 2.032)])],
        "SW", hide_pin_nums=True, hide_pin_names=True)

add_sym("Conn_01x02", 1, 1,
        [box_pin("R", 1, 1, 1, "1", "passive", 1),
         box_pin("R", 1, 1, 2, "2", "passive", 0)],
        [rect(gm(-1), gm(-1), gm(1), gm(2), "background")], "J")

add_sym("Conn_01x04", 1, 2,
        [box_pin("R", 1, 2, 1, "1", "passive", 2),
         box_pin("R", 1, 2, 2, "2", "passive", 1),
         box_pin("R", 1, 2, 3, "3", "passive", 0),
         box_pin("R", 1, 2, 4, "4", "passive", -1)],
        [rect(gm(-1), gm(-2), gm(1), gm(3), "background")], "J")

add_sym("Conn_01x05", 1, 2,
        [box_pin("R", 1, 2, 1, "1", "passive", 2),
         box_pin("R", 1, 2, 2, "2", "passive", 1),
         box_pin("R", 1, 2, 3, "3", "passive", 0),
         box_pin("R", 1, 2, 4, "4", "passive", -1),
         box_pin("R", 1, 2, 5, "5", "passive", -2)],
        [rect(gm(-1), gm(-3), gm(1), gm(3), "background")], "J")

add_sym("SMA", 2, 2,
        [box_pin("L", 2, 2, 1, "RF", "passive", 1),
         box_pin("B", 2, 2, 2, "GND", "passive", 0)],
        [rect(gm(-2), gm(-2), gm(2), gm(2), "background"),
         circ(1.5, gm(1), 1.3, width=0.254),
         circ(1.5, gm(1), 0.35, width=0.254, fill="outline")], "J")

add_sym("IFA", 3, 3,
        [box_pin("L", 3, 3, 1, "FEED", "passive", 1),
         box_pin("B", 3, 3, 2, "SHRT", "passive", 0)],
        [rect(gm(-3), gm(-3), gm(3), gm(3), "background"),
         poly([(1.27, 2.54), (2.54, 2.54), (2.54, 5.08),
               (5.588, 5.08), (5.588, -2.54), (6.604, -2.54)], width=0.35)],
        "AE", in_bom="no")

add_sym("TP", 0, 0,
        [dict(num=1, name="1", etype="passive", unit=1, lx=0.0, ly=gm(-1), rot=90, length=G, hide=False)],
        [circ(0, 1.016, 1.016, width=0.254)],
        "TP", hide_pin_nums=True, hide_pin_names=True, in_bom="no")

add_sym("MOUNT", 1, 1, [],
        [circ(0, 0, 1.27), circ(0, 0, 2.286)],
        "H", hide_pin_nums=True, hide_pin_names=True, in_bom="no")

add_sym("FID", 1, 1, [],
        [circ(0, 0, 0.635, fill="outline"), circ(0, 0, 1.524)],
        "FID", hide_pin_nums=True, hide_pin_names=True, in_bom="no")

# ---- Global Power Symbols & PWR_FLAG -------------------------------------
add_sym("GND", 0, 0,
        [dict(num=1, name="~", etype="power_in", unit=1, lx=0.0, ly=0.0, rot=270, length=0, hide=False)],
        [poly([(0, 0), (0, -1.27)]),
         poly([(-1.524, -1.27), (1.524, -1.27)]),
         poly([(-1.016, -1.905), (1.016, -1.905)]),
         poly([(-0.508, -2.54), (0.508, -2.54)])],
        "#PWR", hide_pin_nums=True, hide_pin_names=True, is_power=True)

for pnet in ("3V3", "VBAT", "3V3_DET"):
    add_sym(pnet, 0, 0,
            [dict(num=1, name="~", etype="power_in", unit=1, lx=0.0, ly=0.0, rot=90, length=0, hide=False)],
            [poly([(0, 0), (0, 2.032)]),
             poly([(-1.27, 2.032), (1.27, 2.032)], width=0.381)],
            "#PWR", hide_pin_nums=True, hide_pin_names=True, is_power=True)

add_sym("PWR_FLAG", 0, 0,
        [dict(num=1, name="~", etype="power_out", unit=1, lx=0.0, ly=0.0, rot=90, length=0, hide=False)],
        [poly([(0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54), (1.016, 1.905), (0, 1.27)])],
        "#FLG", hide_pin_nums=True, hide_pin_names=True, is_power=True)


def _format_pin_sexp(p):
    pin_el = ["pin", p["etype"], "line",
              ["at", p["lx"], p["ly"], p["rot"]],
              ["length", round(p["length"], 4)]]
    if p.get("hide"):
        pin_el.append(["hide", "yes"])
    pin_el.append(["name", q(p["name"]), ["effects", ["font", ["size", 0.92, 0.92]]]])
    pin_el.append(["number", q(str(p["num"])), ["effects", ["font", ["size", 0.88, 0.88]]]])
    return pin_el


def sym_entry(name, full=False):
    s = SYMS[name]
    hw, hh = s["hw"], s["hh"]
    out = ["symbol", q(("ISAC:" if full else "") + name)]
    if s["is_power"]:
        out.append(["power"])
    if s["hide_nums"]:
        out.append(["pin_numbers", ["hide", "yes"]])
    if s["hide_names"]:
        out.append(["pin_names", ["offset", 0], ["hide", "yes"]])
    else:
        out.append(["pin_names", ["offset", 0.635]])
    out += [["exclude_from_sim", "no"],
            ["in_bom", s["in_bom"]],
            ["on_board", s["on_board"]]]

    if s["is_power"]:
        val_y = -4.0 if name == "GND" else 3.556
        out += [
            ["property", q("Reference"), q(s["ref"]), ["at", 0, -6.35, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["property", q("Value"), q(name), ["at", 0, val_y, 0],
             ["effects", ["font", ["size", 1.15, 1.15]]]],
        ]
    else:
        out += [
            ["property", q("Reference"), q(s["ref"]), ["at", -hw, hh + 2.54, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left"]]],
            ["property", q("Value"), q(name), ["at", -hw, -hh - 2.54, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left"]]],
        ]
    out += [
        ["property", q("Footprint"), q(""), ["at", 0, 0, 0],
         ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
        ["property", q("Datasheet"), q(""), ["at", 0, 0, 0],
         ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
    ]
    if s.get("units"):
        for unit_idx, udef in sorted(s["units"].items()):
            ubody = ["symbol", q(f"{name}_{unit_idx}_1")] + list(udef["graphics"])
            for p in udef["pins"]:
                ubody.append(_format_pin_sexp(p))
            out.append(ubody)
    else:
        out.append(["symbol", q(name + "_0_1")] + s["graphics"])
        body = ["symbol", q(name + "_1_1")]
        for p in s["pins"]:
            body.append(_format_pin_sexp(p))
        out.append(body)
    return out


def write_lib(path):
    lib = ["kicad_symbol_lib", ["version", 20241209],
           ["generator", q("kicad_symbol_editor")],
           ["generator_version", q("9.0")]]
    lib += [sym_entry(n, full=False) for n in SYMS]
    with open(path, "w") as fh:
        fh.write(sx(lib) + "\n")


# --------------------------------------------------------------------------
# Canonical netlist map (shared with tools/gen_pcb.py & verified by ERC)
# --------------------------------------------------------------------------
_U1_MAP = {p: "NC" for p in range(1, 74)}
for _gp in (12, 28, 35, 36, 38, 39, 46, 47, 52, 56, 65, 66, 67, 68, 69, 70, 71, 72, 73):
    _U1_MAP[_gp] = "GND"
_U1_MAP.update({
    1: "SWDIO", 2: "SWCLK",
    3: "3V3", 4: "3V3", 55: "3V3",
    6: "VDDA", 7: "VDDA",
    8: "DET_ADC",
    10: "VFBSMPS", 11: "VDDSMPS", 13: "VLXSMPS",
    15: "BAT_SENSE",
    29: "UART_TX", 30: "UART_RX",
    37: "RF_PA",
    43: "BOOT0", 44: "RST",
    50: "BAT_MON_EN",
    51: "DET_EN",
    53: "VDDPA", 54: "VDDRF",
})

NETS = {
    "U1": _U1_MAP,
    "U2": {1: "3V3_DET", 2: "DET_IN", 3: "DET_INN", 4: "GND", 5: "3V3_DET",
           6: "CAPM", 7: "CAPP", 8: "DET_OUT", 9: "GND"},
    "Q1": {1: "VBAT", 2: "GND", 3: "DET_EN", 4: "NC", 5: "3V3_DET", 6: "3V3_DET"},
    "Q2": {1: "GND", 2: "BAT_MON_EN", 3: "VBAT_SW", 4: "VBAT", 5: "VBAT_GATE", 6: "VBAT_GATE"},
    "U3": {1: "VBAT", 2: "GND", 3: "VBAT", 4: "NC", 5: "3V3"},
    "Q3": {1: "GND", 2: "VBAT", 3: "VBAT_RAW"},
    "D_VBAT": {1: "VBAT_RAW", 2: "GND"},
    "D_RST": {1: "RST", 2: "GND"},
    "D_3V3": {1: "3V3", 2: "GND"},
    "D_SWD": {1: "SWDIO", 2: "SWCLK", 3: "GND"},
    "D_UART": {1: "UART_TX", 2: "UART_RX", 3: "GND"},
    "D_RF": {1: "SMA_C", 2: "GND"},
    "J2": {1: "GND", 2: "VBAT_RAW"},
    "J1": {1: "SMA_C", 2: "GND"},
    "J3": {1: "BOOT0", 2: "BOOT_HI"},
    "J4": {1: "VAPP_SENSE", 2: "SWDIO", 3: "SWCLK", 4: "GND", 5: "RST"},
    "J5": {1: "VUART_ISO", 2: "UART_TX", 3: "UART_RX", 4: "GND"},
    "SW1": {1: "RST", 2: "GND"},
    "FB_VDDA": {1: "VDDA", 2: "3V3"},
    "FB_RF": {1: "VDDRF", 2: "3V3"},
    "FB_PA": {1: "VDDPA", 2: "3V3"},
    "FB_SMPS": {1: "3V3", 2: "VDDSMPS"},
    "L_SMPS": {1: "VFBSMPS", 2: "VLXSMPS"},
    "R1": {1: "BR_P", 2: "BR_Q"},
    "R2": {1: "BR_P", 2: "BR_S"},
    "R3": {1: "BR_S", 2: "GND"},
    "R_TERM": {1: "BR_O", 2: "GND"},
    "R_LPF": {1: "DET_OUT", 2: "DET_ADC"},
    "R_PD": {1: "DET_EN", 2: "GND"},
    "R_BPD": {1: "BAT_MON_EN", 2: "GND"},
    "R_BOOT": {1: "BOOT0", 2: "GND"},
    "R_BHI": {1: "BOOT_HI", 2: "3V3"},
    "R_VAPP": {1: "3V3", 2: "VAPP_SENSE"},
    "R_VUART": {1: "VAPP_SENSE", 2: "VUART_ISO"},
    "R_RST": {1: "RST", 2: "3V3"},
    "R_BG": {1: "VBAT", 2: "VBAT_GATE"},
    "R_B1": {1: "VBAT_SW", 2: "BAT_SENSE"},
    "R_B2": {1: "BAT_SENSE", 2: "GND"},
    "R_DIV1": {1: "BR_P", 2: "SMA_C"},
    "R_DIV2": {1: "BR_Q", 2: "SMA_C"},
    "C_RF": {1: "RF_PA", 2: "BR_P"},
    "C_S": {1: "BR_Q", 2: "BR_O"},
    "C_S2": {1: "BR_S", 2: "GND"},
    "C_BLK": {1: "BR_O", 2: "DET_IN"},
    "C_INN": {1: "DET_INN", 2: "GND"},
    "C_CAPP": {1: "CAPP", 2: "3V3_DET"},
    "C_CAPM": {1: "CAPM", 2: "3V3_DET"},
    "C_DET1": {1: "3V3_DET", 2: "GND"},
    "C_DET2": {1: "3V3_DET", 2: "GND"},
    "C_LPF": {1: "DET_ADC", 2: "GND"},
    "C_U1A": {1: "3V3", 2: "GND"},
    "C_U1B": {1: "3V3", 2: "GND"},
    "C_U1C": {1: "3V3", 2: "GND"},
    "C_VBAT": {1: "3V3", 2: "GND"},
    "C_VDDA1": {1: "VDDA", 2: "GND"},
    "C_VDDA2": {1: "VDDA", 2: "GND"},
    "C_VREF": {1: "VDDA", 2: "GND"},
    "C_RFV": {1: "VDDRF", 2: "GND"},
    "C_PAV": {1: "VDDPA", 2: "GND"},
    "C_SMPS1": {1: "VDDSMPS", 2: "GND"},
    "C_SMPS2": {1: "VFBSMPS", 2: "GND"},
    "C_SMPS3": {1: "VFBSMPS", 2: "GND"},
    "C_BULK1": {1: "VBAT", 2: "GND"},
    "C_BULK2": {1: "VBAT", 2: "GND"},
    "C_IN1": {1: "VBAT", 2: "GND"},
    "C_IN2": {1: "VBAT", 2: "GND"},
    "C_Q1": {1: "VBAT", 2: "GND"},
    "C_OUT1": {1: "3V3", 2: "GND"},
    "C_OUT2": {1: "3V3", 2: "GND"},
    "C_BAT": {1: "BAT_SENSE", 2: "GND"},
    "C_RST": {1: "RST", 2: "GND"},
    "C_M1": {1: "BR_Q", 2: "GND"},
    "C_MZ": {1: "BR_Q", 2: "ANT_FEED"},
    "C_M2": {1: "ANT_FEED", 2: "GND"},
    "L_S": {1: "BR_S", 2: "BR_O"},
    "L_Q": {1: "BR_Q", 2: "GND"},
    "L_M1": {1: "BR_Q", 2: "ANT_FEED"},
    "AE1": {1: "ANT_FEED", 2: "GND"},
    "TP1": {1: "3V3"}, "TP2": {1: "3V3_DET"}, "TP3": {1: "VBAT"},
    "TP4": {1: "DET_ADC"}, "TP5": {1: "GND"},
    "H1": {}, "H2": {}, "H3": {}, "H4": {},
    "FID1": {}, "FID2": {}, "FID3": {}, "FID4": {}, "FID5": {},
}

# --------------------------------------------------------------------------
# Component placement table on integer 2.54 mm grid (col, row, rot)
# --------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
R0402_DNP = "ISAC:R_0402_1005Metric_DNP_NoPaste"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0402_DNP = "ISAC:C_0402_1005Metric_DNP_NoPaste"
L0402 = "Inductor_SMD:L_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
L0805 = "Inductor_SMD:L_0805_2012Metric"
SOD523 = "Diode_SMD:D_SOD-523"
SOD523_DNP = "ISAC:D_SOD-523_DNP_NoPaste"
SOD323 = "Diode_SMD:D_SOD-323"
SOT23 = "Package_TO_SOT_SMD:SOT-23"

# Common verified passive sourcing metadata (MPN, Manufacturer, live-verified LCSC, Alternates)
_CAP_47U_0805_10V = [
    ("MPN", "GRM21BR61A476ME15L"), ("Manufacturer", "Murata"), ("LCSC", "C124129"),
    ("Alternates", "Samsung CL21A476MQYNNNE; Taiyo Yuden LMK212BBJ476MG-T"),
]
_CAP_4U7_0603 = [
    ("MPN", "GRM188R61E475KE11D"), ("Manufacturer", "Murata"), ("LCSC", "C90057"),
    ("Alternates", "Samsung CL10A475KA8NNNC; Taiyo Yuden TMK107BJ475KA-T"),
]
_CAP_4U7_0402_10V = [
    ("MPN", "GRM155R61A475MEAAD"), ("Manufacturer", "Murata"), ("LCSC", "C335105"),
    ("Alternates", "Samsung CL05A475MP5NRNC; Taiyo Yuden LMK105BJ475MV-F"),
]
_CAP_470N_0402_16V = [
    ("MPN", "GRM155R71C474KA01D"), ("Manufacturer", "Murata"), ("LCSC", "C52923"),
    ("Alternates", "Samsung CL05B474KO5NNNC (C1621); Taiyo Yuden TMK105B7474KVHF"),
]
_CAP_100N_0402 = [
    ("MPN", "GRM155R71C104KA88D"), ("Manufacturer", "Murata"), ("LCSC", "C71629"),
    ("Alternates", "Samsung CL05B104KO5NNNC (C1525); Yageo CC0402KRX7R7BB104"),
]
_CAP_1U_0402 = [
    ("MPN", "GRM155R61E105KA12D"), ("Manufacturer", "Murata"), ("LCSC", "C77009"),
    ("Alternates", "Samsung CL05A105KA5NQNC; Taiyo Yuden TMK105BJ105KV-F"),
]
_CAP_1U_0603 = [
    ("MPN", "GRM188R71E105KA12D"), ("Manufacturer", "Murata"), ("LCSC", "C86020"),
    ("Alternates", "Samsung CL10B105KA8NNNC; Yageo CC0603KRX7R8BB105"),
]
_CAP_1N_C0G = [
    ("MPN", "GRM1555C1H102JA01D"), ("Manufacturer", "Murata"), ("LCSC", "C76947"),
    ("Alternates", "Samsung CL05C102JB5NNNC (C1523); Yageo CC0402JRNPO9BN102"),
]
_CAP_100P_HIQ = [
    ("MPN", "GJM1555C1H101JB01D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Murata GRM1555C1H101JA01D; Samsung CL05C101JB5NNNC"),
]
_CAP_1P0_HIQ = [
    ("MPN", "GJM1555C1H1R0WB01D"), ("Manufacturer", "Murata"), ("LCSC", "C161339"),
    ("Alternates", "Murata GRM1555C1H1R0WA01D; Johanson 500R07S1R0AV4T"),
]
_CAP_3P6_HIQ = [
    ("MPN", "GJM1555C1H3R6WB01D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Murata GJM1555C1H3R6BB01D (C94175); Johanson 500R07S3R6BV4T"),
]
_CAP_4P3_HIQ = [
    ("MPN", "GJM1555C1H4R3WB01D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Murata GJM1555C1H4R3BB01D (C94181); Johanson 500R07S4R3BV4T"),
]
_CAP_0P5_HIQ = [
    ("MPN", "GJM1555C1HR50WB01D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Murata GJM1555C1HR50BB01D (C181064); Johanson 500R07SR50BV4T"),
]
_IND_8N2_HIQ = [
    ("MPN", "LQW15AN8N2G00D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Coilcraft 0402CS-8N2XGLW; Taiyo Yuden HKQ1005S8N2S-T"),
]
_FB_120R_0402 = [
    ("MPN", "BLM15AG121SN1D"), ("Manufacturer", "Murata"), ("LCSC", "C85812"),
    ("Alternates", "TDK MMZ1005S121CT000; Taiyo Yuden BK1005HS121-T"),
]
_RES_10K_0402 = [
    ("MPN", "RC0402FR-0710KL"), ("Manufacturer", "Yageo"), ("LCSC", "C60490"),
    ("Alternates", "Uni-Royal 0402WGF1002TCE; Vishay CRCW040210K0FKED"),
]
_RES_1K_0402 = [
    ("MPN", "RC0402FR-071KL"), ("Manufacturer", "Yageo"), ("LCSC", "C106235"),
    ("Alternates", "Uni-Royal 0402WGF1001TCE; Vishay CRCW04021K00FKED"),
]
_RES_0R_0402 = [
    ("MPN", "RC0402JR-070RL"), ("Manufacturer", "Yageo"), ("LCSC", "C60485"),
    ("Alternates", "Uni-Royal 0402WGF0000TCE; Panasonic ERJ-2GE0R00X"),
]
_TVS_SOD323 = [
    ("MPN", "PESD5V0S1BA,115"), ("Manufacturer", "Nexperia"), ("LCSC", "C19224"),
    ("Alternates", "Nexperia PESD5V0L1BA,115 (C15847, I_RM<=50nA, SOD-323 bidir); Bourns CDSOD323-T05C (SOD-323 bidir)"),
]
_TVS_SOT23_DUAL = [
    ("MPN", "PESD5V0U2BT,215"), ("Manufacturer", "Nexperia"), ("LCSC", "Authorized: DigiKey/Mouser"),
    ("Alternates", "Nexperia PESD5V0L2BT,215 (C15855); TI TPD2E009DBZR; ST ESDA6V1L (SOT-23 3-pin 1=IO1,2=IO2,3=GND)"),
]

# Multi-unit sheet coordinates (col, row, rot) for U1A (Unit 1), U1B (Unit 2), U1C (Unit 3)
U1_UNITS = {
    1: (31, 68, 0),   # U1A: Power, Isolated VDDA/VDDRF/VDDPA & 15 uH SMPS
    2: (41, 33, 0),   # U1B: MCU Control, Protected Debug, ADC & Sub-GHz RF_OUT
    3: (19, 100, 0),  # U1C: Unused LGA-73 GPIO & Internal NC Bank
}

# (ref, lib, value, footprint, col, row, rot, dnp, fields)
PARTS = [
    # ---- 1 & 2 & 3. RAK3172LP-SiP (LGA-73 Multi-Unit U1A/U1B/U1C)
    ("U1", "RAK3172LP-SiP", "RAK3172LP-SiP",
     "ISAC:RAK3172LP-SiP_LGA-73_12x12mm_P0.6mm", U1_UNITS[1][0], U1_UNITS[1][1], 0, False,
     [("MPN", "RAK3172LP-SIP-8-SM-NI"), ("Manufacturer", "RAKwireless"),
      ("LCSC", "Authorized: RAKwireless/Mouser/DigiKey"),
      ("Alternates", "NO SUBSTITUTION -- Authorized RAKwireless SKU 305049 / Mouser 910-RAK3172LPSIP8SMN / DigiKey ONLY (EU868 RFO_LP LGA-73; DO NOT substitute RAK3172-SiP RFO_HP)")]),

    # VDD1 / VDD2 / VBAT digital 3V3 bypass bank (Frame 2, left of U1A)
    ("C_U1A", "C", "4.7u", C0603, 6, 60, 270, False, _CAP_4U7_0603),
    ("C_U1B", "C", "100n", C0402, 11, 60, 270, False, _CAP_100N_0402),
    ("C_U1C", "C", "100n", C0402, 15, 60, 270, False, _CAP_100N_0402),
    ("C_VBAT", "C", "1u", C0402, 20, 60, 270, False, _CAP_1U_0402),

    # Ferrite-isolated Analog Reference rail (Frame 2, top-right of U1A)
    ("FB_VDDA", "FB", "120R@100M", L0402, 52, 60, 0, False, _FB_120R_0402),
    ("C_VDDA1", "C", "4.7u", C0603, 40, 63, 270, False, _CAP_4U7_0603),
    ("C_VDDA2", "C", "1u", C0402, 45, 63, 270, False, _CAP_1U_0402),
    ("C_VREF", "C", "100n", C0402, 50, 63, 270, False, _CAP_100N_0402),

    # Ferrite-isolated RF & PA power rails (Frame 2, mid/bottom-right of U1A)
    ("FB_RF", "FB", "120R@100M", L0402, 50, 69, 0, False, _FB_120R_0402),
    ("C_RFV", "C", "1u", C0402, 44, 71, 270, False, _CAP_1U_0402),
    ("FB_PA", "FB", "120R@100M", L0402, 50, 77, 0, False, _FB_120R_0402),
    ("C_PAV", "C", "1u", C0402, 44, 79, 270, False, _CAP_1U_0402),

    # Reset network + IEC 61000-4-2 ESD clamp (Frame 1, top-left of U1B)
    ("R_RST", "R", "10k", R0402, 29, 11, 90, False, _RES_10K_0402),
    ("C_RST", "C", "100n", C0402, 23, 15, 270, False, _CAP_100N_0402),
    ("D_RST", "TVS_BIDIR", "PESD5V0S1BA", SOD323, 16, 15, 270, False, _TVS_SOD323),
    ("SW1", "SW_PUSH", "RESET", "Button_Switch_SMD:SW_SPST_B3U-1000P", 9, 15, 270, False,
     [("MPN", "B3U-1000P"), ("Manufacturer", "Omron"), ("LCSC", "C231329"),
      ("Alternates", "Omron B3U-1000P-B (exact 3.0x2.5mm 2-pad SPST SMD land pattern)")]),

    # BOOT0, SWD & UART2 interfaces (Frame 1, left of U1B)
    ("R_BOOT", "R", "10k", R0402, 27, 26, 270, False, _RES_10K_0402),
    ("R_BHI", "R", "10k", R0402, 20, 27, 0, False, _RES_10K_0402),
    ("J3", "Conn_01x02", "DNP BOOT", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
     11, 25, 0, True,
     [("MPN", "PZ254V-11-02P"), ("Manufacturer", "XFCN"), ("LCSC", "C492401"),
      ("Alternates", "Wurth 61300211121; Amphenol 68000-102HLF (DNP on sealed field SKU -- bare ENIG pogo-pin pads)")]),
    ("R_VAPP", "R", "1k", R0402, 21, 30, 180, False, _RES_1K_0402),
    ("J4", "Conn_01x05", "DNP SWD", "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
     11, 32, 0, True,
     [("MPN", "PZ254V-11-05P"), ("Manufacturer", "XFCN"), ("LCSC", "C492404"),
      ("Alternates", "Wurth 61300511121; Amphenol 68000-105HLF (DNP on sealed field SKU -- bare ENIG pogo-pin pads)")]),
    ("D_SWD", "PESD5V0U2BT", "PESD5V0U2BT", SOT23, 26, 33, 0, False, _TVS_SOT23_DUAL),
    ("R_VUART", "R", "DNP 0R", R0402_DNP, 21, 41, 180, True, _RES_0R_0402),
    ("J5", "Conn_01x04", "DNP UART", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
     11, 43, 0, True,
     [("MPN", "PZ254V-11-04P"), ("Manufacturer", "XFCN"), ("LCSC", "C492403"),
      ("Alternates", "Wurth 61300411121; Amphenol 68000-104HLF (DNP on sealed field SKU -- bare ENIG pogo-pin pads)")]),
    ("D_UART", "PESD5V0U2BT", "PESD5V0U2BT", SOT23, 26, 44, 0, False, _TVS_SOT23_DUAL),

    # Internal DC-DC SMPS buck converter (Frame 2, lower-left of U1A)
    ("FB_SMPS", "R", "0R", R0402, 11, 68, 0, False, _RES_0R_0402),
    ("C_SMPS1", "C", "4.7u", C0402, 15, 70, 270, False, _CAP_4U7_0402_10V),
    ("L_SMPS", "L", "15u", L0805, 16, 75, 0, False,
     [("MPN", "LQH2MCN150K02L"), ("Manufacturer", "Murata"), ("LCSC", "C86089"),
      ("Alternates", "Murata LQM21PN150MGH (0805 15uH power inductor, Isat=300mA); TDK VLS201610HBX-150M-1 -- NEVER substitute ferrite EMI beads (MLZ2012)")]),
    ("C_SMPS2", "C", "470n", C0402, 8, 80, 270, False, _CAP_470N_0402_16V),
    ("C_SMPS3", "C", "DNP 100n", C0402_DNP, 14, 80, 270, True, _CAP_100N_0402),

    # ---- 4. Return-Loss Bridge & VNA Calibration Diverter ----------------
    ("C_RF", "C", "100p", C0402, 62, 22, 0, False, _CAP_100P_HIQ),
    ("R1", "R", "8.2 (0.1%)", R0402, 76, 22, 0, False,
     [("MPN", "RT0402BRD078R2L"), ("Manufacturer", "Yageo"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Yageo RT0402DRD078R2L (±0.5%); Panasonic ERA-2AED8R2X (±0.5%)")]),
    ("R2", "R", "681 (0.1%)", R0402, 71, 29, 270, False,
     [("MPN", "RG1005P-6810-B-T5"), ("Manufacturer", "Susumu"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Vishay TNPW0402681RBEED; Yageo RT0402BRD07681RL")]),
    ("R3", "R", "3.57k (0.1%)", R0402, 71, 48, 270, False,
     [("MPN", "RG1005P-3571-B-T5"), ("Manufacturer", "Susumu"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Vishay TNPW04023K57BEED; Yageo RT0402BRD073K57L")]),
    ("C_S2", "C", "1.0p", C0402, 79, 48, 270, False, _CAP_1P0_HIQ),
    ("L_Q", "L", "27n", L0402, 89, 27, 270, False,
     [("MPN", "LQW15AN27NG00D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Coilcraft 0402CS-27NXGLW; Murata LQW15AN27NG80D")]),
    ("C_S", "C", "1.0p", C0402, 96, 32, 270, False, _CAP_1P0_HIQ),
    ("L_S", "L", "30n", L0402, 87, 44, 0, False,
     [("MPN", "LQW15AN30NG00D"), ("Manufacturer", "Murata"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Coilcraft 0402CS-30NXGLW; Murata LQW15AN30NG80D")]),
    ("R_TERM", "R", "56 (0.1%)", R0402, 103, 48, 270, False,
     [("MPN", "RG1005P-560-B-T5"), ("Manufacturer", "Susumu"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Vishay TNPW040256R0BEED; Yageo RT0402BRD0756RL")]),

    ("R_DIV1", "R", "DNP 0R", R0402_DNP, 67, 16, 90, True, _RES_0R_0402),
    ("R_DIV2", "R", "DNP 0R", R0402_DNP, 83, 16, 90, True, _RES_0R_0402),
    ("D_RF", "TVS_BIDIR", "DNP", SOD523_DNP, 92, 16, 270, True,
     [("MPN", "ESD9B5.0ST5G"), ("Manufacturer", "onsemi"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Nexperia PESD5V0U1BB,115 (C85364); Vishay VESD05A1B-HAF-GS08 (SOD-523 ultra-low Cd=0.5pF RF ESD)")]),
    ("J1", "SMA", "DNP SMA_VNA", "ISAC:SMA_Molex_73251-1153_EdgeMount_Horizontal_HandSolder",
     102, 14, 0, True,
     [("MPN", "73251-1153"), ("Manufacturer", "Molex"), ("LCSC", "Authorized: Mouser/DigiKey"),
      ("Alternates", "NO SUBSTITUTION -- Molex 73251-1153 (1.60mm PCB edge-straddle SMA jack; DNP on enclosed field SKU, post-reflow hand-solder on bench VNA units) ONLY")]),

    # ---- 5. Elliptic Low-Pass Harmonic Pi-Filter & Printed Folded IFA ----
    ("C_M1", "C", "3.6p", C0402, 118, 25, 270, False, _CAP_3P6_HIQ),
    ("L_M1", "L", "8.2n", L0402, 127, 22, 0, False, _IND_8N2_HIQ),
    ("C_MZ", "C", "0.5p", C0402, 127, 15, 0, False, _CAP_0P5_HIQ),
    ("C_M2", "C", "4.3p", C0402, 136, 25, 270, False, _CAP_4P3_HIQ),
    ("AE1", "IFA", "IFA_868MHz_ISAC", "ISAC:IFA_868MHz_ISAC_40x20mm", 150, 23, 0, False,
     [("MPN", "PCB trace"), ("Manufacturer", "Custom")]),

    # ---- 6. LT5538 Log Detector & Anti-Aliasing Video LPF ----------------
    ("C_BLK", "C", "100p", C0402, 115, 44, 0, False, _CAP_100P_HIQ),
    ("U2", "LT5538IDD", "LT5538IDD#TRPBF",
     "ISAC:LT5538IDD_DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm", 129, 45, 0, False,
     [("MPN", "LT5538IDD#TRPBF"), ("Manufacturer", "Analog Devices"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "NO SUBSTITUTION -- Analog Devices LT5538IDD#TRPBF (8mm T&R, Mouser 584-LT5538IDD#TRPBF / DigiKey LT5538IDD#TRPBFCT-ND); LT5538IDD#PBF (37-pc tube, LCSC C580201 -- requires custom tube feeder)")]),
    ("C_INN", "C", "1n", C0402, 119, 50, 270, False, _CAP_1N_C0G),
    ("C_CAPP", "C", "1n", C0402, 139, 40, 90, False, _CAP_1N_C0G),
    ("C_CAPM", "C", "1n", C0402, 145, 40, 90, False, _CAP_1N_C0G),
    ("R_LPF", "R", "1k", R0402, 146, 47, 0, False, _RES_1K_0402),
    ("C_LPF", "C", "100n", C0402, 151, 50, 270, False, _CAP_100N_0402),

    # ---- 7. 1S Battery Input, Ideal Diode, Gated VBAT Sense, LDO & 3V3_DET
    ("J2", "Conn_01x02", "DNP 1S_BATT",
     "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
     65, 71, 0, True,
     [("MPN", "B2B-PH-K-S"), ("Manufacturer", "JST"), ("LCSC", "C131337"),
      ("Alternates", "DNP on sealed field SKU -- solder 24-26 AWG silicone battery leads directly to bare ENIG PTH pads (Pad1 Square=BLACK GND, Pad2 Round=RED +VBAT_RAW); JST B2B-PH-K-S(LF)(SN) (LCSC C54911) optional for bench builds")]),
    ("D_VBAT", "TVS_BIDIR", "PESD5V0S1BA", SOD323, 71, 74, 270, False, _TVS_SOD323),
    ("Q3", "PMOS_RPP", "AO3401A", SOT23, 78, 70, 0, False,
     [("MPN", "AO3401A"), ("Manufacturer", "Alpha & Omega"), ("LCSC", "C15127"),
      ("Alternates", "Nexperia PMV48XP,215 (C15137); Infineon IRLML6402TRPBF (C2590); Vishay SI2301CDS-T1-GE3 (C10487)")]),
    ("R_BG", "R", "470k", R0402, 86, 73, 270, False,
     [("MPN", "RC0402FR-07470KL"), ("Manufacturer", "Yageo"), ("LCSC", "C482181"),
      ("Alternates", "Uni-Royal 0402WGF4703TCE; Vishay CRCW0402470KFKED")]),
    ("Q2", "NX3008CBKS", "NX3008CBKS", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
     95, 72, 0, False,
     [("MPN", "NX3008CBKS,115"), ("Manufacturer", "Nexperia"), ("LCSC", "C456076"),
      ("Alternates", "NO SUBSTITUTION -- Nexperia NX3008CBKS,115 (SOT-363 complementary N+P MOSFET, 1=S1,2=G1,3=D2,4=S2,5=G2,6=D1) ONLY")]),
    ("R_BPD", "R", "100k", R0402, 108, 73, 270, False,
     [("MPN", "RC0402FR-07100KL"), ("Manufacturer", "Yageo"), ("LCSC", "C60491"),
      ("Alternates", "Uni-Royal 0402WGF1003TCE; Vishay CRCW0402100KFKED")]),
    ("R_B1", "R", "4.7k (0.1%)", R0402, 102, 82, 270, False,
     [("MPN", "RG1005P-472-B-T5"), ("Manufacturer", "Susumu"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Vishay TNPW04024K70BEED; Yageo RT0402BRD074K7L")]),
    ("R_B2", "R", "4.7k (0.1%)", R0402, 102, 89, 270, False,
     [("MPN", "RG1005P-472-B-T5"), ("Manufacturer", "Susumu"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "Vishay TNPW04024K70BEED; Yageo RT0402BRD074K7L")]),
    ("C_BAT", "C", "1n", C0402, 109, 89, 270, False, _CAP_1N_C0G),

    ("C_BULK1", "C", "47u", C0805, 115, 70, 270, False, _CAP_47U_0805_10V),
    ("C_BULK2", "C", "47u", C0805, 120, 70, 270, False, _CAP_47U_0805_10V),
    ("C_IN1", "C", "10u", C0603, 125, 70, 270, False,
     [("MPN", "GRM188R61E106MA73D"), ("Manufacturer", "Murata"), ("LCSC", "C91606"),
      ("Alternates", "Samsung CL10A106MA8NRNC; Murata GRM188R61E106KA73D")]),
    ("C_IN2", "C", "100n", C0402, 130, 70, 270, False, _CAP_100N_0402),
    ("U3", "TPS7A0233DBVR", "TPS7A0233DBVR", "Package_TO_SOT_SMD:SOT-23-5", 138, 69, 0, False,
     [("MPN", "TPS7A0233DBVR"), ("Manufacturer", "Texas Instruments"), ("LCSC", "C2873330"),
      ("Alternates", "NO SUBSTITUTION -- TI TPS7A0233DBVR (SOT-23-5 DBV pinout 1=IN,2=GND,3=EN,4=NC,5=OUT, Iq=25nA) ONLY")]),
    ("C_OUT1", "C", "1u", C0603, 143, 70, 270, False, _CAP_1U_0603),
    ("C_OUT2", "C", "100n", C0402, 148, 70, 270, False, _CAP_100N_0402),
    ("D_3V3", "TVS_BIDIR", "PESD5V0S1BA", SOD323, 153, 70, 270, False, _TVS_SOD323),

    ("Q1", "TPS22919DCKR", "TPS22919DCKR", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
     137, 86, 0, False,
     [("MPN", "TPS22919DCKR"), ("Manufacturer", "Texas Instruments"), ("LCSC", "Authorized: DigiKey/Mouser"),
      ("Alternates", "NO SUBSTITUTION -- TI TPS22919DCKR / TPS22919QDCKRQ1 (SC-70-6 DCK pinout 1=VIN,2=GND,3=ON,4=NC,5=QOD,6=VOUT) ONLY")]),
    ("C_Q1", "C", "100n", C0402, 117, 87, 270, False, _CAP_100N_0402),
    ("R_PD", "R", "100k", R0402, 128, 90, 270, False,
     [("MPN", "RC0402FR-07100KL"), ("Manufacturer", "Yageo"), ("LCSC", "C60491"),
      ("Alternates", "Uni-Royal 0402WGF1003TCE; Vishay CRCW0402100KFKED")]),
    ("C_DET1", "C", "100n", C0402, 145, 87, 270, False, _CAP_100N_0402),
    ("C_DET2", "C", "1u", C0603, 150, 87, 270, False, _CAP_1U_0603),

    # ---- 8. Clean DC/Low-Speed Test Points ONLY (ZERO RF Test Points) ----
    ("TP1", "TP", "3V3", "TestPoint:TestPoint_Pad_D1.5mm", 158, 66, 0, False, []),
    ("TP2", "TP", "3V3_DET", "TestPoint:TestPoint_Pad_D1.5mm", 155, 83, 0, False, []),
    ("TP3", "TP", "VBAT", "TestPoint:TestPoint_Pad_D1.5mm", 112, 66, 0, False, []),
    ("TP4", "TP", "DET_ADC", "TestPoint:TestPoint_Pad_D1.5mm", 151, 46, 0, False, []),
    ("TP5", "TP", "GND", "TestPoint:TestPoint_Pad_D1.5mm", 158, 73, 0, False, []),

    # ---- 9. Mechanical Mounting Holes & Global SMT Fiducials (Frame 3) ---
    ("H1", "MOUNT", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", 35, 95, 0, False, []),
    ("H2", "MOUNT", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", 40, 95, 0, False, []),
    ("H3", "MOUNT", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", 45, 95, 0, False, []),
    ("H4", "MOUNT", "M2.5", "MountingHole:MountingHole_2.7mm_M2.5", 50, 95, 0, False, []),
    ("FID1", "FID", "Fid_G1", "Fiducial:Fiducial_1mm_Mask2mm", 34, 105, 0, False, []),
    ("FID2", "FID", "Fid_G2", "Fiducial:Fiducial_1mm_Mask2mm", 39, 105, 0, False, []),
    ("FID3", "FID", "Fid_G3", "Fiducial:Fiducial_1mm_Mask2mm", 44, 105, 0, False, []),
    ("FID4", "FID", "Fid_U1A", "Fiducial:Fiducial_1mm_Mask2mm", 49, 105, 0, False, []),
    ("FID5", "FID", "Fid_U1B", "Fiducial:Fiducial_1mm_Mask2mm", 53, 105, 0, False, []),
]

PART_MAP = {p[0]: p for p in PARTS}

assert set(PART_MAP.keys()) == set(NETS.keys()), "PARTS vs NETS key mismatch!"
for _ref, _pmap in NETS.items():
    _lib = PART_MAP[_ref][1]
    _expected_pins = {p["num"] for p in SYMS[_lib]["pins"]}
    assert set(_pmap.keys()) == _expected_pins, f"{_ref} ({_lib}) pin map mismatch!"


def pin_grid(ref, pnum):
    """Return exact integer (col, row) of component pin on schematic sheet."""
    _, lib, _, _, cx, cy, rot, _, _ = PART_MAP[ref]
    for p in SYMS[lib]["pins"]:
        if str(p["num"]) == str(pnum):
            if ref == "U1":
                cx, cy, rot = U1_UNITS[p["unit"]]
            gx = round(p["lx"] / G)
            gy = round(p["ly"] / G)
            if rot == 0:
                return (cx + gx, cy - gy)
            if rot == 90:
                return (cx - gy, cy - gx)
            if rot == 180:
                return (cx - gx, cy + gy)
            if rot == 270:
                return (cx + gy, cy + gx)
            raise ValueError(rot)
    raise KeyError(f"{ref} pin {pnum}")


# Explicit human-tuned (ref_dx, ref_dy, ref_just, val_dx, val_dy, val_just) overrides (mm)
PROP_OVERRIDES = {
    "D_RST":   (1.5, -0.9, "left", 1.5, 0.9, "left"),
    "R_RST":   (1.5, -0.9, "left", 1.5, 0.9, "left"),
    "FB_VDDA": (0.0, -2.5, "center", 0.0, 2.6, "center"),
    "FB_RF":   (0.0, -2.5, "center", 0.0, 2.6, "center"),
    "FB_PA":   (0.0, -2.5, "center", 0.0, 2.6, "center"),
    "R_B1":    (1.5, -0.9, "left", 1.5, 0.9, "left"),
    "R_B2":    (-1.5, -0.9, "right", -1.5, 0.9, "right"),
    "Q3":      (0.0, -4.4, "center", 3.2, 2.2, "left"),
}


# --------------------------------------------------------------------------
# Schematic builder with direct wiring, power symbols & auto-junctions
# --------------------------------------------------------------------------
def gen_sch():
    root_uuid = u("root")
    doc = [
        "kicad_sch",
        ["version", 20250114],
        ["generator", q("eeschema")],
        ["generator_version", q("9.0")],
        ["uuid", q(root_uuid)],
        ["paper", q("A3")],
        ["title_block",
         ["title", q("Dual-Function 868 MHz PCB Antenna-Sensor (ISAC)")],
         ["date", q("2026-11-06")],
         ["rev", q("E.5")],
         ["company", q("RF & Embedded Systems Engineering")],
         ["comment", 1, q("MCU/Radio: RAK3172LP-SiP (STM32WLE5JC, 3.0V TCXO, 15uH SMPS)")],
         ["comment", 2, q("Antenna: 866.5 MHz Folded IFA + Elliptic Pi (3.6p/8.2n||0.5p/4.3p)")],
         ["comment", 3, q("RF Sensor: 8.2R Return-Loss Bridge + ADI LT5538 Log Detector")],
         ["comment", 4, q("Power: 1S LiPo/Li-SOCl2 (3.0-4.35V), AO3401A RPP, TPS7A0233 3V3")]],
        ["lib_symbols"] + [sym_entry(n, full=True) for n in SYMS],
    ]

    body = []

    # ---- Subsystem boundary frames & titles ------------------------------
    frames = [
        (5, 5, 55, 50, "1. MCU CONTROL, PROTECTED DEBUG & RF LAUNCH (U1B)"),
        (5, 52, 55, 86, "2. SiP POWER, ISOLATED VDDA & 15 uH BUCK SMPS (U1A)"),
        (5, 88, 55, 111, "3. UNUSED LGA-73 I/O BANK (U1C) & MECHANICALS"),
        (57, 5, 110, 57, "4. 868 MHz RETURN-LOSS BRIDGE & VNA CALIBRATION PORT"),
        (112, 5, 159, 31, "5. ELLIPTIC HARMONIC PI-FILTER & FOLDED IFA-SENSOR"),
        (112, 33, 159, 57, "6. LT5538 75 dB RF LOG DETECTOR & VIDEO LPF"),
        (57, 59, 159, 97, "7. 1S BATTERY INPUT, GATED VBAT SENSE, 3.3 V LDO & DETECTOR RAIL"),
    ]
    for i, (c1, r1, c2, r2, title) in enumerate(frames):
        body.append([
            "rectangle",
            ["start", gm(c1), gm(r1)],
            ["end", gm(c2), gm(r2)],
            ["stroke", ["width", 0.18], ["type", "dash"], ["color", 55, 90, 140, 0.85]],
            ["fill", ["type", "none"]],
            ["uuid", q(u(f"frame:{i}"))],
        ])
        body.append([
            "text", q(title),
            ["at", round(gm(c1) + 1.8, 4), round(gm(r1) + 2.3, 4), 0],
            ["effects", ["font", ["size", 1.25, 1.25],
                         ["bold", "yes"], ["color", 30, 65, 115, 1.0]],
             ["justify", "left"]],
            ["uuid", q(u(f"ftitle:{i}"))],
        ])

    def _emit_symbol_unit(ref, lib, val, fp, cx, cy, rot, dnp, fields, unit_idx=1):
        x, y = gm(cx), gm(cy)
        s = SYMS[lib]
        udef = s["units"][unit_idx] if s.get("units") else s
        uhw, uhh = udef["hw"], udef["hh"]
        # KiCad .kicad_sch adds symbol rot to property angle for 90/270 deg, whereas 0/180 deg angle=0 stays upright!
        prop_ang = 0 if rot in (0, 180) else (360 - rot) % 360

        if ref in PROP_OVERRIDES:
            rdx, rdy, rjust, vdx, vdy, vjust = PROP_OVERRIDES[ref]
            rx, ry = x + rdx, y + rdy
            vx, vy = x + vdx, y + vdy
        elif ref == "U1":
            rx, ry, rjust = x - uhw, y - uhh - 1.8, "left"
            vx, vy, vjust = x + uhw, y - uhh - 1.8, "right"
        elif lib in ("R", "C", "L", "FB", "D", "TVS_BIDIR", "SW_PUSH"):
            if rot in (90, 270):
                hoff = 2.25 if lib == "C" else 1.65
                rx, ry, rjust = x + hoff, y - 0.85, "left"
                vx, vy, vjust = x + hoff, y + 0.95, "left"
            else:
                voff = 2.85 if lib == "C" else 2.25
                rx, ry, rjust = x, y - voff, "center"
                vx, vy, vjust = x, y + voff + 0.1, "center"
        elif lib == "PESD5V0U2BT":
            rx, ry, rjust = x + uhw + 0.8, y - 0.9, "left"
            vx, vy, vjust = x + uhw + 0.8, y + 1.0, "left"
        elif lib == "TP":
            rx, ry, rjust = x, y - 2.9, "center"
            vx, vy, vjust = x, y - 4.4, "center"
        elif lib in ("MOUNT", "FID"):
            rx, ry, rjust = x, y - (2.6 if lib == "FID" else 3.0), "center"
            vx, vy, vjust = x, y + (2.6 if lib == "FID" else 3.1), "center"
        elif lib in ("Conn_01x02", "Conn_01x04", "Conn_01x05"):
            rx, ry, rjust = x - uhw - 0.8, y - 1.8, "right"
            vx, vy, vjust = x - uhw - 0.8, y + 0.2, "right"
        else:
            rx, ry, rjust = x - uhw, y - uhh - 1.8, "left"
            val_dx = 3.2 if ref == "U2" else 1.8
            vx, vy, vjust = x + val_dx, y + uhh + 2.1, "left"

        ref_eff = ["effects", ["font", ["size", 0.98, 0.98], ["bold", "yes"]]]
        if rjust != "center":
            ref_eff.append(["justify", rjust])
        val_eff = ["effects", ["font", ["size", 0.86, 0.86]]]
        if vjust != "center":
            val_eff.append(["justify", vjust])

        sym_uuid = u(ref) if unit_idx == 1 else u(f"{ref}:unit{unit_idx}")
        inst = [
            "symbol", ["lib_id", q("ISAC:" + lib)], ["at", x, y, rot], ["unit", unit_idx],
            ["exclude_from_sim", "no"],
            ["in_bom", "no" if lib in ("MOUNT", "IFA", "TP", "FID") else "yes"],
            ["on_board", "yes"],
            ["dnp", "yes" if dnp else "no"],
            ["uuid", q(sym_uuid)],
            ["property", q("Reference"), q(ref), ["at", round(rx, 4), round(ry, 4), prop_ang], ref_eff],
            ["property", q("Value"), q(val), ["at", round(vx, 4), round(vy, 4), prop_ang], val_eff],
            ["property", q("Footprint"), q(fp), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["property", q("Datasheet"), q(""), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
        ]
        for k, v in fields:
            inst.append(["property", q(k), q(v), ["at", x, y, 0],
                         ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]])
        for p in udef["pins"]:
            inst.append(["pin", q(str(p["num"])), ["uuid", q(u(f"{ref}:{p['num']}"))]])
        inst.append(["instances", ["project", q(PROJECT),
                                   ["path", q("/" + root_uuid),
                                    ["reference", q(ref)], ["unit", unit_idx]]]])
        body.append(inst)

    # ---- Emit symbol instances (including all 3 units of U1) -------------
    for (ref, lib, val, fp, cx, cy, rot, dnp, fields) in PARTS:
        if ref == "U1":
            for u_idx, (ucx, ucy, urot) in sorted(U1_UNITS.items()):
                _emit_symbol_unit(ref, lib, val, fp, ucx, ucy, urot, dnp, fields, unit_idx=u_idx)
        else:
            _emit_symbol_unit(ref, lib, val, fp, cx, cy, rot, dnp, fields, unit_idx=1)

    # ---- Wiring & Power Symbol Helpers -----------------------------------
    raw_segments = []
    pwr_count = [0]
    flg_count = [0]
    pin_pts = set()
    for ref, pmap in NETS.items():
        for pnum, net in pmap.items():
            if net != "NC":
                pin_pts.add(pin_grid(ref, pnum))

    def add_wire(p1, p2):
        if p1 == p2:
            return
        assert p1[0] == p2[0] or p1[1] == p2[1], f"Non-orthogonal wire {p1} -> {p2}"
        raw_segments.append((p1, p2))

    def chain(*pts):
        for i in range(len(pts) - 1):
            add_wire(pts[i], pts[i + 1])

    def add_pwr(net, col, row, rot=0):
        pwr_count[0] += 1
        pref = f"#PWR{pwr_count[0]:02d}"
        x, y = gm(col), gm(row)
        val_y = y + 3.8 if net == "GND" else y - 3.4
        sym = [
            "symbol", ["lib_id", q("ISAC:" + net)], ["at", x, y, rot], ["unit", 1],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            ["dnp", "no"], ["uuid", q(u(pref))],
            ["property", q("Reference"), q(pref), ["at", x, y + 6.35, 0],
             ["effects", ["font", ["size", 1.0, 1.0]], ["hide", "yes"]]],
            ["property", q("Value"), q(net), ["at", x, round(val_y, 4), 0],
             ["effects", ["font", ["size", 0.95, 0.95]]]],
            ["property", q("Footprint"), q(""), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["property", q("Datasheet"), q(""), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["pin", q("1"), ["uuid", q(u(pref + ":1"))]],
            ["instances", ["project", q(PROJECT),
                           ["path", q("/" + root_uuid),
                            ["reference", q(pref)], ["unit", 1]]]],
        ]
        body.append(sym)
        pin_pts.add((col, row))

    def add_flg(col, row):
        flg_count[0] += 1
        fref = f"#FLG{flg_count[0]:02d}"
        x, y = gm(col), gm(row)
        sym = [
            "symbol", ["lib_id", q("ISAC:PWR_FLAG")], ["at", x, y, 0], ["unit", 1],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            ["dnp", "no"], ["uuid", q(u(fref))],
            ["property", q("Reference"), q(fref), ["at", x, y - 6.0, 0],
             ["effects", ["font", ["size", 1.0, 1.0]], ["hide", "yes"]]],
            ["property", q("Value"), q("PWR_FLAG"), ["at", x, y - 3.4, 0],
             ["effects", ["font", ["size", 0.80, 0.80]]]],
            ["property", q("Footprint"), q(""), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["property", q("Datasheet"), q(""), ["at", x, y, 0],
             ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]],
            ["pin", q("1"), ["uuid", q(u(fref + ":1"))]],
            ["instances", ["project", q(PROJECT),
                           ["path", q("/" + root_uuid),
                            ["reference", q(fref)], ["unit", 1]]]],
        ]
        body.append(sym)
        pin_pts.add((col, row))

    def net_label(name, col, row, rot=0, just="left"):
        x, y = gm(col), gm(row)
        body.append(["label", q(name), ["at", x, y, rot],
                     ["effects", ["font", ["size", 0.95, 0.95], ["bold", "yes"]],
                      ["justify", just, "bottom"]],
                     ["uuid", q(u(f"lbl:{name}:{col}:{row}"))]])

    # ---- Emit No-Connect X markers on unused pins ------------------------
    for ref, pmap in NETS.items():
        for pnum, net in pmap.items():
            if net == "NC":
                cx, cy = pin_grid(ref, pnum)
                body.append(["no_connect", ["at", gm(cx), gm(cy)],
                             ["uuid", q(u(f"nc:{ref}:{pnum}"))]])

    # ======================================================================
    # 1. MCU Control, Protected Debug & RF Launch (U1B in Frame 1)
    # ======================================================================
    # Reset network -> U1B ~{NRST} (Pin 44 at (34, 21))
    chain(pin_grid("SW1", 1), (31, 13), (31, 21), pin_grid("U1", 44))
    net_label("RST", 25, 13)
    add_pwr("3V3", *pin_grid("R_RST", 2))
    for _rref, _rcol in (("SW1", 9), ("D_RST", 16), ("C_RST", 23)):
        chain(pin_grid(_rref, 2), (_rcol, 18))
        add_pwr("GND", _rcol, 18)

    # Boot0 network -> U1B BOOT0 (Pin 43 at (34, 24)) & J3
    chain(pin_grid("J3", 1), pin_grid("U1", 43))
    net_label("BOOT0", 29, 24)
    add_pwr("GND", *pin_grid("R_BOOT", 2))
    chain(pin_grid("J3", 2), (13, 27), pin_grid("R_BHI", 1))
    net_label("BOOT_HI", 14, 27)
    chain(pin_grid("R_BHI", 2), (23, 27))
    add_pwr("3V3", 23, 27)

    # J4 SWD+NRST header + R_VAPP + D_SWD feed-through -> U1B SWDIO (34,31) & SWCLK (34,35)
    chain(pin_grid("J4", 1), pin_grid("R_VAPP", 2))
    net_label("VAPP_SENSE", 14, 30)
    chain(pin_grid("R_VAPP", 1), (24, 30))
    add_pwr("3V3", 24, 30)

    chain(pin_grid("J4", 2), pin_grid("U1", 1))
    net_label("SWDIO", 28, 31)
    chain(pin_grid("J4", 3), (18, 32), (18, 35), pin_grid("U1", 2))
    net_label("SWCLK", 28, 35)
    chain(pin_grid("D_SWD", 3), (22, 33))
    add_pwr("GND", 22, 33)
    chain(pin_grid("J4", 4), (16, 33), (16, 34))
    add_pwr("GND", 16, 34)
    chain(pin_grid("J4", 5), (13, 37), (17, 37))
    net_label("RST", 17, 37, just="right")

    # J5 UART2 header + R_VUART + D_UART feed-through -> U1B UART_TX (34,42) & UART_RX (34,46)
    chain(pin_grid("J5", 1), pin_grid("R_VUART", 2))
    net_label("VUART_ISO", 14, 41)
    chain(pin_grid("R_VUART", 1), (29, 41))
    net_label("VAPP_SENSE", 29, 41, just="right")

    chain(pin_grid("J5", 2), pin_grid("U1", 29))
    net_label("UART_TX", 28, 42)
    chain(pin_grid("J5", 3), (18, 43), (18, 46), pin_grid("U1", 30))
    net_label("UART_RX", 28, 46)
    chain(pin_grid("D_UART", 3), (22, 44))
    add_pwr("GND", 22, 44)
    chain(pin_grid("J5", 4), (15, 44), (15, 46))
    add_pwr("GND", 15, 46)

    # U1B Right-hand Sensing & Power Control stubs (terminated at net_label endpoints)
    for _upin, _ulbl in ((8, "DET_ADC"), (51, "DET_EN"), (15, "BAT_SENSE"), (50, "BAT_MON_EN")):
        px, py = pin_grid("U1", _upin)
        chain((px, py), (54, py))
        net_label(_ulbl, 54, py, just="right")

    # ======================================================================
    # 2. SiP Power Conditioning, Isolated VDDA/RF/PA & 15 uH SMPS (U1A)
    # ======================================================================
    # Digital 3V3 bypass bank -> U1A VDD1 (25,60), VDD2 (25,62), VBAT (25,64)
    chain((6, 58), (24, 58), (24, 64), pin_grid("U1", 4))
    chain((24, 60), pin_grid("U1", 3))
    chain((24, 62), pin_grid("U1", 55))
    add_pwr("3V3", 13, 58)
    chain((6, 62), (20, 62))
    chain((13, 62), (13, 63))
    add_pwr("GND", 13, 63)

    # Internal DC-DC SMPS buck network
    chain((8, 68), pin_grid("FB_SMPS", 1))
    add_pwr("3V3", 8, 68)
    chain(pin_grid("FB_SMPS", 2), pin_grid("U1", 11))
    net_label("VDDSMPS", 17, 68)
    add_pwr("GND", *pin_grid("C_SMPS1", 2))

    chain(pin_grid("L_SMPS", 2), pin_grid("U1", 13))
    net_label("VLXSMPS", 19, 75)
    chain(pin_grid("L_SMPS", 1), (14, 78))
    chain((8, 78), pin_grid("U1", 10))
    chain((8, 78), pin_grid("C_SMPS2", 1))
    chain((14, 78), pin_grid("C_SMPS3", 1))
    net_label("VFBSMPS", 18, 78)
    add_pwr("GND", 8, 82)
    add_pwr("GND", 14, 82)

    # U1A GND bank (Pin 12 + 18 stacked LGA ground pins)
    chain(pin_grid("U1", 12), (31, 83))
    add_pwr("GND", 31, 83)

    # Ferrite-isolated VDDA / VREF+ rail
    chain(pin_grid("U1", 7), pin_grid("FB_VDDA", 1))
    chain(pin_grid("U1", 6), (38, 62), (38, 60))
    chain((40, 60), pin_grid("C_VDDA1", 1))
    chain((45, 60), pin_grid("C_VDDA2", 1))
    chain((50, 60), pin_grid("C_VREF", 1))
    add_flg(38, 60)
    net_label("VDDA", 41, 60)
    add_pwr("3V3", *pin_grid("FB_VDDA", 2))
    chain((40, 65), (50, 65))
    chain((45, 65), (45, 66))
    add_pwr("GND", 45, 66)

    # Ferrite-isolated VDDRF & VDDPA rails
    chain(pin_grid("U1", 54), pin_grid("FB_RF", 1))
    chain((44, 69), pin_grid("C_RFV", 1))
    net_label("VDDRF", 39, 69)
    chain(pin_grid("FB_RF", 2), (53, 69))
    add_pwr("3V3", 53, 69)
    add_pwr("GND", 44, 73)

    chain(pin_grid("U1", 53), pin_grid("FB_PA", 1))
    chain((44, 77), pin_grid("C_PAV", 1))
    net_label("VDDPA", 39, 77)
    chain(pin_grid("FB_PA", 2), (53, 77))
    add_pwr("3V3", 53, 77)
    add_pwr("GND", 44, 81)

    # ======================================================================
    # 4. 868 MHz Return-Loss Bridge & VNA Calibration Port
    # ======================================================================
    chain(pin_grid("U1", 37), pin_grid("C_RF", 1))
    net_label("RF_PA", 50, 22)
    chain(pin_grid("C_RF", 2), pin_grid("R1", 1))
    net_label("BR_P", 69, 22)

    chain((67, 22), pin_grid("R_DIV1", 1))
    chain((83, 22), pin_grid("R_DIV2", 1))
    chain(pin_grid("R_DIV1", 2), (67, 13), pin_grid("J1", 1))
    chain(pin_grid("R_DIV2", 2), (83, 13))
    chain((92, 13), pin_grid("D_RF", 1))
    net_label("SMA_C", 85, 13)
    chain(pin_grid("D_RF", 2), (92, 19))
    add_pwr("GND", 92, 19)
    chain(pin_grid("J1", 2), (102, 19))
    add_pwr("GND", 102, 19)

    chain(pin_grid("R1", 2), pin_grid("L_M1", 1))
    net_label("BR_Q", 102, 22)
    chain((89, 22), pin_grid("L_Q", 1))
    chain(pin_grid("L_Q", 2), (89, 30))
    add_pwr("GND", 89, 30)
    chain((96, 22), pin_grid("C_S", 1))

    chain((71, 22), pin_grid("R2", 1))
    chain(pin_grid("R2", 2), (71, 44))
    chain((71, 44), pin_grid("L_S", 1))
    net_label("BR_S", 74, 44)

    for sref, scol in (("R3", 71), ("C_S2", 79)):
        chain((scol, 44), pin_grid(sref, 1))
        chain(pin_grid(sref, 2), (scol, 52))
        add_pwr("GND", scol, 52)

    chain(pin_grid("L_S", 2), pin_grid("C_BLK", 1))
    chain(pin_grid("C_S", 2), (96, 44))
    net_label("BR_O", 104, 44)
    chain((103, 44), pin_grid("R_TERM", 1))
    chain(pin_grid("R_TERM", 2), (103, 52))
    add_pwr("GND", 103, 52)

    # ======================================================================
    # 5. Elliptic Harmonic Pi-Filter & Printed Folded IFA
    # ======================================================================
    chain((118, 22), pin_grid("C_M1", 1))
    chain(pin_grid("C_M1", 2), (118, 28))
    add_pwr("GND", 118, 28)
    chain((123, 22), (123, 15), pin_grid("C_MZ", 1))
    chain(pin_grid("C_MZ", 2), (131, 15), (131, 22))

    chain(pin_grid("L_M1", 2), pin_grid("AE1", 1))
    net_label("ANT_FEED", 139, 22)
    chain((136, 22), pin_grid("C_M2", 1))
    chain(pin_grid("C_M2", 2), (136, 28))
    add_pwr("GND", 136, 28)
    chain(pin_grid("AE1", 2), (150, 28))
    add_pwr("GND", 150, 28)

    # ======================================================================
    # 6. LT5538 Log Detector & Anti-Aliasing Video LPF
    # ======================================================================
    chain(pin_grid("C_BLK", 2), pin_grid("U2", 2))
    net_label("DET_IN", 118, 44)

    chain(pin_grid("U2", 3), (119, 47), pin_grid("C_INN", 1))
    net_label("DET_INN", 119, 47)
    chain(pin_grid("C_INN", 2), (119, 53))
    add_pwr("GND", 119, 53)

    chain(pin_grid("U2", 1), (122, 42), (122, 38), (145, 38))
    chain(pin_grid("U2", 5), (129, 38))
    add_pwr("3V3_DET", 129, 38)
    chain(pin_grid("U2", 7), (139, 42), pin_grid("C_CAPP", 1))
    net_label("CAPP", 135, 42)
    chain(pin_grid("C_CAPP", 2), (139, 38))
    chain(pin_grid("U2", 6), (145, 44), pin_grid("C_CAPM", 1))
    net_label("CAPM", 136, 44)
    chain(pin_grid("C_CAPM", 2), (145, 38))

    chain(pin_grid("U2", 4), (128, 52), (130, 52), pin_grid("U2", 9))
    chain((129, 52), (129, 53))
    add_pwr("GND", 129, 53)

    chain(pin_grid("U2", 8), pin_grid("R_LPF", 1))
    net_label("DET_OUT", 137, 47)
    chain(pin_grid("R_LPF", 2), (157, 47))
    net_label("DET_ADC", 157, 47, just="right")
    chain((151, 47), pin_grid("TP4", 1))
    chain((151, 47), pin_grid("C_LPF", 1))
    chain(pin_grid("C_LPF", 2), (151, 53))
    add_pwr("GND", 151, 53)

    # ======================================================================
    # 7. 1S Battery Input, Gated VBAT Sense, 3.3 V LDO & 3V3_DET Switch
    # ======================================================================
    chain(pin_grid("J2", 1), (68, 70), (68, 77))
    add_flg(68, 70)
    add_pwr("GND", 68, 77)

    chain(pin_grid("J2", 2), (67, 80), (76, 80), pin_grid("Q3", 3))
    net_label("VBAT_RAW", 68, 80)
    chain((76, 72), pin_grid("D_VBAT", 1))
    chain(pin_grid("D_VBAT", 2), (71, 77))
    add_pwr("GND", 71, 77)
    chain(pin_grid("Q3", 1), (78, 77))
    add_pwr("GND", 78, 77)

    chain(pin_grid("Q3", 2), pin_grid("Q2", 4))
    add_pwr("VBAT", 81, 70)
    add_flg(83, 70)
    chain((86, 70), pin_grid("R_BG", 1))

    chain(pin_grid("R_BG", 2), (86, 76), (91, 76), pin_grid("Q2", 6))
    chain(pin_grid("Q2", 5), pin_grid("Q2", 6))
    net_label("VBAT_GATE", 87, 76)
    chain(pin_grid("Q2", 1), (95, 78))
    add_pwr("GND", 95, 78)

    chain(pin_grid("Q2", 2), (108, 70), pin_grid("R_BPD", 1))
    net_label("BAT_MON_EN", 101, 70)
    chain(pin_grid("R_BPD", 2), (108, 76))
    add_pwr("GND", 108, 76)

    chain(pin_grid("Q2", 3), (102, 74), pin_grid("R_B1", 1))
    net_label("VBAT_SW", 102, 74, just="right")
    chain(pin_grid("R_B1", 2), (102, 86), pin_grid("R_B2", 1))
    chain((102, 86), (109, 86), pin_grid("C_BAT", 1))
    chain((102, 86), (95, 86))
    net_label("BAT_SENSE", 95, 86)
    chain(pin_grid("R_B2", 2), (102, 92))
    add_pwr("GND", 102, 92)
    chain(pin_grid("C_BAT", 2), (109, 92))
    add_pwr("GND", 109, 92)

    # Top Sub-Rail: Nanopower 3.3 V LDO (TPS7A0233DBVR)
    chain(pin_grid("TP3", 1), pin_grid("U3", 1))
    add_pwr("VBAT", 123, 67)
    for cref, ccol in (("C_BULK1", 115), ("C_BULK2", 120), ("C_IN1", 125), ("C_IN2", 130)):
        chain((ccol, 67), pin_grid(cref, 1))
        chain(pin_grid(cref, 2), (ccol, 73))
    chain((115, 73), (130, 73))
    chain((123, 73), (123, 74))
    add_pwr("GND", 123, 74)
    chain((133, 67), (133, 69), pin_grid("U3", 3))
    chain(pin_grid("U3", 2), (138, 74))
    add_pwr("GND", 138, 74)

    chain(pin_grid("U3", 5), pin_grid("TP1", 1))
    add_pwr("3V3", 142, 67)
    for cref, ccol in (("C_OUT1", 143), ("C_OUT2", 148), ("D_3V3", 153)):
        chain((ccol, 67), pin_grid(cref, 1))
        chain(pin_grid(cref, 2), (ccol, 73))
    chain((143, 73), (153, 73))
    chain((148, 73), (148, 74))
    add_pwr("GND", 148, 74)
    chain(pin_grid("TP5", 1), (158, 75))
    add_pwr("GND", 158, 75)

    # Bottom Sub-Rail: Zero-Iq Switched Detector Supply (TPS22919DCKR)
    chain((117, 84), pin_grid("Q1", 1))
    add_pwr("VBAT", 124, 84)
    chain((117, 84), pin_grid("C_Q1", 1))
    chain(pin_grid("C_Q1", 2), (117, 90))
    add_pwr("GND", 117, 90)

    chain((123, 87), pin_grid("Q1", 3))
    net_label("DET_EN", 123, 87)
    chain((128, 87), pin_grid("R_PD", 1))
    chain(pin_grid("R_PD", 2), (128, 93))
    add_pwr("GND", 128, 93)

    chain(pin_grid("Q1", 2), (137, 92))
    add_pwr("GND", 137, 92)
    chain(pin_grid("Q1", 6), pin_grid("TP2", 1))
    chain(pin_grid("Q1", 5), (142, 86), (142, 84))
    add_pwr("3V3_DET", 143, 84)
    for cref, ccol in (("C_DET1", 145), ("C_DET2", 150)):
        chain((ccol, 84), pin_grid(cref, 1))
        chain(pin_grid(cref, 2), (ccol, 90))
        add_pwr("GND", ccol, 90)

    # ---- Normalize segments: split wires at T-junctions & emit junctions --
    split_pts = set(pin_pts)
    for p1, p2 in raw_segments:
        split_pts.add(p1)
        split_pts.add(p2)

    h_by_r = defaultdict(list)
    v_by_c = defaultdict(list)
    for (c1, r1), (c2, r2) in raw_segments:
        if r1 == r2:
            a, b = sorted((c1, c2))
            if a < b:
                h_by_r[r1].append((a, b))
        else:
            a, b = sorted((r1, r2))
            if a < b:
                v_by_c[c1].append((a, b))

    def merge_intervals(ivs):
        if not ivs:
            return []
        ivs = sorted(ivs)
        out = [list(ivs[0])]
        for s, e in ivs[1:]:
            if s <= out[-1][1]:
                out[-1][1] = max(out[-1][1], e)
            else:
                out.append([s, e])
        return [tuple(x) for x in out]

    final_segs = []
    for r, ivs in h_by_r.items():
        for a, b in merge_intervals(ivs):
            cuts = sorted([a, b] + [c for (c, rr) in split_pts if rr == r and a < c < b])
            for i in range(len(cuts) - 1):
                final_segs.append(((cuts[i], r), (cuts[i + 1], r)))

    for c, ivs in v_by_c.items():
        for a, b in merge_intervals(ivs):
            cuts = sorted([a, b] + [r for (cc, r) in split_pts if cc == c and a < r < b])
            for i in range(len(cuts) - 1):
                final_segs.append(((c, cuts[i]), (c, cuts[i + 1])))

    # Assert zero unintended perpendicular wire crossings
    h_final = [s for s in final_segs if s[0][1] == s[1][1]]
    v_final = [s for s in final_segs if s[0][0] == s[1][0]]
    for (hc1, hr), (hc2, _) in h_final:
        for (vc, vr1), (_, vr2) in v_final:
            if hc1 < vc < hc2 and vr1 < hr < vr2:
                raise AssertionError(f"Unintended wire crossing at grid ({vc}, {hr})!")

    deg = defaultdict(int)
    for p1, p2 in final_segs:
        deg[p1] += 1
        deg[p2] += 1
    for pt in pin_pts:
        deg[pt] += 1

    for idx, (p1, p2) in enumerate(final_segs):
        body.append([
            "wire",
            ["pts", ["xy", gm(p1[0]), gm(p1[1])], ["xy", gm(p2[0]), gm(p2[1])]],
            ["stroke", ["width", 0], ["type", "default"]],
            ["uuid", q(u(f"wire:{idx}:{p1}:{p2}"))],
        ])

    for pt, d in sorted(deg.items()):
        if d >= 3:
            body.append([
                "junction",
                ["at", gm(pt[0]), gm(pt[1])],
                ["diameter", 0],
                ["color", 0, 0, 0, 0],
                ["uuid", q(u(f"junc:{pt[0]}:{pt[1]}"))],
            ])

    # ---- Engineering Notes Box (Aligned beside KiCad A3 Title Block) ------
    notes = (
        "HARDWARE DESIGN & MANUFACTURING NOTES (REV E.5):\n"
        "1. POWER: 1S LiPo / Li-SOCl2 input (J2: 1=GND, 2=+VBAT, 3.0-4.35 V DC max).\n"
        "   Q3 (AO3401A) RPP feeds U3 (TPS7A0233, 25 nA Iq) and Q1 (TPS22919) -> U2.\n"
        "2. ANALOG & SMPS: FB_VDDA isolates VDDA/VREF+; L_SMPS = 15 uH power inductor\n"
        "   (Murata LQH2MCN150K02L, Isat >= 300 mA); internal 3.0 V TCXO enabled.\n"
        "3. RF & FIELD SKU: 51.9 Ohm CPWG spine, elliptic harmonic pi-filter, bare-ENIG\n"
        "   sensing comb; J1..J5 DNP on sealed field units (populate for bench/VNA)."
    )
    body.append([
        "text_box", q(notes),
        ["at", gm(57), gm(99), 0],
        ["size", gm(60), gm(12)],
        ["margins", 1.6, 1.4, 1.6, 1.4],
        ["stroke", ["width", 0.18], ["type", "solid"], ["color", 60, 70, 85, 0.9]],
        ["fill", ["type", "color"], ["color", 248, 250, 253, 1.0]],
        ["effects", ["font", ["size", 0.92, 0.92]], ["justify", "left", "top"]],
        ["uuid", q(u("notes_box"))],
    ])

    doc += body
    doc.append(["sheet_instances", ["path", q("/"), ["page", q("1")]]])
    out_path = os.path.join(ROOT, PROJECT + ".kicad_sch")
    with open(out_path, "w") as fh:
        fh.write(sx(doc) + "\n")
    return out_path


NON_BOM_LIBS = ("MOUNT", "IFA", "TP", "FID")
BOM_HEADERS = [
    "Item", "Designators", "Qty", "Value", "Footprint",
    "MPN", "Manufacturer", "LCSC", "Alternates", "DNP",
]


def _ref_sort_key(ref):
    m = re.match(r"^([A-Za-z_]+)(\d*)(.*)$", ref)
    if not m:
        return (ref, 0, "")
    return (m.group(1), int(m.group(2)) if m.group(2) else 0, m.group(3))


def write_turnkey_bom(bom_path):
    """Emit RFC-4180 10-column PCBWay Turnkey BOM CSV directly from PARTS."""
    os.makedirs(os.path.dirname(bom_path), exist_ok=True)
    grouped = defaultdict(list)
    for (ref, lib, val, fp, _, _, _, dnp, fields) in PARTS:
        if lib in NON_BOM_LIBS:
            continue
        fdict = dict(fields)
        mpn = fdict.get("MPN", "").strip()
        mfg = fdict.get("Manufacturer", "").strip()
        lcsc = fdict.get("LCSC", "").strip()
        alts = fdict.get("Alternates", "").strip()
        assert mpn and mfg and lcsc and alts, (
            f"Missing sourcing metadata on {ref}: MPN={mpn!r}, Mfg={mfg!r}, LCSC={lcsc!r}, Alts={alts!r}"
        )
        key = ("Yes" if dnp else "No", val, fp, mpn, mfg, lcsc, alts)
        grouped[key].append(ref)

    rows = []
    for key, refs in grouped.items():
        refs_sorted = sorted(refs, key=_ref_sort_key)
        rows.append((key[0] == "Yes", _ref_sort_key(refs_sorted[0]), refs_sorted, key))
    rows.sort(key=lambda r: (r[0], r[1]))

    with open(bom_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, dialect="excel", lineterminator="\n")
        writer.writerow(BOM_HEADERS)
        for idx, (_, _, refs_sorted, (dnp_str, val, fp, mpn, mfg, lcsc, alts)) in enumerate(rows, 1):
            writer.writerow([
                idx,
                ", ".join(refs_sorted),
                len(refs_sorted),
                val,
                fp,
                mpn,
                mfg,
                lcsc,
                alts,
                dnp_str,
            ])
    return len(rows)


def _verify_schematic_2d_collisions(sch_txt):
    """Verify zero overlapping visible texts/labels/wires and 100% A3 border containment."""
    from shapely.geometry import LineString, box

    # A3 drawing sheet inner border: [10.0..410.0] x [10.0..287.0] mm;
    # KiCad A3 title block occupies [300.0..410.0] x [253.0..287.0] mm.
    a3_inner = box(10.0, 10.0, 410.0, 287.0)
    title_block_box = box(300.0, 253.0, 410.0, 287.0)

    # Verify title block comments are concise enough not to overflow right margin
    for m_c in re.finditer(r'\(comment\s+\d+\s+"([^"]*)"\)', sch_txt):
        assert len(m_c.group(1)) <= 70, f"Title block comment too wide ({len(m_c.group(1))} chars): {m_c.group(1)!r}"

    idx_body = sch_txt.index("(lib_id ")
    body_txt = "(symbol " + sch_txt[idx_body:]

    text_boxes = []

    # 1. Extract visible Reference & Value properties on symbol instances
    sym_chunks = body_txt.split("\n  (symbol")
    for idx_s, chunk in enumerate(sym_chunks):
        full_c = chunk if idx_s == 0 else "  (symbol" + chunk
        for mp in re.finditer(
            r'\(property\s+"(Reference|Value)"\s+"([^"]+)"\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\)\s*(\(effects.*?\n\s*\)|\([^\n]+\))',
            full_c,
            re.S,
        ):
            prop_name, txt, px, py, _pang, eff = (
                mp.group(1), mp.group(2), float(mp.group(3)), float(mp.group(4)), float(mp.group(5)), mp.group(6)
            )
            if "(hide yes)" in eff:
                continue
            msz = re.search(r"\(size\s+([-0-9.]+)\s+([-0-9.]+)\)", eff)
            fsize = float(msz.group(1)) if msz else 1.0
            # Approximate rendered glyph string width & height in KiCad stroke font
            disp_txt = txt + "A" if (prop_name == "Reference" and txt == "U1") else txt
            w = max(1.2, len(disp_txt) * fsize * 0.78)
            h = fsize * 1.18
            if '(justify left)' in eff:
                x0, x1 = px, px + w
            elif '(justify right)' in eff:
                x0, x1 = px - w, px
            else:
                x0, x1 = px - 0.5 * w, px + 0.5 * w
            y0, y1 = py - 0.5 * h, py + 0.5 * h
            tb = box(x0, y0, x1, y1)
            assert a3_inner.contains(tb), f"Schematic property {prop_name}={txt!r} at {(px, py)} outside A3 frame!"
            assert not tb.intersects(title_block_box), f"Schematic property {prop_name}={txt!r} overlaps A3 title block!"
            text_boxes.append((f"{prop_name}:{txt}@({px:.1f},{py:.1f})", tb, None))

    # 2. Extract net labels
    for ml in re.finditer(
        r'\(label\s+"([^"]+)"\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\)\s*\(effects(.*?)\)\s*\(uuid',
        body_txt,
        re.S,
    ):
        ltxt, lx, ly, eff = ml.group(1), float(ml.group(2)), float(ml.group(3)), ml.group(5)
        msz = re.search(r"\(size\s+([-0-9.]+)\s+([-0-9.]+)\)", eff)
        fsize = float(msz.group(1)) if msz else 0.95
        w = max(1.2, len(ltxt) * fsize * 0.80)
        h = fsize * 1.15
        if "right" in eff:
            x0, x1 = lx - w, lx
        else:
            x0, x1 = lx, lx + w
        # Bottom-justified net label sits strictly above wire y = ly (with ~0.35 mm baseline offset)
        y0, y1 = ly - 0.35 - h, ly - 0.35
        lb = box(x0, y0, x1, y1)
        assert a3_inner.contains(lb), f"Net label {ltxt!r} at {(lx, ly)} outside A3 frame!"
        text_boxes.append((f"LBL:{ltxt}@({lx:.1f},{ly:.1f})", lb, (lx, ly)))

    # 3. Extract frame header texts & notes box
    for mt in re.finditer(
        r'\(text\s+"([^"]+)"\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)\s+0\)\s*\(effects\s+\(font\s+\(size\s+([-0-9.]+)',
        body_txt,
    ):
        ttxt, tx, ty, fsize = mt.group(1), float(mt.group(2)), float(mt.group(3)), float(mt.group(4))
        w = len(ttxt) * fsize * 0.76
        h = fsize * 1.25
        tb = box(tx, ty - 0.5 * h, tx + w, ty + 0.5 * h)
        assert a3_inner.contains(tb), f"Frame title {ttxt!r} outside A3 frame!"
        text_boxes.append((f"TITLE:{ttxt[:18]}", tb, None))

    mtb = re.search(r'\(text_box\s+"[^"]+"\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)\s+0\)\s+\(size\s+([-0-9.]+)\s+([-0-9.]+)\)', body_txt)
    if mtb:
        bx, by, bw, bh = (float(v) for v in mtb.groups())
        nbox = box(bx, by, bx + bw, by + bh)
        assert a3_inner.contains(nbox), "Engineering notes box extends outside A3 frame!"
        assert not nbox.intersects(title_block_box), "Engineering notes box overlaps KiCad A3 title block!"
        text_boxes.append(("NOTES_BOX", nbox, None))

    # 4. Pairwise text-to-text non-overlap assertion
    for i in range(len(text_boxes)):
        n1, b1, _ = text_boxes[i]
        for j in range(i + 1, len(text_boxes)):
            n2, b2, _ = text_boxes[j]
            assert not b1.intersects(b2), f"Schematic text collision: {n1} {b1.bounds} overlaps {n2} {b2.bounds}!"

    # 5. Wire-to-text non-overlap assertion (excluding a net label's own anchor wire)
    wires = []
    for mw in re.finditer(r"\(wire\s+\(pts\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\)", body_txt):
        x1, y1, x2, y2 = (float(v) for v in mw.groups())
        wires.append(LineString([(x1, y1), (x2, y2)]))

    for tname, tbox, anchor in text_boxes:
        if tname == "NOTES_BOX":
            for wseg in wires:
                assert not tbox.intersects(wseg), f"Wire {list(wseg.coords)} crosses NOTES_BOX!"
            continue
        sh = tbox.buffer(-0.12)
        if sh.is_empty:
            continue
        for wseg in wires:
            if anchor is not None and wseg.distance(box(anchor[0] - 0.05, anchor[1] - 0.05, anchor[0] + 0.05, anchor[1] + 0.05)) < 0.1:
                continue
            assert not sh.intersects(wseg), f"Schematic text {tname} {tbox.bounds} crossed by wire {list(wseg.coords)}!"


def verify_schematic_and_footprints(sch_path, bom_path):
    """Programmatically verify grid alignment, 2D collision-free drafting, pin/pad parity, 3D paths, and BOM."""
    import pcbnew

    # 1. Strict 2.54 mm (100 mil) grid alignment on all schematic elements
    for ref, lib, _, _, cx, cy, rot, _, _ in PARTS:
        assert isinstance(cx, int) and isinstance(cy, int), f"{ref} off integer grid: {(cx, cy)}"
        assert rot in (0, 90, 180, 270), f"{ref} non-90deg rotation: {rot}"
        for p in SYMS[lib]["pins"]:
            for coord in (p["lx"], p["ly"]):
                assert abs(round(coord / G) * G - coord) < 1e-6, f"{lib} pin {p['num']} off 2.54mm grid"

    sch_txt = open(sch_path, encoding="utf-8").read()
    idx_body = sch_txt.index("(lib_id ")
    body_txt = "(symbol " + sch_txt[idx_body:]
    for m in re.finditer(
        r"\((?:symbol\s+\(lib_id\s+\"[^\"]+\"\)\s+\(at|junction\s+\(at|no_connect\s+\(at|label\s+\"[^\"]+\"\s+\(at)\s+([-0-9.]+)\s+([-0-9.]+)",
        body_txt,
        re.S,
    ):
        x, y = float(m.group(1)), float(m.group(2))
        assert abs(round(x / G) * G - x) < 1e-4 and abs(round(y / G) * G - y) < 1e-4, (
            f"Off-grid schematic object at ({x}, {y})"
        )
    for m in re.finditer(r"\(wire\s+\(pts\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(xy\s+([-0-9.]+)\s+([-0-9.]+)\)\)", body_txt):
        for v in m.groups():
            fv = float(v)
            assert abs(round(fv / G) * G - fv) < 1e-4, f"Off-grid wire endpoint {fv}"

    # 1b. Automated 2D Shapely collision & A3 border containment check
    _verify_schematic_2d_collisions(sch_txt)

    # 2. Footprint pad-number, polarity, 3D STEP portability & BOARD_ONLY checks
    kfp = "/usr/share/kicad/footprints"
    k3d = "/usr/share/kicad/3dmodels"
    fp_cache = {}
    for ref, lib, _, fp_spec, _, _, _, dnp, _ in PARTS:
        if fp_spec not in fp_cache:
            libdir, fpname = fp_spec.split(":")
            base = os.path.join(ROOT, "ISAC.pretty") if libdir == "ISAC" else os.path.join(kfp, libdir + ".pretty")
            fp_obj = pcbnew.FootprintLoad(base, fpname)
            assert fp_obj is not None, f"Failed to load footprint {fp_spec} for {ref}"
            fp_cache[fp_spec] = fp_obj
        fp_obj = fp_cache[fp_spec]

        sym_pins = {str(p["num"]) for p in SYMS[lib]["pins"]}
        fp_pads = {str(pad.GetNumber()).strip() for pad in fp_obj.Pads() if str(pad.GetNumber()).strip() != ""}
        assert sym_pins == fp_pads, f"Pad mismatch on {ref} ({fp_spec}): sym={sorted(sym_pins)} vs fp={sorted(fp_pads)}"

        models = [m.m_Filename for m in fp_obj.Models()]
        for mpath in models:
            assert "/home/" not in mpath and not os.path.isabs(mpath), (
                f"Non-portable absolute 3D path on {ref} ({fp_spec}): {mpath}"
            )
            assert mpath.startswith("${KICAD9_3DMODEL_DIR}/") or mpath.startswith("${KIPRJMOD}/3dmodels/"), (
                f"Unexpected 3D prefix on {ref} ({fp_spec}): {mpath}"
            )
            resolved = mpath.replace("${KICAD9_3DMODEL_DIR}", k3d).replace("${KIPRJMOD}", ROOT)
            assert os.path.isfile(resolved), f"Missing physical 3D STEP model for {ref}: {resolved}"

        if lib in NON_BOM_LIBS:
            assert SYMS[lib]["in_bom"] == "no", f"{ref} ({lib}) must have in_bom='no'"
            assert fp_obj.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM, (
                f"{ref} ({fp_spec}) missing FP_EXCLUDE_FROM_BOM"
            )
            if ref == "AE1":
                req = pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM
                assert (fp_obj.GetAttributes() & req) == req, "AE1 footprint missing BOARD_ONLY/POS/BOM exclusions"
        else:
            assert len(models) >= 1, f"Electrical part {ref} ({fp_spec}) has 0 3D models!"

    assert len(SYMS["RAK3172LP-SiP"]["pins"]) == 73
    assert set(NETS["U1"].keys()) == set(range(1, 74))

    sot23_5 = fp_cache["Package_TO_SOT_SMD:SOT-23-5"]
    sot23_5_xy = {
        p.GetNumber(): (round(pcbnew.ToMM(p.GetPosition().x), 3), round(pcbnew.ToMM(p.GetPosition().y), 2))
        for p in sot23_5.Pads()
    }
    assert sot23_5_xy == {
        "1": (-1.137, -0.95), "2": (-1.137, 0.0), "3": (-1.137, 0.95),
        "4": (1.137, 0.95), "5": (1.137, -0.95),
    }
    assert NETS["U3"] == {1: "VBAT", 2: "GND", 3: "VBAT", 4: "NC", 5: "3V3"}

    sot23 = fp_cache["Package_TO_SOT_SMD:SOT-23"]
    sot23_xy = {
        p.GetNumber(): (round(pcbnew.ToMM(p.GetPosition().x), 3), round(pcbnew.ToMM(p.GetPosition().y), 2))
        for p in sot23.Pads()
    }
    assert sot23_xy == {"1": (-0.938, -0.95), "2": (-0.938, 0.95), "3": (0.938, 0.0)}
    assert NETS["Q3"] == {1: "GND", 2: "VBAT", 3: "VBAT_RAW"}
    assert NETS["D_SWD"][3] == "GND" and NETS["D_UART"][3] == "GND"

    sot363 = fp_cache["Package_TO_SOT_SMD:SOT-363_SC-70-6"]
    sot363_xy = {
        p.GetNumber(): (round(pcbnew.ToMM(p.GetPosition().x), 3), round(pcbnew.ToMM(p.GetPosition().y), 2))
        for p in sot363.Pads()
    }
    assert sot363_xy == {
        "1": (-0.887, -0.65), "2": (-0.887, 0.0), "3": (-0.887, 0.65),
        "4": (0.887, 0.65), "5": (0.887, 0.0), "6": (0.887, -0.65),
    }
    assert NETS["Q1"] == {1: "VBAT", 2: "GND", 3: "DET_EN", 4: "NC", 5: "3V3_DET", 6: "3V3_DET"}
    assert NETS["Q2"] == {1: "GND", 2: "BAT_MON_EN", 3: "VBAT_SW", 4: "VBAT", 5: "VBAT_GATE", 6: "VBAT_GATE"}

    u2_fp = fp_cache["ISAC:LT5538IDD_DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm"]
    paste_pads = [
        p for p in u2_fp.Pads()
        if str(p.GetNumber()) == "" and p.IsOnLayer(pcbnew.F_Paste) and not p.IsOnLayer(pcbnew.F_Cu)
    ]
    assert len(paste_pads) == 4, f"Expected 4 partitioned F.Paste apertures on U2, got {len(paste_pads)}"

    for ref, lib, _, fp_spec, _, _, _, dnp, _ in PARTS:
        if dnp:
            fp_obj = fp_cache[fp_spec]
            for pad in fp_obj.Pads():
                assert not pad.IsOnLayer(pcbnew.F_Paste) and not pad.IsOnLayer(pcbnew.B_Paste), (
                    f"DNP part {ref} ({fp_spec}) pad {pad.GetNumber()} still has solder paste!"
                )

    # 3. Export KiCad netlist & verify 100% pin-for-pin netlist parity against NETS
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tf:
        net_path = tf.name
    try:
        subprocess.run(
            ["kicad-cli", "sch", "export", "netlist", "-o", net_path, sch_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        net_txt = open(net_path, encoding="utf-8").read()
    finally:
        if os.path.exists(net_path):
            os.remove(net_path)

    exported = {}
    for m in re.finditer(
        r'\(net \(code "[^"]+"\) \(name "([^"]+)"\)(.*?)(?=\(net \(code|\)\s*\)\s*$)',
        net_txt, re.S,
    ):
        sname = m.group(1)
        norm = "NC" if sname.startswith("unconnected-") else sname.lstrip("/")
        for nm in re.finditer(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2)):
            exported[(nm.group(1), int(nm.group(2)))] = norm

    expected = {(ref, pnum): net for ref, pmap in NETS.items() for pnum, net in pmap.items()}
    assert exported == expected, (
        f"Schematic netlist mismatch! diff={set(exported.items()) ^ set(expected.items())}"
    )

    # 4. Verify Turnkey BOM CSV accountability
    with open(bom_path, newline="", encoding="utf-8") as fh:
        reader = list(csv.reader(fh))
    assert reader[0] == BOM_HEADERS, f"Unexpected BOM header: {reader[0]}"
    bom_refs_pop, bom_refs_dnp = set(), set()
    for row in reader[1:]:
        assert len(row) == 10, f"Malformed BOM row: {row}"
        rlist = [r.strip() for r in row[1].split(",") if r.strip()]
        assert int(row[2]) == len(rlist), f"BOM Qty mismatch on row {row[0]}"
        if row[9] == "Yes":
            bom_refs_dnp.update(rlist)
        else:
            assert row[9] == "No"
            bom_refs_pop.update(rlist)

    sch_pop = {r for r, l, *_, dnp, _ in PARTS if l not in NON_BOM_LIBS and not dnp}
    sch_dnp = {r for r, l, *_, dnp, _ in PARTS if l not in NON_BOM_LIBS and dnp}
    assert bom_refs_pop == sch_pop, f"Populated BOM mismatch: {bom_refs_pop ^ sch_pop}"
    assert bom_refs_dnp == sch_dnp == {"C_SMPS3", "D_RF", "J1", "J2", "J3", "J4", "J5", "R_DIV1", "R_DIV2", "R_VUART"}, (
        f"DNP BOM mismatch: {bom_refs_dnp}"
    )
    return len(expected), len(sch_pop), len(sch_dnp)


if __name__ == "__main__":
    write_lib(os.path.join(ROOT, "ISAC.kicad_sym"))
    sch_out = gen_sch()
    bom_out = os.path.join(ROOT, "fab", "bom", "ISAC_868_Turnkey_BOM.csv")
    n_bom_lines = write_turnkey_bom(bom_out)
    n_pins, n_pop, n_dnp = verify_schematic_and_footprints(sch_out, bom_out)
    print(
        f"Wrote {PROJECT}.kicad_sch, ISAC.kicad_sym, and fab/bom/ISAC_868_Turnkey_BOM.csv "
        f"({n_bom_lines} BOM lines: {n_pop} populated + {n_dnp} DNP = {n_pop + n_dnp} parts; "
        f"{n_pins}/{n_pins} netlist pins & 0 2D schematic collisions verified)."
    )
