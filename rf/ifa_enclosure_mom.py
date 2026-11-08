#!/usr/bin/env python3
"""
ifa_enclosure_mom.py -- Full-Wave 3D Non-Uniform Yee-Grid Maxwell FDTD Solver &
                        4-Element Elliptic Low-Pass Harmonic Filter Co-Analysis
                        for ISAC_868 Rev E.5.

Methodology:
  1. Parses the copper segments and pad primitives directly from
     `ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod`.
  2. Constructs the 3D stackup in `rf/libfdtd_3d_ant.so` (OpenMP 3D Yee-grid
     FDTD with 8-cell Convolutional PML absorbing boundaries):
       - 50 x 40 mm finite F.Cu + B.Cu ground counterpoise with stitching vias
       - 1.51 mm FR-4 core (eps_r = 4.4, tan_d = 0.020; plus 4.2 / 4.6 corners)
       - 25 um 3M 467MP acrylic transfer adhesive (eps_r = 2.80) + 0.80 mm UV-stabilized
         ASA/PETG flush sensing window (eps_r = 3.05, tan_d = 0.012) + enclosure walls/base
       - Optional 302535 LiPo cell pouch (z = -3.60 mm under counterpoise X < 50 mm)
       - 2.00 mm superstrate layers across Dry Air, PTFE/Oil, Glaze Ice, Alumina, IPA, and Water
  3. Cascades the populated 4-element elliptic low-pass harmonic Pi-network
     (`C_M1 = 3.6 pF`, `L_M1 = 8.2 nH || C_MZ = 0.5 pF`, `C_M2 = 4.3 pF`) between `/BR_Q`
     and `/ANT_FEED`, evaluating:
       - Standalone (`/ANT_FEED`) & cascaded (`/BR_Q`) Enclosed Dry-Air |S11(866.5 MHz)| <= -14.0 dB
       - Harmonic suppression >= 28.0 dB at 2*f0 (1733.0 MHz) and >= 45.0 dB at 3*f0 (2599.5 MHz)
         across 50 Ohm, Dry-Air AE1, and Water-detuned AE1 loads.

Outputs:
  - rf/results/ifa_s11_efficiency.csv
  - rf/results/ifa_pi_match_tuning_table.csv
  - rf/results/ifa_fullwave_3d.json
  - rf/results/ifa_enclosure_mom.png
"""
from __future__ import annotations

import csv
import ctypes
import json
import math
import os
import re
import subprocess
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)

C_PATH = os.path.join(HERE, "fdtd_3d_ant.c")
SO_PATH = os.path.join(HERE, "libfdtd_3d_ant.so")
KICAD_MOD_PATH = os.path.join(ROOT, "ISAC.pretty", "IFA_868MHz_ISAC_40x20mm.kicad_mod")

EPS0 = 8.8541878128e-12
MU0 = 1.25663706212e-6
Z0 = 50.0

# Populated Rev E.5 4-Element Elliptic Low-Pass Harmonic Pi-Network
# Pre-distorted for 0.65 nH shunt 0402 pad+via ESL & LQW15AN8N2G00D 3.9 GHz SRF:
HARMONIC_PI_NOM = dict(
    c_m1_pf=3.6,       # Murata GJM1555C1H3R6WB01D (3.6 pF +/-0.05 pF 50V C0G)
    l_m1_nh=8.2,       # Murata LQW15AN8N2G00D     (8.2 nH +/-2% wirewound, Q>=42 @ 868 MHz, SRF>=3.9 GHz)
    c_mz_pf=0.50,      # Murata GJM1555C1HR50WB01D (0.50 pF +/-0.05 pF 50V C0G 2f0 notch zero)
    c_m2_pf=4.3,       # Murata GJM1555C1H4R3WB01D (4.3 pF +/-0.05 pF 50V C0G)
    q_ind_868=42.0,
    esl_shunt_nh=0.65, # 0402 body (0.35 nH) + pad/via-to-B.Cu loop (0.30 nH)
    srf_l1_ghz=3.90,   # Murata LQW15AN8N2G00D datasheet minimum self-resonant frequency
    esl_cmz_nh=0.25,   # 0402 piggyback C_MZ package series inductance
)


def enig_sheet_resistance_ohm(f_hz: float = 866.5e6) -> float:
    """
    First-principles IPC-4552 ENIG RF surface sheet resistance R_s(f) [Ohm/sq]:
      - 0.05 um immersion Au (rho = 2.44e-8 Ohm*m) over
      - 4.50 um electroless NiP (8.5 wt% P, rho = 7.5e-7 Ohm*m, mu_r = 2.0) over
      - 35.0 um electrodeposited Cu (1 oz, rho = 1.72e-8 Ohm*m).
    """
    w = 2.0 * math.pi * f_hz
    d_cu = math.sqrt(2.0 * 1.72e-8 / (w * MU0))
    zs_cu = complex(1.0, 1.0) * (1.72e-8 / d_cu)
    rho_ni, mur_ni, t_ni = 7.5e-7, 2.0, 4.5e-6
    d_ni = math.sqrt(2.0 * rho_ni / (w * MU0 * mur_ni))
    z0_ni = complex(1.0, 1.0) * (rho_ni / d_ni)
    gam_ni = complex(1.0, 1.0) / d_ni
    th_ni = np.tanh(gam_ni * t_ni)
    zs_ni_cu = z0_ni * (zs_cu + z0_ni * th_ni) / (z0_ni + zs_cu * th_ni)
    g_au = 0.05e-6 / 2.44e-8
    zs_tot = 1.0 / ((1.0 / zs_ni_cu) + g_au)
    return float(zs_tot.real)


def _load_fdtd_lib() -> ctypes.CDLL:
    need_build = (not os.path.isfile(SO_PATH)) or (
        os.path.getmtime(C_PATH) > os.path.getmtime(SO_PATH)
    )
    if need_build:
        subprocess.run(
            [
                "gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC",
                "-Wall", "-Wextra", "-Werror", C_PATH, "-o", SO_PATH, "-lm",
            ],
            check=True,
        )
    lib = ctypes.CDLL(SO_PATH)
    lib.fdtd_solve_port.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_double,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_double,
        ctypes.c_int, ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.fdtd_solve_port.restype = ctypes.c_int
    return lib


def parse_ae1_kicad_mod_gbr(mod_path: str = KICAD_MOD_PATH):
    """
    Parse exact F.Cu copper traces and pads directly from `IFA_868MHz_ISAC_40x20mm.kicad_mod`
    into Right-Handed Gerber coordinates (`X_gbr = 50.0 + x_fp`, `Y_gbr = 20.0 - y_fp`),
    plus the PCB counterpoise ground return ties (`x_fp = -1.5 -> 0.0`) at Pad 2 anchors.
    """
    with open(mod_path, "r", encoding="utf-8") as fh:
        txt = fh.read()

    def gbr(xf: float, yf: float) -> tuple[float, float]:
        return (50.0 + xf, 20.0 - yf)

    geoms = []
    gnd_vias_gbr: list[tuple[float, float]] = []

    # 1. Parse (fp_line ... (layer "F.Cu"))
    fp_line_pat = re.compile(
        r'\(fp_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+'
        r'\(stroke\s+\(width\s+([-\d.]+)\)\s+\(type\s+\w+\)\)\s+\(layer\s+"F\.Cu"\)'
    )
    fcu_seg_count = 0
    for m in fp_line_pat.finditer(txt):
        x1, y1, x2, y2, w = (float(m.group(k)) for k in range(1, 6))
        geoms.append(LineString([gbr(x1, y1), gbr(x2, y2)]).buffer(0.5 * w, cap_style=1, join_style=1))
        fcu_seg_count += 1

    # 2. Parse rectangular SMD pads on F.Cu
    rect_pad_pat = re.compile(
        r'\(pad\s+"(\d+)"\s+smd\s+rect\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)\s+'
        r'\(size\s+([-\d.]+)\s+([-\d.]+)\)\s+\(layers\s+"F\.Cu"\)'
    )
    for m in rect_pad_pat.finditer(txt):
        pnum = m.group(1)
        px, py, pw, ph = (float(m.group(k)) for k in range(2, 6))
        gx, gy = gbr(px, py)
        geoms.append(box(gx - 0.5 * pw, gy - 0.5 * ph, gx + 0.5 * pw, gy + 0.5 * ph))
        if pnum == "2":
            gnd_vias_gbr.append((gx, gy))
            # PCB F.Cu ground return strap from counterpoise X_gbr=48.5..50.0 into Pad 2
            geoms.append(LineString([gbr(-1.5, py), gbr(px, py)]).buffer(0.5 * max(ph, 2.0), cap_style=1))

    # 3. Parse custom Pad 2 return bar & grounded IDE fingers
    custom_pat = re.compile(
        r'\(pad\s+"2"\s+smd\s+custom\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)\s+'
        r'\(size\s+([-\d.]+)\s+([-\d.]+)\).*?\(primitives\s*(.*?)\n\t\t\)',
        re.S,
    )
    gr_line_pat = re.compile(
        r'\(gr_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+\(width\s+([-\d.]+)\)\)'
    )
    custom_seg_count = 0
    for m in custom_pat.finditer(txt):
        ax, ay, aw, ah = (float(m.group(k)) for k in range(1, 5))
        body = m.group(5)
        gx, gy = gbr(ax, ay)
        geoms.append(box(gx - 0.5 * aw, gy - 0.5 * ah, gx + 0.5 * aw, gy + 0.5 * ah))
        gnd_vias_gbr.append((gx, gy))
        geoms.append(LineString([gbr(-1.5, ay), gbr(ax, ay)]).buffer(0.5 * ah, cap_style=1))
        for gm in gr_line_pat.finditer(body):
            lx1, ly1, lx2, ly2, lw = (float(gm.group(k)) for k in range(1, 6))
            geoms.append(
                LineString([gbr(ax + lx1, ay + ly1), gbr(ax + lx2, ay + ly2)]).buffer(
                    0.5 * lw, cap_style=1, join_style=1
                )
            )
            custom_seg_count += 1

    assert fcu_seg_count >= 8 and custom_seg_count >= 4, (
        f"Failed to parse AE1 copper from {mod_path} (fcu={fcu_seg_count}, custom={custom_seg_count})"
    )
    return unary_union(geoms), gnd_vias_gbr


def eval_elliptic_pi_zin_and_s21(
    z_load: np.ndarray | complex,
    freqs: np.ndarray,
    c1_pf: float = HARMONIC_PI_NOM["c_m1_pf"],
    l1_nh: float = HARMONIC_PI_NOM["l_m1_nh"],
    cz_pf: float = HARMONIC_PI_NOM["c_mz_pf"],
    c2_pf: float = HARMONIC_PI_NOM["c_m2_pf"],
    q_ind_868: float = HARMONIC_PI_NOM["q_ind_868"],
    esl_shunt_nh: float = HARMONIC_PI_NOM["esl_shunt_nh"],
    srf_l1_ghz: float = HARMONIC_PI_NOM["srf_l1_ghz"],
    esl_cmz_nh: float = HARMONIC_PI_NOM["esl_cmz_nh"],
):
    """
    Evaluate input impedance Z_in(f) at `/BR_Q` and transducer power gain G_T(f) = P_deliv / P_avail
    across the parasitic-aware 4-element Elliptic Low-Pass Harmonic Pi-Network (`C_M1`, `L_M1 || C_MZ`,
    `C_M2`) including 0402 shunt pad+via ESL (`0.65 nH`), `L_M1` parasitic self-capacitance (`SRF = 3.9 GHz`),
    and `C_MZ` package ESL (`0.25 nH`) terminated in complex frequency-dependent antenna impedance `z_load(f)`.
    """
    w = 2.0 * np.pi * freqs
    q_f = q_ind_868 * np.sqrt(np.maximum(freqs, 100e6) / 866.5e6)
    l1 = l1_nh * 1e-9
    c_self = 1.0 / (((2.0 * math.pi * (srf_l1_ghz * 1e9)) ** 2) * l1)
    z_l1_core = 1j * w * l1 + (w * l1) / q_f
    y_ser = (1.0 / z_l1_core) + 1j * w * c_self
    if cz_pf > 1e-6:
        z_cmz = 0.06 + (1.0 / (1j * w * (cz_pf * 1e-12))) + 1j * w * (esl_cmz_nh * 1e-9)
        y_ser = y_ser + (1.0 / z_cmz)
    z_ser = 1.0 / y_ser

    y2 = 1.0 / z_load
    if c2_pf > 1e-6:
        z_c2 = 0.08 + (1.0 / (1j * w * (c2_pf * 1e-12))) + 1j * w * (esl_shunt_nh * 1e-9)
        y2 = y2 + (1.0 / z_c2)
    z2 = 1.0 / y2
    z_mid = z_ser + z2
    y_in = 1.0 / z_mid
    if c1_pf > 1e-6:
        z_c1 = 0.08 + (1.0 / (1j * w * (c1_pf * 1e-12))) + 1j * w * (esl_shunt_nh * 1e-9)
        y_in = y_in + (1.0 / z_c1)
    z_in = 1.0 / y_in

    # Voltage divider from Vs = 2 V (Z_source = 50 Ohm -> P_avail = |Vs|^2 / (8*Z0) = 1/100 W):
    v_brq = 2.0 * z_in / (Z0 + z_in)
    v_ant = v_brq * (z2 / z_mid)
    g_load = np.real(1.0 / z_load)
    # Time-average real power delivered into z_load (with Vs peak = 2V -> P = 0.5 * |V_ant|^2 * Re(Y_load),
    # while P_avail = |Vs|^2 / (8*Z0) = 4 / 400 = 0.01 W):
    p_deliv = 0.5 * (np.abs(v_ant) ** 2) * np.maximum(g_load, 0.0)
    p_avail = (2.0 ** 2) / (8.0 * Z0)
    gt_lin = np.maximum(p_deliv / p_avail, 1e-20)
    atten_db = -10.0 * np.log10(gt_lin)
    return z_in, atten_db


def solve_ae1_fullwave_fdtd(
    lib: ctypes.CDLL,
    poly_fcu,
    gnd_vias_gbr: list[tuple[float, float]],
    freqs: np.ndarray,
    enclosed: bool = True,
    include_lipo: bool = False,
    er_fr4: float = 4.4,
    er_sup: float = 1.0,
    ei_sup: float = 0.0,
    n_steps: int = 22000,
):
    """
    Execute a genuine 3D Non-Uniform Yee-Grid Maxwell FDTD simulation in `libfdtd_3d_ant.so`
    directly from Maxwell's curl equations (`curl E = -mu0 dH/dt`, `curl H = eps dE/dt + sigma E`).
    """
    xs_mm = np.unique(np.round(np.concatenate([
        -4.0 - np.arange(1, 10)[::-1] * 2.0,
        np.linspace(-4.0, 0.0, 4),
        np.linspace(0.0, 46.0, 26),
        np.linspace(46.0, 49.4, 5),
        [49.4, 50.0],
        np.linspace(50.0, 73.5, 34),
        np.linspace(73.5, 87.5, 29),   # 0.50 mm grid across bare-ENIG IDE comb
        np.linspace(87.5, 94.0, 8),
        94.0 + np.arange(1, 10) * 2.0,
    ]), 5))

    ys_mm = np.unique(np.round(np.concatenate([
        -4.0 - np.arange(1, 10)[::-1] * 2.0,
        np.linspace(-4.0, 7.4, 14),
        np.linspace(7.4, 20.6, 45),    # 0.30 mm uniform fine grid across IDE comb + feed
        np.linspace(20.6, 44.0, 24),
        44.0 + np.arange(1, 10) * 2.0,
    ]), 5))

    zs_mm = np.unique(np.round(np.concatenate([
        -9.6 - np.arange(1, 10)[::-1] * 2.0,
        [-9.6, -7.6, -5.6, -3.60],
        np.linspace(-3.60, -1.51, 4),
        np.linspace(-1.51, 0.0, 4),
        [0.0, 0.40, 0.80],
        np.linspace(0.80, 2.80, 5),
        [2.80, 4.50, 6.50, 8.50, 10.50],
        10.50 + np.arange(1, 10) * 2.0,
    ]), 5))

    x = xs_mm * 1e-3
    y = ys_mm * 1e-3
    z = zs_mm * 1e-3
    nx, ny, nz = len(x) - 1, len(y) - 1, len(z) - 1

    xc = 0.5 * (xs_mm[:-1] + xs_mm[1:])
    yc = 0.5 * (ys_mm[:-1] + ys_mm[1:])
    zc = 0.5 * (zs_mm[:-1] + zs_mm[1:])

    eps_r = np.ones((nz, ny, nx), dtype=np.float32)
    sigma = np.zeros((nz, ny, nx), dtype=np.float32)

    f0_loss = 866.5e6
    w0 = 2.0 * math.pi * f0_loss

    # 1.51 mm FR-4 PCB substrate (0..90 x 0..40 mm)
    in_pcb_x = (xc >= 0.0) & (xc <= 90.0)
    in_pcb_y = (yc >= 0.0) & (yc <= 40.0)
    in_fr4_z = (zc >= -1.51) & (zc <= 0.0)
    sig_fr4 = w0 * EPS0 * er_fr4 * 0.020
    for k in np.where(in_fr4_z)[0]:
        eps_r[k][np.ix_(in_pcb_y, in_pcb_x)] = er_fr4
        sigma[k][np.ix_(in_pcb_y, in_pcb_x)] = sig_fr4

    # Full UV-stabilized ASA/PETG Rev E.5 enclosure (2.60 mm walls, open-East self-draining Z=+0.80 mm runoff deck)
    if enclosed:
        er_asa = 3.05
        sig_asa = w0 * EPS0 * er_asa * 0.012
        in_out_x = (xc >= -2.60) & (xc <= 92.60)
        in_out_y = (yc >= -2.60) & (yc <= 42.60)
        in_in_x = (xc >= -0.25) & (xc <= 90.25)
        in_in_y = (yc >= -0.25) & (yc <= 40.25)
        wall_xy = np.outer(in_out_y, in_out_x) & (~np.outer(in_in_y, in_in_x))
        in_runoff = np.outer((yc >= 7.65) & (yc <= 20.20), (xc >= 74.60) & (xc <= 92.60))

        for k, zv in enumerate(zc):
            if -7.6 <= zv <= -5.6:
                eps_r[k][np.outer(in_out_y, in_out_x)] = er_asa
                sigma[k][np.outer(in_out_y, in_out_x)] = sig_asa
            elif -5.6 < zv < 8.5:
                w_mask = (wall_xy & (~in_runoff)) if zv > 0.80 else wall_xy
                eps_r[k][w_mask] = er_asa
                sigma[k][w_mask] = sig_asa
                if 0.0 < zv <= 0.80:
                    east_deck = np.outer((yc >= 6.85) & (yc <= 20.60), (xc >= 87.60) & (xc <= 92.60))
                    eps_r[k][east_deck] = er_asa
                    sigma[k][east_deck] = sig_asa

            if 6.5 <= zv <= 8.5:
                m_ec = np.outer(in_in_y, (xc >= -0.25) & (xc <= 50.0))
                eps_r[k][m_ec] = er_asa
                sigma[k][m_ec] = sig_asa

            if 4.5 <= zv <= 8.5:
                m_ar = np.outer(in_in_y, (xc >= 50.0) & (xc <= 90.25)) & (~in_runoff)
                eps_r[k][m_ar] = er_asa
                sigma[k][m_ar] = sig_asa

            if 0.0 <= zv <= 4.5:
                in_boss = np.outer((yc >= 6.85) & (yc <= 20.60), (xc >= 73.60) & (xc <= 87.60))
                if zv <= 0.80:
                    if zv <= 0.40:
                        # Series homogenized 25 um 3M 467MP acrylic tape (eps_r = 2.80) + ASA/PETG
                        f_tape = 0.025 / 0.40
                        er_eff = 1.0 / (f_tape / 2.80 + (1.0 - f_tape) / er_asa)
                        eps_r[k][in_boss] = er_eff
                    else:
                        eps_r[k][in_boss] = er_asa
                    sigma[k][in_boss] = sig_asa
                else:
                    collar = in_boss & (~in_runoff)
                    eps_r[k][collar] = er_asa
                    sigma[k][collar] = sig_asa

            if 0.80 < zv <= 2.80 and (er_sup > 1.0001 or ei_sup > 0.0):
                in_win = np.outer((yc >= 7.65) & (yc <= 20.20), (xc >= 74.60) & (xc <= 86.60))
                eps_r[k][in_win] = er_sup
                sigma[k][in_win] = w0 * EPS0 * ei_sup

    pec_ex = np.zeros((nz + 1, ny + 1, nx), dtype=np.uint8)
    pec_ey = np.zeros((nz + 1, ny, nx + 1), dtype=np.uint8)
    pec_ez = np.zeros((nz, ny + 1, nx + 1), dtype=np.uint8)

    k_bcu = int(np.argmin(np.abs(zs_mm - (-1.51))))
    k_fcu = int(np.argmin(np.abs(zs_mm - 0.0)))

    # Finite 50 x 40 mm B.Cu + F.Cu ground counterpoise
    bcu_ex_x = (xc >= 0.45) & (xc <= 50.00)
    bcu_ex_y = (ys_mm >= 0.45) & (ys_mm <= 39.55)
    pec_ex[k_bcu][np.ix_(bcu_ex_y, bcu_ex_x)] = 1
    bcu_ey_x = (xs_mm >= 0.45) & (xs_mm <= 50.00)
    bcu_ey_y = (yc >= 0.45) & (yc <= 39.55)
    pec_ey[k_bcu][np.ix_(bcu_ey_y, bcu_ey_x)] = 1

    fcu_ex_x = (xc >= 0.45) & (xc <= 49.40)
    pec_ex[k_fcu][np.ix_(bcu_ex_y, fcu_ex_x)] = 1
    fcu_ey_x = (xs_mm >= 0.45) & (xs_mm <= 49.40)
    pec_ey[k_fcu][np.ix_(bcu_ey_y, fcu_ey_x)] = 1

    # Optional 302535 LiPo conductive aluminum-laminate pouch at z = -3.60 mm under counterpoise
    if include_lipo:
        k_lipo = int(np.argmin(np.abs(zs_mm - (-3.60))))
        lx_ex = (xc >= 10.0) & (xc <= 45.0)
        ly_ex = (ys_mm >= 8.0) & (ys_mm <= 33.0)
        pec_ex[k_lipo][np.ix_(ly_ex, lx_ex)] = 1
        lx_ey = (xs_mm >= 10.0) & (xs_mm <= 45.0)
        ly_ey = (yc >= 8.0) & (yc <= 33.0)
        pec_ey[k_lipo][np.ix_(ly_ey, lx_ey)] = 1

    # Rasterize exact parsed AE1 F.Cu polygon
    for j, yv in enumerate(ys_mm):
        if -1.0 <= yv <= 41.0:
            for i, xv in enumerate(xc):
                if 48.0 <= xv <= 90.0 and poly_fcu.covers(Point(xv, yv)):
                    pec_ex[k_fcu, j, i] = 1
    for j, yv in enumerate(yc):
        if -1.0 <= yv <= 41.0:
            for i, xv in enumerate(xs_mm):
                if 48.0 <= xv <= 90.0 and poly_fcu.covers(Point(xv, yv)):
                    pec_ey[k_fcu, j, i] = 1

    # Counterpoise East-edge stitching fence vias + AE1 Pad 2 return vias
    i_494 = int(np.argmin(np.abs(xs_mm - 49.40)))
    for y_via in [2.0, 5.5, 9.0, 12.5, 16.0, 18.0, 22.0, 26.0, 30.0, 34.0, 38.0]:
        jv = int(np.argmin(np.abs(ys_mm - y_via)))
        pec_ez[k_bcu:k_fcu, jv, i_494] = 1

    for vx, vy in gnd_vias_gbr:
        iv = int(np.argmin(np.abs(xs_mm - vx)))
        jv = int(np.argmin(np.abs(ys_mm - vy)))
        for dj in (-1, 0, 1):
            if 0 <= jv + dj <= ny:
                pec_ez[k_bcu:k_fcu, jv + dj, iv] = 1

    # 50-Ohm lumped coaxial/CPWG launch port across counterpoise gap X_gbr = 49.40 -> 50.00 at Pad 1 (Y_gbr = 20.00)
    p_i = i_494
    j_slot0 = int(np.argmin(np.abs(ys_mm - 18.50)))
    j_slot1 = int(np.argmin(np.abs(ys_mm - 21.50))) + 1
    for j in range(j_slot0, j_slot1):
        pec_ex[k_fcu, j, p_i] = 0
    for j in range(j_slot0, j_slot1 - 1):
        pec_ey[k_fcu, j, p_i] = 0

    p_j0 = int(np.argmin(np.abs(ys_mm - 19.50)))
    p_j1 = int(np.argmin(np.abs(ys_mm - 20.50))) + 1
    for j in range(p_j0, p_j1):
        pec_ex[k_fcu, j, p_i + 1] = 1
    for j in range(p_j0, p_j1 - 1):
        pec_ey[k_fcu, j, p_i] = 1
        pec_ey[k_fcu, j, p_i + 1] = 1
    for j in range(p_j0, p_j1):
        pec_ez[k_bcu:k_fcu, j, p_i] = 1

    nf = len(freqs)
    vr, vi, ir, ii, reff = [np.zeros(nf, dtype=np.float64) for _ in range(5)]

    rs_enig = enig_sheet_resistance_ohm(866.5e6)
    rc = lib.fdtd_solve_port(
        nx, ny, nz,
        x.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        y.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        z.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        eps_r.ravel().ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        sigma.ravel().ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        pec_ex.ravel().ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        pec_ey.ravel().ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        pec_ez.ravel().ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        rs_enig,
        0, p_i, p_j0, p_j1, k_fcu, k_fcu + 1,
        Z0, n_steps, 8, 1000e6, 900e6, nf,
        freqs.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        vr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        vi.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ir.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ii.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        reff.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )
    assert rc == 0, f"fdtd_solve_port returned error code {rc}"
    z_ant = (vr + 1j * vi) / (ir + 1j * ii)
    # Clamp numerical radiation efficiency to physical [0.01, 0.99]
    eta_rad = np.clip(reff, 0.01, 0.99)
    return z_ant, eta_rad


def synthesize_pi_match(z_load: complex, f_hz: float, q_net: float = 1.4) -> dict[str, float]:
    """Synthesize standard 3-element low-pass VNA post-fab Pi-match (`C_MZ` unpopulated)."""
    w = 2.0 * math.pi * f_hz
    y_load = 1.0 / z_load
    g_l = max(1e-5, float(np.real(y_load)))
    b_l = float(np.imag(y_load))
    r_p = 1.0 / g_l
    r_min = min(Z0, r_p)
    r_v = r_min / (1.0 + q_net * q_net)
    q1 = math.sqrt(max(0.01, Z0 / r_v - 1.0))
    q2 = math.sqrt(max(0.01, r_p / r_v - 1.0))
    b_c1 = q1 / Z0
    b_c2_added = (q2 / r_p) - b_l
    x_l_series = r_v * (q1 + q2)
    return {
        "C_M1_pF": round(max(0.0, (b_c1 / w) * 1e12), 2),
        "L_M1_nH": round(max(0.0, (x_l_series / w) * 1e9), 2),
        "C_MZ_pF": 0.0,
        "C_M2_pF": round(max(0.0, (b_c2_added / w) * 1e12), 2),
    }


def run_full_ifa_audit() -> None:
    t_start = time.time()
    print("Compiling/loading 3D Non-Uniform Yee-Grid Maxwell FDTD solver (libfdtd_3d_ant.so)...")
    lib = _load_fdtd_lib()
    poly_fcu, gnd_vias_gbr = parse_ae1_kicad_mod_gbr(KICAD_MOD_PATH)

    # Wide frequency vector spanning 730..940 MHz + exact ISAC tones + 2f0 & 3f0 harmonics
    freqs_band = np.linspace(730.0e6, 940.0e6, 421)
    freqs_special = np.array([
        863.1e6, 866.5e6, 868.1e6, 868.3e6, 868.5e6, 869.5e6, 869.525e6,
        1726.2e6, 1733.0e6, 1739.0e6,
        2589.3e6, 2599.5e6, 2608.5e6,
    ])
    freqs = np.unique(np.round(np.concatenate([freqs_band, freqs_special]), 1))

    band_mask = freqs <= 940.0e6
    eu_mask = (freqs >= 863.0e6) & (freqs <= 870.0e6)
    idx_863 = int(np.argmin(np.abs(freqs - 863.1e6)))
    idx_866 = int(np.argmin(np.abs(freqs - 866.5e6)))
    idx_869 = int(np.argmin(np.abs(freqs - 869.5e6)))
    idx_2f0 = int(np.argmin(np.abs(freqs - 1733.0e6)))
    idx_3f0 = int(np.argmin(np.abs(freqs - 2599.5e6)))

    scenarios = [
        ("1_Bare_PCB_FreeSpace (no lid)",                 False, False, 4.4, 1.0,  0.0,    "bare"),
        ("2_Enclosed_Nom_0p80mm_ASA (er=4.4, Dry Air)",   True,  False, 4.4, 1.0,  0.0,    "dry air"),
        ("3_Enclosed_With_302535_LiPo_Under_GND",         True,  True,  4.4, 1.0,  0.0,    "lipo"),
        ("4_Enclosed_FR4_Low_er4p2",                      True,  False, 4.2, 1.0,  0.0,    "fr4_low"),
        ("5_Enclosed_FR4_High_er4p6",                     True,  False, 4.6, 1.0,  0.0,    "fr4_high"),
        ("6_PTFE_Oil_on_0p80mm_Window (eps*=2.1-j0.0002)",True,  False, 4.4, 2.1,  0.0002, "PTFE"),
        ("7_Glaze_Ice_on_0p80mm_Window (eps*=3.2-j0.003)",True,  False, 4.4, 3.2,  0.003,  "glaze ice"),
        ("8_Alumina_on_0p80mm_Window (eps*=9.8-j0.002)",  True,  False, 4.4, 9.8,  0.002,  "alumina Al2O3"),
        ("9_IPA_on_0p80mm_Window (eps*=6.29-j6.09)",      True,  False, 4.4, 6.29, 6.09,   "IPA (868 MHz)"),
        ("10_Water_Film_on_Window (eps*=79.9-j3.81)",     True,  False, 4.4, 79.9, 3.81,   "water film"),
    ]

    summary_rows = []
    curves = {}
    fullwave_export = {
        "solver": "3D Non-Uniform Yee-Grid Maxwell FDTD (rf/fdtd_3d_ant.c, 8-cell CPML, ENIG Rs + Volumetric Loss DFT, 22000 steps)",
        "footprint": "ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod",
        "surface_finish": f"IPC-4552 ENIG (Rs_866p5 = {enig_sheet_resistance_ohm(866.5e6)*1e3:.2f} mOhm/sq)",
        "window_material": "UV-stabilized ASA/PETG (0.80 mm flush open-East runoff deck + 25 um 3M 467MP transfer adhesive)",
        "harmonic_pi_network": HARMONIC_PI_NOM,
        "media": {},
    }

    for sc_name, encl, lipo, er_sub, er_sup, ei_sup, medium_key in scenarios:
        t0 = time.time()
        z_ant, eta_rad = solve_ae1_fullwave_fdtd(
            lib, poly_fcu, gnd_vias_gbr, freqs,
            enclosed=encl, include_lipo=lipo, er_fr4=er_sub, er_sup=er_sup, ei_sup=ei_sup, n_steps=22000,
        )
        z_casc, harm_atten_db = eval_elliptic_pi_zin_and_s21(z_ant, freqs)

        gam_raw = np.abs((z_ant - Z0) / (z_ant + Z0))
        s11_raw_db = 20.0 * np.log10(gam_raw + 1e-30)

        gam_casc = np.abs((z_casc - Z0) / (z_casc + Z0))
        s11_casc_db = 20.0 * np.log10(gam_casc + 1e-30)

        # Total efficiency including harmonic pi-network insertion loss + mismatch
        gt_fund = 10.0 ** (-harm_atten_db / 10.0)
        eta_tot = eta_rad * gt_fund

        s11_band = s11_raw_db[band_mask]
        f_band = freqs[band_mask]
        idx_min = int(np.argmin(s11_band))
        f_res_mhz = float(f_band[idx_min] / 1e6)
        min_s11_db = float(s11_band[idx_min])

        bw10 = f_band[s11_band <= -10.0]
        bw10_mhz = float((bw10[-1] - bw10[0]) / 1e6) if len(bw10) > 1 else 0.0

        curves[sc_name] = (s11_raw_db[band_mask], eta_tot[band_mask] * 100.0, z_ant, z_casc, harm_atten_db)

        row = {
            "scenario": sc_name,
            "f_res_MHz": round(f_res_mhz, 2),
            "min_s11_dB": round(min_s11_db, 2),
            "worst_s11_863_870_dB": round(float(np.max(s11_casc_db[eu_mask])), 2),
            "s11_866p5_raw_dB": round(float(s11_raw_db[idx_866]), 2),
            "s11_866p5_dB": round(float(s11_casc_db[idx_866]), 2),
            "bw_minus10dB_MHz": round(bw10_mhz, 2),
            "eta_rad_866p5_pct": round(float(eta_rad[idx_866] * 100.0), 1),
            "eta_tot_866p5_pct": round(float(eta_tot[idx_866] * 100.0), 1),
            "eta_tot_866p5_dB": round(10.0 * math.log10(float(eta_tot[idx_866]) + 1e-30), 2),
            "harm_atten_2f0_dB": round(float(harm_atten_db[idx_2f0]), 2),
            "harm_atten_3f0_dB": round(float(harm_atten_db[idx_3f0]), 2),
        }
        summary_rows.append(row)

        fullwave_export["media"][medium_key] = {
            "scenario": sc_name,
            "eps_real": er_sup,
            "eps_imag": ei_sup,
            "f0_MHz": round(f_res_mhz, 2),
            "min_s11_dB": round(min_s11_db, 2),
            "s11_866p5_raw_dB": round(float(s11_raw_db[idx_866]), 2),
            "s11_866p5_cascaded_dB": round(float(s11_casc_db[idx_866]), 2),
            "worst_s11_863_870_dB": round(float(np.max(s11_casc_db[eu_mask])), 2),
            "eta_rad_pct": round(float(eta_rad[idx_866] * 100.0), 1),
            "eta_tot_pct": round(float(eta_tot[idx_866] * 100.0), 1),
            "z_ant_tones_ohm": [
                [round(float(z_ant[i].real), 3), round(float(z_ant[i].imag), 3)]
                for i in (idx_863, idx_866, idx_869)
            ],
            "z_brq_tones_ohm": [
                [round(float(z_casc[i].real), 3), round(float(z_casc[i].imag), 3)]
                for i in (idx_863, idx_866, idx_869)
            ],
            "harm_atten_2f0_dB": round(float(harm_atten_db[idx_2f0]), 2),
            "harm_atten_3f0_dB": round(float(harm_atten_db[idx_3f0]), 2),
        }
        print(
            f"  [{time.time()-t0:5.1f}s] {sc_name:49s} | f0={f_res_mhz:6.2f} MHz | "
            f"|S11|_866.5={s11_raw_db[idx_866]:6.2f} dB (casc {s11_casc_db[idx_866]:6.2f} dB) | "
            f"2f0={harm_atten_db[idx_2f0]:5.1f} dB | 3f0={harm_atten_db[idx_3f0]:5.1f} dB"
        )

    # Also evaluate 50-Ohm reference harmonic suppression
    _, harm_50_db = eval_elliptic_pi_zin_and_s21(np.full_like(freqs, Z0, dtype=complex), freqs)
    fullwave_export["harmonic_50R_2f0_dB"] = round(float(harm_50_db[idx_2f0]), 2)
    fullwave_export["harmonic_50R_3f0_dB"] = round(float(harm_50_db[idx_3f0]), 2)

    s11_csv = os.path.join(OUT_DIR, "ifa_s11_efficiency.csv")
    with open(s11_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)

    fw_json = os.path.join(OUT_DIR, "ifa_fullwave_3d.json")
    with open(fw_json, "w", encoding="utf-8") as fh:
        json.dump(fullwave_export, fh, indent=2)
        fh.write("\n")

    # Post-fab VNA Pi-match tuning table across +/-20 MHz shift on the real 3D FDTD dry-air curve
    z_dry_full = curves["2_Enclosed_Nom_0p80mm_ASA (er=4.4, Dry Air)"][2]
    f_band_hz = freqs[band_mask]
    z_dry_band = z_dry_full[band_mask]
    tuning_rows = []
    for shift_mhz in (-20.0, -12.0, -6.0, 0.0, +6.0, +12.0, +20.0):
        # Interpolate frequency-shifted physical 3D FDTD impedance Z_dry(f - shift)
        f_query = np.clip(f_band_hz - shift_mhz * 1e6, f_band_hz[0], f_band_hz[-1])
        z_shifted = np.interp(f_query, f_band_hz, z_dry_band.real) + 1j * np.interp(
            f_query, f_band_hz, z_dry_band.imag
        )
        i866_b = int(np.argmin(np.abs(f_band_hz - 866.5e6)))
        eu_b = (f_band_hz >= 863.0e6) & (f_band_hz <= 870.0e6)
        z_866 = complex(z_shifted[i866_b])
        if abs(shift_mhz) < 1e-6:
            c1 = HARMONIC_PI_NOM["c_m1_pf"]
            l1 = HARMONIC_PI_NOM["l_m1_nh"]
            cz = HARMONIC_PI_NOM["c_mz_pf"]
            c2 = HARMONIC_PI_NOM["c_m2_pf"]
            note = "Nominal Rev E.5 Populated Elliptic Harmonic Pi-Network (C_M1=3.6p, L_M1=8.2n||C_MZ=0.5p, C_M2=4.3p)"
        else:
            pm = synthesize_pi_match(z_866, 866.5e6, q_net=1.4)
            c1, l1, cz, c2 = pm["C_M1_pF"], pm["L_M1_nH"], pm["C_MZ_pF"], pm["C_M2_pF"]
            note = "Post-VNA 0402 Murata GJM1555C1H / LQW15AN trim (C_MZ DNP)"
        zin_m, _ = eval_elliptic_pi_zin_and_s21(z_shifted, f_band_hz, c1, l1, cz, c2)
        s11_m = 20.0 * np.log10(np.abs((zin_m - Z0) / (zin_m + Z0)) + 1e-30)
        tuning_rows.append({
            "unmatched_f0_shift_MHz": shift_mhz,
            "unmatched_Z_866p5_ohm": f"{z_866.real:.1f}{z_866.imag:+.1f}j",
            "C_M1_pF": c1,
            "L_M1_nH": l1,
            "C_MZ_pF": cz,
            "C_M2_pF": c2,
            "matched_s11_866p5_dB": round(float(s11_m[i866_b]), 2),
            "matched_worst_s11_863_870_dB": round(float(np.max(s11_m[eu_b])), 2),
            "bom_action": note,
        })

    tune_csv = os.path.join(OUT_DIR, "ifa_pi_match_tuning_table.csv")
    with open(tune_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tuning_rows[0].keys()))
        w.writeheader()
        w.writerows(tuning_rows)

    # Plot 2-panel validation figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.4), dpi=160)
    f_mhz = freqs[band_mask] / 1e6
    plot_styles = [
        ("1_Bare_PCB_FreeSpace (no lid)",                  "#78909c", "--"),
        ("2_Enclosed_Nom_0p80mm_ASA (er=4.4, Dry Air)",    "#0d47a1", "-"),
        ("3_Enclosed_With_302535_LiPo_Under_GND",          "#2e7d32", ":"),
        ("6_PTFE_Oil_on_0p80mm_Window (eps*=2.1-j0.0002)", "#6a1b9a", "-."),
        ("7_Glaze_Ice_on_0p80mm_Window (eps*=3.2-j0.003)", "#00acc1", "-"),
        ("9_IPA_on_0p80mm_Window (eps*=6.29-j6.09)",       "#fb8c00", "--"),
        ("10_Water_Film_on_Window (eps*=79.9-j3.81)",      "#c62828", "-"),
    ]
    for sc_name, col, ls in plot_styles:
        ax1.plot(f_mhz, curves[sc_name][0], lw=1.8, color=col, ls=ls, label=sc_name.split("_", 1)[1])
    ax1.axvspan(863.0, 870.0, color="#fff59d", alpha=0.45, label="EU868 Band (863-870 MHz)")
    ax1.axhline(-14.0, color="#1b5e20", ls="--", lw=1.0, label="-14 dB Spec @ 866.5 MHz")
    ax1.set_xlim(750, 925)
    ax1.set_ylim(-36, 0)
    ax1.set_xlabel("Frequency (MHz)")
    ax1.set_ylabel("Standalone 3D-FDTD |S11| (dB)")
    ax1.set_title("A. Full-Wave 3D Maxwell FDTD |S11(f)| Across Superstrates")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=6.3, loc="lower left")

    for sc_name, col, ls in plot_styles:
        ax2.plot(f_mhz, curves[sc_name][1], lw=1.8, color=col, ls=ls, label=sc_name.split("_", 1)[1])
    ax2.axvspan(863.0, 870.0, color="#fff59d", alpha=0.45)
    ax2.set_xlim(750, 925)
    ax2.set_ylim(0, 92)
    ax2.set_xlabel("Frequency (MHz)")
    ax2.set_ylabel("System Total Efficiency eta_tot (%)")
    ax2.set_title("B. Total Efficiency (3D-FDTD + Populated Harmonic Pi-Filter)")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=6.3, loc="lower left")

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "ifa_enclosure_mom.png"), bbox_inches="tight")
    plt.close(fig)

    # Mandatory Rev E.5 Acceptance Gate Assertions
    nom_row = summary_rows[1]
    bat_row = summary_rows[2]
    er42_row = summary_rows[3]
    er46_row = summary_rows[4]
    water_row = summary_rows[-1]
    assert nom_row["s11_866p5_raw_dB"] <= -14.0, (
        f"Standalone 3D-FDTD Dry-Air |S11|(866.5 MHz) = {nom_row['s11_866p5_raw_dB']} dB > -14.0 dB!"
    )
    assert nom_row["s11_866p5_dB"] <= -14.0, (
        f"Filter-cascaded Dry-Air |S11|(866.5 MHz) = {nom_row['s11_866p5_dB']} dB > -14.0 dB!"
    )
    for corner_label, r_chk in [
        ("Enclosed er=4.4 Dry Air", nom_row),
        ("Enclosed LiPo Dry Air", bat_row),
        ("Enclosed FR-4 er=4.2 Low Corner", er42_row),
        ("Enclosed FR-4 er=4.6 High Corner", er46_row),
    ]:
        assert r_chk["worst_s11_863_870_dB"] <= -10.0, (
            f"({corner_label}) — EU868 worst |S11| = {r_chk['worst_s11_863_870_dB']} dB > -10.0 dB!"
        )
    assert 35.0 <= nom_row["eta_rad_866p5_pct"] <= 62.0, (
        f"Unexpected ENIG+FR4+ASA radiation efficiency {nom_row['eta_rad_866p5_pct']}%"
    )
    for tag, h2, h3 in [
        ("50-Ohm", float(harm_50_db[idx_2f0]), float(harm_50_db[idx_3f0])),
        ("Dry-Air AE1", nom_row["harm_atten_2f0_dB"], nom_row["harm_atten_3f0_dB"]),
        ("Water-Detuned AE1", water_row["harm_atten_2f0_dB"], water_row["harm_atten_3f0_dB"]),
    ]:
        assert h2 >= 28.0, f"({tag}) — parasitic-aware 2f0 suppression {h2:.2f} dB < 28.0 dB!"
        assert h3 >= 45.0, f"({tag}) — parasitic-aware 3f0 suppression {h3:.2f} dB < 45.0 dB!"

    print(
        f"[PASS] Full-Wave 3D Maxwell FDTD + Parasitic-Aware Elliptic Harmonic Filter Audit ({time.time()-t_start:.1f}s):\n"
        f"  Enclosed 0.80mm ASA Dry : f0 = {nom_row['f_res_MHz']:.2f} MHz, "
        f"|S11|(866.5) = {nom_row['s11_866p5_raw_dB']:.2f} dB raw / {nom_row['s11_866p5_dB']:.2f} dB cascaded (<= -14 dB), "
        f"eta_rad = {nom_row['eta_rad_866p5_pct']:.1f}%, eta_tot = {nom_row['eta_tot_866p5_pct']:.1f}%\n"
        f"  FR-4 Corners (863-870)  : er=4.2 worst |S11| = {er42_row['worst_s11_863_870_dB']:.2f} dB | "
        f"er=4.4 = {nom_row['worst_s11_863_870_dB']:.2f} dB | er=4.6 = {er46_row['worst_s11_863_870_dB']:.2f} dB (all <= -10.0 dB)\n"
        f"  Harmonic Rejection      : 2f0 = {nom_row['harm_atten_2f0_dB']:.1f} dB (Dry) / "
        f"{water_row['harm_atten_2f0_dB']:.1f} dB (Water, >= 28 dB); "
        f"3f0 = {nom_row['harm_atten_3f0_dB']:.1f} dB (Dry) / {water_row['harm_atten_3f0_dB']:.1f} dB (Water, >= 45 dB)."
    )


if __name__ == "__main__":
    run_full_ifa_audit()
