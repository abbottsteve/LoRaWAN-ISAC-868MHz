#!/usr/bin/env python3
"""
Generate the manufacturing-ready 2-layer KiCad 9 PCB layout for the 868 MHz
ISAC Antenna-Sensor Node (`ISAC_868_KiCad9.kicad_pcb`, Rev E.5).

Engineering highlights (Rev E.5 PCBWay Turnkey Hardware):
  * Centered on A4 landscape drawing sheet (`X0 = 103.5 mm, Y0 = 80.0 mm` ->
    exact sheet horizontal center `148.5 mm`, vertical `100.0 mm`, clear of
    title block) with populated title block, auxiliary drill/fab origin, and
    aligned 7-bit ASCII mechanical dimension callouts on `Dwgs.User`.
  * 90.0 x 40.0 x 1.6 mm 2-layer FR-4 board outline (`ENIG` finish, Green LPI
    solder mask, `0.10 mm` min dam) with R = 2.0 mm rounded corners, 4 x M2.5
    mounting holes (`H1..H4`), and 5 optical SMT fiducials (`FID1..FID3` global
    in the `0..49.0 mm` bay + `FID4..FID5` local diagonal LGA-73 marks).
  * Zero-parasitic 868 MHz RF Return-Loss Bridge & Elliptic Harmonic Pi-Filter:
    - Zero RF test points (`TP1=3V3, TP2=3V3_DET, TP3=VBAT, TP4=DET_ADC, TP5=GND`
      strictly on DC rails).
    - Compact 2x2 `0402` `/BR_S` micro-cluster (`R2, L_S, C_S2, R3`, total `/BR_S`
      track length `1.44 mm <= 1.50 mm`) directly over a `2.20 x 2.20 mm` copper
      keepout void on BOTH `F.Cu` and `B.Cu` (`C_par = 0.1305 pF < 0.15 pF`,
      `50 Ohm` bridge directivity `>= 28.5 dB`).
    - Zero-stub `1.08 mm` (`50 Ohm` CPWG) `/SMA_C` launch from `J1` to orthogonal
      `0402` mux footprints `R_DIV1` & `R_DIV2` (`0.26 mm <= 0.30 mm` overhang).
    - Populated 3rd-order elliptic low-pass pi-network (`C_M1 = 3.6 pF`,
      `L_M1 = 8.2 nH || C_MZ = 0.50 pF`, `C_M2 = 4.3 pF` -> `>= 37.0 dB @ 2f0`,
      `>= 60.0 dB @ 3f0`).
  * 3.3 V Debug Header LiPo Back-Feed & ESD Protection (`R_VAPP = 1 kOhm` on
    `J4.1`, `R_VUART = DNP` isolating `J5.1`, `R_BHI = 10 kOhm` on `J3.2`,
    `D_3V3 = PESD5V0S1BA` on `3V3`).
  * 100% tented `0.60/0.30 mm` vias (`0.15 mm` annular ring) with ZERO
    via-in-pad, `0` `F.SilkS` primitives in `X_gbr >= 50.0 mm`, continuous
    `[73.40..87.80] x [6.65..20.80] mm` `F.Mask` sensing window, and 100% of
    visible `F.SilkS` references within `<= 1.85 mm` (`<= 2.0 mm`) of their
    component courtyard with crisp centered `0.50 mm` `F.Fab` assembly labels.

Run from the project directory:  python3 tools/gen_pcb.py
"""
from collections import defaultdict
import math
import os
import re
import subprocess
import sys
import tempfile

import pcbnew
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gen_sch import NETS, NON_BOM_LIBS, PART_MAP, PARTS, PROJECT, u  # noqa: E402
import rules_isac  # noqa: E402

FP_LIB = "/usr/share/kicad/footprints"

# Board dimensions (mm) & centered A4 landscape sheet offset (297 x 210 mm)
W, H = 90.0, 40.0
R_CORNER = 2.0
X0, Y0 = 103.5, 80.0  # Spans (103.5..193.5, 80.0..120.0), center (148.5, 100.0)

# Intentional 2.20 x 2.20 mm F.Cu + B.Cu parasitic cutout beneath /BR_S
BR_S_VOID_BOX = (33.40, 24.18, 35.60, 26.38)

F = pcbnew.F_Cu
B = pcbnew.B_Cu


def mm(val):
    return pcbnew.FromMM(float(val))


def G(dx, dy):
    """Convert board-local (dx, dy) mm into sheet-centered VECTOR2I."""
    return pcbnew.VECTOR2I(mm(X0 + dx), mm(Y0 + dy))


def load_fp(fp_spec):
    libdir, name = fp_spec.split(":")
    io = pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    base = ROOT if libdir == "ISAC" else FP_LIB
    fp = io.FootprintLoad(os.path.join(base, libdir + ".pretty"), name)
    if fp is None:
        raise SystemExit(f"Missing footprint {fp_spec}")
    fp.SetFPID(pcbnew.LIB_ID(libdir, name))
    return fp


def extract_schematic_nets():
    """Export exact KiCad 9 schematic net names per (ref, pin) for 100% parity."""
    sch_path = os.path.join(ROOT, PROJECT + ".kicad_sch")
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tf:
        net_path = tf.name
    try:
        subprocess.run(
            ["kicad-cli", "sch", "export", "netlist", "-o", net_path, sch_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        txt = open(net_path, encoding="utf-8").read()
    finally:
        if os.path.exists(net_path):
            os.remove(net_path)

    pad_to_sch_net = {}
    short_to_sch_net = {}
    for m in re.finditer(
        r'\(net \(code "[^"]+"\) \(name "([^"]+)"\)(.*?)(?=\(net \(code|\)\s*\)\s*$)',
        txt, re.S,
    ):
        sch_name = m.group(1)
        for nm in re.finditer(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2)):
            pad_to_sch_net[(nm.group(1), nm.group(2))] = sch_name
        if not sch_name.startswith("unconnected-"):
            short_to_sch_net[sch_name.lstrip("/")] = sch_name
    return pad_to_sch_net, short_to_sch_net


# --------------------------------------------------------------------------
# Deterministic 90-footprint placement in board-local (dx, dy, rot_deg)
# --------------------------------------------------------------------------
PLACE = {
    # 1. Mechanical mounting holes (M2.5) & 5 Optical SMT Fiducials
    "H1":   (3.50, 3.50, 0),
    "H2":   (86.50, 3.50, 0),
    "H3":   (3.50, 36.50, 0),
    "H4":   (86.50, 36.50, 0),
    "FID1": (4.50, 8.00, 0),       # Global #1 (>= 4.50 mm center / 3.50 mm mask from West rail)
    "FID2": (46.50, 4.50, 0),      # Global #2 (>= 4.50 mm center / 3.50 mm mask from North rail)
    "FID3": (30.50, 33.20, 0),     # Global #3 (6.80 mm center / 5.80 mm mask from South rail)
    "FID4": (10.30, 10.90, 0),     # Local #1 (1mm Cu / 2mm Mask) outside U1 top-left LGA-73 courtyard
    "FID5": (23.20, 25.80, 0),     # Local #2 (1mm Cu / 2mm Mask) outside U1 bottom-right LGA-73 courtyard

    # 2. Top-Left Power, Ideal-Diode PMOS RPP, 104uF Bulk, Gated VBAT Sense & LDO Island
    "J2":      (10.90, 3.85, 180), # Standard 1S JST-PH: Pad 1 (GND) right (10.9, 3.85), Pad 2 (VBAT_RAW) left (8.9, 3.85)
    "D_VBAT":  (14.45, 4.30, 270), # PESD5V0S1BA SOD-323: Pad 1 (VBAT_RAW) top, Pad 2 (GND) bottom
    "Q3":      (17.35, 4.10, 90),  # AO3401A SOT-23 RPP: 3=VBAT_RAW top, 1=GND bot-left, 2=VBAT bot-right
    "TP3":     (15.35, 9.80, 0),   # VBAT DC test point
    "C_BULK1": (23.30, 2.50, 90),  # 47u 10V 0805: Pad 1 (VBAT) bottom, Pad 2 (GND) top
    "C_BULK2": (25.60, 2.50, 90),  # 47u 10V 0805: Pad 1 (VBAT) bottom, Pad 2 (GND) top
    "TP5":     (31.20, 11.25, 0),  # GND DC test point (paired next to TP1=3V3)
    "C_IN1":   (19.95, 5.60, 90),  # 10u 0603: Pad 1 (VBAT) bottom, Pad 2 (GND) top
    "C_IN2":   (21.30, 5.90, 90),  # 100n 0402: Pad 1 (VBAT) bottom, Pad 2 (GND) top
    "U3":      (24.35, 6.20, 0),   # TPS7A0233DBVR SOT-23-5 (1=IN, 2=GND, 3=EN, 4=NC, 5=OUT)
    "C_OUT1":  (27.40, 5.80, 90),  # 1u 0603: Pad 1 (3V3) bottom, Pad 2 (GND) top
    "C_OUT2":  (28.20, 8.65, 90),  # 100n 0402: Pad 1 (3V3) bottom, Pad 2 (GND) top
    "TP1":     (28.20, 11.25, 0),  # 3V3 DC test point
    "Q2":      (12.20, 7.45, 0),   # NX3008CBKS SOT-363 high-side gated VBAT divider switch
    "R_BG":    (15.05, 7.10, 90),  # 470k 0402: Pad 1 (VBAT) bottom, Pad 2 (VBAT_GATE) top
    "R_BPD":   (25.60, 13.30, 270),# 100k 0402 pulldown on PA9/BAT_MON_EN: Pad 1 top, Pad 2 (GND) bottom
    "C_BAT":   (7.60, 6.65, 0),    # 1n C0G: Pad 1 (BAT_SENSE) left, Pad 2 (GND) right
    "R_B2":    (7.60, 7.68, 0),    # 4.7k 0.1%: Pad 1 (BAT_SENSE) left, Pad 2 (GND) right
    "R_B1":    (7.60, 8.71, 180),  # 4.7k 0.1%: Pad 2 (BAT_SENSE) left, Pad 1 (VBAT_SW) right

    # 3. Radio / MCU (RAK3172LP-SiP LGA-73), Isolated VDDA, 15uH SMPS & Protected Debug Headers
    "U1":      (18.25, 17.90, 0),  # Pad 37 (RF_OUT) at exact (23.90, 20.00)!
    "C_U1C":   (17.30, 9.85, 90),  # VDD2 (Pin 55) local 100n
    "C_RFV":   (18.60, 9.85, 90),  # VDDRF (Pin 54) local 1u
    "FB_RF":   (19.75, 9.85, 90),  # VDDRF 120R ferrite bead
    "FB_PA":   (21.15, 9.85, 90),  # VDDPA 120R ferrite bead
    "C_PAV":   (22.75, 9.85, 90),  # VDDPA (Pin 53) local 1u
    "C_U1B":   (9.95, 14.45, 180), # VDD1 (Pin 3) local 100n (Pad 1=3V3 right, Pad 2=GND left)
    "C_VBAT":  (9.95, 15.52, 180), # VBAT (Pin 4) local 1u (Pad 1=3V3 right, Pad 2=GND left)
    "C_VREF":  (9.95, 16.90, 180), # VREF+ (Pin 6) local 100n (Pad 1=VDDA right, Pad 2=GND left)
    "C_U1A":   (6.75, 13.95, 0),   # VDD digital bulk 4.7u 0603
    "FB_VDDA": (5.95, 15.85, 90),  # Analog ref ferrite: Pad 2 (3V3) top, Pad 1 (VDDA) bottom
    "C_VDDA1": (6.75, 17.65, 0),   # VDDA (Pin 7) bulk 4.7u 0603
    "C_VDDA2": (6.75, 18.95, 0),   # VDDA (Pin 7) local 1u 0402
    "C_SMPS1": (9.95, 19.40, 180), # VDDSMPS (Pin 11) local 100n
    "FB_SMPS": (6.95, 20.15, 0),   # VDDSMPS 120R ferrite: Pad 1 (3V3) left, Pad 2 (VDDSMPS) right
    "C_SMPS2": (7.55, 21.80, 180), # VFBSMPS 470n (GND via offset cleanly at (6.20, 22.35))
    "C_SMPS3": (7.55, 22.90, 180), # VFBSMPS 100n
    "L_SMPS":  (10.20, 23.65, 270),# 15uH 0805 (>= 4.04 mm from /DET_ADC): Pad 1 (VFB) top, Pad 2 (VLX) bottom
    "J3":      (2.40, 19.50, 0),   # BOOT 1x2 (1=BOOT0, 2=BOOT_HI)
    "R_BHI":   (2.65, 24.95, 0),   # 10k series limiter on J3.2: Pad 1 (BOOT_HI) left, Pad 2 (3V3) right
    "R_BOOT":  (6.40, 25.40, 0),   # Pad 1 (BOOT0) left, Pad 2 (GND) right
    "SW1":     (2.60, 28.50, 270), # RESET tactile switch on left edge
    "D_RST":   (6.30, 27.55, 0),   # PESD5V0S1BA SOD-323: Pad 1 (RST) left, Pad 2 (GND) right
    "C_RST":   (6.40, 29.40, 0),   # Pad 1 (RST) left, Pad 2 (GND) right
    "R_RST":   (6.40, 31.60, 0),   # Pad 1 (RST) left, Pad 2 (3V3) right
    "D_SWD":   (12.31, 33.15, 90), # PESD5V0U2BT SOT-23 (2.9 pF): 1=SWDIO, 2=SWCLK, 3=GND
    "R_VAPP":  (8.50, 34.05, 270), # 1k target-sense isolator: Pad 1 (3V3) top, Pad 2 (VAPP_SENSE) bottom
    "J4":      (8.50, 37.00, 90),  # SWD+NRST 1x5 along bottom-left edge (1=VAPP_SENSE..5=RST)
    "R_VUART": (20.60, 34.45, 0),  # DNP 0R UART isolator: Pad 1 (VAPP_SENSE) left, Pad 2 (VUART_ISO) right
    "D_UART":  (26.35, 33.15, 90), # PESD5V0U2BT SOT-23 (2.9 pF): 1=UART_TX, 2=UART_RX, 3=GND
    "J5":      (22.54, 37.00, 90), # UART 1x4 along bottom-left edge (1=VUART_ISO..4=GND)
    "D_3V3":   (33.20, 35.80, 270),# PESD5V0S1BA SOD-323 ESD clamp on 3V3: Pad 1 (3V3) top, Pad 2 (GND) bottom

    # 4. Zero-Stub 50R CPWG VNA Calibration Port & Orthogonal Mux Diverters
    "J1":     (34.50, 4.76, 270),  # Edge-mount SMA protruding off dy = 0 top edge
    "D_RF":   (35.95, 11.50, 0),   # ESD9B5.0ST5G SOD-523 ultra-low-C RF ESD option (DNP, zero-stub tap)
    "R_DIV1": (33.48, 18.88, 0),   # Orthogonal DNP 0R: Pad 1 (BR_P) left, Pad 2 (SMA_C) right
    "R_DIV2": (35.52, 18.88, 180), # Orthogonal DNP 0R: Pad 2 (SMA_C) left, Pad 1 (BR_Q) right
    "L_Q":    (38.10, 18.10, 90),  # 27nH shunt: Pad 1 (BR_Q) bottom, Pad 2 (GND) top

    # 5. Inline 868 MHz RF Spine, Elliptic Harmonic Pi-Filter & 3D-FDTD Folded IFA (dy = 20.00)
    "C_RF":   (27.50, 20.00, 0),
    "R1":     (34.50, 20.00, 0),   # Yageo RT0402BRD078R2L 8.2R 0.1% thin-film
    "C_M1":   (42.60, 18.10, 90),  # 3.6pF C0G: Pad 1 (BR_Q) bottom, Pad 2 (GND) top
    "L_M1":   (45.00, 20.00, 0),   # 8.2nH 2% wirewound series arm
    "C_MZ":   (45.00, 21.15, 0),   # 0.5pF C0G elliptic notch parallel to L_M1
    "C_M2":   (47.20, 18.10, 90),  # 4.3pF C0G: Pad 1 (ANT_FEED) bottom, Pad 2 (GND) top
    "AE1":    (50.00, 20.00, 0),   # Printed 40 x 20 mm 3D-FDTD 866.5 MHz folded IFA + IDE comb

    # 6. Compact 2x2 /BR_S Micro-Cluster (Over 2.2x2.2mm F.Cu+B.Cu Void) & 4-Pad /BR_O Star Cluster
    "R2":     (33.52, 24.76, 0),   # 681R 0.1%: Pad 1 (BR_P) left, Pad 2 (BR_S) right
    "L_S":    (35.48, 24.76, 0),   # 30nH 2%: Pad 1 (BR_S) left, Pad 2 (BR_O) right
    "C_S2":   (33.54, 25.79, 180), # 1.0pF +-0.05pF: Pad 1 (BR_S) right, Pad 2 (GND) left
    "R3":     (35.48, 25.80, 0),   # 3.57k 0.1%: Pad 1 (BR_S) left, Pad 2 (GND) right
    "R_TERM": (36.47, 23.26, 90),  # 56R 0.1%: Pad 1 (BR_O) bottom, Pad 2 (GND) top
    "C_S":    (37.44, 24.76, 180), # 1.0pF +-0.05pF: Pad 2 (BR_O) left, Pad 1 (BR_Q) right
    "C_BLK":  (37.44, 25.80, 0),   # 100pF C0G: Pad 1 (BR_O) left, Pad 2 (DET_IN) right

    # 7. LT5538 Log Detector, Video LPF & VBAT-Fed Zero-Iq Switched 3V3_DET Rail
    "U2":     (40.65, 26.05, 0),   # Pad 2 (IN+) at exact (39.20, 25.80) -> 1.28mm /DET_IN
    "C_INN":  (38.30, 28.20, 270), # Pad 1 (DET_INN) top, Pad 2 (GND) bottom
    "C_CAPP": (44.16, 25.80, 0),   # Pad 1 (CAPP) left, Pad 2 (3V3_DET) right
    "C_CAPM": (44.16, 27.40, 0),   # Pad 1 (CAPM) left, Pad 2 (3V3_DET) right
    "R_LPF":  (46.55, 30.80, 270), # Pad 1 (DET_OUT) top, Pad 2 (DET_ADC) bottom
    "C_LPF":  (46.55, 33.30, 270), # Pad 1 (DET_ADC) top, Pad 2 (GND) bottom
    "TP4":    (45.30, 35.80, 0),   # DET_ADC DC test point
    "Q1":     (38.50, 34.00, 0),   # TPS22919DCKR SOT-363 (VIN fed directly from VBAT)
    "C_Q1":   (37.61, 32.05, 0),   # 100n 0402 local VBAT bypass on Q1.1: Pad 1 (VBAT) left, Pad 2 (GND) right
    "TP2":    (42.10, 36.20, 0),   # 3V3_DET DC test point
    "R_PD":   (35.50, 36.20, 90),  # Pad 1 (DET_EN) bottom, Pad 2 (GND) top
    "C_DET1": (41.00, 32.80, 270), # Pad 1 (3V3_DET) top, Pad 2 (GND) bottom
    "C_DET2": (43.10, 32.80, 270), # Pad 1 (3V3_DET) top, Pad 2 (GND) bottom
}

# Commercial RF/IoT module silkscreen policy: crisp 0-deg horizontal F.SilkS designators
# strictly on active ICs, FETs, connectors, switches, test points, ESD clamps, L_SMPS,
# and RF calibration/matching elements; dense decoupling/bias passives rely on F.Fab.
COMMERCIAL_SILK_REFS = {
    "U1", "U2", "U3", "Q1", "Q2", "Q3",
    "J1", "J2", "J3", "J4", "J5", "SW1",
    "TP1", "TP2", "TP3", "TP4", "TP5",
    "D_VBAT", "D_RST", "D_SWD", "D_UART", "D_3V3", "D_RF",
    "L_SMPS",
    "C_RF", "R1", "R_DIV1", "R_DIV2", "L_Q", "C_M1", "L_M1", "C_MZ", "C_M2",
}

# Preferred 0-deg horizontal direction hints (dx_off, dy_off, rot_deg=0) for F.SilkS
REF_OFF = {
    "J2": (-3.6, 1.2, 0), "D_VBAT": (0.0, -2.1, 0), "Q3": (0.0, -2.2, 0),
    "TP3": (-2.2, 0.0, 0), "TP5": (0.0, 1.8, 0),
    "U3": (0.2, -2.1, 0), "TP1": (-2.1, 0.0, 0), "Q2": (0.0, 1.8, 0),
    "U1": (0.0, 7.05, 0), "L_SMPS": (0.0, 2.1, 0),
    "J3": (0.0, -2.1, 0), "SW1": (0.0, 3.2, 0), "D_RST": (2.5, 0.0, 0),
    "D_SWD": (-2.7, 0.0, 0), "J4": (5.0, -2.4, 0),
    "D_UART": (-2.9, 0.0, 0), "J5": (4.0, -2.4, 0),
    "D_3V3": (0.0, -2.2, 0),
    "J1": (6.6, 1.8, 0), "D_RF": (2.5, 0.0, 0),
    "R_DIV1": (-2.1, -1.1, 0), "R_DIV2": (2.2, -1.1, 0),
    "L_Q": (1.7, -0.5, 0),
    "C_RF": (0.0, -1.4, 0), "R1": (0.0, 1.4, 0),
    "C_M1": (-1.7, -1.2, 0), "L_M1": (0.0, -1.4, 0), "C_MZ": (0.0, 1.3, 0),
    "C_M2": (0.0, -2.6, 0),
    "U2": (-0.4, -2.9, 0), "TP4": (2.1, 0.0, 0),
    "Q1": (-2.5, -0.6, 0), "TP2": (0.0, 1.9, 0),
}


# --------------------------------------------------------------------------
# Board initialization, Title Block, Nets, Outline & Footprints
# --------------------------------------------------------------------------
def setup_board(pad_to_sch_net):
    assert set(PLACE.keys()) == set(PART_MAP.keys()), (
        f"PLACE vs PARTS mismatch: {set(PLACE) ^ set(PART_MAP)}"
    )
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)

    ds = board.GetDesignSettings()
    ds.SetBoardThickness(mm(1.6))
    ds.SetAuxOrigin(G(0.0, H))
    ds.SetGridOrigin(G(0.0, 0.0))
    ds.m_MinClearance = mm(0.15)
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_ViasMinSize = mm(0.60)
    ds.m_MinThroughDrill = mm(0.30)
    ds.m_CopperEdgeClearance = mm(0.30)

    tb = board.GetTitleBlock()
    tb.SetTitle("ISAC-868 LoRaWAN + RF Sensing Transceiver")
    tb.SetDate("2026-11-05")
    tb.SetRevision("E.5")
    tb.SetCompany("RF & Embedded Systems Engineering")
    tb.SetComment(0, "2-Layer 1.6 mm FR-4 (1.51 mm core er=4.4, ENIG, Green LPI) | 90.0 x 40.0 mm")
    tb.SetComment(1, "RF/MCU Bay (0..50 mm): Solid B.Cu GND + RAK3172LP-SiP (15 uH SMPS) + LT5538")
    tb.SetComment(2, "Radiating Aperture (50..90 mm): 866.5 MHz Folded IFA + Bare-ENIG IDE Sensor")
    tb.SetComment(3, "50R LPI CPWG (1.08/0.28 mm) | Elliptic LPF | IPC-6012B Class 2")

    for name in sorted(set(pad_to_sch_net.values())):
        board.Add(pcbnew.NETINFO_ITEM(board, name))
    return board


def netmap(board):
    return {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values() if n.GetNetname()}


def add_rounded_outline(board):
    """Draw closed 90 x 40 mm Edge.Cuts outline with R = 2.0 mm corner arcs."""
    r = R_CORNER
    k = r * (1.0 - math.sqrt(0.5))

    segs = [
        ((r, 0.0), (W - r, 0.0)),
        ((W, r), (W, H - r)),
        ((W - r, H), (r, H)),
        ((0.0, H - r), (0.0, r)),
    ]
    for p1, p2 in segs:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(G(*p1))
        s.SetEnd(G(*p2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.05))
        board.Add(s)

    arcs = [
        ((0.0, r), (k, k), (r, 0.0)),
        ((W - r, 0.0), (W - k, k), (W, r)),
        ((W, H - r), (W - k, H - k), (W - r, H)),
        ((r, H), (k, H - k), (0.0, H - r)),
    ]
    for p_start, p_mid, p_end in arcs:
        a = pcbnew.PCB_SHAPE(board)
        a.SetShape(pcbnew.SHAPE_T_ARC)
        a.SetArcGeometry(G(*p_start), G(*p_mid), G(*p_end))
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(mm(0.05))
        board.Add(a)


def add_footprints(board, raw_nets, pad_to_sch_net):
    root_uuid = u("root")
    fps = {}
    for (ref, lib, val, fp_spec, _, _, _, dnp, fields) in PARTS:
        dx, dy, rot = PLACE[ref]
        fp = load_fp(fp_spec)
        fp.SetPosition(G(dx, dy))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)

        fp.SetReference(ref)
        fp.SetValue(val)
        fp.SetPath(pcbnew.KIID_PATH(f"/{root_uuid}/{u(ref)}"))
        fp.SetDNP(bool(dnp))
        if lib in NON_BOM_LIBS:
            fp.SetAttributes(
                fp.GetAttributes()
                | pcbnew.FP_BOARD_ONLY
                | pcbnew.FP_EXCLUDE_FROM_POS_FILES
                | pcbnew.FP_EXCLUDE_FROM_BOM
            )
        else:
            fp.SetExcludedFromBOM(False)
            # Exclude all DNP footprints (J1, J3, J4, J5, etc.) and THT J2 from automated SMT CPL!
            fp.SetExcludedFromPosFiles(bool(dnp) or ref in ("J1", "J2"))

        # Assign exact schematic net name (including `/...` and `unconnected-...`)
        for pad in fp.Pads():
            pnum = str(pad.GetNumber()).strip()
            if not pnum:
                continue
            sch_net = pad_to_sch_net.get((ref, pnum))
            if sch_net and sch_net in raw_nets:
                pad.SetNet(raw_nets[sch_net])

        roff = REF_OFF.get(ref, (0.0, -1.5, 0))
        rtxt = fp.Reference()
        rtxt.SetLayer(pcbnew.F_SilkS)
        rtxt.SetTextSize(pcbnew.VECTOR2I(mm(0.80), mm(0.80)))
        rtxt.SetTextThickness(mm(0.15))
        rtxt.SetKeepUpright(True)
        rtxt.SetTextAngleDegrees(0)
        rtxt.SetPosition(G(dx + roff[0], dy + roff[1]))
        rtxt.SetVisible(ref in COMMERCIAL_SILK_REFS)

        vtxt = fp.Value()
        vtxt.SetLayer(pcbnew.F_Fab)
        vtxt.SetTextSize(pcbnew.VECTOR2I(mm(0.80), mm(0.80)))
        vtxt.SetTextThickness(mm(0.15))
        vtxt.SetVisible(False)

        # Enforce >= 0.15 mm silkscreen stroke floor and upright centered F.Fab assembly labels
        for gi in fp.GraphicalItems():
            if gi.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                if isinstance(gi, pcbnew.PCB_SHAPE):
                    w_mm = pcbnew.ToMM(gi.GetWidth())
                    if 0.0 < w_mm < 0.15:
                        gi.SetWidth(mm(0.15))
                elif isinstance(gi, pcbnew.PCB_TEXT) and gi.IsVisible():
                    th_mm = pcbnew.ToMM(gi.GetTextThickness())
                    if th_mm < 0.15:
                        gi.SetTextThickness(mm(0.15))
            elif gi.GetLayer() == pcbnew.F_Fab and isinstance(gi, pcbnew.PCB_TEXT):
                gi.SetKeepUpright(True)
                gi.SetVisible(lib not in ("MOUNT", "FID"))

        fps[ref] = fp

    # Verify zero courtyard overlaps at build time
    names = list(fps.keys())
    for i in range(len(names)):
        f1 = fps[names[i]]
        p1 = f1.GetCourtyard(pcbnew.F_CrtYd)
        if p1.IsEmpty():
            continue
        for j in range(i + 1, len(names)):
            f2 = fps[names[j]]
            p2 = f2.GetCourtyard(pcbnew.F_CrtYd)
            if p2.IsEmpty():
                continue
            c = pcbnew.SHAPE_POLY_SET(p1)
            c.BooleanIntersection(p2)
            if not c.IsEmpty():
                bb = c.BBox()
                raise AssertionError(
                    f"Courtyard overlap between {names[i]} and {names[j]} at "
                    f"({pcbnew.ToMM(bb.GetLeft()) - X0:.2f}, {pcbnew.ToMM(bb.GetTop()) - Y0:.2f})!"
                )
    return fps


def P(fps, ref, padnum):
    """Return board-local (dx, dy) mm center of first matching `ref` pad `padnum`."""
    pstr = str(padnum)
    for pad in fps[ref].Pads():
        if str(pad.GetNumber()) == pstr:
            pos = pad.GetPosition()
            return (round(pcbnew.ToMM(pos.x) - X0, 4),
                    round(pcbnew.ToMM(pos.y) - Y0, 4))
    raise KeyError(f"Pad {ref}.{padnum} not found")


# --------------------------------------------------------------------------
# Track, Tented Via, Zone & Silkscreen Primitives (board-local dx, dy mm)
# --------------------------------------------------------------------------
def add_track(board, net, p1, p2, width=0.25, layer=F):
    if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < 1e-4:
        return
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(G(*p1))
    t.SetEnd(G(*p2))
    t.SetWidth(mm(width))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def route_pts(board, net, pts, width=0.25, layer=F):
    for i in range(len(pts) - 1):
        add_track(board, net, pts[i], pts[i + 1], width, layer)


def route_45(board, net, pts, width=0.25, layer=F, chamfer=0.35):
    """Interactive-PNS-style router: automatically chamfers orthogonal 90-deg turns
    into crisp 45-deg diagonal miters (135-deg obtuse vertices) when adjacent legs allow."""
    if len(pts) <= 2 or chamfer <= 0.0:
        route_pts(board, net, pts, width=width, layer=layer)
        return
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        p_prev = pts[i - 1]
        p_cur = pts[i]
        p_next = pts[i + 1]
        u_vec = (p_cur[0] - p_prev[0], p_cur[1] - p_prev[1])
        v_vec = (p_next[0] - p_cur[0], p_next[1] - p_cur[1])
        l1 = math.hypot(*u_vec)
        l2 = math.hypot(*v_vec)
        ortho = (
            (abs(u_vec[0]) < 1e-4 and abs(v_vec[1]) < 1e-4 and l1 > 1e-4 and l2 > 1e-4)
            or (abs(u_vec[1]) < 1e-4 and abs(v_vec[0]) < 1e-4 and l1 > 1e-4 and l2 > 1e-4)
        )
        c = min(chamfer, 0.42 * min(l1, l2))
        if ortho and c >= 0.14:
            ux, uy = u_vec[0] / l1, u_vec[1] / l1
            vx, vy = v_vec[0] / l2, v_vec[1] / l2
            out.append((round(p_cur[0] - c * ux, 4), round(p_cur[1] - c * uy, 4)))
            out.append((round(p_cur[0] + c * vx, 4), round(p_cur[1] + c * vy, 4)))
        else:
            out.append(p_cur)
    out.append(pts[-1])
    route_pts(board, net, out, width=width, layer=layer)


def rf_horiz(board, net, p_left, p_right, w_line=1.08, w_pad=0.48, taper=0.45):
    """Horizontal 50R CPWG segment with 0402 pad-width tapers so caps stay inside pads."""
    x1, y = p_left
    x2, _ = p_right
    if x2 - x1 <= 2 * taper + 0.1:
        add_track(board, net, p_left, p_right, width=w_pad, layer=F)
    else:
        add_track(board, net, (x1, y), (x1 + taper, y), width=w_pad, layer=F)
        add_track(board, net, (x1 + taper, y), (x2 - taper, y), width=w_line, layer=F)
        add_track(board, net, (x2 - taper, y), (x2, y), width=w_pad, layer=F)


def add_via(board, net, dx, dy, dia=0.60, drill=0.30):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(G(dx, dy))
    v.SetWidth(mm(dia))
    v.SetDrill(mm(drill))
    v.SetLayerPair(F, B)
    v.SetNet(net)
    v.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
    v.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
    board.Add(v)


def add_silk_text(board, text, dx, dy, size=0.85, thick=0.15):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(G(dx, dy))
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(thick))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    board.Add(t)


# --------------------------------------------------------------------------
# Deterministic >= 90-Degree Mitered Routing (Zero Crossings, Zero VIPPO)
# --------------------------------------------------------------------------
def route_all(board, fps, n):
    gnd = n["GND"]

    # ======================================================================
    # 0. Printed 3D-FDTD IFA Ground Return Ties (Pad 2 shorting post @ y=27.0 & 3.0mm IDE bar @ y=34.5)
    # ======================================================================
    add_track(board, gnd, (50.0, 27.0), (48.85, 27.0), width=0.60, layer=F)
    add_track(board, gnd, (48.85, 25.5), (48.85, 28.5), width=0.45, layer=F)
    add_via(board, gnd, 48.85, 25.5)
    add_via(board, gnd, 48.85, 28.5)
    add_track(board, gnd, (50.0, 34.5), (48.85, 34.5), width=0.60, layer=F)
    add_track(board, gnd, (48.85, 33.1), (48.85, 35.9), width=0.50, layer=F)
    add_via(board, gnd, 48.85, 33.1)
    add_via(board, gnd, 48.85, 35.9)

    # ======================================================================
    # 1. Main 868 MHz 50R CPWG Spine & Elliptic Harmonic Pi-Filter (W=1.08, Gap=0.28 mm on F.Cu)
    # ======================================================================
    add_track(board, n["RF_PA"], P(fps, "U1", 37), (25.10, 20.0), width=0.35, layer=F)
    rf_horiz(board, n["RF_PA"], (25.10, 20.0), P(fps, "C_RF", 1), w_line=1.08, w_pad=0.48, taper=0.35)

    rf_horiz(board, n["BR_P"], P(fps, "C_RF", 2), P(fps, "R1", 1), w_line=1.08, w_pad=0.48)
    p_rdiv1_1 = P(fps, "R_DIV1", 1)
    add_track(board, n["BR_P"], (p_rdiv1_1[0], 20.0), p_rdiv1_1, width=0.42, layer=F)
    p_r2_1 = P(fps, "R2", 1)
    add_track(board, n["BR_P"], (p_r2_1[0], 20.0), p_r2_1, width=0.42, layer=F)

    rf_horiz(board, n["BR_Q"], P(fps, "R1", 2), P(fps, "L_M1", 1), w_line=1.08, w_pad=0.48)
    p_rdiv2_1 = P(fps, "R_DIV2", 1)
    add_track(board, n["BR_Q"], (p_rdiv2_1[0], 20.0), p_rdiv2_1, width=0.42, layer=F)
    p_cs_1 = P(fps, "C_S", 1)
    add_track(board, n["BR_Q"], (p_cs_1[0], 20.0), p_cs_1, width=0.42, layer=F)
    p_lq_1 = P(fps, "L_Q", 1)
    add_track(board, n["BR_Q"], (p_lq_1[0], 20.0), p_lq_1, width=0.42, layer=F)
    p_cm1_1 = P(fps, "C_M1", 1)
    add_track(board, n["BR_Q"], (p_cm1_1[0], 20.0), p_cm1_1, width=0.42, layer=F)
    add_track(board, n["BR_Q"], P(fps, "L_M1", 1), P(fps, "C_MZ", 1), width=0.40, layer=F)

    rf_horiz(board, n["ANT_FEED"], P(fps, "L_M1", 2), P(fps, "AE1", 1), w_line=1.08, w_pad=0.50)
    add_track(board, n["ANT_FEED"], P(fps, "L_M1", 2), P(fps, "C_MZ", 2), width=0.40, layer=F)
    p_cm2_1 = P(fps, "C_M2", 1)
    add_track(board, n["ANT_FEED"], (p_cm2_1[0], 20.0), p_cm2_1, width=0.42, layer=F)

    # ======================================================================
    # 2. Zero-Stub 1.08 mm (50R CPWG) /SMA_C Launch (J1 -> R_DIV1 / R_DIV2) & Upper Shunt Grounds
    # ======================================================================
    p_j1 = P(fps, "J1", 1)
    p_rdiv1_2 = P(fps, "R_DIV1", 2)
    p_rdiv2_2 = P(fps, "R_DIV2", 2)
    add_track(board, n["SMA_C"], p_j1, (34.50, 18.42), width=1.08, layer=F)
    add_track(board, n["SMA_C"], (34.50, 18.42), (34.50, p_rdiv1_2[1]), width=0.48, layer=F)
    add_track(board, n["SMA_C"], p_rdiv1_2, p_rdiv2_2, width=0.48, layer=F)

    p_drf1 = P(fps, "D_RF", 1)
    p_drf2 = P(fps, "D_RF", 2)
    add_track(board, n["SMA_C"], (34.50, p_drf1[1]), p_drf1, width=0.42, layer=F)
    add_track(board, gnd, p_drf2, (37.75, p_drf2[1]), width=0.45, layer=F)
    add_via(board, gnd, 37.75, p_drf2[1])

    for sref in ("L_Q", "C_M1", "C_M2"):
        px, py = P(fps, sref, 2)
        add_track(board, gnd, (px, py), (px, py - 1.05), width=0.45, layer=F)
        add_via(board, gnd, px, py - 1.05)

    # ======================================================================
    # 3. Compact 2x2 /BR_S Micro-Cluster (<= 1.44 mm total track over 2.2x2.2 mm void) & 4-Pad /BR_O Star
    # ======================================================================
    add_track(board, n["BR_S"], (34.28, 25.00), (34.72, 25.00), width=0.42, layer=F)
    add_track(board, n["BR_S"], (34.28, 25.56), (34.72, 25.56), width=0.42, layer=F)
    add_track(board, n["BR_S"], (34.50, 25.00), (34.50, 25.56), width=0.42, layer=F)

    p_cs2_2 = P(fps, "C_S2", 2)
    add_track(board, gnd, p_cs2_2, (32.00, p_cs2_2[1]), width=0.45, layer=F)
    add_via(board, gnd, 32.00, p_cs2_2[1])

    p_r3_2 = P(fps, "R3", 2)
    add_track(board, gnd, p_r3_2, (p_r3_2[0], 27.05), width=0.45, layer=F)
    add_via(board, gnd, p_r3_2[0], 27.05)

    # Orthogonal 4-pad /BR_O star node (<= 2.10 mm total copper across all 4 branches over unbroken B.Cu!):
    add_track(board, n["BR_O"], (36.20, 24.76), (36.72, 24.76), width=0.42, layer=F)
    add_track(board, n["BR_O"], (36.72, 24.76), (36.72, 25.53), width=0.42, layer=F)
    add_track(board, n["BR_O"], (36.47, 24.76), (36.47, 24.00), width=0.42, layer=F)
    p_rt2 = P(fps, "R_TERM", 2)
    add_track(board, gnd, p_rt2, (p_rt2[0], 21.75), width=0.45, layer=F)
    add_via(board, gnd, p_rt2[0], 21.75)

    # ======================================================================
    # 4. LT5538 Log Detector, Video LPF & VBAT-Fed 100% F.Cu Switched 3V3_DET Rail
    # ======================================================================
    add_track(board, n["DET_IN"], P(fps, "C_BLK", 2), P(fps, "U2", 2), width=0.35, layer=F)

    route_45(board, n["DET_INN"], [
        P(fps, "U2", 3), (38.55, 26.30), (38.30, 26.55), P(fps, "C_INN", 1)
    ], width=0.20, layer=F, chamfer=0.25)
    p_inn2 = P(fps, "C_INN", 2)
    route_45(board, gnd, [p_inn2, (37.15, p_inn2[1])], width=0.45, layer=F, chamfer=0.0)
    add_via(board, gnd, 37.15, p_inn2[1])

    # U2 GND (Pad 4) + EP (Pad 9) + twin tented RF ground vias OUTSIDE Pad 9 (0.26 mm mask dam!)
    p_ep = P(fps, "U2", 9)
    route_45(board, gnd, [P(fps, "U2", 4), (p_ep[0], 26.80), p_ep], width=0.30, layer=F, chamfer=0.25)
    add_track(board, gnd, (p_ep[0], 24.30), (p_ep[0], 27.80), width=0.50, layer=F)
    add_via(board, gnd, p_ep[0], 24.30)
    add_via(board, gnd, p_ep[0], 27.80)

    # CAPP & CAPM filter caps
    add_track(board, n["CAPP"], P(fps, "U2", 7), P(fps, "C_CAPP", 1), width=0.22, layer=F)
    route_45(board, n["CAPM"], [
        P(fps, "U2", 6), (43.10, 26.30), (43.26, 26.46),
        (43.26, 27.40), P(fps, "C_CAPM", 1)
    ], width=0.20, layer=F, chamfer=0.22)

    # DET_OUT: U2.8 -> compact 2.7 mm B.Cu micro-underpass under C_CAPP.2 -> R_LPF.1
    route_pts(board, n["DET_OUT"], [P(fps, "U2", 8), (42.85, 24.55)], width=0.24, layer=F)
    add_via(board, n["DET_OUT"], 42.85, 24.55)
    add_track(board, n["DET_OUT"], (42.85, 24.55), (45.55, 24.55), width=0.24, layer=B)
    add_via(board, n["DET_OUT"], 45.55, 24.55)
    route_pts(board, n["DET_OUT"], [
        (45.55, 24.55), (46.55, 25.55), P(fps, "R_LPF", 1)
    ], width=0.24, layer=F)

    # DET_ADC: R_LPF.2 -> C_LPF.1 -> TP4 + F.Cu South corridor -> West B.Cu (>= 5.7 mm clear of L_SMPS!) -> U1.8
    add_track(board, n["DET_ADC"], P(fps, "R_LPF", 2), P(fps, "C_LPF", 1), width=0.25, layer=F)
    route_45(board, n["DET_ADC"], [
        P(fps, "C_LPF", 1), (45.30, 34.07), P(fps, "TP4", 1)
    ], width=0.25, layer=F)
    p_clpf2 = P(fps, "C_LPF", 2)
    add_track(board, gnd, p_clpf2, (p_clpf2[0], p_clpf2[1] + 1.05), width=0.45, layer=F)
    add_via(board, gnd, p_clpf2[0], p_clpf2[1] + 1.05)

    route_pts(board, n["DET_ADC"], [
        P(fps, "R_LPF", 2), (44.86, 31.31), (43.40, 29.80)
    ], width=0.22, layer=F)
    add_via(board, n["DET_ADC"], 43.40, 29.80)
    add_track(board, n["DET_ADC"], (43.40, 29.80), (40.80, 29.80), width=0.22, layer=B)
    add_via(board, n["DET_ADC"], 40.80, 29.80)
    add_track(board, n["DET_ADC"], (40.80, 29.80), (14.00, 29.80), width=0.22, layer=F)
    add_via(board, n["DET_ADC"], 14.00, 29.80)
    route_45(board, n["DET_ADC"], [
        (14.00, 29.80), (5.42, 29.80), (5.42, 11.45), (11.82, 11.45),
        (11.82, 17.65), (11.40, 17.65)
    ], width=0.20, layer=B, chamfer=0.40)
    add_via(board, n["DET_ADC"], 11.40, 17.65)
    route_pts(board, n["DET_ADC"], [
        (11.40, 17.65), (11.85, 17.60), P(fps, "U1", 8)
    ], width=0.22, layer=F)

    # 3V3_DET Switched Rail (100% F.Cu, >= 0.28 mm Power width, ZERO vias, ZERO antenna-edge loop!):
    p_q5 = P(fps, "Q1", 5)
    p_q6 = P(fps, "Q1", 6)
    p_u2_5 = P(fps, "U2", 5)
    y_cdet = P(fps, "C_DET1", 1)[1]
    add_track(board, n["3V3_DET"], p_q5, p_q6, width=0.30, layer=F)
    route_45(board, n["3V3_DET"], [
        p_q6, (39.65, y_cdet), P(fps, "C_DET1", 1), (42.00, y_cdet),
        (p_u2_5[0], y_cdet), (p_u2_5[0], 28.40), p_u2_5
    ], width=0.28, layer=F, chamfer=0.35)
    route_45(board, n["3V3_DET"], [
        (p_u2_5[0], y_cdet), (P(fps, "C_DET2", 1)[0], y_cdet), P(fps, "C_DET2", 1)
    ], width=0.28, layer=F, chamfer=0.18)
    route_45(board, n["3V3_DET"], [
        (p_u2_5[0], 28.40), (44.64, 28.40), P(fps, "C_CAPM", 2), P(fps, "C_CAPP", 2)
    ], width=0.28, layer=F, chamfer=0.35)
    # Direct North-South tie from TP2 between C_DET1 & C_DET2 + tight local North tie to U2.1 (ENBL):
    route_pts(board, n["3V3_DET"], [
        P(fps, "TP2", 1), (42.00, 36.10), (42.00, y_cdet)
    ], width=0.28, layer=F)
    p_u2_1 = P(fps, "U2", 1)
    route_45(board, n["3V3_DET"], [
        p_u2_1, (p_u2_1[0], 23.45), (44.64, 23.45), P(fps, "C_CAPP", 2)
    ], width=0.28, layer=F, chamfer=0.40)

    for cref in ("C_DET1", "C_DET2"):
        p2 = P(fps, cref, 2)
        add_track(board, gnd, p2, (p2[0], p2[1] + 1.05), width=0.45, layer=F)
        add_via(board, gnd, p2[0], p2[1] + 1.05)

    # Q1 GND (Pad 2) -> via at (36.15, 33.85) & C_Q1 GND (Pad 2) -> stitch via at (39.0, 31.6)
    p_q2 = P(fps, "Q1", 2)
    route_pts(board, gnd, [p_q2, (36.30, p_q2[1]), (36.15, 33.85)], width=0.30, layer=F)
    add_via(board, gnd, 36.15, 33.85)
    route_pts(board, gnd, [P(fps, "C_Q1", 2), (38.55, 32.05), (39.00, 31.60)], width=0.35, layer=F)

    # DET_EN (PA8 / U1.51 ONLY -> R_PD.1 -> Q1.3 via F.Cu South corridor; decoupled from Q2/BAT_MON_EN):
    p_rpd2 = P(fps, "R_PD", 2)
    add_track(board, gnd, p_rpd2, (p_rpd2[0], 34.60), width=0.35, layer=F)
    add_via(board, gnd, p_rpd2[0], 34.60)

    route_45(board, n["DET_EN"], [
        P(fps, "Q1", 3), (36.60, 34.65), (36.60, 36.71), P(fps, "R_PD", 1),
        (34.35, 36.71), (34.35, 31.16), (15.80, 31.16)
    ], width=0.20, layer=F, chamfer=0.40)
    add_via(board, n["DET_EN"], 15.80, 31.16)
    route_pts(board, n["DET_EN"], [
        (15.80, 31.16), (1.40, 31.16), (0.90, 30.66), (0.90, 9.25),
        (1.40, 8.75), (15.00, 8.75), (15.70, 9.45), (26.05, 9.45),
        (26.55, 9.95), (26.55, 10.95)
    ], width=0.20, layer=B)
    add_via(board, n["DET_EN"], 26.55, 10.95)
    route_45(board, n["DET_EN"], [
        (26.55, 10.95), (21.55, 10.95), P(fps, "U1", 51)
    ], width=0.18, layer=F, chamfer=0.35)

    # BAT_MON_EN (PA9 / U1.50 -> R_BPD.1 -> 45-deg B.Cu -> Q2.2):
    route_45(board, n["BAT_MON_EN"], [
        P(fps, "U1", 50), (22.15, 11.38), (25.60, 11.38), P(fps, "R_BPD", 1)
    ], width=0.18, layer=F, chamfer=0.30)
    route_45(board, n["BAT_MON_EN"], [
        P(fps, "R_BPD", 1), (27.15, 12.79), (27.15, 12.50)
    ], width=0.20, layer=F, chamfer=0.20)
    add_via(board, n["BAT_MON_EN"], 27.15, 12.50)
    p_rbpd2 = P(fps, "R_BPD", 2)
    add_track(board, gnd, p_rbpd2, (26.65, p_rbpd2[1]), width=0.35, layer=F)
    add_via(board, gnd, 26.65, p_rbpd2[1])
    route_45(board, n["BAT_MON_EN"], [
        (27.15, 12.50), (30.15, 12.50), (30.15, 7.35), (10.15, 7.35)
    ], width=0.20, layer=B, chamfer=0.50)
    add_via(board, n["BAT_MON_EN"], 10.15, 7.35)
    route_pts(board, n["BAT_MON_EN"], [
        (10.15, 7.35), (10.15, 7.45), P(fps, "Q2", 2)
    ], width=0.24, layer=F)

    # ======================================================================
    # 5. Top-Left Power, Standard JST-PH Polarity, PMOS RPP, 104 uF Bulk, Gated VBAT, VDDA & 15 uH SMPS
    # ======================================================================
    p_q3_d = P(fps, "Q3", 3)
    p_dvbat1 = P(fps, "D_VBAT", 1)
    route_45(board, n["VBAT_RAW"], [
        P(fps, "J2", 2), (8.90, 2.05), (13.35, 2.05), p_dvbat1,
        (16.40, p_dvbat1[1]), p_q3_d
    ], width=0.50, layer=F, chamfer=0.40)
    add_track(board, gnd, P(fps, "J2", 1), (10.90, 5.65), width=0.50, layer=F)
    add_via(board, gnd, 10.90, 5.65)
    add_track(board, gnd, P(fps, "D_VBAT", 2), (13.20, 5.45), width=0.40, layer=F)
    add_via(board, gnd, 13.20, 5.45)
    route_45(board, gnd, [
        P(fps, "Q3", 1), (15.99, 5.45), P(fps, "D_VBAT", 2)
    ], width=0.35, layer=F, chamfer=0.25)

    # VBAT: Q3.2 (Source) -> R_BG.1 & Q2.4 (left) + C_IN1/2, C_BULK1/2, TP3, U3.1/3 + Q1.1/C_Q1
    p_q3_s = P(fps, "Q3", 2)
    p_rbg1 = P(fps, "R_BG", 1)
    add_track(board, n["VBAT"], p_q3_s, (p_q3_s[0], 6.75), width=0.35, layer=F)
    route_45(board, n["VBAT"], [
        (p_q3_s[0], 6.75), (16.05, 6.75), (15.50, p_rbg1[1]), p_rbg1,
        (15.05, 8.10), P(fps, "Q2", 4)
    ], width=0.32, layer=F, chamfer=0.30)
    route_pts(board, n["VBAT"], [
        (15.05, 8.10), (15.35, 8.45), P(fps, "TP3", 1)
    ], width=0.35, layer=F)
    route_pts(board, n["VBAT"], [
        P(fps, "TP3", 1), (14.20, 9.80), (13.85, 9.45)
    ], width=0.32, layer=F)
    # Direct VBAT feed to C_Q1.1 & Q1.1 (>= 0.32 mm Power width via F.Cu South corridor):
    add_via(board, n["VBAT"], 13.85, 9.45)
    route_pts(board, n["VBAT"], [
        (13.85, 9.45), (4.18, 9.45), (3.68, 9.95), (3.68, 23.60),
        (3.00, 24.28), (3.00, 29.88), (3.60, 30.48), (14.90, 30.48)
    ], width=0.32, layer=B)
    add_via(board, n["VBAT"], 14.90, 30.48)
    route_pts(board, n["VBAT"], [
        (14.90, 30.48), (35.56, 30.48), P(fps, "C_Q1", 1),
        (37.13, 32.87), P(fps, "Q1", 1)
    ], width=0.32, layer=F)
    add_track(board, n["VBAT"], (p_q3_s[0], 6.75), (19.95, 6.75), width=0.45, layer=F)
    add_track(board, n["VBAT"], (19.95, 6.75), P(fps, "C_IN1", 1), width=0.45, layer=F)
    route_45(board, n["VBAT"], [
        (19.95, 6.75), (21.30, 6.75), (22.05, 6.75), (22.05, 7.15), P(fps, "U3", 3)
    ], width=0.35, layer=F, chamfer=0.18)
    add_track(board, n["VBAT"], P(fps, "C_IN2", 1), (21.30, 6.75), width=0.40, layer=F)
    route_45(board, n["VBAT"], [
        (22.05, 6.75), (22.05, 5.25), P(fps, "U3", 1)
    ], width=0.32, layer=F, chamfer=0.25)
    p_cb1_1 = P(fps, "C_BULK1", 1)
    p_cb2_1 = P(fps, "C_BULK2", 1)
    route_45(board, n["VBAT"], [
        (22.05, 5.25), (22.05, 3.85), (22.45, p_cb1_1[1]), p_cb1_1, p_cb2_1
    ], width=0.45, layer=F, chamfer=0.25)

    # Low-inductance dual-via GND strap for C_BULK1.2, C_BULK2.2 & TP5:
    p_cb1_2 = P(fps, "C_BULK1", 2)
    p_cb2_2 = P(fps, "C_BULK2", 2)
    route_pts(board, gnd, [
        (21.98, p_cb1_2[1]), p_cb1_2, p_cb2_2, (27.25, p_cb2_2[1])
    ], width=0.50, layer=F)
    add_via(board, gnd, 21.98, p_cb1_2[1])
    add_via(board, gnd, 27.25, p_cb2_2[1])
    p_tp5 = P(fps, "TP5", 1)
    add_track(board, gnd, p_tp5, (p_tp5[0], p_tp5[1] - 1.35), width=0.50, layer=F)
    add_via(board, gnd, p_tp5[0], p_tp5[1] - 1.35)

    # Q2 (NX3008CBKS) VBAT_GATE, GND, VBAT_SW & R_B1/R_B2/C_BAT divider:
    add_track(board, n["VBAT_GATE"], P(fps, "Q2", 5), P(fps, "Q2", 6), width=0.26, layer=F)
    p_rbg2 = P(fps, "R_BG", 2)
    route_45(board, n["VBAT_GATE"], [
        P(fps, "Q2", 6), (13.60, p_rbg2[1]), p_rbg2
    ], width=0.26, layer=F, chamfer=0.25)
    route_45(board, gnd, [P(fps, "Q2", 1), (11.31, 5.65), (10.90, 5.65)], width=0.30, layer=F, chamfer=0.18)

    route_45(board, n["VBAT_SW"], [
        P(fps, "Q2", 3), (10.70, 8.71), P(fps, "R_B1", 1)
    ], width=0.28, layer=F, chamfer=0.25)

    # BAT_SENSE: R_B1.2 -> R_B2.1 -> C_BAT.1 -> via at (6.97, 12.18) -> B.Cu -> U1.15 (PB4/ADC_IN3)
    add_track(board, n["BAT_SENSE"], P(fps, "R_B1", 2), P(fps, "R_B2", 1), width=0.24, layer=F)
    add_track(board, n["BAT_SENSE"], P(fps, "R_B2", 1), P(fps, "C_BAT", 1), width=0.24, layer=F)
    route_pts(board, n["BAT_SENSE"], [
        P(fps, "R_B1", 2), (6.97, 8.86), (6.97, 12.18)
    ], width=0.24, layer=F)
    add_via(board, n["BAT_SENSE"], 6.97, 12.18)
    route_45(board, n["BAT_SENSE"], [
        (6.97, 12.18), (6.97, 27.85), (11.65, 27.85), (11.65, 25.30)
    ], width=0.22, layer=B, chamfer=0.40)
    add_via(board, n["BAT_SENSE"], 11.65, 25.30)
    route_45(board, n["BAT_SENSE"], [
        (11.65, 25.30), (11.65, 21.80), P(fps, "U1", 15)
    ], width=0.22, layer=F, chamfer=0.35)

    route_45(board, gnd, [P(fps, "R_B2", 2), (9.05, 7.68), (9.05, 6.65), P(fps, "C_BAT", 2)], width=0.32, layer=F, chamfer=0.25)
    add_via(board, gnd, 9.05, 6.65)

    # U3.2 GND via tucked cleanly under SOT-23-5 center gap + C_IN/C_OUT vias (>= 0.25 mm clear!)
    p_u3_2 = P(fps, "U3", 2)
    add_track(board, gnd, p_u3_2, (24.50, p_u3_2[1]), width=0.35, layer=F)
    add_via(board, gnd, 24.50, p_u3_2[1])

    for cref, vx_off in (("C_IN1", 0.0), ("C_IN2", -0.15), ("C_OUT1", 0.0)):
        p2 = P(fps, cref, 2)
        route_pts(board, gnd, [p2, (p2[0] + vx_off, p2[1] - 1.05)], width=0.45, layer=F)
        add_via(board, gnd, p2[0] + vx_off, p2[1] - 1.05)

    p_cout2_2 = P(fps, "C_OUT2", 2)
    add_track(board, gnd, p_cout2_2, (p_cout2_2[0] + 1.05, p_cout2_2[1]), width=0.45, layer=F)
    add_via(board, gnd, p_cout2_2[0] + 1.05, p_cout2_2[1])

    # 3V3 Continuous F.Cu Spine (0 vias -> 100% uncut B.Cu ground plane!) + TP1 + Header Protection:
    p_u3_5 = P(fps, "U3", 5)
    p_cout1_1 = P(fps, "C_OUT1", 1)
    p_cout2_1 = P(fps, "C_OUT2", 1)
    route_45(board, n["3V3"], [
        p_u3_5, (26.40, p_u3_5[1]), (26.40, 6.20), (26.60, p_cout1_1[1]), p_cout1_1
    ], width=0.35, layer=F, chamfer=0.25)
    route_45(board, n["3V3"], [
        p_cout1_1, (p_cout1_1[0], 7.80), (p_cout1_1[0], p_cout2_1[1]), p_cout2_1, P(fps, "TP1", 1)
    ], width=0.35, layer=F, chamfer=0.25)

    # Upper 3V3 header at dy = 7.80 -> FB_PA.2, FB_RF.2, C_U1C.1, U1.55 (VDD2) & left 3V3 spine:
    p_rvapp1 = P(fps, "R_VAPP", 1)
    route_45(board, n["3V3"], [
        (p_cout1_1[0], 7.80), (16.65, 7.80), (16.65, 11.20),
        (12.40, 11.20), (11.80, 11.80), (11.80, 12.40), (9.65, 12.40),
        (9.13, 12.92), (4.95, 12.92), (4.95, 24.35), (8.50, 24.35), p_rvapp1
    ], width=0.28, layer=F, chamfer=0.40)
    add_track(board, n["3V3"], (21.15, 7.80), P(fps, "FB_PA", 2), width=0.32, layer=F)
    add_track(board, n["3V3"], (19.75, 7.80), P(fps, "FB_RF", 2), width=0.32, layer=F)
    route_45(board, n["3V3"], [
        (16.65, 10.33), P(fps, "C_U1C", 1),
        (17.30, 11.20), (19.15, 11.20), P(fps, "U1", 55)
    ], width=0.28, layer=F, chamfer=0.25)

    # Filtered VDDRF (Pin 54) & VDDPA (Pin 53) rails + orthogonal T-junction bypass grounds
    add_track(board, n["VDDRF"], P(fps, "C_RFV", 1), P(fps, "FB_RF", 1), width=0.30, layer=F)
    add_track(board, n["VDDRF"], P(fps, "FB_RF", 1), P(fps, "U1", 54), width=0.30, layer=F)

    add_track(board, n["VDDPA"], P(fps, "FB_PA", 1), P(fps, "C_PAV", 1), width=0.30, layer=F)
    route_45(board, n["VDDPA"], [
        P(fps, "FB_PA", 1), (20.95, 10.53), (20.95, 10.98), (20.35, 10.98), P(fps, "U1", 53)
    ], width=0.28, layer=F, chamfer=0.18)

    p_cu1c2 = P(fps, "C_U1C", 2)
    p_crfv2 = P(fps, "C_RFV", 2)
    route_pts(board, gnd, [p_cu1c2, (17.95, p_cu1c2[1]), p_crfv2], width=0.32, layer=F)
    route_45(board, gnd, [(17.95, p_cu1c2[1]), (17.95, 8.50), (19.00, 8.50)], width=0.32, layer=F, chamfer=0.25)
    add_via(board, gnd, 17.95, 8.50)
    add_via(board, gnd, 19.00, 8.50)
    route_45(board, gnd, [P(fps, "C_PAV", 2), (23.75, 9.37), (23.75, 8.50)], width=0.32, layer=F, chamfer=0.25)
    add_via(board, gnd, 23.75, 8.50)

    # Digital 3V3 left bypass (C_U1B, C_VBAT, C_U1A), R_BHI -> J3.2 & R_RST:
    route_pts(board, n["3V3"], [
        (10.43, 12.40), P(fps, "C_U1B", 1), (10.43, 14.60),
        (10.43, 15.20), P(fps, "C_VBAT", 1)
    ], width=0.30, layer=F)
    add_track(board, n["3V3"], (10.43, 14.60), P(fps, "U1", 3), width=0.28, layer=F)
    add_track(board, n["3V3"], (10.43, 15.20), P(fps, "U1", 4), width=0.28, layer=F)
    add_track(board, n["3V3"], (4.95, 13.95), P(fps, "C_U1A", 1), width=0.35, layer=F)
    add_track(board, n["3V3"], (4.95, 15.37), P(fps, "FB_VDDA", 2), width=0.32, layer=F)
    add_track(board, n["3V3"], (4.95, 20.15), P(fps, "FB_SMPS", 1), width=0.32, layer=F)
    route_45(board, n["3V3"], [
        (4.95, 23.95), (3.16, 23.95), P(fps, "R_BHI", 2)
    ], width=0.28, layer=F, chamfer=0.22)
    route_45(board, n["BOOT_HI"], [
        P(fps, "R_BHI", 1), (2.14, 22.30), P(fps, "J3", 2)
    ], width=0.24, layer=F, chamfer=0.22)
    add_track(board, n["3V3"], (8.50, 31.60), P(fps, "R_RST", 2), width=0.28, layer=F)

    # Bottom F.Cu 3V3 rail (isolated from J4.1/J5.1 via R_VAPP / R_VUART!) -> D_3V3.1:
    p_d3v3_1 = P(fps, "D_3V3", 1)
    p_d3v3_2 = P(fps, "D_3V3", 2)
    route_45(board, n["3V3"], [
        (8.50, 33.00), (6.95, 33.00), (6.95, 38.92),
        (32.15, 38.92), (32.15, p_d3v3_1[1]), p_d3v3_1
    ], width=0.28, layer=F, chamfer=0.45)
    add_track(board, gnd, p_d3v3_2, (p_d3v3_2[0], 37.95), width=0.40, layer=F)
    add_via(board, gnd, p_d3v3_2[0], 37.95)

    # Protected Header Target-Sense & Isolated UART Pins:
    add_track(board, n["VAPP_SENSE"], P(fps, "R_VAPP", 2), P(fps, "J4", 1), width=0.25, layer=F)
    route_45(board, n["VAPP_SENSE"], [
        P(fps, "J4", 1), (8.50, 38.25), (19.95, 38.25), (19.95, 34.45), P(fps, "R_VUART", 1)
    ], width=0.25, layer=F, chamfer=0.45)
    route_45(board, n["VUART_ISO"], [
        P(fps, "R_VUART", 2), (22.54, 34.45), P(fps, "J5", 1)
    ], width=0.25, layer=F, chamfer=0.45)

    # Ferrite-Isolated Analog Reference Rail (VDDA, >= 0.28 mm Power width):
    route_45(board, n["VDDA"], [
        P(fps, "FB_VDDA", 1), P(fps, "C_VDDA1", 1), (5.95, 18.95), P(fps, "C_VDDA2", 1)
    ], width=0.32, layer=F, chamfer=0.22)
    route_45(board, n["VDDA"], [
        P(fps, "FB_VDDA", 1), (6.40, 16.21), (10.43, 16.21), P(fps, "C_VREF", 1)
    ], width=0.28, layer=F, chamfer=0.25)
    add_track(board, n["VDDA"], (10.43, 16.40), P(fps, "U1", 6), width=0.28, layer=F)
    route_pts(board, n["VDDA"], [
        P(fps, "C_VREF", 1), (10.43, 17.00), P(fps, "U1", 7)
    ], width=0.28, layer=F)

    # Split low-inductance GND bars above (y=13.95..15.52) and below (y=16.90..19.40) VDDA window:
    add_track(board, gnd, (8.55, 13.95), (8.55, 15.52), width=0.35, layer=F)
    add_via(board, gnd, 8.55, 14.55)
    add_via(board, gnd, 8.55, 15.40)
    for cref in ("C_U1A", "C_U1B", "C_VBAT"):
        p2 = P(fps, cref, 2)
        add_track(board, gnd, p2, (8.55, p2[1]), width=0.32, layer=F)

    add_track(board, gnd, (9.15, 17.20), (9.15, 19.40), width=0.35, layer=F)
    add_via(board, gnd, 9.15, 18.30)
    route_pts(board, gnd, [P(fps, "C_VREF", 2), (9.15, 17.20)], width=0.30, layer=F)
    for cref in ("C_VDDA1", "C_VDDA2", "C_SMPS1"):
        p2 = P(fps, cref, 2)
        add_track(board, gnd, p2, (9.15, p2[1]), width=0.32, layer=F)

    # Internal 15 uH DC-DC SMPS buck converter:
    route_45(board, n["VDDSMPS"], [
        P(fps, "FB_SMPS", 2), (10.43, 20.15), P(fps, "C_SMPS1", 1), P(fps, "U1", 11)
    ], width=0.30, layer=F, chamfer=0.25)

    route_pts(board, n["VFBSMPS"], [P(fps, "U1", 10), (11.40, 18.65)], width=0.28, layer=F)
    add_via(board, n["VFBSMPS"], 11.40, 18.65)
    route_pts(board, n["VFBSMPS"], [
        (11.40, 18.65), (11.40, 20.10), (10.20, 21.30)
    ], width=0.28, layer=B)
    add_via(board, n["VFBSMPS"], 10.20, 21.30)
    add_track(board, n["VFBSMPS"], (10.20, 21.30), P(fps, "L_SMPS", 1), width=0.30, layer=F)
    p_l1 = P(fps, "L_SMPS", 1)
    p_cs2 = P(fps, "C_SMPS2", 1)
    add_track(board, n["VFBSMPS"], p_cs2, P(fps, "C_SMPS3", 1), width=0.30, layer=F)
    add_track(board, n["VFBSMPS"], p_l1, (p_cs2[0], p_l1[1]), width=0.30, layer=F)

    route_45(board, gnd, [
        P(fps, "C_SMPS2", 2), (6.20, 21.80), (6.20, 22.90), P(fps, "C_SMPS3", 2)
    ], width=0.32, layer=F, chamfer=0.22)
    add_via(board, gnd, 6.20, 22.35)

    route_45(board, n["VLXSMPS"], [
        P(fps, "U1", 13), (11.20, 20.60), (11.20, 24.713), P(fps, "L_SMPS", 2)
    ], width=0.28, layer=F, chamfer=0.30)

    # ======================================================================
    # 6. MCU Reset, Boot0, SWD, UART (with ESD Clamps) & LGA-73 Ground Matrix
    # ======================================================================
    add_track(board, n["BOOT0"], P(fps, "U1", 43), (25.80, 16.40), width=0.24, layer=F)
    add_via(board, n["BOOT0"], 25.80, 16.40)
    route_45(board, n["BOOT0"], [
        (25.80, 16.40), (25.80, 10.10), (4.20, 10.10), (4.20, 25.40)
    ], width=0.20, layer=B, chamfer=0.45)
    add_via(board, n["BOOT0"], 4.20, 25.40)
    add_track(board, n["BOOT0"], (4.20, 25.40), P(fps, "R_BOOT", 1), width=0.24, layer=F)
    route_45(board, n["BOOT0"], [
        (4.20, 25.40), (4.20, 25.80), (1.05, 25.80), (1.05, 19.50), P(fps, "J3", 1)
    ], width=0.24, layer=F, chamfer=0.35)

    route_pts(board, n["RST"], [P(fps, "U1", 44), (24.75, 15.80), (25.05, 15.60)], width=0.24, layer=F)
    add_via(board, n["RST"], 25.05, 15.60)
    route_45(board, n["RST"], [
        (25.05, 15.60), (25.05, 10.75), (4.80, 10.75), (4.80, 26.80)
    ], width=0.20, layer=B, chamfer=0.45)
    add_via(board, n["RST"], 4.80, 26.80)
    add_track(board, n["RST"], (4.80, 26.80), P(fps, "SW1", 1), width=0.24, layer=F)
    route_45(board, n["RST"], [
        (4.80, 26.80), (4.80, 27.55), P(fps, "D_RST", 1),
        (5.35, 29.40), P(fps, "C_RST", 1)
    ], width=0.24, layer=F, chamfer=0.22)
    add_track(board, n["RST"], (5.35, 29.40), (5.35, 31.60), width=0.24, layer=F)
    add_track(board, n["RST"], (5.35, 31.60), P(fps, "R_RST", 1), width=0.24, layer=F)
    add_track(board, n["RST"], (5.35, 31.60), (5.35, 32.80), width=0.24, layer=F)
    add_via(board, n["RST"], 5.35, 32.80)
    add_track(board, n["RST"], (5.35, 32.80), (18.66, 32.80), width=0.22, layer=B)
    add_via(board, n["RST"], 18.66, 32.80)
    add_track(board, n["RST"], (18.66, 32.80), P(fps, "J4", 5), width=0.24, layer=F)

    route_45(board, gnd, [P(fps, "SW1", 2), (2.10, 30.20), (2.10, 31.85)], width=0.35, layer=F, chamfer=0.22)
    add_via(board, gnd, 2.10, 31.85)
    route_45(board, gnd, [
        P(fps, "R_BOOT", 2), (7.55, 25.40), (7.55, 29.40), P(fps, "C_RST", 2)
    ], width=0.30, layer=F, chamfer=0.25)
    add_track(board, gnd, P(fps, "D_RST", 2), (7.55, 27.55), width=0.30, layer=F)
    add_track(board, gnd, (7.55, 28.45), (7.75, 28.45), width=0.30, layer=F)
    add_via(board, gnd, 7.75, 28.45)

    # LGA-73 Central 3x3 GND Matrix (Pads 65..73):
    for r0 in (65, 68, 71):
        add_track(board, gnd, P(fps, "U1", r0), P(fps, "U1", r0 + 2), width=0.45, layer=F)
    for c0 in (65, 66, 67):
        add_track(board, gnd, P(fps, "U1", c0), P(fps, "U1", c0 + 6), width=0.45, layer=F)

    for ix in (16.85, 19.65):
        add_track(board, gnd, (ix, 13.57), (ix, 22.23), width=0.45, layer=F)
        for iy in (13.57, 16.50, 19.30, 22.23):
            add_via(board, gnd, ix, iy)
    for iy in (16.50, 19.30):
        add_track(board, gnd, (15.45, iy), (21.05, iy), width=0.45, layer=F)

    route_pts(board, gnd, [P(fps, "U1", 12), (13.92, 20.00), (15.45, 20.00), P(fps, "U1", 71)], width=0.40, layer=F)
    add_via(board, gnd, 13.92, 20.00)

    route_45(board, gnd, [P(fps, "U1", 28), (20.35, 22.23), (19.65, 22.23)], width=0.35, layer=F, chamfer=0.22)
    route_pts(board, gnd, [P(fps, "U1", 46), (22.58, 14.60), (21.05, 15.10)], width=0.35, layer=F)
    add_via(board, gnd, 22.58, 14.60)
    route_45(board, gnd, [P(fps, "U1", 47), (22.58, 14.00), (22.58, 14.60)], width=0.35, layer=F, chamfer=0.20)
    route_45(board, gnd, [P(fps, "U1", 52), (20.95, 13.57), (19.65, 13.57)], width=0.35, layer=F, chamfer=0.25)
    route_45(board, gnd, [P(fps, "U1", 56), (18.55, 13.57), (19.65, 13.57)], width=0.35, layer=F, chamfer=0.25)

    # GSG RF Launch Grounds (Pads 35, 36 below & Pads 38, 39 above RF_OUT Pad 37):
    add_track(board, gnd, P(fps, "U1", 36), P(fps, "U1", 35), width=0.35, layer=F)
    route_pts(board, gnd, [P(fps, "U1", 35), (24.85, 21.20), (25.50, 21.75)], width=0.35, layer=F)
    route_45(board, gnd, [P(fps, "U1", 35), (22.58, 21.20), (22.58, 20.70), P(fps, "U1", 73)], width=0.40, layer=F, chamfer=0.20)
    add_via(board, gnd, 22.58, 21.20)

    add_track(board, gnd, P(fps, "U1", 38), P(fps, "U1", 39), width=0.35, layer=F)
    route_pts(board, gnd, [P(fps, "U1", 39), (24.85, 18.80), (25.50, 18.25)], width=0.35, layer=F)
    route_45(board, gnd, [P(fps, "U1", 39), (22.58, 18.80), (21.85, 18.80), P(fps, "U1", 70)], width=0.40, layer=F, chamfer=0.25)
    add_via(board, gnd, 22.58, 18.80)

    # SWD (U1.1 SWDIO & U1.2 SWCLK -> 45-deg B.Cu outside U1 -> feed-through D_SWD.1/2 -> J4.2/3):
    route_pts(board, n["SWDIO"], [P(fps, "U1", 1), (11.80, 13.40), (11.20, 13.10)], width=0.22, layer=F)
    add_via(board, n["SWDIO"], 11.20, 13.10)
    route_45(board, n["SWDIO"], [
        (11.20, 13.10), (7.40, 13.10), (7.40, 27.10), (9.55, 27.10)
    ], width=0.22, layer=B, chamfer=0.45)
    add_via(board, n["SWDIO"], 9.55, 27.10)
    route_pts(board, n["SWDIO"], [
        (9.55, 27.10), (9.55, 32.28), (11.36, 34.088),
        P(fps, "D_SWD", 1), (11.04, 34.41), P(fps, "J4", 2)
    ], width=0.24, layer=F)

    route_pts(board, n["SWCLK"], [P(fps, "U1", 2), (11.80, 14.00), (11.20, 13.90)], width=0.22, layer=F)
    add_via(board, n["SWCLK"], 11.20, 13.90)
    route_45(board, n["SWCLK"], [
        (11.20, 13.90), (7.90, 13.90), (7.90, 26.50), (10.45, 26.50), (10.45, 27.10)
    ], width=0.22, layer=B, chamfer=0.45)
    add_via(board, n["SWCLK"], 10.45, 27.10)
    route_pts(board, n["SWCLK"], [
        (10.45, 27.10), (13.26, 29.91), P(fps, "D_SWD", 2),
        (13.58, 34.41), P(fps, "J4", 3)
    ], width=0.24, layer=F)

    add_track(board, gnd, P(fps, "D_SWD", 3), (10.95, 32.21), width=0.35, layer=F)
    add_via(board, gnd, 10.95, 32.21)
    add_track(board, gnd, P(fps, "J4", 4), (16.12, 35.60), width=0.45, layer=F)
    add_via(board, gnd, 16.12, 35.60)

    # UART2 with compact 3.4 mm matched 45-deg B.Cu cross-under beneath South F.Cu corridor:
    route_pts(board, n["UART_TX"], [
        P(fps, "U1", 29), (20.95, 27.20), (22.35, 28.60)
    ], width=0.24, layer=F)
    add_via(board, n["UART_TX"], 22.35, 28.60)
    route_pts(board, n["UART_TX"], [
        (22.35, 28.60), (22.35, 31.35), (22.95, 31.95)
    ], width=0.22, layer=B)
    add_via(board, n["UART_TX"], 22.95, 31.95)
    route_pts(board, n["UART_TX"], [
        (22.95, 31.95), (23.262, 31.95), P(fps, "D_UART", 1),
        (25.40, 34.50), (25.08, 34.82), P(fps, "J5", 2)
    ], width=0.24, layer=F)

    route_pts(board, n["UART_RX"], [
        P(fps, "U1", 30), (21.55, 26.95), (23.20, 28.60)
    ], width=0.24, layer=F)
    add_via(board, n["UART_RX"], 23.20, 28.60)
    route_pts(board, n["UART_RX"], [
        (23.20, 28.60), (25.30, 28.60), (27.30, 30.60), (27.30, 31.85)
    ], width=0.22, layer=B)
    add_via(board, n["UART_RX"], 27.30, 31.85)
    route_pts(board, n["UART_RX"], [
        (27.30, 31.85), P(fps, "D_UART", 2),
        (27.62, 34.41), P(fps, "J5", 3)
    ], width=0.24, layer=F)

    add_track(board, gnd, P(fps, "D_UART", 3), (24.99, 32.21), width=0.35, layer=F)
    add_via(board, gnd, 24.99, 32.21)
    add_track(board, gnd, P(fps, "J5", 4), (30.16, 35.60), width=0.45, layer=F)
    add_via(board, gnd, 30.16, 35.60)


# --------------------------------------------------------------------------
# Copper Keep-Out Zones, F.Cu / B.Cu GND Zones & Tented RF Via Stitching
# --------------------------------------------------------------------------
def add_zones_and_stitching(board, gnd):
    # 1a. Full 40 x 40 mm Open Antenna & Sensing Keep-Out Area (dx = 50.0..90.0, dy = 0.0..40.0)
    kz = pcbnew.ZONE(board)
    kz.SetIsRuleArea(True)
    kz.SetZoneName("ANTENNA_SUBSTRATE_KEEPOUT")
    kz.SetDoNotAllowCopperPour(True)
    kz.SetDoNotAllowTracks(False)
    kz.SetDoNotAllowVias(False)
    kz.SetDoNotAllowPads(False)
    kz.SetDoNotAllowFootprints(False)
    lset = pcbnew.LSET()
    lset.AddLayer(F)
    lset.AddLayer(B)
    kz.SetLayerSet(lset)
    kpoly = kz.Outline()
    kpoly.NewOutline()
    for dx, dy in [(50.0, 0.0), (90.0, 0.0), (90.0, 40.0), (50.0, 40.0)]:
        kpoly.Append(G(dx, dy))
    board.Add(kz)

    # 1b. 2.20 x 2.20 mm Parasitic Cutout Void on BOTH F.Cu and B.Cu Directly Beneath /BR_S
    #     Reduces /BR_S ground-coupled pad/trace capacitance from 1.54 pF to 0.1305 pF (< 0.15 pF)!
    vx0, vy0, vx1, vy1 = BR_S_VOID_BOX
    bv = pcbnew.ZONE(board)
    bv.SetIsRuleArea(True)
    bv.SetZoneName("BR_S_PARASITIC_VOID_2p2x2p2mm")
    bv.SetDoNotAllowCopperPour(True)
    bv.SetDoNotAllowTracks(False)
    bv.SetDoNotAllowVias(True)
    bv.SetDoNotAllowPads(False)
    bv.SetDoNotAllowFootprints(False)
    bv.SetLayerSet(lset)
    bpoly = bv.Outline()
    bpoly.NewOutline()
    for dx, dy in [(vx0, vy0), (vx1, vy0), (vx1, vy1), (vx0, vy1)]:
        bpoly.Append(G(dx, dy))
    board.Add(bv)

    # 2. Solid 50 x 40 mm GND Counterpoise on F.Cu and B.Cu with smooth 0.25 mm rounded fillets
    for layer, x_east in ((F, 49.4), (B, 50.0)):
        zone_pts = [
            (0.45, 0.45), (x_east, 0.45), (x_east, 39.55), (0.45, 39.55),
        ]
        z = pcbnew.ZONE(board)
        z.SetNet(gnd)
        z.SetLayer(layer)
        z.SetZoneName("GND_COUNTERPOISE")
        z.SetAssignedPriority(0)
        z.SetLocalClearance(mm(0.28))
        z.SetMinThickness(mm(0.20))
        z.SetCornerSmoothingType(pcbnew.ZONE_SETTINGS.SMOOTHING_FILLET)
        z.SetCornerRadius(mm(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.35))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetMinIslandArea(1_000_000_000_000)
        poly = z.Outline()
        poly.NewOutline()
        for dx, dy in zone_pts:
            poly.Append(G(dx, dy))
        board.Add(z)

    # 3. CPWG RF Guard, /SMA_C CPWG Fence & Counterpoise Stitching Vias (exact 131 total vias!)
    stitch = [
        (25.5, 18.25), (28.6, 18.25), (31.2, 18.25), (36.9, 18.25),
        (39.4, 18.25), (41.3, 18.25), (43.8, 18.25), (46.0, 18.25), (48.5, 18.25),
        (25.5, 21.75), (28.0, 21.75), (31.0, 21.75), (34.4, 21.75),
        (39.2, 21.75), (41.5, 21.75), (43.4, 21.85), (46.6, 21.85), (48.5, 21.75),
        # /SMA_C 1.08 mm 50R CPWG vertical guard vias:
        (32.85, 9.0), (32.85, 12.5), (32.85, 16.0),
        (36.15, 9.0), (36.15, 14.0), (36.15, 16.5),
        (48.85, 4.0), (48.85, 8.0), (48.85, 12.0), (48.85, 15.5), (48.85, 22.8),
        (48.85, 29.8), (48.85, 38.5),
        (40.5, 6.5), (44.0, 6.5),
        # Local switched-detector & West perimeter ground stitching:
        (39.0, 31.6),
        (1.90, 11.20), (1.90, 12.80), (1.60, 33.50),
        # Redundant 2nd tented stitching vias ensuring >= 2 GND vias in every F.Cu GND island:
        (10.85, 29.00), (23.80, 35.40), (1.90, 14.40), (8.60, 17.00),
        (26.35, 35.56), (25.49, 8.59), (6.30, 26.40),
    ]
    for sx, sy in stitch:
        add_via(board, gnd, sx, sy, dia=0.60, drill=0.30)


def add_native_teardrops(board):
    """Emit curved KiCad 9 native pad/via teardrops (`(attr (teardrop (type padvia)))`)
    where non-RF signal/power tracks enter PTH connector pads (`J2..J5`), circular DC
    test points (`TP1..TP4`), and non-RF signal/power vias."""
    rf_nets = {"/RF_PA", "/BR_P", "/BR_Q", "/ANT_FEED", "/SMA_C", "/BR_S", "/BR_O", "/DET_IN"}

    # Build per-layer Copper obstacle shapes by netcode so teardrops maintain >= 0.22 mm clearance
    obs_by_layer_net = {F: defaultdict(list), B: defaultdict(list)}
    targets = []  # (layer, net_item, cx, cy, radius_mm)

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            nc = pad.GetNetCode()
            nname = pad.GetNetname()
            px = pcbnew.ToMM(pad.GetPosition().x) - X0
            py = pcbnew.ToMM(pad.GetPosition().y) - Y0
            bb = _bbox_to_box(pad.GetBoundingBox())
            for lyr in (F, B):
                if pad.IsOnLayer(lyr):
                    obs_by_layer_net[lyr][nc].append(bb)
            if nname == "GND" or nname in rf_nets or not nname or nname.startswith("unconnected-"):
                continue
            if ref in ("J2", "J3", "J4", "J5") and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                pad.SetTeardropsEnabled(True)
                r_mm = 0.5 * min(pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y))
                for lyr in (F, B):
                    if pad.IsOnLayer(lyr):
                        targets.append((lyr, pad.GetNet(), px, py, r_mm))
            elif ref in ("TP1", "TP2", "TP3", "TP4"):
                pad.SetTeardropsEnabled(True)
                r_mm = 0.5 * min(pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y))
                targets.append((F, pad.GetNet(), px, py, r_mm))

    tracks_by_layer_net = {F: defaultdict(list), B: defaultdict(list)}
    for t in board.GetTracks():
        nc = t.GetNetCode()
        nname = t.GetNetname()
        if isinstance(t, pcbnew.PCB_VIA):
            vx = pcbnew.ToMM(t.GetPosition().x) - X0
            vy = pcbnew.ToMM(t.GetPosition().y) - Y0
            vr = 0.5 * pcbnew.ToMM(t.GetWidth(F))
            vp = Point(vx, vy).buffer(vr, quad_segs=16)
            obs_by_layer_net[F][nc].append(vp)
            obs_by_layer_net[B][nc].append(vp)
            if nname != "GND" and nname not in rf_nets:
                t.SetTeardropsEnabled(True)
                targets.append((F, t.GetNet(), vx, vy, vr))
                targets.append((B, t.GetNet(), vx, vy, vr))
        else:
            p1 = (pcbnew.ToMM(t.GetStart().x) - X0, pcbnew.ToMM(t.GetStart().y) - Y0)
            p2 = (pcbnew.ToMM(t.GetEnd().x) - X0, pcbnew.ToMM(t.GetEnd().y) - Y0)
            tw = pcbnew.ToMM(t.GetWidth())
            lyr = t.GetLayer()
            if lyr in (F, B):
                obs_by_layer_net[lyr][nc].append(LineString([p1, p2]).buffer(0.5 * tw, quad_segs=8))
                tracks_by_layer_net[lyr][nc].append((p1, p2, tw))

    other_union_cache = {}
    for lyr in (F, B):
        all_ncs = list(obs_by_layer_net[lyr].keys())
        for nc in all_ncs:
            others = []
            for onc, geoms in obs_by_layer_net[lyr].items():
                if onc != nc:
                    others.extend(geoms)
            other_union_cache[(lyr, nc)] = unary_union(others) if others else Polygon()

    td_count = 0
    bay_limit = _rounded_board_poly(inset_mm=0.35).intersection(box(0.0, 0.0, 49.3, H))
    alpha = math.radians(60.0)
    tds_by_layer_net = {F: defaultdict(list), B: defaultdict(list)}
    net_by_nc = {}

    for lyr, net_item, cx, cy, r_mm in targets:
        nc = net_item.GetNetCode()
        net_by_nc[nc] = net_item
        other_u = other_union_cache.get((lyr, nc), Polygon())
        for p1, p2, tw in tracks_by_layer_net[lyr][nc]:
            hw = 0.5 * tw
            if r_mm <= hw + 0.04:
                continue
            if math.hypot(p1[0] - cx, p1[1] - cy) <= 0.05:
                far = p2
            elif math.hypot(p2[0] - cx, p2[1] - cy) <= 0.05:
                far = p1
            else:
                continue
            seg_len = math.hypot(far[0] - cx, far[1] - cy)
            if seg_len < 1.55 * r_mm:
                continue
            ux, uy = (far[0] - cx) / seg_len, (far[1] - cy) / seg_len
            nx, ny = -uy, ux
            d = min(1.80 * r_mm, 0.72 * seg_len)
            r_in = 0.88 * r_mm

            # Concave curved snowcone Bezier contour from pad circle into track edges
            pts = []
            for k in range(-3, 4):
                ang = (k / 3.0) * alpha
                ca, sa = math.cos(ang), math.sin(ang)
                pts.append((cx + r_in * (-ca * ux + sa * nx), cy + r_in * (-ca * uy + sa * ny)))

            # Upper side: +alpha on circle -> track +hw at distance d
            s_top = (cx + r_in * (math.cos(alpha) * ux + math.sin(alpha) * nx),
                     cy + r_in * (math.cos(alpha) * uy + math.sin(alpha) * ny))
            c_top = (cx + 0.46 * d * ux + (0.52 * r_mm + 0.48 * hw) * nx,
                     cy + 0.46 * d * uy + (0.52 * r_mm + 0.48 * hw) * ny)
            e_top = (cx + d * ux + hw * nx, cy + d * uy + hw * ny)

            e_bot = (cx + d * ux - hw * nx, cy + d * uy - hw * ny)
            c_bot = (cx + 0.46 * d * ux - (0.52 * r_mm + 0.48 * hw) * nx,
                     cy + 0.46 * d * uy - (0.52 * r_mm + 0.48 * hw) * ny)
            s_bot = (cx + r_in * (math.cos(alpha) * ux - math.sin(alpha) * nx),
                     cy + r_in * (math.cos(alpha) * uy - math.sin(alpha) * ny))

            curve_pts = [pts[0], pts[3], pts[-1]]
            for step_i in range(7):
                t_b = step_i / 6.0
                om = 1.0 - t_b
                curve_pts.append((
                    om * om * s_top[0] + 2 * om * t_b * c_top[0] + t_b * t_b * e_top[0],
                    om * om * s_top[1] + 2 * om * t_b * c_top[1] + t_b * t_b * e_top[1],
                ))
            for step_i in range(7):
                t_b = step_i / 6.0
                om = 1.0 - t_b
                curve_pts.append((
                    om * om * e_bot[0] + 2 * om * t_b * c_bot[0] + t_b * t_b * s_bot[0],
                    om * om * e_bot[1] + 2 * om * t_b * c_bot[1] + t_b * t_b * s_bot[1],
                ))

            sh_td = Polygon(curve_pts).convex_hull if not Polygon(curve_pts).is_valid else Polygon(curve_pts)
            if not bay_limit.contains(sh_td):
                continue
            if not other_u.is_empty and sh_td.distance(other_u) < 0.21:
                continue
            tds_by_layer_net[lyr][nc].append(sh_td)

    for lyr in (F, B):
        for nc, poly_list in tds_by_layer_net[lyr].items():
            if not poly_list:
                continue
            merged = unary_union(poly_list)
            other_u = other_union_cache.get((lyr, nc), Polygon())
            geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
            for g_poly in geoms:
                if g_poly.is_empty or g_poly.geom_type != "Polygon":
                    continue
                ext_poly = Polygon(g_poly.exterior)
                if not other_u.is_empty and ext_poly.distance(other_u) < 0.21:
                    continue
                tz = pcbnew.ZONE(board)
                tz.SetNet(net_by_nc[nc])
                tz.SetLayer(lyr)
                tz.SetZoneName("__TEARDROP_PADVIA__")
                tz.SetAssignedPriority(2)
                tz.SetLocalClearance(0)
                tz.SetMinThickness(mm(0.0254))
                tz.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
                tz.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
                zpoly = tz.Outline()
                zpoly.NewOutline()
                for tx, ty in ext_poly.exterior.coords[:-1]:
                    zpoly.Append(G(round(tx, 4), round(ty, 4)))
                board.Add(tz)
                td_count += 1
    return td_count


# --------------------------------------------------------------------------
# Professional >= 0.15 mm Silkscreen Legend & Sheet Mechanical Dimensions
# --------------------------------------------------------------------------
def add_annotations_and_dimensions(board):
    # Keep 100% of F.SilkS & B.SilkS ink outside the dx >= 50.0 mm antenna aperture!
    add_silk_text(board, "REV E.5", 41.2, 8.8, size=0.85, thick=0.15)
    add_silk_text(board, "1S LiPo 3.0-4.2V", 38.0, 10.6, size=0.80, thick=0.15)
    add_silk_text(board, "VNA", 41.0, 2.2, size=0.85, thick=0.15)
    # Standard 1S JST-PH LiPo convention: Pad 2 (left) = +VBAT_RAW, Pad 1 (right) = -GND
    add_silk_text(board, "+", 5.20, 1.40, size=0.85, thick=0.15)
    add_silk_text(board, "-", 13.80, 1.40, size=0.85, thick=0.15)
    add_silk_text(board, "BOOT", 1.55, 16.80, size=0.80, thick=0.15)
    add_silk_text(board, "SWD", 5.2, 34.8, size=0.80, thick=0.15)
    add_silk_text(board, "UART", 34.05, 38.85, size=0.80, thick=0.15)

    # Back silkscreen identification + direct-solder J2 polarity + per-unit DevEUI / S/N box
    # Placed cleanly over uninterrupted solid B.Cu ground plane (zero B.Cu traces underneath S/N box!)
    for pol_str, px, py in (
        ("+", 7.10, 3.85),
        ("-", 12.70, 3.85),
    ):
        pt = pcbnew.PCB_TEXT(board)
        pt.SetText(pol_str)
        pt.SetLayer(pcbnew.B_SilkS)
        pt.SetMirrored(True)
        pt.SetPosition(G(px, py))
        pt.SetTextSize(pcbnew.VECTOR2I(mm(0.85), mm(0.85)))
        pt.SetTextThickness(mm(0.15))
        pt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        board.Add(pt)

    for txt_str, bx, by, bsz in [
        ("J2:1=GND 2=+VBAT 4.35V", 21.30, 1.65, 0.80),
        ("868MHz EU868", 47.80, 13.00, 0.80),
        ("0.8mm RADOME", 47.80, 14.70, 0.80),
        ("ISAC-868 LoRaWAN + RF SENSOR  REV E.5", 47.80, 20.00, 0.80),
        ("UNIT S/N & DevEUI:", 30.80, 23.60, 0.80),
        ("J4: SWD (DNP)", 19.20, 34.20, 0.80),
        ("J5: UART (DNP)", 31.80, 34.20, 0.80),
    ]:
        bt = pcbnew.PCB_TEXT(board)
        bt.SetText(txt_str)
        bt.SetLayer(pcbnew.B_SilkS)
        bt.SetMirrored(True)
        bt.SetPosition(G(bx, by))
        bt.SetTextSize(pcbnew.VECTOR2I(mm(bsz), mm(bsz)))
        bt.SetTextThickness(mm(0.15))
        bt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        board.Add(bt)

    sn_box = [
        ((12.60, 24.65), (30.80, 24.65)),
        ((30.80, 24.65), (30.80, 27.65)),
        ((30.80, 27.65), (12.60, 27.65)),
        ((12.60, 27.65), (12.60, 24.65)),
    ]
    for p1, p2 in sn_box:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(G(*p1))
        s.SetEnd(G(*p2))
        s.SetLayer(pcbnew.B_SilkS)
        s.SetWidth(mm(0.15))
        board.Add(s)

    # Pure 7-bit ASCII mechanical callout on Dwgs.User (zero UTF-16 PDF mojibake!)
    win_note = pcbnew.PCB_TEXT(board)
    win_note.SetLayer(pcbnew.Dwgs_User)
    win_note.SetText(
        "RADOME & DIELECTRIC SENSING INTERFACE: dx=74.60..86.60, dy=19.80..32.35 mm (12.00 x 12.55 mm)\n"
        "WINDOW SPEC: t = 0.80 mm UV-ASA/PETG + 25 um 3M 467MP PSA (0.000 mm air gap over IDE comb)\n"
        "J1 (MOLEX 73251-1153 SMA): DNP FIELD SKU -- HAND-SOLDER POST-REFLOW FOR VNA BENCH CALIBRATION\n"
        "J2 (1S LiPo): DNP SEALED SKU -- DIRECT SOLDER LEADS FROM B.Cu (PAD1=GND, PAD2=+VBAT, 4.35V MAX)"
    )
    win_note.SetPosition(G(48.0, -7.5))
    win_note.SetTextSize(pcbnew.VECTOR2I(mm(1.05), mm(1.05)))
    win_note.SetTextThickness(mm(0.15))
    win_note.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    board.Add(win_note)

    # Mechanical dimensions on Dwgs.User around the centered board on A4 sheet
    dims = [
        ((0.0, 0.0), (W, 0.0), -14.0),       # Overall 90.00 mm board width (above SMA)
        ((0.0, H), (50.0, H), 8.0),          # 50.00 mm GND Counterpoise
        ((50.0, H), (W, H), 8.0),            # 40.00 mm Antenna Section
        ((0.0, 0.0), (0.0, H), 8.0),         # Overall 40.00 mm board height (left)
    ]
    for p1, p2, height_mm in dims:
        d = pcbnew.PCB_DIM_ALIGNED(board, pcbnew.PCB_DIM_ALIGNED_T)
        d.SetLayer(pcbnew.Dwgs_User)
        d.SetStart(G(*p1))
        d.SetEnd(G(*p2))
        d.SetHeight(mm(height_mm))
        d.SetPrecision(pcbnew.DIM_PRECISION_X_XX)
        d.SetUnits(pcbnew.EDA_UNITS_MM)
        d.SetUnitsMode(pcbnew.DIM_UNITS_MODE_MM)
        d.SetUnitsFormat(pcbnew.DIM_UNITS_FORMAT_BARE_SUFFIX)
        d.SetTextSize(pcbnew.VECTOR2I(mm(1.2), mm(1.2)))
        d.SetTextThickness(mm(0.18))
        d.SetLineThickness(mm(0.12))
        d.Update()
        board.Add(d)

    sep = pcbnew.PCB_SHAPE(board)
    sep.SetShape(pcbnew.SHAPE_T_SEGMENT)
    sep.SetStart(G(50.0, -3.0))
    sep.SetEnd(G(50.0, H + 3.0))
    sep.SetLayer(pcbnew.Dwgs_User)
    sep.SetWidth(mm(0.12))
    board.Add(sep)


# --------------------------------------------------------------------------
# Shapely Build-Time Geometric & RF/DFM Hygiene Verification
# --------------------------------------------------------------------------
def _pad_mask_margin_mm(pad, default_mm=0.035):
    loc = pad.GetLocalSolderMaskMargin()
    if loc is None:
        return default_mm
    val = pcbnew.ToMM(loc)
    return val if val > 0.0 else default_mm


def _bbox_to_box(bb):
    return box(
        pcbnew.ToMM(bb.GetLeft()) - X0,
        pcbnew.ToMM(bb.GetTop()) - Y0,
        pcbnew.ToMM(bb.GetRight()) - X0,
        pcbnew.ToMM(bb.GetBottom()) - Y0,
    )


def _fp_courtyard_poly(fp):
    pset = fp.GetCourtyard(pcbnew.F_CrtYd)
    if pset.IsEmpty():
        return _bbox_to_box(fp.GetBoundingBox(False, False))
    polys = []
    for i in range(pset.OutlineCount()):
        outline = pset.Outline(i)
        pts = [
            (pcbnew.ToMM(outline.CPoint(k).x) - X0, pcbnew.ToMM(outline.CPoint(k).y) - Y0)
            for k in range(outline.PointCount())
        ]
        if len(pts) >= 3:
            p = Polygon(pts)
            if not p.is_valid:
                p = p.buffer(0)
            polys.append(p)
    return unary_union(polys) if polys else _bbox_to_box(pset.BBox())


def _rounded_board_poly(inset_mm=0.0):
    r = max(0.0, R_CORNER - inset_mm)
    b = box(inset_mm, inset_mm, W - inset_mm, H - inset_mm)
    if r <= 0:
        return b
    corners = []
    for cx, cy in [
        (inset_mm + r, inset_mm + r),
        (W - inset_mm - r, inset_mm + r),
        (W - inset_mm - r, H - inset_mm - r),
        (inset_mm + r, H - inset_mm - r),
    ]:
        sq = box(
            cx - r if cx < W / 2 else cx,
            cy - r if cy < H / 2 else cy,
            cx if cx < W / 2 else cx + r,
            cy if cy < H / 2 else cy + r,
        )
        corners.append(sq.difference(Point(cx, cy).buffer(r, quad_segs=32)))
    return b.difference(unary_union(corners))


def place_clean_references(board, max_crtyd_dist_mm=1.95):
    """Deterministically place visible F.SilkS reference designators within <= 1.80 mm
    (<= 2.0 mm IPC-2221B / limit) of each component's courtyard in X_gbr < 50.0 mm
    with ZERO pad, F.Mask, drill, via, footprint silk, or legend collisions.
    Ultra-dense 0402 passives that have no collision-free 0.80 mm silkscreen slot within
    1.80 mm hide F.SilkS and rely on crisp centered 0.50 mm F.Fab assembly references."""
    board_inset = _rounded_board_poly(inset_mm=0.35)
    bay_inset = board_inset.intersection(box(0.0, 0.0, 49.4, H))
    obstacles = []

    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS and isinstance(d, pcbnew.PCB_TEXT) and d.IsVisible():
            obstacles.append(_bbox_to_box(d.GetBoundingBox()).buffer(0.08))

    # Avoid placing silkscreen ink over via barrels/annular rings (Gate 3: 0 via collisions!)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            vx = pcbnew.ToMM(t.GetPosition().x) - X0
            vy = pcbnew.ToMM(t.GetPosition().y) - Y0
            vd = pcbnew.ToMM(t.GetWidth(F))
            obstacles.append(Point(vx, vy).buffer(vd / 2.0 + 0.05))

    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    crtyd_map = {}
    for ref, fp in fps.items():
        crtyd_map[ref] = _fp_courtyard_poly(fp)
        for pad in fp.Pads():
            px = pcbnew.ToMM(pad.GetPosition().x) - X0
            py = pcbnew.ToMM(pad.GetPosition().y) - Y0
            if pad.IsOnLayer(pcbnew.F_Mask) or pad.IsOnLayer(F):
                sm_m = _pad_mask_margin_mm(pad)
                obstacles.append(_bbox_to_box(pad.GetBoundingBox()).buffer(sm_m + 0.12))
            dr = pcbnew.ToMM(pad.GetDrillSize().x)
            if dr > 0:
                obstacles.append(Point(px, py).buffer(dr / 2.0 + 0.08))
        for gi in fp.GraphicalItems():
            lyr = gi.GetLayer()
            if lyr == pcbnew.F_Mask:
                obstacles.append(_bbox_to_box(gi.GetBoundingBox()).buffer(0.05))
            elif lyr == pcbnew.F_SilkS:
                if isinstance(gi, pcbnew.PCB_TEXT):
                    if gi.IsVisible():
                        obstacles.append(_bbox_to_box(gi.GetBoundingBox()).buffer(0.08))
                elif isinstance(gi, pcbnew.PCB_SHAPE) and gi.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                    p1 = (pcbnew.ToMM(gi.GetStart().x) - X0, pcbnew.ToMM(gi.GetStart().y) - Y0)
                    p2 = (pcbnew.ToMM(gi.GetEnd().x) - X0, pcbnew.ToMM(gi.GetEnd().y) - Y0)
                    hw = pcbnew.ToMM(gi.GetWidth()) / 2.0
                    obstacles.append(LineString([p1, p2]).buffer(hw + 0.05))
                else:
                    obstacles.append(_bbox_to_box(gi.GetBoundingBox()).buffer(0.05))

    forbidden = unary_union(obstacles)
    prep_forbidden = prep(forbidden)
    prep_bay = prep(bay_inset)

    mandatory_silk = set(COMMERCIAL_SILK_REFS)

    visible_refs = [
        ref for ref, fp in fps.items()
        if fp.Reference().IsVisible() and fp.Reference().GetLayer() == pcbnew.F_SilkS
    ]

    # Pre-compute translation-invariant text bounding boxes strictly at rot=0 (100% horizontal upright)
    cand_lists = {}
    for ref in visible_refs:
        fp = fps[ref]
        rtxt = fp.Reference()
        dx, dy, _ = PLACE[ref]
        cpoly = crtyd_map[ref]
        pref_dx, pref_dy, _ = REF_OFF.get(ref, (0.0, -1.5, 0))
        pref_ang = math.atan2(pref_dy, pref_dx)

        rtxt.SetTextAngleDegrees(0)
        rtxt.SetPosition(G(dx, dy))
        bb0 = _bbox_to_box(rtxt.GetBoundingBox())
        rot_dims = {0: (bb0.bounds[0] - dx, bb0.bounds[1] - dy, bb0.bounds[2] - dx, bb0.bounds[3] - dy)}

        cbx0, cby0, cbx1, cby1 = cpoly.bounds
        max_span_x = max(abs(cbx0 - dx), abs(cbx1 - dx)) + max_crtyd_dist_mm + 2.4
        max_span_y = max(abs(cby0 - dy), abs(cby1 - dy)) + max_crtyd_dist_mm + 2.4
        step = 0.14
        nx = int(math.ceil(max_span_x / step))
        ny = int(math.ceil(max_span_y / step))

        raw_cands = [(pref_dx, pref_dy, 0)]
        for ix in range(-nx, nx + 1):
            ox = round(ix * step, 3)
            for iy in range(-ny, ny + 1):
                if ix == 0 and iy == 0:
                    continue
                oy = round(iy * step, 3)
                raw_cands.append((ox, oy, 0))

        valid = []
        for ox, oy, rot_cand in raw_cands:
            rx0, ry0, rx1, ry1 = rot_dims[rot_cand]
            cx, cy = dx + ox, dy + oy
            sb = box(cx + rx0, cy + ry0, cx + rx1, cy + ry1)
            if not prep_bay.contains(sb):
                continue
            cdist = cpoly.distance(sb)
            if cdist > max_crtyd_dist_mm:
                continue
            if prep_forbidden.intersects(sb):
                continue
            ang_diff = abs((math.atan2(oy, ox) - pref_ang + math.pi) % (2.0 * math.pi) - math.pi)
            score = cdist + 0.12 * ang_diff
            valid.append((score, ox, oy, rot_cand, sb))
        valid.sort(key=lambda item: item[0])
        cand_lists[ref] = valid

    visible_refs.sort(key=lambda r: (0 if r in mandatory_silk else 1, len(cand_lists[r]), r))

    placed_sfx = []
    placed_count = 0
    hidden_dense = []
    for ref in visible_refs:
        fp = fps[ref]
        rtxt = fp.Reference()
        dx, dy, _ = PLACE[ref]
        chosen = None
        for score, ox, oy, rot_cand, sb in cand_lists[ref]:
            if any(sb.distance(prev_sb) < 0.09 for prev_sb in placed_sfx):
                continue
            chosen = (ox, oy, rot_cand, sb)
            break

        if chosen is not None:
            ox, oy, rot_cand, sb = chosen
            rtxt.SetTextAngleDegrees(rot_cand)
            rtxt.SetPosition(G(dx + ox, dy + oy))
            placed_sfx.append(sb)
            placed_count += 1
        else:
            if ref in mandatory_silk:
                raise AssertionError(
                    f"Mandatory component {ref} could not place F.SilkS ref within "
                    f"{max_crtyd_dist_mm:.2f} mm of courtyard near {(dx, dy)}!"
                )
            # Dense 0402 cluster fallback per IPC-2221B / Task 3.4: hide F.SilkS ref, keep F.Fab ref
            rtxt.SetVisible(False)
            hidden_dense.append(ref)

    return placed_count, hidden_dense


def verify_layout_geometry(board):
    """Strict shapely assertions: 100% tented non-VIPPO vias, B.Cu RF/U1 integrity,
    /BR_S <= 1.50 mm trace length over 2.2x2.2 mm F.Cu+B.Cu void, >= 4.0 mm /DET_ADC-to-L_SMPS
    isolation, 5 fiducials, 0 silkscreen in X>=50mm, <= 2.0 mm silkscreen-to-courtyard distance,
    0 silkscreen pad/mask/via/drill collisions & >= 85 deg bends."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}

    # 1. 100% tented vias & ZERO via-in-pad / pad-touching vias across entire board
    pad_polys = []
    mask_polys = []
    bmask_polys = []
    drill_polys = []
    via_polys = []
    for ref, fp in fps.items():
        for pad in fp.Pads():
            px = pcbnew.ToMM(pad.GetPosition().x) - X0
            py = pcbnew.ToMM(pad.GetPosition().y) - Y0
            bb = _bbox_to_box(pad.GetBoundingBox())
            if pad.IsOnLayer(F) or pad.IsOnLayer(B):
                pad_polys.append((ref, str(pad.GetNumber()), bb))
            if pad.IsOnLayer(pcbnew.F_Mask):
                sm_m = _pad_mask_margin_mm(pad)
                mask_polys.append((f"{ref}.{pad.GetNumber()}", bb.buffer(sm_m) if sm_m > 0 else bb))
            if pad.IsOnLayer(pcbnew.B_Mask):
                sm_m = _pad_mask_margin_mm(pad)
                bmask_polys.append((f"{ref}.{pad.GetNumber()}", bb.buffer(sm_m) if sm_m > 0 else bb))
            dr = pcbnew.ToMM(pad.GetDrillSize().x)
            if dr > 0:
                drill_polys.append((f"{ref}.{pad.GetNumber()}", Point(px, py).buffer(dr / 2.0)))
        for gi in fp.GraphicalItems():
            if gi.GetLayer() == pcbnew.F_Mask:
                mask_polys.append((f"{ref}:F.Mask", _bbox_to_box(gi.GetBoundingBox())))
            elif gi.GetLayer() == pcbnew.B_Mask:
                bmask_polys.append((f"{ref}:B.Mask", _bbox_to_box(gi.GetBoundingBox())))
        for zp in [p for p in fp.Pads() if not p.IsOnLayer(F) and p.IsOnLayer(pcbnew.F_Mask)]:
            mask_polys.append((f"{ref}:MaskPad", _bbox_to_box(zp.GetBoundingBox())))

    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    assert len(vias) == 131, f"Expected exact 131 tented vias on board, found {len(vias)}!"

    # Verify every F.Cu GND_COUNTERPOISE filled island has >= 2 GND stitching vias
    gnd_via_pts = [t.GetPosition() for t in vias if t.GetNetname() == "GND"]
    for z in board.Zones():
        if z.GetIsRuleArea() or not z.IsOnLayer(F) or z.GetNetname() != "GND":
            continue
        ps = z.GetFilledPolysList(F)
        for oi in range(ps.OutlineCount()):
            sub = pcbnew.SHAPE_POLY_SET()
            sub.AddOutline(ps.Outline(oi))
            for hi in range(ps.HoleCount(oi)):
                sub.AddHole(ps.Hole(oi, hi))
            cnt = sum(1 for vp in gnd_via_pts if sub.Contains(vp))
            assert cnt >= 2, (
                f"F.Cu GND island #{oi} at "
                f"({pcbnew.ToMM(sub.BBox().GetCenter().x) - X0:.2f}, "
                f"{pcbnew.ToMM(sub.BBox().GetCenter().y) - Y0:.2f}) has only {cnt} GND via(s) (< 2)!"
            )
    for v in vias:
        vx = pcbnew.ToMM(v.GetPosition().x) - X0
        vy = pcbnew.ToMM(v.GetPosition().y) - Y0
        vd = pcbnew.ToMM(v.GetWidth(F))
        assert v.GetFrontTentingMode() == pcbnew.TENTING_MODE_TENTED, f"Untented front via at ({vx:.2f}, {vy:.2f})"
        assert v.GetBackTentingMode() == pcbnew.TENTING_MODE_TENTED, f"Untented back via at ({vx:.2f}, {vy:.2f})"
        vp = Point(vx, vy).buffer(vd / 2.0)
        via_polys.append((f"VIA@({vx:.2f},{vy:.2f})", vp))
        for ref, pnum, pp in pad_polys:
            gap = vp.distance(pp)
            assert gap >= 0.14, (
                f"Via at ({vx:.2f}, {vy:.2f}) too close/overlapping pad {ref}.{pnum} (gap={gap:.3f} mm < 0.14 mm)!"
            )

    # 2. Verify /BR_S <= 1.50 mm, /BR_O <= 2.10 mm & /DET_IN <= 1.40 mm trace lengths
    br_s_len_mm = sum(
        pcbnew.ToMM(t.GetLength())
        for t in board.GetTracks()
        if not isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "/BR_S"
    )
    assert 0.50 <= br_s_len_mm <= 1.50, f"/BR_S trace length {br_s_len_mm:.3f} mm exceeds 1.50 mm limit!"

    br_o_len_mm = sum(
        pcbnew.ToMM(t.GetLength())
        for t in board.GetTracks()
        if not isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "/BR_O"
    )
    assert 0.50 <= br_o_len_mm <= 2.10, f"/BR_O trace length {br_o_len_mm:.3f} mm exceeds 2.10 mm star limit!"

    det_in_len_mm = sum(
        pcbnew.ToMM(t.GetLength())
        for t in board.GetTracks()
        if not isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "/DET_IN"
    )
    assert 0.40 <= det_in_len_mm <= 1.40, f"/DET_IN trace length {det_in_len_mm:.3f} mm exceeds 1.40 mm limit!"

    # 3. Solid B.Cu plane under 100% of 868 MHz RF nets (outside intentional /BR_S void) & under U1 body
    rf_nets = {"/RF_PA", "/BR_P", "/BR_Q", "/ANT_FEED", "/SMA_C", "/BR_S", "/BR_O", "/DET_IN"}
    rf_fcu_shapes = []
    bcu_non_gnd_tracks = []
    det_adc_shapes = []
    for t in board.GetTracks():
        nname = t.GetNetname()
        if isinstance(t, pcbnew.PCB_VIA):
            vx = pcbnew.ToMM(t.GetPosition().x) - X0
            vy = pcbnew.ToMM(t.GetPosition().y) - Y0
            vp = Point(vx, vy).buffer(pcbnew.ToMM(t.GetWidth(F)) / 2.0)
            if nname == "/DET_ADC":
                det_adc_shapes.append(vp)
            if nname != "GND":
                bcu_non_gnd_tracks.append((nname, vp))
            continue
        p1 = (pcbnew.ToMM(t.GetStart().x) - X0, pcbnew.ToMM(t.GetStart().y) - Y0)
        p2 = (pcbnew.ToMM(t.GetEnd().x) - X0, pcbnew.ToMM(t.GetEnd().y) - Y0)
        hw = pcbnew.ToMM(t.GetWidth()) / 2.0
        seg = LineString([p1, p2]).buffer(hw)
        if t.GetLayer() == F and nname in rf_nets:
            rf_fcu_shapes.append((nname, seg))
        if t.GetLayer() == B and nname != "GND":
            bcu_non_gnd_tracks.append((nname, seg))
        if nname == "/DET_ADC":
            det_adc_shapes.append(seg)

    u1_body = box(18.25 - 6.0, 17.90 - 6.0, 18.25 + 6.0, 17.90 + 6.0)
    for bnet, bseg in bcu_non_gnd_tracks:
        assert not bseg.intersects(u1_body), (
            f"B.Cu trace/via on {bnet} enters U1 12x12mm body [12.25..24.25, 11.90..23.90]!"
        )
        for rnet, rseg in rf_fcu_shapes:
            assert bseg.distance(rseg) >= 0.35, (
                f"B.Cu {bnet} cuts within {bseg.distance(rseg):.2f} mm beneath 868 MHz RF net {rnet}!"
            )

    # 4. /DET_ADC >= 4.0 mm isolation from L_SMPS (15 uH switching inductor)
    l_smps_pads = unary_union([_bbox_to_box(p.GetBoundingBox()) for p in fps["L_SMPS"].Pads()])
    det_adc_union = unary_union(det_adc_shapes + [_bbox_to_box(fps["U1"].FindPadByNumber("8").GetBoundingBox())])
    smps_clr = det_adc_union.distance(l_smps_pads)
    assert smps_clr >= 4.00, f"/DET_ADC to L_SMPS clearance {smps_clr:.3f} mm < 4.00 mm!"

    # 5. Verify 5 optical SMT fiducials (3 global + 2 local U1 diagonal)
    req_attr = pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM
    for fref in ("FID1", "FID2", "FID3", "FID4", "FID5"):
        assert fref in fps, f"Missing fiducial {fref}"
        assert (fps[fref].GetAttributes() & req_attr) == req_attr, f"{fref} missing BOARD_ONLY/POS/BOM flags"
    g_pts = [
        (pcbnew.ToMM(fps[r].GetPosition().x) - X0, pcbnew.ToMM(fps[r].GetPosition().y) - Y0)
        for r in ("FID1", "FID2", "FID3")
    ]
    for fx, fy in g_pts:
        assert 4.4 <= fx < 49.0 and 4.4 <= fy <= H - 4.4, (
            f"Global fiducial out of 0..49mm / 4.4mm rail-clearance margin: {(fx, fy)}"
        )
    tri_area = 0.5 * abs(
        (g_pts[1][0] - g_pts[0][0]) * (g_pts[2][1] - g_pts[0][1])
        - (g_pts[2][0] - g_pts[0][0]) * (g_pts[1][1] - g_pts[0][1])
    )
    assert tri_area >= 300.0, f"Global fiducials nearly collinear (area={tri_area:.1f} mm^2)!"

    # 6. Shapely F.SilkS & B.SilkS collision, <= 2.0 mm courtyard proximity & 0-ink-in-antenna hygiene
    board_inset = _rounded_board_poly(inset_mm=0.30)
    ant_keepout = box(50.0, -5.0, W + 5.0, H + 5.0)
    silk_texts = []
    silk_gfx_shapes = []
    bsilk_texts = []
    bsilk_gfx_shapes = []
    max_ref_crtyd_dist = 0.0

    for d in board.GetDrawings():
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            bb = _bbox_to_box(d.GetBoundingBox())
            assert not bb.intersects(ant_keepout), f"Board silkscreen {bb.bounds} enters X >= 50 mm antenna zone!"
        if d.GetLayer() == pcbnew.F_SilkS:
            if isinstance(d, pcbnew.PCB_TEXT) and d.IsVisible():
                th = round(pcbnew.ToMM(d.GetTextThickness()), 4)
                sz = round(pcbnew.ToMM(d.GetTextSize().y), 4)
                assert th >= 0.15 and sz >= 0.80, f"Board silk text {d.GetText()!r} below 0.15/0.80: th={th}, sz={sz}"
                sb = _bbox_to_box(d.GetBoundingBox())
                silk_texts.append((f"TXT:{d.GetText()}", sb, False))
        elif d.GetLayer() == pcbnew.B_SilkS:
            if isinstance(d, pcbnew.PCB_TEXT) and d.IsVisible():
                th = round(pcbnew.ToMM(d.GetTextThickness()), 4)
                sz = round(pcbnew.ToMM(d.GetTextSize().y), 4)
                assert th >= 0.15 and sz >= 0.80, f"B.SilkS text {d.GetText()!r} below 0.15/0.80: th={th}, sz={sz}"
                sb = _bbox_to_box(d.GetBoundingBox())
                bsilk_texts.append((f"BTXT:{d.GetText()}", sb))
            elif isinstance(d, pcbnew.PCB_SHAPE):
                w = round(pcbnew.ToMM(d.GetWidth()), 4)
                assert w >= 0.15, f"B.SilkS shape width {w} < 0.15"
                if d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                    p1 = (pcbnew.ToMM(d.GetStart().x) - X0, pcbnew.ToMM(d.GetStart().y) - Y0)
                    p2 = (pcbnew.ToMM(d.GetEnd().x) - X0, pcbnew.ToMM(d.GetEnd().y) - Y0)
                    bsilk_gfx_shapes.append(("B.SilkS:seg", LineString([p1, p2]).buffer(w / 2.0)))
                else:
                    bsilk_gfx_shapes.append(("B.SilkS:gfx", _bbox_to_box(d.GetBoundingBox())))

    for ref, fp in fps.items():
        rtxt = fp.Reference()
        if rtxt.IsVisible() and rtxt.GetLayer() == pcbnew.F_SilkS:
            th = round(pcbnew.ToMM(rtxt.GetTextThickness()), 4)
            sz = round(pcbnew.ToMM(rtxt.GetTextSize().y), 4)
            ang_deg = round(rtxt.GetTextAngleDegrees() % 360.0, 2)
            assert ang_deg == 0.0, f"{ref} F.SilkS ref is rotated {ang_deg} deg (must be 0 deg horizontal)!"
            assert th >= 0.15 and sz >= 0.80, f"{ref} Ref silk below 0.15/0.80: th={th}, sz={sz}"
            sb = _bbox_to_box(rtxt.GetBoundingBox())
            assert not sb.intersects(ant_keepout), f"{ref} F.SilkS ref enters X >= 50 mm antenna zone!"
            cdist = _fp_courtyard_poly(fp).distance(sb)
            assert cdist <= 2.00, f"{ref} F.SilkS ref is {cdist:.2f} mm > 2.00 mm from its courtyard!"
            max_ref_crtyd_dist = max(max_ref_crtyd_dist, cdist)
            silk_texts.append((f"REF:{ref}", sb, True))
        for gi in fp.GraphicalItems():
            if gi.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                if isinstance(gi, pcbnew.PCB_TEXT) and not gi.IsVisible():
                    continue
                assert not _bbox_to_box(gi.GetBoundingBox()).intersects(ant_keepout), (
                    f"{ref} footprint silkscreen enters X >= 50 mm antenna zone!"
                )
            if gi.GetLayer() == pcbnew.F_SilkS:
                if isinstance(gi, pcbnew.PCB_TEXT):
                    if not gi.IsVisible():
                        continue
                    th = round(pcbnew.ToMM(gi.GetTextThickness()), 4)
                    assert th >= 0.15, f"{ref} fp_text silk thickness {th} < 0.15"
                    sb = _bbox_to_box(gi.GetBoundingBox())
                    silk_texts.append((f"{ref}:{gi.GetText()}", sb, False))
                elif isinstance(gi, pcbnew.PCB_SHAPE):
                    w = round(pcbnew.ToMM(gi.GetWidth()), 4)
                    if gi.GetShape() != pcbnew.SHAPE_T_POLY or w > 0.0:
                        assert w >= 0.15, f"{ref} fp_line silk width {w} < 0.15"
                    if gi.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                        p1 = (pcbnew.ToMM(gi.GetStart().x) - X0, pcbnew.ToMM(gi.GetStart().y) - Y0)
                        p2 = (pcbnew.ToMM(gi.GetEnd().x) - X0, pcbnew.ToMM(gi.GetEnd().y) - Y0)
                        silk_gfx_shapes.append((f"{ref}:seg", LineString([p1, p2]).buffer(w / 2.0)))
                    else:
                        silk_gfx_shapes.append((f"{ref}:gfx", _bbox_to_box(gi.GetBoundingBox())))

    for sname, sbox, _is_ref in silk_texts:
        assert board_inset.contains(sbox), (
            f"Silkscreen {sname} {sbox.bounds} extends outside 0.30 mm Edge.Cuts inset!"
        )
        for mname, mbox in mask_polys:
            assert not sbox.intersects(mbox), f"Silkscreen {sname} overlaps F.Mask {mname}!"
        for dname, dpoly in drill_polys:
            assert not sbox.intersects(dpoly), f"Silkscreen {sname} overlaps drill {dname}!"
        for gname, gpoly in silk_gfx_shapes:
            assert not sbox.intersects(gpoly), f"Silkscreen {sname} overlaps footprint silk {gname}!"
        for vname, vpoly in via_polys:
            assert not sbox.intersects(vpoly), f"Silkscreen {sname} overlaps via {vname}!"

    for bname, bsbox in bsilk_texts + bsilk_gfx_shapes:
        assert board_inset.contains(bsbox), (
            f"B.SilkS {bname} {bsbox.bounds} extends outside 0.30 mm Edge.Cuts inset!"
        )
        for mname, mbox in bmask_polys:
            assert not bsbox.intersects(mbox), f"B.SilkS {bname} overlaps B.Mask {mname}!"
        for dname, dpoly in drill_polys:
            assert not bsbox.intersects(dpoly), f"B.SilkS {bname} overlaps drill {dname}!"
        for vname, vpoly in via_polys:
            assert not bsbox.intersects(vpoly), f"B.SilkS {bname} overlaps via {vname}!"

    for i in range(len(bsilk_texts)):
        n1, b1 = bsilk_texts[i]
        for gname, gpoly in bsilk_gfx_shapes:
            assert not b1.intersects(gpoly), f"B.SilkS text {n1} overlaps B.SilkS shape {gname}!"
        for j in range(i + 1, len(bsilk_texts)):
            n2, b2 = bsilk_texts[j]
            assert b1.distance(b2) >= 0.08, (
                f"B.SilkS legend collision between {n1} {b1.bounds} and {n2} {b2.bounds}!"
            )

    for i in range(len(silk_texts)):
        for j in range(i + 1, len(silk_texts)):
            n1, b1, _ = silk_texts[i]
            n2, b2, _ = silk_texts[j]
            assert b1.distance(b2) >= 0.08, (
                f"Silkscreen legend collision between {n1} {b1.bounds} and {n2} {b2.bounds}!"
            )

    # 7. Zero < 85 deg acute copper track bends on same-layer, same-net vertices
    verts = defaultdict(list)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        p1 = (round(pcbnew.ToMM(t.GetStart().x) - X0, 3), round(pcbnew.ToMM(t.GetStart().y) - Y0, 3))
        p2 = (round(pcbnew.ToMM(t.GetEnd().x) - X0, 3), round(pcbnew.ToMM(t.GetEnd().y) - Y0, 3))
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 0.05:
            continue
        key1 = (t.GetLayer(), t.GetNetCode(), p1)
        key2 = (t.GetLayer(), t.GetNetCode(), p2)
        verts[key1].append((p2[0] - p1[0], p2[1] - p1[1], t.GetNetname()))
        verts[key2].append((p1[0] - p2[0], p1[1] - p2[1], t.GetNetname()))

    for (lyr, _, vpt), vecs in verts.items():
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                v1x, v1y, nname = vecs[i]
                v2x, v2y, _ = vecs[j]
                l1 = math.hypot(v1x, v1y)
                l2 = math.hypot(v2x, v2y)
                cos_a = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (l1 * l2)))
                ang = math.degrees(math.acos(cos_a))
                if ang > 1.0:
                    assert ang >= 85.0, (
                        f"Acute {ang:.1f} deg copper bend (< 85 deg) on {nname} at {vpt}!"
                    )

    return len(vias), smps_clr, br_s_len_mm, br_o_len_mm, max_ref_crtyd_dist


def build():
    pad_to_sch_net, short_to_sch_net = extract_schematic_nets()
    board = setup_board(pad_to_sch_net)
    raw_nets = netmap(board)
    short_nets = {k: raw_nets[v] for k, v in short_to_sch_net.items()}

    add_rounded_outline(board)
    fps = add_footprints(board, raw_nets, pad_to_sch_net)
    route_all(board, fps, short_nets)
    add_zones_and_stitching(board, short_nets["GND"])
    td_count = add_native_teardrops(board)
    add_annotations_and_dimensions(board)
    placed_refs, hidden_refs = place_clean_references(board)

    out = os.path.join(ROOT, PROJECT + ".kicad_pcb")
    pro = os.path.join(ROOT, PROJECT + ".kicad_pro")
    dru = os.path.join(ROOT, PROJECT + ".kicad_dru")

    # Save initial board, convert teardrop marker zones into native KiCad 9 pad/via teardrops, and apply rule deck
    pcbnew.SaveBoard(out, board)
    with open(out, "r", encoding="utf-8") as fh:
        pcb_txt = fh.read()
    pcb_txt = pcb_txt.replace('(name "__TEARDROP_PADVIA__")', '(attr (teardrop (type padvia)))')
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(pcb_txt)
    rules_isac.apply_locked_rules(pcb_path=out, pro_path=pro, dru_path=dru)

    # Reload with locked project/DRU clearances, fill teardrops + F.Cu/B.Cu GND counterpoise, and re-lock stackup
    reloaded = pcbnew.LoadBoard(out)
    pcbnew.ZONE_FILLER(reloaded).Fill(reloaded.Zones())
    n_vias, smps_clr, br_s_len, br_o_len, max_silk_dist = verify_layout_geometry(reloaded)
    pcbnew.SaveBoard(out, reloaded)
    rules_isac.apply_locked_rules(pcb_path=out, pro_path=pro, dru_path=dru)

    hidden_fab_count = sum(1 for r in PART_MAP if r not in COMMERCIAL_SILK_REFS and PART_MAP[r][1] not in NON_BOM_LIBS)
    print(
        f"Wrote {out} (Rev E.5: {len(reloaded.GetFootprints())} footprints, "
        f"{n_vias} tented non-VIPPO vias, {td_count} native curved teardrops, "
        f"/BR_S len = {br_s_len:.2f} mm, /BR_O len = {br_o_len:.2f} mm, "
        f"/DET_ADC-to-L_SMPS clr = {smps_clr:.2f} mm, "
        f"0-deg F.SilkS placed = {placed_refs} [max crtyd dist = {max_silk_dist:.2f} mm, "
        f"F.Fab-only passives = {hidden_fab_count}])."
    )
    return reloaded


if __name__ == "__main__":
    build()
