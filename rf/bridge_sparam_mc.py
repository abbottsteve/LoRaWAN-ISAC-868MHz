#!/usr/bin/env python3
"""
bridge_sparam_mc.py -- Complex 2-Port S-Parameter, Distributed Microstrip [Y]-Matrix,
                       3D Stratified Laplace Parasitic Extraction & 2,000-Trial Monte-Carlo
                       Solver for the ISAC Rev E.5 Return-Loss Bridge.

Model Summary:
  1. PCB Copper Length Extraction & Distributed Lossy Microstrip [Y] Network:
     - Reads physical trace lengths directly from `ISAC_868_KiCad9.kicad_pcb` via `pcbnew`
       (`/BR_S = 1.44 mm`, `/BR_O = 2.05 mm` 4-branch star, `/DET_IN = 1.28 mm`).
     - Embeds Hammerstad-Jensen lossy microstrip 2-port `[Y]` matrices (IPC-4552 ENIG
       sheet resistance R_s(866.5 MHz) = 23.74 mOhm/sq and FR-4 tan_d = 0.020) for `/BR_O` and
       `/DET_IN`, giving 24.81 dB nominal 50-Ohm directivity at 866.5 MHz with `R_TERM = 56.0 Ohm`
       (`Susumu RG1005P-560-B-T5`, 0.1%).
  2. +4.0 dBm CW Sensing Sweep & 2-Point Factory Calibration:
     - Runs the 3-tone CW sensing sweep at P_TX = +4.0 dBm (+14.0 dBm retained for LoRaWAN TX),
       keeping LT5538 input power <= -25.4 dBm across all media (> 12 dB below the -13 dBm
       compression point).
     - Models 2-point factory calibration (`cal_dry_mv[3]` dry-air tare + `cal_ref_cdb`
       high-reflection Al2O3 reference offset in `isac_provision_t.cal_ref_cdb`) with
       `(Notch, Tilt, Level_cal)` classification:
       * Water vs. IPA 1st-percentile (`P01`) separation: 0.65 dB (>= 0.50 dB target),
         yielding 99.72% Water-vs-IPA separation across 2,000 Monte-Carlo trials.

Outputs:
  - rf/results/bridge_sparam_sweep.csv
  - rf/results/bridge_mc_summary.csv
  - rf/results/bridge_3tone_curves.json
  - rf/results/bridge_sparam_mc.png
"""
from __future__ import annotations

import cmath
import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)

Z0 = 50.0
P_TX_DBM = 4.0  # Rev E.5 linear LT5538 operating point (+4.0 dBm CW sensing; +14.0 dBm LoRaWAN TX)
K_SLOPE = 19.0e-3
P_INT = -88.8
V_FLOOR = 0.12
TONE_FREQS_HZ = (863.1e6, 866.5e6, 869.5e6)
C0_M_S = 299792458.0
RS_ENIG_866P5_OHM_SQ = 0.02374  # IPC-4552 ENIG (5 um NiP + 0.08 um Au) RF sheet resistance


def extract_live_pcb_bridge_lengths_mm() -> dict[str, float]:
    """Extract live physical F.Cu/B.Cu copper lengths of bridge nets from `ISAC_868_KiCad9.kicad_pcb`."""
    pcb_path = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")
    if not os.path.isfile(pcb_path):
        raise FileNotFoundError(f"Missing {pcb_path}; run `python3 tools/gen_pcb.py` first!")
    board = pcbnew.LoadBoard(pcb_path)
    nets = ("/BR_P", "/BR_Q", "/BR_S", "/BR_O", "/DET_IN")
    lengths_mm: dict[str, float] = {}
    for net in nets:
        total_mm = sum(
            t.GetLength() * 1e-6
            for t in board.GetTracks()
            if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net
        )
        lengths_mm[net] = round(float(total_mm), 3)

    assert lengths_mm["/BR_S"] <= 1.50, f"/BR_S copper length {lengths_mm['/BR_S']} mm > 1.50 mm!"
    assert lengths_mm["/BR_O"] <= 2.15, f"/BR_O copper length {lengths_mm['/BR_O']} mm > 2.15 mm!"
    assert lengths_mm["/DET_IN"] <= 1.40, f"/DET_IN copper length {lengths_mm['/DET_IN']} mm > 1.40 mm!"
    return lengths_mm


def microstrip_two_port_y(
    f_hz: float,
    w_mm: float,
    l_mm: float,
    h_core_mm: float = 1.51,
    er: float = 4.4,
    tan_d: float = 0.020,
) -> tuple[complex, complex]:
    """
    Hammerstad-Jensen lossy microstrip 2-port nodal `[Y]` parameters `(y11, y12)` on 1.51 mm FR-4
    core with IPC-4552 ENIG conductor loss and substrate dielectric loss.
    """
    if l_mm <= 1e-6:
        return 1e9 + 0j, -1e9 + 0j
    u = w_mm / h_core_mm
    eeff = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (
        (1.0 + 12.0 / u) ** -0.5 + (0.04 * ((1.0 - u) ** 2) if u < 1.0 else 0.0)
    )
    if u <= 1.0:
        z0_line = (60.0 / math.sqrt(eeff)) * math.log(8.0 / u + 0.25 * u)
    else:
        z0_line = (120.0 * math.pi / math.sqrt(eeff)) / (u + 1.393 + 0.667 * math.log(u + 1.444))
    beta = 2.0 * math.pi * f_hz * math.sqrt(eeff) / C0_M_S
    rs = RS_ENIG_866P5_OHM_SQ * math.sqrt(f_hz / 866.5e6)
    alpha_c = rs / (z0_line * (w_mm * 1e-3))
    alpha_d = 0.5 * beta * (er / eeff) * ((eeff - 1.0) / (er - 1.0)) * tan_d
    gl = complex(alpha_c + alpha_d, beta) * (l_mm * 1e-3)
    y0_line = 1.0 / z0_line
    return y0_line / cmath.tanh(gl), -y0_line / cmath.sinh(gl)


def extract_brs_parasitic_cap_3d_fvm(void_xy_mm: float = 2.20) -> float:
    """
    Solve 3D stratified Finite-Volume Laplace equation div(eps(z) grad(Phi)) = 0 with open
    Neumann outer boundaries for the compacted `/BR_S` micro-cluster (`<= 1.50 mm` trace
    + inner 0402 pad landings) centered over a `void_xy_mm x void_xy_mm` copper keepout void
    on BOTH F.Cu (z = 0.0 mm) and B.Cu (z = -1.51 mm FR-4 core, er = 4.4).
    Returns mutual shunt capacitance C_par(/BR_S -> GND) in Farads.
    """
    eps0 = 8.8541878128e-12
    h = 0.20e-3
    xs = np.arange(-5.0, 5.01, 0.20)
    ys = np.arange(-5.0, 5.01, 0.20)
    zs = np.arange(-4.6, 3.41, 0.20)
    nx, ny, nz = len(xs), len(ys), len(zs)
    iz_fcu = int(round((0.0 - zs[0]) / 0.20))
    iz_bcu = int(round((-1.60 - zs[0]) / 0.20))

    zc = 0.5 * (zs[:-1] + zs[1:])
    eps_z = np.where((zc > -1.60) & (zc < 0.0), 4.4, 1.0)
    eps_xy = 0.5 * (eps_z[1:] + eps_z[:-1])
    w_tot = 4.0 * eps_xy + eps_z[1:] + eps_z[:-1]

    v_half = 0.5 * void_xy_mm
    s_mask = np.zeros((nx, ny), dtype=bool)
    g_mask = np.zeros((nx, ny), dtype=bool)
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            if abs(x) <= 0.55 and abs(y) <= 0.45:
                s_mask[i, j] = True
            elif not (abs(x) <= v_half and abs(y) <= v_half):
                g_mask[i, j] = True

    phi = np.zeros((nx, ny, nz))
    fixed = np.zeros((nx, ny, nz), dtype=bool)
    fixed[s_mask, iz_fcu] = True
    phi[s_mask, iz_fcu] = 0.5
    fixed[g_mask, iz_fcu] = True
    phi[g_mask, iz_fcu] = -0.5
    fixed[g_mask, iz_bcu] = True
    phi[g_mask, iz_bcu] = -0.5

    ix = np.arange(1, nx - 1)[:, None, None]
    iy = np.arange(1, ny - 1)[None, :, None]
    iz = np.arange(1, nz - 1)[None, None, :]
    rb0 = ((ix + iy + iz) % 2 == 0) & (~fixed[1:-1, 1:-1, 1:-1])
    rb1 = ((ix + iy + iz) % 2 == 1) & (~fixed[1:-1, 1:-1, 1:-1])

    for _ in range(700):
        phi[0, :, :] = phi[1, :, :]
        phi[-1, :, :] = phi[-2, :, :]
        phi[:, 0, :] = phi[:, 1, :]
        phi[:, -1, :] = phi[:, -2, :]
        phi[:, :, 0] = phi[:, :, 1]
        phi[:, :, -1] = phi[:, :, -2]
        phi[s_mask, iz_fcu] = 0.5
        phi[g_mask, iz_fcu] = -0.5
        phi[g_mask, iz_bcu] = -0.5
        for rb in (rb0, rb1):
            nb = (
                eps_xy[None, None, :]
                * (
                    phi[2:, 1:-1, 1:-1]
                    + phi[:-2, 1:-1, 1:-1]
                    + phi[1:-1, 2:, 1:-1]
                    + phi[1:-1, :-2, 1:-1]
                )
                + eps_z[None, None, 1:] * phi[1:-1, 1:-1, 2:]
                + eps_z[None, None, :-1] * phi[1:-1, 1:-1, :-2]
            ) / w_tot[None, None, :]
            phi[1:-1, 1:-1, 1:-1][rb] = -0.82 * phi[1:-1, 1:-1, 1:-1][rb] + 1.82 * nb[rb]

    ex2 = 0.25 * (
        (phi[1:, :-1, :-1] - phi[:-1, :-1, :-1]) ** 2
        + (phi[1:, 1:, :-1] - phi[:-1, 1:, :-1]) ** 2
        + (phi[1:, :-1, 1:] - phi[:-1, :-1, 1:]) ** 2
        + (phi[1:, 1:, 1:] - phi[1:, :-1, 1:]) ** 2
    ) / (h * h)
    # Exact symmetric cell-edge E_x^2 formula:
    ex2 = 0.25 * (
        (phi[1:, :-1, :-1] - phi[:-1, :-1, :-1]) ** 2
        + (phi[1:, 1:, :-1] - phi[:-1, 1:, :-1]) ** 2
        + (phi[1:, :-1, 1:] - phi[:-1, :-1, 1:]) ** 2
        + (phi[1:, 1:, 1:] - phi[:-1, 1:, 1:]) ** 2
    ) / (h * h)
    ey2 = 0.25 * (
        (phi[:-1, 1:, :-1] - phi[:-1, :-1, :-1]) ** 2
        + (phi[1:, 1:, :-1] - phi[1:, :-1, :-1]) ** 2
        + (phi[:-1, 1:, 1:] - phi[:-1, :-1, 1:]) ** 2
        + (phi[1:, 1:, 1:] - phi[1:, :-1, 1:]) ** 2
    ) / (h * h)
    ez2 = 0.25 * (
        (phi[:-1, :-1, 1:] - phi[:-1, :-1, :-1]) ** 2
        + (phi[1:, :-1, 1:] - phi[1:, :-1, :-1]) ** 2
        + (phi[:-1, 1:, 1:] - phi[:-1, 1:, :-1]) ** 2
        + (phi[1:, 1:, 1:] - phi[1:, 1:, :-1]) ** 2
    ) / (h * h)
    return float(np.sum(eps0 * eps_z[None, None, :] * (ex2 + ey2 + ez2)) * (h ** 3))


PCB_BRIDGE_LENS_MM = extract_live_pcb_bridge_lengths_mm()
C_PAR_BRS_F = extract_brs_parasitic_cap_3d_fvm(2.20)

# Nominal Rev E.5 BOM values (R1 = Yageo RT0402BRD078R2L 8.2R 0.1% Thin Film;
# R_TERM = Susumu RG1005P-560-B-T5 56R 0.1% Thin Film;
# U2 LT5538IDD#PBF IN+ Table 1 interpolated at 866.5 MHz: 63.48 - j120.35 Ohm series == 291.65 Ohm || 1.194 pF)
LT5538_ZIN_800MHZ = 69.3 - 127.4j
LT5538_ZIN_1000MHZ = 51.8 - 106.2j
_t_866 = (866.5 - 800.0) / (1000.0 - 800.0)
LT5538_ZIN_866P5_SERIES = LT5538_ZIN_800MHZ + _t_866 * (LT5538_ZIN_1000MHZ - LT5538_ZIN_800MHZ)
_y_det_866 = 1.0 / LT5538_ZIN_866P5_SERIES
LT5538_RDET_PAR_OHM = round(float(1.0 / _y_det_866.real), 2)
LT5538_CDET_PAR_F = float(_y_det_866.imag / (2.0 * math.pi * 866.5e6))

NOM = dict(
    r1=8.2,
    r2=681.0,
    r3=3570.0,
    rterm=56.0,
    cs=1.0e-12,
    cs2=1.0e-12,
    lq=27.0e-9,
    ls=30.0e-9,
    crf=100.0e-12,
    cblk=100.0e-12,
    q_ind=42.0,
    c_pad=0.14e-12,
    c_par_brs=C_PAR_BRS_F,
    r_det=LT5538_RDET_PAR_OHM,
    c_det=LT5538_CDET_PAR_F,
    l_bro_mm=round(0.5 * PCB_BRIDGE_LENS_MM["/BR_O"], 4),
    l_det_in_mm=PCB_BRIDGE_LENS_MM["/DET_IN"],
    h_core_mm=1.51,
    er_sub=4.4,
)


def _solve_nodal(
    f_hz: float,
    p: dict,
    z_port1: complex | None = 50.0,
    vs_port1: complex = 0.0,
    z_port2: complex | None = 50.0,
    vs_port2: complex = 0.0,
) -> np.ndarray:
    """
    8-node complex nodal + distributed microstrip `[Y]` solve:
      0: PA_PORT     (left of C_RF)
      1: BR_P        (right of C_RF, left of R1 & R2)
      2: BR_Q        (antenna port, right of R1, top of L_Q & C_S)
      3: BR_S        (phase divider node between R2, R3||C_S2, and L_S over 2.2x2.2mm F/B void)
      4: BR_O_STAR   (4-branch summing star apex between C_S, L_S, and R_TERM)
      5: BR_O_CBLK   (distributed 0.42 mm microstrip trunk to C_BLK.1)
      6: DET_IN_CBLK (right pad of C_BLK)
      7: DET_IN_PAD  (distributed 0.35 mm microstrip launch to LT5538 Pin 2 IN+)
    """
    w = 2.0 * math.pi * f_hz
    Y = np.zeros((8, 8), dtype=complex)
    I = np.zeros(8, dtype=complex)

    def connect(a: int, b: int, y_adm: complex) -> None:
        Y[a, a] += y_adm
        Y[b, b] += y_adm
        Y[a, b] -= y_adm
        Y[b, a] -= y_adm

    def connect_tline(a: int, b: int, w_mm: float, l_mm: float) -> None:
        y11, y12 = microstrip_two_port_y(
            f_hz,
            w_mm=w_mm,
            l_mm=l_mm,
            h_core_mm=p.get("h_core_mm", 1.51),
            er=p.get("er_sub", 4.4),
        )
        Y[a, a] += y11
        Y[b, b] += y11
        Y[a, b] += y12
        Y[b, a] += y12

    if z_port1 is not None:
        Y[0, 0] += 1.0 / z_port1
        I[0] += vs_port1 / z_port1

    connect(0, 1, 1j * w * p["crf"])
    Y[1, 1] += 1j * w * p["c_pad"]

    connect(1, 2, 1.0 / p["r1"])
    connect(1, 3, 1.0 / p["r2"])
    c_brs = p.get("c_par_brs", p["c_pad"])
    Y[3, 3] += 1.0 / p["r3"] + 1j * w * (p["cs2"] + c_brs)

    z_lq = 1j * w * p["lq"] + (w * p["lq"]) / p["q_ind"]
    Y[2, 2] += 1.0 / z_lq + 1j * w * p["c_pad"]

    if z_port2 is not None:
        Y[2, 2] += 1.0 / z_port2
        I[2] += vs_port2 / z_port2

    connect(2, 4, 1j * w * p["cs"])
    z_ls = 1j * w * p["ls"] + (w * p["ls"]) / p["q_ind"]
    connect(3, 4, 1.0 / z_ls)

    Y[4, 4] += 1.0 / p["rterm"] + 0.5j * w * p["c_pad"]
    connect_tline(4, 5, 0.42, p["l_bro_mm"])
    Y[5, 5] += 0.5j * w * p["c_pad"]
    connect(5, 6, 1j * w * p["cblk"])
    connect_tline(6, 7, 0.35, p["l_det_in_mm"])
    Y[7, 7] += 1.0 / p["r_det"] + 1j * w * p["c_det"]

    return np.linalg.solve(Y, I)


def two_port_sparams(f_hz: float, p: dict) -> tuple[complex, complex, complex, complex]:
    v_fwd = _solve_nodal(f_hz, p, z_port1=Z0, vs_port1=2.0, z_port2=Z0, vs_port2=0.0)
    s11 = v_fwd[0] - 1.0
    s21 = v_fwd[2]

    v_rev = _solve_nodal(f_hz, p, z_port1=Z0, vs_port1=0.0, z_port2=Z0, vs_port2=2.0)
    s12 = v_rev[0]
    s22 = v_rev[2] - 1.0
    return s11, s21, s12, s22


def det_vout_for_zant(
    f_hz: float,
    z_ant: complex,
    p: dict,
    p_tx_dbm: float = P_TX_DBM,
    p_int_dbm: float = P_INT,
) -> tuple[float, float]:
    p_avail_w = (10.0 ** (p_tx_dbm / 10.0)) * 1e-3
    vs_pk = math.sqrt(8.0 * Z0 * p_avail_w)
    v = _solve_nodal(f_hz, p, z_port1=Z0, vs_port1=vs_pk, z_port2=z_ant, vs_port2=0.0)
    v_det = abs(v[7])
    p_det_dbm = 10.0 * math.log10((v_det ** 2) / (2.0 * Z0) / 1e-3 + 1e-30)
    v_out = float(np.clip(K_SLOPE * (p_det_dbm - p_int_dbm), V_FLOOR, 2.50))
    return p_det_dbm, v_out


def bridge_metrics(f_hz: float, p: dict) -> dict[str, float]:
    s11, s21, s12, s22 = two_port_sparams(f_hz, p)
    p_null_dbm, v_null = det_vout_for_zant(f_hz, Z0, p)
    p_open_dbm, _ = det_vout_for_zant(f_hz, 1.0e7, p)
    p_short_dbm, _ = det_vout_for_zant(f_hz, 1.0e-4, p)
    dir_db = min(p_open_dbm, p_short_dbm) - p_null_dbm
    return {
        "s11_dB": 20.0 * math.log10(abs(s11) + 1e-30),
        "s21_dB": 20.0 * math.log10(abs(s21) + 1e-30),
        "s12_dB": 20.0 * math.log10(abs(s12) + 1e-30),
        "s22_dB": 20.0 * math.log10(abs(s22) + 1e-30),
        "null_50R_dBm": p_null_dbm,
        "vout_50R_V": v_null,
        "directivity_wc_dB": dir_db,
    }


def run_bridge_analysis() -> None:
    fw_path = os.path.join(OUT_DIR, "ifa_fullwave_3d.json")
    if not os.path.isfile(fw_path):
        raise FileNotFoundError(
            f"Missing {fw_path}; run `python3 rf/ifa_enclosure_mom.py` first!"
        )
    with open(fw_path, "r", encoding="utf-8") as fh:
        fw_data = json.load(fh)

    assert C_PAR_BRS_F < 0.15e-12, (
        f"Extracted C_par(/BR_S) = {C_PAR_BRS_F*1e12:.4f} pF exceeds 0.15 pF limit!"
    )

    # Verify R1 +/-0.5% alternate tolerance impact (+/-0.041 Ohm on 8.2 Ohm)
    nom_866 = bridge_metrics(866.5e6, NOM)
    r1_det_nulls, r1_s21_drifts = [], []
    for delta_ohm in (-0.041, +0.041):
        p_alt = dict(NOM)
        p_alt["r1"] = 8.2 + delta_ohm
        m_alt = bridge_metrics(866.5e6, p_alt)
        r1_det_nulls.append(m_alt["directivity_wc_dB"])
        r1_s21_drifts.append(abs(m_alt["s21_dB"] - nom_866["s21_dB"]))
    assert min(r1_det_nulls) >= 24.0, f"R1 +/-0.5% point-null {min(r1_det_nulls):.2f} dB < 24.0 dB!"
    assert max(r1_s21_drifts) < 0.01, f"R1 +/-0.5% S21 drift {max(r1_s21_drifts):.4f} dB >= 0.01 dB!"

    # Compare ensemble RSS directivity between R1=0.1% and R1=0.5% alternates
    mc_r1_compare = {}
    for r1_tol_test in (0.001, 0.005):
        rng_r1 = np.random.default_rng(20261105)
        d_list = []
        for _ in range(2000):
            tr = dict(NOM)
            tr["r1"] = NOM["r1"] * (1.0 + rng_r1.normal(0.0, r1_tol_test / 3.0))
            for rk in ("r2", "r3", "rterm"):
                tr[rk] = NOM[rk] * (1.0 + rng_r1.normal(0.0, 0.001 / 3.0))
            for lk in ("lq", "ls"):
                tr[lk] = NOM[lk] * (1.0 + rng_r1.normal(0.0, 0.02 / 3.0))
            for ck in ("cs", "cs2"):
                tr[ck] = max(0.2e-12, NOM[ck] + rng_r1.normal(0.0, 0.05e-12 / 3.0))
            tr["q_ind"] = max(12.0, NOM["q_ind"] * (1.0 + rng_r1.normal(0.0, 0.10 / 3.0)))
            tr["c_pad"] = max(0.05e-12, NOM["c_pad"] + rng_r1.normal(0.0, 0.02e-12 / 3.0))
            tr["c_par_brs"] = max(0.05e-12, NOM["c_par_brs"] + rng_r1.normal(0.0, 0.015e-12 / 3.0))
            d_list.append(bridge_metrics(866.5e6, tr)["directivity_wc_dB"])
        arr_d = np.array(d_list)
        mc_r1_compare[r1_tol_test] = (
            float(np.mean(arr_d)),
            float(np.median(arr_d)),
            float(np.percentile(arr_d, 10)),
            float(np.percentile(arr_d, 5)),
        )
    max_r1_0p5pct_impact_db = max(
        abs(mc_r1_compare[0.005][i] - mc_r1_compare[0.001][i]) for i in range(4)
    )
    assert max_r1_0p5pct_impact_db < 0.05, (
        f"R1 +/-0.5% (+/-0.041 Ohm) ensemble directivity impact {max_r1_0p5pct_impact_db:.4f} dB >= 0.05 dB!"
    )

    freqs = np.linspace(850.0e6, 890.0e6, 81)
    sweep_rows = []
    for f in freqs:
        m = bridge_metrics(float(f), NOM)
        sweep_rows.append({"freq_MHz": round(float(f) / 1e6, 2), **{k: round(v, 3) for k, v in m.items()}})

    sweep_csv = os.path.join(OUT_DIR, "bridge_sparam_sweep.csv")
    with open(sweep_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sweep_rows[0].keys()))
        w.writeheader()
        w.writerows(sweep_rows)

    # Full-wave 3D FDTD cascaded impedances at BR_Q (zero hardcoded antenna constants!)
    media_z = {
        k: [complex(r, x) for r, x in fw_data["media"][k]["z_brq_tones_ohm"]]
        for k in ("dry air", "PTFE", "glaze ice", "alumina Al2O3", "IPA (868 MHz)", "water film")
    }
    z_ant_air_866 = media_z["dry air"][1]
    z_ant_ice_866 = media_z["glaze ice"][1]

    _, v_nom_air_866 = det_vout_for_zant(866.5e6, z_ant_air_866, NOM)
    p_nom_air_lin_866 = 10.0 ** (((v_nom_air_866 / K_SLOPE) + P_INT) / 10.0)
    nom_ref_lvl_dbm = sum(
        (det_vout_for_zant(f, z, NOM)[1] / K_SLOPE) + P_INT
        for f, z in zip(TONE_FREQS_HZ, media_z["alumina Al2O3"])
    ) / 3.0

    # Monte-Carlo N = 2,000 trials at 866.5 MHz + 2-point calibrated 3-tone classification
    rng = np.random.default_rng(20261105)
    n_mc = 2000

    configs = [
        (
            "RevE5_Precision_BOM_2PtCal (0.1% Thin-Film R, 2% Wirewound L, +/-0.05pF C0G + 2-Pt Factory Cal)",
            0.001, 0.02, 0.05e-12, 0.10, True,
        ),
        (
            "RevE5_Precision_BOM_Uncalibrated (0.1% Thin-Film R, 2% Wirewound L, +/-0.05pF C0G, Raw)",
            0.001, 0.02, 0.05e-12, 0.10, False,
        ),
        (
            "Counterfactual_Generic_5pct (5% Thick-Film R, 5% Multilayer L, +/-0.25pF C, Raw)",
            0.050, 0.05, 0.25e-12, 0.25, False,
        ),
    ]

    mc_summary_rows = []
    mc_traces = {}
    cal_water_ipa_gaps_db = []
    cal_water_ipa_ok = 0
    cal_hazard4_ok = 0

    for label, r_tol, l_tol, c_abs_tol, q_tol, use_2pt in configs:
        dirs, s21s, s11s, nulls, ice_contrasts = [], [], [], [], []
        for _ in range(n_mc):
            trial = dict(NOM)
            for rk in ("r1", "r2", "r3", "rterm"):
                trial[rk] = NOM[rk] * (1.0 + rng.normal(0.0, r_tol / 3.0))
            for lk in ("lq", "ls"):
                trial[lk] = NOM[lk] * (1.0 + rng.normal(0.0, l_tol / 3.0))
            for ck in ("cs", "cs2"):
                trial[ck] = max(0.2e-12, NOM[ck] + rng.normal(0.0, c_abs_tol / 3.0))
            trial["q_ind"] = max(12.0, NOM["q_ind"] * (1.0 + rng.normal(0.0, q_tol / 3.0)))
            trial["c_pad"] = max(0.05e-12, NOM["c_pad"] + rng.normal(0.0, 0.02e-12 / 3.0))
            trial["c_par_brs"] = max(0.05e-12, NOM["c_par_brs"] + rng.normal(0.0, 0.015e-12 / 3.0))
            trial["r_det"] = NOM["r_det"] * (1.0 + rng.normal(0.0, 0.10 / 3.0))
            trial["c_det"] = max(0.8e-12, NOM["c_det"] + rng.normal(0.0, 0.15e-12 / 3.0))

            m = bridge_metrics(866.5e6, trial)
            p_air_dbm, v_air = det_vout_for_zant(866.5e6, z_ant_air_866, trial)
            p_ice_dbm, v_ice = det_vout_for_zant(866.5e6, z_ant_ice_866, trial)

            if use_2pt:
                p_tx_u = P_TX_DBM + rng.normal(0.0, 1.0 / 3.0)
                p_int_u = P_INT + rng.normal(0.0, 1.5 / 3.0)

                # Point 1: Factory dry-air baseline `cal_dry_mv[3]`
                cal_dry_mv_3 = [
                    round(det_vout_for_zant(f, z, trial, p_tx_u, p_int_u)[1] * 1000.0 + rng.normal(0.0, 0.4))
                    for f, z in zip(TONE_FREQS_HZ, media_z["dry air"])
                ]
                # Point 2: Factory high-reflection ceramic reference `cal_ref_cdb`
                ref_mv_3 = [
                    det_vout_for_zant(f, z, trial, p_tx_u, p_int_u)[1] * 1000.0 + rng.normal(0.0, 0.4)
                    for f, z in zip(TONE_FREQS_HZ, media_z["alumina Al2O3"])
                ]
                cal_ref_db = round(
                    sum((v * 1e-3 / K_SLOPE) + P_INT for v in ref_mv_3) / 3.0 - nom_ref_lvl_dbm,
                    2,
                )

                # Tared 866.5 MHz Air-to-Ice contrast with common-mode offset removed
                cal_f2_db = ((cal_dry_mv_3[1] * 1e-3) / K_SLOPE + P_INT) - cal_ref_db
                p_cal_lin = 10.0 ** (cal_f2_db / 10.0)
                p_tare_lin = p_cal_lin - p_nom_air_lin_866

                va_m_mv = det_vout_for_zant(866.5e6, z_ant_air_866, trial, p_tx_u, p_int_u)[1] * 1000.0 + rng.normal(0.0, 0.4)
                vi_m_mv = det_vout_for_zant(866.5e6, z_ant_ice_866, trial, p_tx_u, p_int_u)[1] * 1000.0 + rng.normal(0.0, 0.4)
                pa_m_lin = 10.0 ** ((((va_m_mv * 1e-3) / K_SLOPE + P_INT) - cal_ref_db) / 10.0)
                pi_m_lin = 10.0 ** ((((vi_m_mv * 1e-3) / K_SLOPE + P_INT) - cal_ref_db) / 10.0)
                pa_corr = max(0.25 * p_nom_air_lin_866, pa_m_lin - p_tare_lin)
                pi_corr = max(0.25 * p_nom_air_lin_866, pi_m_lin)
                contrast_db = 10.0 * math.log10(pi_corr / pa_corr)

                # Evaluate 2-point calibrated 2D (Notch/DryDelta, Tilt, Level_cal) classifier
                lvl_by_m = {}
                for mname in ("dry air", "glaze ice", "IPA (868 MHz)", "water film"):
                    m_mv = [
                        det_vout_for_zant(f, z, trial, p_tx_u, p_int_u)[1] * 1000.0 + rng.normal(0.0, 0.4)
                        for f, z in zip(TONE_FREQS_HZ, media_z[mname])
                    ]
                    max_ddry_mv = max(abs(m_mv[i] - cal_dry_mv_3[i]) for i in range(3))
                    tilt_db_m = ((m_mv[0] - m_mv[2]) * 1e-3) / K_SLOPE
                    lvl_cal_m = sum((v * 1e-3 / K_SLOPE) + P_INT for v in m_mv) / 3.0 - cal_ref_db
                    lvl_by_m[mname] = lvl_cal_m

                    if max_ddry_mv <= 15.0:
                        pred = "dry air"
                    elif lvl_cal_m < -31.15:
                        pred = "PTFE"
                    elif tilt_db_m <= 0.84:
                        pred = "glaze ice"
                    elif lvl_cal_m >= -26.94:
                        pred = "water film"
                    else:
                        pred = "IPA (868 MHz)"

                    if pred == mname:
                        cal_hazard4_ok += 1
                        if mname in ("water film", "IPA (868 MHz)"):
                            cal_water_ipa_ok += 1

                cal_water_ipa_gaps_db.append(lvl_by_m["water film"] - lvl_by_m["IPA (868 MHz)"])
            else:
                contrast_db = p_ice_dbm - p_air_dbm

            dirs.append(m["directivity_wc_dB"])
            s21s.append(m["s21_dB"])
            s11s.append(m["s11_dB"])
            nulls.append(m["null_50R_dBm"])
            ice_contrasts.append(contrast_db)

        dirs_a = np.array(dirs)
        s21_a = np.array(s21s)
        s11_a = np.array(s11s)
        ice_a = np.array(ice_contrasts)
        mc_traces[label] = dirs_a
        mc_summary_rows.append({
            "bom_grade": label,
            "trials": n_mc,
            "s21_median_dB": round(float(np.median(s21_a)), 3),
            "s21_p01_dB": round(float(np.percentile(s21_a, 1)), 3),
            "s11_median_dB": round(float(np.median(s11_a)), 2),
            "s11_p99_dB": round(float(np.percentile(s11_a, 99)), 2),
            "directivity_median_dB": round(float(np.median(dirs_a)), 2),
            "directivity_p10_dB": round(float(np.percentile(dirs_a, 10)), 2),
            "directivity_p05_dB": round(float(np.percentile(dirs_a, 5)), 2),
            "air_to_ice_contrast_median_dB": round(float(np.median(ice_a)), 2),
            "air_to_ice_contrast_p01_dB": round(float(np.percentile(ice_a, 1)), 2),
            "yield_ice_contrast_gt_6dB_pct": round(float(np.mean(ice_a >= 6.0) * 100.0), 2),
        })

    mc_csv = os.path.join(OUT_DIR, "bridge_mc_summary.csv")
    with open(mc_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(mc_summary_rows[0].keys()))
        w.writeheader()
        w.writerows(mc_summary_rows)

    gaps_arr = np.array(cal_water_ipa_gaps_db)
    water_ipa_gap_med_db = round(float(np.median(gaps_arr)), 3)
    water_ipa_gap_p01_db = round(float(np.percentile(gaps_arr, 1)), 3)
    water_ipa_yield_pct = round(100.0 * cal_water_ipa_ok / (2.0 * n_mc), 2)
    hazard4_yield_pct = round(100.0 * cal_hazard4_ok / (4.0 * n_mc), 2)

    assert water_ipa_gap_p01_db >= 0.50, (
        f"2-pt calibrated Water vs IPA P01 separation {water_ipa_gap_p01_db:.3f} dB < 0.50 dB!"
    )
    assert water_ipa_yield_pct >= 99.0, (
        f"2-pt calibrated Water vs IPA yield {water_ipa_yield_pct:.2f}% < 99.0%!"
    )
    assert hazard4_yield_pct >= 99.0, (
        f"2-pt calibrated 4-hazard yield {hazard4_yield_pct:.2f}% < 99.0%!"
    )

    # Compute exact 3-tone benchmark curves at +4.0 dBm across all 6 sensing media
    media_order = [
        ("dry air", "dry air"),
        ("PTFE", "PTFE"),
        ("glaze ice", "glaze ice"),
        ("alumina Al2O3", "alumina Al2O3"),
        ("IPA (868 MHz)", "IPA (868 MHz)"),
        ("water film", "water film"),
    ]
    curves_table = []
    max_p_det_dbm = -200.0
    for json_key, display_name in media_order:
        md = fw_data["media"][json_key]
        z_tones = [complex(r, x) for r, x in md["z_brq_tones_ohm"]]
        p_dets, v_outs = [], []
        for f_hz, z_l in zip(TONE_FREQS_HZ, z_tones):
            pd_dbm, vo_v = det_vout_for_zant(f_hz, z_l, NOM, p_tx_dbm=P_TX_DBM)
            p_dets.append(round(pd_dbm, 4))
            v_outs.append(round(vo_v, 4))
            max_p_det_dbm = max(max_p_det_dbm, pd_dbm)
        tilt_db = round((v_outs[0] - v_outs[2]) / K_SLOPE, 2)
        notch_db = round(((0.5 * (v_outs[0] + v_outs[2])) - v_outs[1]) / K_SLOPE, 2)
        p_from_v = [(v / K_SLOPE) + P_INT for v in v_outs]
        level_dbm = round(sum(p_from_v) / 3.0, 2)
        s11_tones = [
            round(20.0 * math.log10(abs((z_l - Z0) / (z_l + Z0)) + 1e-30), 2)
            for z_l in z_tones
        ]
        curves_table.append({
            "medium": display_name,
            "eps_real": md["eps_real"],
            "eps_imag": md["eps_imag"],
            "f_res_MHz": md["f0_MHz"],
            "df_MHz": round(md["f0_MHz"] - fw_data["media"]["dry air"]["f0_MHz"], 2),
            "s11_dB": s11_tones,
            "p_det_dBm": p_dets,
            "vout_v": v_outs,
            "tilt_dB": tilt_db,
            "notch_dB": notch_db,
            "level_dBm": level_dbm,
        })

    assert max_p_det_dbm <= -20.0, (
        f"Max LT5538 detector input {max_p_det_dbm:.2f} dBm exceeds -20.0 dBm linear ceiling!"
    )

    # 2L FR-4 core-thickness tolerance sensitivity sweep (1.51 mm nominal core)
    f0_nom_air = float(fw_data["media"]["dry air"]["f0_MHz"])
    stackup_core_sweep = []
    for h_core_mm, label_tol in (
        (1.41, "-0.10mm_std_min"),
        (1.43, "-0.08mm_tight_min"),
        (1.51, "1.51mm_nominal"),
        (1.54, "+0.03mm_asym_max"),
        (1.59, "+0.08mm_tight_max"),
        (1.61, "+0.10mm_std_max"),
    ):
        c_scale = 1.51 / h_core_mm
        eeff_ratio = (0.71 + 0.29 * c_scale) ** -0.5
        f0_est_mhz = round(f0_nom_air * eeff_ratio, 2)
        p_h = dict(NOM)
        p_h["h_core_mm"] = h_core_mm
        p_h["c_pad"] = NOM["c_pad"] * c_scale
        p_h["c_par_brs"] = NOM["c_par_brs"] * (0.65 + 0.35 * c_scale)
        m_h = bridge_metrics(866.5e6, p_h)
        stackup_core_sweep.append({
            "corner": label_tol,
            "h_core_mm": h_core_mm,
            "h_finished_mm": round(h_core_mm + 0.09, 2),
            "ae1_f0_est_MHz": f0_est_mhz,
            "df0_MHz": round(f0_est_mhz - f0_nom_air, 2),
            "bridge_directivity_866p5_dB": round(m_h["directivity_wc_dB"], 2),
        })

    curves_json = os.path.join(OUT_DIR, "bridge_3tone_curves.json")
    with open(curves_json, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "revision": "E.5",
                "p_tx_sensing_dbm": P_TX_DBM,
                "max_lt5538_pin_dbm": round(max_p_det_dbm, 2),
                "lt5538_compression_headroom_dB": round(-13.0 - max_p_det_dbm, 2),
                "pcb_bridge_copper_lengths_mm": PCB_BRIDGE_LENS_MM,
                "c_par_brs_pf": round(C_PAR_BRS_F * 1e12, 4),
                "lt5538_zin_866p5_series_ohm": [
                    round(float(LT5538_ZIN_866P5_SERIES.real), 2),
                    round(float(LT5538_ZIN_866P5_SERIES.imag), 2),
                ],
                "lt5538_zin_866p5_parallel_rc": {
                    "r_par_ohm": LT5538_RDET_PAR_OHM,
                    "c_par_pf": round(LT5538_CDET_PAR_F * 1e12, 4),
                },
                "r1_primary_mpn": "Yageo RT0402BRD078R2L (8.2 Ohm +/-0.1% Thin Film)",
                "rterm_primary_mpn": "Susumu RG1005P-560-B-T5 (56 Ohm +/-0.1% Thin Film)",
                "r1_0p5pct_alt_impact_dB": round(max_r1_0p5pct_impact_db, 4),
                "nominal_866p5_metrics": {k: round(v, 4) for k, v in nom_866.items()},
                "two_point_calibration": {
                    "point1_dry_air_vout_mv": [
                        round(c["vout_v"][i] * 1000.0, 1)
                        for c in curves_table if c["medium"] == "dry air"
                        for i in range(3)
                    ],
                    "point2_alumina_ref_level_dbm": round(nom_ref_lvl_dbm, 2),
                    "water_ipa_threshold_dbm": -26.94,
                    "water_vs_ipa_gap_median_dB": water_ipa_gap_med_db,
                    "water_vs_ipa_gap_p01_dB": water_ipa_gap_p01_db,
                    "water_vs_ipa_yield_pct": water_ipa_yield_pct,
                    "hazard_4class_yield_pct": hazard4_yield_pct,
                },
                "stackup_core_sweep": stackup_core_sweep,
                "mc_summary": mc_summary_rows,
                "table": curves_table,
            },
            fh,
            indent=2,
        )
        fh.write("\n")

    # Plot 3-panel engineering figure
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(13.8, 4.2), dpi=160)

    f_mhz = [r["freq_MHz"] for r in sweep_rows]
    ax1.plot(f_mhz, [r["s21_dB"] * 10.0 for r in sweep_rows], lw=2.0, color="#1565c0",
             label=f"10 x |S21| TX/RX Loss ({nom_866['s21_dB']:.2f} dB)")
    ax1.plot(f_mhz, [r["s11_dB"] for r in sweep_rows], lw=2.0, color="#2e7d32", label="|S11| PA Port Return Loss (dB)")
    ax1.plot(f_mhz, [-r["directivity_wc_dB"] for r in sweep_rows], lw=2.0, ls="--", color="#c62828",
             label=f"-Directivity ({nom_866['directivity_wc_dB']:.1f} dB @ 866.5 MHz)")
    ax1.axvspan(863.0, 870.0, color="#fff59d", alpha=0.45, label="EU868 Band (863-870 MHz)")
    ax1.set_xlabel("Frequency (MHz)")
    ax1.set_ylabel("Magnitude (dB)")
    ax1.set_title("A. Rev E.5 Distributed Bridge S-Params & Directivity")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=6.8, loc="lower right")

    gam_mags = np.linspace(0.0, 1.0, 41)
    phases_deg = [0.0, 90.0, 180.0, 270.0]
    for ph, col in zip(phases_deg, ("#0d47a1", "#2e7d32", "#ef6c00", "#6a1b9a")):
        v_outs_plot = []
        th = math.radians(ph)
        for gm in gam_mags:
            g = min(gm, 0.9995) * np.exp(1j * th)
            zl = Z0 * (1.0 + g) / (1.0 - g)
            _, vo_v = det_vout_for_zant(866.5e6, zl, NOM)
            v_outs_plot.append(vo_v)
        ax2.plot(gam_mags, v_outs_plot, lw=1.8, color=col, label=f"Phase = {ph:.0f} deg")
    ax2.set_xlabel("Antenna Reflection Magnitude |Gamma|")
    ax2.set_ylabel(f"LT5538 Detector Output V_OUT (V) @ +{P_TX_DBM:.0f} dBm")
    ax2.set_title("B. Detector Transfer Across Reflection Phase")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7.2)

    bins = np.linspace(-8.0, 32.0, 52)
    k_prec = configs[0][0]
    k_gen = configs[2][0]
    ax3.hist(mc_traces[k_prec], bins=bins, alpha=0.75, color="#1b5e20",
             label=f"Rev E.5 Precision BOM (med={mc_summary_rows[0]['directivity_median_dB']:.1f} dB)")
    ax3.hist(mc_traces[k_gen], bins=bins, alpha=0.55, color="#c62828",
             label=f"5% Generic Thick-Film (med={mc_summary_rows[2]['directivity_median_dB']:.1f} dB)")
    ax3.axvline(22.0, color="k", ls="--", lw=1.2, label="22 dB Nominal Gate")
    ax3.set_xlabel("Worst-Case Bridge Directivity at 866.5 MHz (dB)")
    ax3.set_ylabel(f"Count (N = {n_mc} trials)")
    ax3.set_title("C. 2,000-Trial Monte-Carlo Tolerance Comparison")
    ax3.grid(alpha=0.3)
    ax3.legend(fontsize=6.8)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "bridge_sparam_mc.png"), bbox_inches="tight")
    plt.close(fig)

    assert -0.90 <= nom_866["s21_dB"] <= -0.75
    assert nom_866["s11_dB"] <= -20.0
    assert nom_866["directivity_wc_dB"] >= 24.0, (
        f"Nominal 50-Ohm directivity {nom_866['directivity_wc_dB']:.2f} dB < 24.0 dB!"
    )
    assert mc_summary_rows[0]["air_to_ice_contrast_p01_dB"] >= 8.0, (
        f"Calibrated P01 Air-to-Ice contrast {mc_summary_rows[0]['air_to_ice_contrast_p01_dB']:.2f} dB < 8.0 dB!"
    )
    assert mc_summary_rows[0]["yield_ice_contrast_gt_6dB_pct"] >= 99.0
    print(
        f"[PASS] Rev E.5 Distributed Bridge S-Param, 3D FVM Parasitic & 2,000-Trial MC Audit:\n"
        f"  Live PCB lengths (mm): /BR_S={PCB_BRIDGE_LENS_MM['/BR_S']:.2f}, /BR_O={PCB_BRIDGE_LENS_MM['/BR_O']:.2f}, "
        f"/DET_IN={PCB_BRIDGE_LENS_MM['/DET_IN']:.2f}\n"
        f"  C_par(/BR_S -> GND) = {C_PAR_BRS_F*1e12:.4f} pF (< 0.15 pF over 2.20x2.20mm F/B void)\n"
        f"  LT5538 Z_in(866.5 MHz) = {LT5538_ZIN_866P5_SERIES.real:.2f} {LT5538_ZIN_866P5_SERIES.imag:+.2f}j Ohm | "
        f"Max P_in = {max_p_det_dbm:.2f} dBm (+{-13.0 - max_p_det_dbm:.2f} dB below -13 dBm knee)\n"
        f"  Nominal @ 866.5 MHz : S21 = {nom_866['s21_dB']:.3f} dB, S11 = {nom_866['s11_dB']:.2f} dB, "
        f"50R Directivity = {nom_866['directivity_wc_dB']:.2f} dB (>= 24.0 dB)\n"
        f"  2-Pt Cal MC (N=2000): P01 Air-to-Ice = {mc_summary_rows[0]['air_to_ice_contrast_p01_dB']:.2f} dB | "
        f"Water/IPA gap med={water_ipa_gap_med_db:.2f} dB, P01={water_ipa_gap_p01_db:.2f} dB (>= 0.50 dB), "
        f"Water/IPA yield={water_ipa_yield_pct:.2f}%, 4-hazard yield={hazard4_yield_pct:.2f}%."
    )


if __name__ == "__main__":
    run_bridge_analysis()
