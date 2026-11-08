#!/usr/bin/env python3
"""
Touchstone (.s1p) and farfield post-processor for ISAC_868 (Rev E.5).

Reads 1-port Touchstone files exported by CST Microwave Studio (`run_cst_batch.py`
or `ISAC_868_Sweep_All_Superstrates.bas`), evaluates the Rev E.5 asymmetric
return-loss bridge (`R1 = 8.2 Ohm`) and Analog Devices `LT5538IDD#TRPBF` logarithmic
detector across the three EU868 probe frequencies (863.1, 866.5, 869.5 MHz), applies
2-point (`Dry Air` + `Al2O3`) calibration, and compares the results against the
in-repository 3D-FDTD solver (`rf/results/ifa_fullwave_3d.json`).

Two CST port planes are supported:
  - `--mode 1` (default): Port 1 is located at `/BR_Q` with the 3D 0402 elliptic
    Pi-filter (`C_M1, L_M1 || C_MZ, C_M2`) included in the EM model. To determine
    the unloaded antenna resonance `f0` without passband-ripple bias from the
    Pi-filter, the post-processor de-embeds the Pi-network analytically when
    locating `min |Gamma_ant(f)|`.
  - `--mode 0`: Port 1 is located directly at `AE1` Pad 1 (`/ANT_FEED`); the
    4-element elliptic Pi-filter is cascaded analytically to `/BR_Q` before
    evaluating the return-loss bridge.
"""
from __future__ import annotations

import argparse
import cmath
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CST_DIR = HERE.parent
ROOT = CST_DIR.parent
sys.path.insert(0, str(ROOT / "rf"))

from bridge_sparam_mc import K_SLOPE, NOM, P_INT, P_TX_DBM, TONE_FREQS_HZ, Z0, det_vout_for_zant  # noqa: E402
from ifa_enclosure_mom import HARMONIC_PI_NOM, eval_elliptic_pi_zin_and_s21  # noqa: E402

IFA_JSON = ROOT / "rf" / "results" / "ifa_fullwave_3d.json"
DESIGN_JSON = ROOT / "firmware" / "test" / "data" / "design_values.json"

CASE_TO_FDTD_KEY = {
    "01_bare_pcb":      "bare",
    "02_dry_air":       "dry air",
    "03_enclosed_lipo": "lipo",
    "04_fr4_low_4p2":   "fr4_low",
    "05_fr4_high_4p6":  "fr4_high",
    "06_oil_ptfe":      "PTFE",
    "07_glaze_ice":     "glaze ice",
    "08_alumina_al2o3": "alumina Al2O3",
    "09_ipa_debye":     "IPA (868 MHz)",
    "10_water_debye":   "water film",
}

DIAGNOSTIC_CASES = {
    "01_bare_pcb":      "— (Unenclosed VNA)",
    "04_fr4_low_4p2":   "— (FR-4 er=4.2 Corner)",
    "05_fr4_high_4p6":  "— (FR-4 er=4.6 Corner)",
}


def deembed_elliptic_pi_to_ant(
    z_in: np.ndarray,
    freqs: np.ndarray,
    c1_pf: float = HARMONIC_PI_NOM["c_m1_pf"],
    l1_nh: float = HARMONIC_PI_NOM["l_m1_nh"],
    cz_pf: float = HARMONIC_PI_NOM["c_mz_pf"],
    c2_pf: float = HARMONIC_PI_NOM["c_m2_pf"],
    q_ind_868: float = HARMONIC_PI_NOM["q_ind_868"],
    esl_shunt_nh: float = HARMONIC_PI_NOM["esl_shunt_nh"],
    srf_l1_ghz: float = HARMONIC_PI_NOM["srf_l1_ghz"],
    esl_cmz_nh: float = HARMONIC_PI_NOM["esl_cmz_nh"],
) -> np.ndarray:
    """Invert `eval_elliptic_pi_zin_and_s21` from `/BR_Q` back to `AE1` Pad 1 (`/ANT_FEED`)."""
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

    y_mid = 1.0 / z_in
    if c1_pf > 1e-6:
        z_c1 = 0.08 + (1.0 / (1j * w * (c1_pf * 1e-12))) + 1j * w * (esl_shunt_nh * 1e-9)
        y_mid = y_mid - (1.0 / z_c1)
    z_mid = 1.0 / y_mid
    z2 = z_mid - z_ser
    y_load = 1.0 / z2
    if c2_pf > 1e-6:
        z_c2 = 0.08 + (1.0 / (1j * w * (c2_pf * 1e-12))) + 1j * w * (esl_shunt_nh * 1e-9)
        y_load = y_load - (1.0 / z_c2)
    return 1.0 / y_load


def parse_touchstone_s1p(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """Return `(freqs_hz, s11_complex, z_ref_ohm)` from a Touchstone 1-port `.s1p` file."""
    unit_scale = 1e9
    fmt = "RI"
    z_ref = 50.0
    freqs: list[float] = []
    s11s: list[complex] = []

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            toks = line[1:].upper().split()
            for idx, tok in enumerate(toks):
                if tok in ("HZ", "KHZ", "MHZ", "GHZ"):
                    unit_scale = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}[tok]
                elif tok in ("RI", "MA", "DB"):
                    fmt = tok
                elif tok == "R" and idx + 1 < len(toks):
                    z_ref = float(toks[idx + 1])
            continue
        if "!" in line:
            line = line.split("!", 1)[0].strip()
        parts = line.split()
        if len(parts) < 3:
            continue
        f_val = float(parts[0]) * unit_scale
        a, b = float(parts[1]), float(parts[2])
        if fmt == "RI":
            s_val = complex(a, b)
        elif fmt == "MA":
            s_val = cmath.rect(a, math.radians(b))
        else:
            s_val = cmath.rect(10.0 ** (a / 20.0), math.radians(b))
        freqs.append(f_val)
        s11s.append(s_val)

    if not freqs:
        raise ValueError(f"No S-parameter rows parsed from {path}")
    order = np.argsort(freqs)
    return np.array(freqs, dtype=float)[order], np.array(s11s, dtype=complex)[order], z_ref


def parse_cst_farfield_efficiency(txt_path: Path) -> tuple[float | None, float | None]:
    """Extract `(eta_rad_pct, eta_tot_pct)` if present in a CST Farfield ASCII header."""
    if not txt_path.is_file():
        return None, None
    txt = txt_path.read_text(encoding="utf-8", errors="ignore")
    m_rad = re.search(r"Radiation\s+efficiency\s*[:=]\s*([-\d.eE+]+)", txt, re.I)
    m_tot = re.search(r"Total\s+efficiency\s*[:=]\s*([-\d.eE+]+)", txt, re.I)
    eta_rad = None
    eta_tot = None
    if m_rad:
        val = float(m_rad.group(1))
        eta_rad = (10.0 ** (val / 10.0)) * 100.0 if val < 0.0 else (val * 100.0 if val <= 1.0 else val)
    if m_tot:
        val = float(m_tot.group(1))
        eta_tot = (10.0 ** (val / 10.0)) * 100.0 if val < 0.0 else (val * 100.0 if val <= 1.0 else val)
    return eta_rad, eta_tot


def interp_complex(freqs_hz: np.ndarray, vals: np.ndarray, target_hz: float) -> complex:
    re_v = float(np.interp(target_hz, freqs_hz, vals.real))
    im_v = float(np.interp(target_hz, freqs_hz, vals.imag))
    return complex(re_v, im_v)


def classify_surface_rev_e5(level_cal_dbm: float, tilt_cal_db: float, notch_cal_db: float, temp_degc: float = 20.0) -> str:
    """Mirror 2-point calibrated decision boundaries in `firmware/src/isac_sensing.c` (lines 662-684)."""
    if notch_cal_db >= 2.20:
        return "DRY_AIR"
    if level_cal_dbm < -31.15:
        return "OIL"
    if tilt_cal_db <= 0.84:
        return "GLAZE_ICE" if temp_degc <= 4.0 else "LIQUID_WATER"
    if level_cal_dbm >= -26.94 and tilt_cal_db <= 1.50:
        return "LIQUID_WATER"
    return "IPA"


def export_fdtd_reference_touchstones(out_dir: Path) -> list[Path]:
    """
    Export broadband (740-960 MHz) 3D-FDTD reference `.s1p` files at `/BR_Q` for
    GUI overlay in CST Studio (`1D Results -> S-Parameters`).

    Each curve combines a series-RLC antenna model centered at the exact 3D-FDTD
    `f0_MHz` and `min_s11_dB` with exact complex impedance knots at the three EU868
    CW probe tones (863.1, 866.5, 869.5 MHz), cascaded through the Rev E.5 elliptic
    Pi-filter (`eval_elliptic_pi_zin_and_s21`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ifa_data = json.loads(IFA_JSON.read_text(encoding="utf-8"))
    f_tones = np.array(TONE_FREQS_HZ, dtype=float)
    written: list[Path] = []

    for case_tag, fdtd_key in CASE_TO_FDTD_KEY.items():
        m = ifa_data["media"][fdtd_key]
        f0_hz = float(m["f0_MHz"]) * 1e6
        gamma_min = 10.0 ** (float(m["min_s11_dB"]) / 20.0)
        z_ant_tones = np.array([complex(zr, zi) for zr, zi in m["z_ant_tones_ohm"]], dtype=complex)

        f_grid = np.unique(np.concatenate([
            np.linspace(740.0e6, 960.0e6, 441),
            f_tones,
            [f0_hz],
        ]))

        # Choose R0 on the side of Z0 matching Re(Z_ant) near EU868, with Q set by the 3D-FDTD reactance slope
        r_hi = Z0 * (1.0 + gamma_min) / max(1e-6, 1.0 - gamma_min)
        r_lo = Z0 * max(1e-6, 1.0 - gamma_min) / (1.0 + gamma_min)
        r_ref = float(np.mean(z_ant_tones.real))
        r0 = r_lo if abs(r_lo - r_ref) <= abs(r_hi - r_ref) else r_hi

        dx_df = float((z_ant_tones[2].imag - z_ant_tones[0].imag) / (f_tones[2] - f_tones[0]))
        nu_tones = (f_tones / f0_hz) - (f0_hz / f_tones)
        if abs(nu_tones[1]) > 0.03 and z_ant_tones[1].imag * nu_tones[1] > 0.0:
            x_slope = float(np.clip(z_ant_tones[1].imag / nu_tones[1], 80.0, 1200.0))
        else:
            x_slope = max(120.0, min(900.0, 0.5 * f0_hz * abs(dx_df)))
        nu = (f_grid / f0_hz) - (f0_hz / f_grid)
        z_rlc = r0 + 1j * x_slope * nu

        # Smooth localized correction around EU868 so Z_ant(f1, f2, f3) matches 3D-FDTD knots identically
        dz_tones = z_ant_tones - (r0 + 1j * x_slope * nu_tones)
        dz_re = np.interp(f_grid, f_tones, dz_tones.real)
        dz_im = np.interp(f_grid, f_tones, dz_tones.imag)
        dist_eu = np.maximum(0.0, np.maximum(f_tones[0] - f_grid, f_grid - f_tones[-1]))
        if f_tones[0] <= f0_hz <= f_tones[-1]:
            # Interpolate across [f1, f2, f0, f3] so the RLC minimum at f0 = 869.0 MHz is preserved identically
            f_knots = np.array([f_tones[0], f_tones[1], f0_hz, f_tones[2]])
            dz_re_k = np.array([dz_tones[0].real, dz_tones[1].real, 0.0, dz_tones[2].real])
            dz_im_k = np.array([dz_tones[0].imag, dz_tones[1].imag, 0.0, dz_tones[2].imag])
            dz_re = np.interp(f_grid, f_knots, dz_re_k)
            dz_im = np.interp(f_grid, f_knots, dz_im_k)
            env = np.exp(-0.5 * (dist_eu / 14.0e6) ** 2)
        else:
            env = np.exp(-0.5 * (dist_eu / 2.2e6) ** 2)
            notch_f0 = ((f_grid - f0_hz) ** 2) / (((f_grid - f0_hz) ** 2) + (1.2e6 ** 2))
            env = env * notch_f0
        z_ant_grid = z_rlc + env * (dz_re + 1j * dz_im)

        z_brq_grid, _ = eval_elliptic_pi_zin_and_s21(z_ant_grid, f_grid)
        # Enforce exact 3D-FDTD cascaded knots at f1, f2, f3
        for k, ft in enumerate(f_tones):
            idx_t = int(np.argmin(np.abs(f_grid - ft)))
            z_brq_grid[idx_t] = complex(*m["z_brq_tones_ohm"][k])
        s_brq_grid = (z_brq_grid - Z0) / (z_brq_grid + Z0)

        p_out = out_dir / f"{case_tag}_fdtd_ref.s1p"
        lines = [
            f"! ISAC_868 Rev E.5 3D-FDTD Reference S11 at /BR_Q ({m['scenario']})",
            f"! Reference plane: /BR_Q (includes C_M1=3.6p, L_M1=8.2n||C_MZ=0.5p, C_M2=4.3p elliptic Pi-filter)",
            f"! Unloaded AE1 f0 = {m['f0_MHz']:.1f} MHz | Standalone |S11(866.5)| = {m['s11_866p5_raw_dB']:.2f} dB | Cascaded |S11(866.5)| = {m['s11_866p5_cascaded_dB']:.2f} dB",
            "# GHz S RI R 50.0",
        ]
        for fh, sv in zip(f_grid, s_brq_grid):
            lines.append(f"{fh * 1e-9:.7f}  {sv.real:+.8e}  {sv.imag:+.8e}")
        p_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(p_out)

    return written


def evaluate_s1p_directory(
    results_dir: Path,
    port_mode: int,
    out_report_dir: Path,
    suffix: str = "",
    is_pipeline_selfcheck: bool = False,
) -> int:
    ifa_data = json.loads(IFA_JSON.read_text(encoding="utf-8"))
    dv_data = json.loads(DESIGN_JSON.read_text(encoding="utf-8"))
    dv_by_med = {r["medium"]: r for r in dv_data["table"]}

    found_cases: dict[str, dict] = {}
    for case_tag, fdtd_key in CASE_TO_FDTD_KEY.items():
        cand = results_dir / f"{case_tag}{suffix}.s1p"
        if not cand.is_file():
            continue
        f_hz, s11_raw, z_ref = parse_touchstone_s1p(cand)
        z_port = z_ref * (1.0 + s11_raw) / (1.0 - s11_raw + 1e-30)

        if port_mode == 0:
            z_ant_curve = z_port
            z_brq_curve, _ = eval_elliptic_pi_zin_and_s21(z_port, f_hz)
        else:
            z_brq_curve = z_port
            z_ant_curve = deembed_elliptic_pi_to_ant(z_port, f_hz)

        s11_ant = (z_ant_curve - Z0) / (z_ant_curve + Z0)
        s11_ant_db = 20.0 * np.log10(np.abs(s11_ant) + 1e-30)
        s11_brq = (z_brq_curve - Z0) / (z_brq_curve + Z0)
        s11_brq_db = 20.0 * np.log10(np.abs(s11_brq) + 1e-30)

        in_band = f_hz <= 955.0e6
        if np.any(in_band):
            idx_min = int(np.argmin(s11_ant_db[in_band]))
            f0_mhz = float(f_hz[in_band][idx_min] * 1e-6)
            min_s11_ant_db = float(s11_ant_db[in_band][idx_min])
        else:
            idx_min = int(np.argmin(s11_ant_db))
            f0_mhz = float(f_hz[idx_min] * 1e-6)
            min_s11_ant_db = float(s11_ant_db[idx_min])

        v_tones_mv = []
        p_tones_dbm = []
        for ft in TONE_FREQS_HZ:
            z_ft = interp_complex(f_hz, z_brq_curve, ft)
            p_dbm, v_v = det_vout_for_zant(ft, z_ft, NOM, p_tx_dbm=P_TX_DBM, p_int_dbm=P_INT)
            p_tones_dbm.append(p_dbm)
            v_tones_mv.append(v_v * 1e3)

        s11_866_ant_db = float(np.interp(866.5e6, f_hz, s11_ant_db))
        s11_866_brq_db = float(np.interp(866.5e6, f_hz, s11_brq_db))
        ff_path = results_dir / f"farfield_866p5MHz_{case_tag}.txt"
        eta_rad, eta_tot = parse_cst_farfield_efficiency(ff_path)

        found_cases[case_tag] = {
            "fdtd_key": fdtd_key,
            "f0_MHz": round(f0_mhz, 2),
            "min_s11_ant_dB": round(min_s11_ant_db, 2),
            "s11_866p5_ant_dB": round(s11_866_ant_db, 2),
            "s11_866p5_brq_dB": round(s11_866_brq_db, 2),
            "v_mv": v_tones_mv,
            "p_dbm": p_tones_dbm,
            "eta_rad_pct": eta_rad,
            "eta_tot_pct": eta_tot,
        }

    if not found_cases:
        sys.stderr.write(f"[CST-POST] No matching .s1p files found in {results_dir}\n")
        return 1

    fdtd_dry_dv = dv_by_med["dry air"]
    fdtd_alu_dv = dv_by_med["alumina Al2O3"]

    if "02_dry_air" in found_cases:
        dry_v = found_cases["02_dry_air"]["v_mv"]
        tare_dv_mv = [
            dry_v[k] - (K_SLOPE * 1e3) * (fdtd_dry_dv["p_det_dBm"][k] - P_INT)
            for k in range(3)
        ]
    else:
        tare_dv_mv = [0.0, 0.0, 0.0]

    cal_ref_db = 0.0
    if "08_alumina_al2o3" in found_cases:
        alu_v_tared = [found_cases["08_alumina_al2o3"]["v_mv"][k] - tare_dv_mv[k] for k in range(3)]
        alu_lvl_raw = sum((v / (K_SLOPE * 1e3)) + P_INT for v in alu_v_tared) / 3.0
        cal_ref_db = alu_lvl_raw - fdtd_alu_dv["level_dBm"]

    out_report_dir.mkdir(parents=True, exist_ok=True)
    stem = "fdtd_touchstone_selfcheck" if is_pipeline_selfcheck else "cst_vs_fdtd_comparison"
    src_col = "Parsed .s1p" if is_pipeline_selfcheck else "CST"
    src_key = "s1p" if is_pipeline_selfcheck else "cst"
    csv_path = out_report_dir / f"{stem}.csv"
    md_path = out_report_dir / f"{stem}.md"

    rows_out = []
    for case_tag, c in found_cases.items():
        fkey = c["fdtd_key"]
        m_fdtd = ifa_data["media"][fkey]
        v_cal = [c["v_mv"][k] - tare_dv_mv[k] for k in range(3)]
        tilt_db = (v_cal[0] - v_cal[2]) / (K_SLOPE * 1e3)
        notch_db = (0.5 * (v_cal[0] + v_cal[2]) - v_cal[1]) / (K_SLOPE * 1e3)
        level_raw = sum((v / (K_SLOPE * 1e3)) + P_INT for v in v_cal) / 3.0
        w_hi = float(np.clip(
            (level_raw - fdtd_dry_dv["level_dBm"]) / max(1.0, fdtd_alu_dv["level_dBm"] - fdtd_dry_dv["level_dBm"]),
            0.0,
            1.15,
        ))
        level_cal = level_raw - w_hi * cal_ref_db

        if case_tag in DIAGNOSTIC_CASES:
            cls_name = DIAGNOSTIC_CASES[case_tag]
        else:
            temp_c = -5.0 if fkey == "glaze ice" else 20.0
            cls_name = classify_surface_rev_e5(level_cal, tilt_db, notch_db, temp_degc=temp_c)

        fdtd_dv = dv_by_med.get(fkey)
        rows_out.append({
            "case": case_tag,
            "medium": fkey,
            f"{src_key}_f0_ant_MHz": c["f0_MHz"],
            "fdtd_f0_ant_MHz": m_fdtd["f0_MHz"],
            f"{src_key}_s11_866p5_ant_dB": c["s11_866p5_ant_dB"],
            f"{src_key}_s11_866p5_brq_dB": c["s11_866p5_brq_dB"],
            "fdtd_s11_866p5_brq_dB": m_fdtd["s11_866p5_cascaded_dB"],
            f"{src_key}_tilt_dB": round(tilt_db, 2),
            "fdtd_tilt_dB": fdtd_dv["tilt_dB"] if fdtd_dv else None,
            f"{src_key}_notch_dB": round(notch_db, 2),
            "fdtd_notch_dB": fdtd_dv["notch_dB"] if fdtd_dv else None,
            f"{src_key}_level_dBm": round(level_cal, 2),
            "fdtd_level_dBm": fdtd_dv["level_dBm"] if fdtd_dv else None,
            "classified_state": cls_name,
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    if is_pipeline_selfcheck:
        title = "# 3D-FDTD Reference Touchstone (`.s1p`) & Bridge Post-Processor Self-Check (`Rev E.5`)"
        note = (
            "> **Note:** This table verifies Touchstone `.s1p` serialization, Pi-filter de-embedding, "
            "and 3-tone return-loss bridge post-processing against the in-repo 3D-FDTD baseline "
            "(`rf/results/ifa_fullwave_3d.json`). No CST Studio Suite solver data are included here; "
            "when CST exports are placed in `cst_studio/results/`, running `postprocess_cst_results.py` "
            "generates `cst_studio/results/cst_vs_fdtd_comparison.md`."
        )
    else:
        title = "# CST Studio Suite vs. 3D-FDTD Cross-Correlation Report (`Rev E.5`)"
        note = (
            "> Reference planes: $f_0$ and $|\\Gamma_{\\text{ant}}|_{866.5}$ are evaluated at `AE1` Pad 1 "
            "(`/ANT_FEED`); $|\\Gamma_{\\text{in}}|_{866.5}$ is evaluated at `/BR_Q` downstream of the "
            "populated 4-element elliptic Pi-filter (`C_M1, L_M1 || C_MZ, C_M2`)."
        )

    md_lines = [
        title,
        "",
        note,
        "",
        f"| Case | Medium | {src_col} $f_0$ [MHz] | FDTD $f_0$ [MHz] | {src_col} $\\lvert\\Gamma_{{\\text{{ant}}}}\\rvert_{{866.5}}$ [dB] | {src_col} $\\lvert\\Gamma_{{\\text{{in}}}}\\rvert_{{866.5}}$ [dB] | {src_col} Tilt [dB] | FDTD Tilt [dB] | {src_col} Level [dBm] | FDTD Level [dBm] | Firmware Class |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for r in rows_out:
        ft = f"{r['fdtd_tilt_dB']:+.2f}" if r["fdtd_tilt_dB"] is not None else "—"
        fl = f"{r['fdtd_level_dBm']:.2f}" if r["fdtd_level_dBm"] is not None else "—"
        md_lines.append(
            f"| `{r['case']}` | {r['medium']} | {r[f'{src_key}_f0_ant_MHz']:.1f} | {r['fdtd_f0_ant_MHz']:.1f} | "
            f"{r[f'{src_key}_s11_866p5_ant_dB']:.2f} | {r[f'{src_key}_s11_866p5_brq_dB']:.2f} | "
            f"{r[f'{src_key}_tilt_dB']:+.2f} | {ft} | "
            f"{r[f'{src_key}_level_dBm']:.2f} | {fl} | `{r['classified_state']}` |"
        )

    if "02_dry_air" in found_cases and "07_glaze_ice" in found_cases:
        sens_val = (found_cases["02_dry_air"]["f0_MHz"] - found_cases["07_glaze_ice"]["f0_MHz"]) / (math.sqrt(3.20) - 1.0)
        md_lines.extend([
            "",
            f"- **Air-to-Ice Resonant Sensitivity (`AE1` feed plane):** {sens_val:.2f} MHz/RIU "
            f"(3D-FDTD baseline: {dv_data['air_to_ice_sensitivity_MHz_per_RIU']:.2f} MHz/RIU)",
        ])

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"[CST-POST] Processed {len(rows_out)} Touchstone case(s) -> {md_path.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Post-process CST Studio .s1p & farfield exports (Rev E.5).")
    ap.add_argument(
        "--results-dir",
        default=str(CST_DIR / "results"),
        help="Directory containing CST exported .s1p and farfield_*.txt files.",
    )
    ap.add_argument(
        "--mode",
        type=int,
        choices=(0, 1),
        default=1,
        help="1 = CST Port 1 at /BR_Q with 3D Pi-filter; 0 = CST Port 1 at AE1 Pad 1.",
    )
    ap.add_argument(
        "--export-fdtd-ref",
        action="store_true",
        help="Export 3D-FDTD reference .s1p files into cst_studio/results/fdtd_reference/.",
    )
    ap.add_argument(
        "--verify-pipeline",
        action="store_true",
        help="Export FDTD reference .s1p files and run round-trip Touchstone + bridge self-check.",
    )
    args = ap.parse_args()

    ref_dir = CST_DIR / "results" / "fdtd_reference"
    if args.export_fdtd_ref or args.verify_pipeline:
        written = export_fdtd_reference_touchstones(ref_dir)
        print(f"[CST-POST] Exported {len(written)} 3D-FDTD reference Touchstone (.s1p) files to {ref_dir.relative_to(ROOT)}")
        if not args.verify_pipeline:
            return 0

    if args.verify_pipeline:
        rc = evaluate_s1p_directory(
            ref_dir,
            port_mode=1,
            out_report_dir=ref_dir,
            suffix="_fdtd_ref",
            is_pipeline_selfcheck=True,
        )
        if rc != 0:
            return rc
        chk_csv = ref_dir / "fdtd_touchstone_selfcheck.csv"
        with open(chk_csv, "r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        max_f0_err = 0.0
        max_tilt_err = 0.0
        max_lvl_err = 0.0
        expected_cls = {
            "dry air": "DRY_AIR",
            "PTFE": "OIL",
            "glaze ice": "GLAZE_ICE",
            "alumina Al2O3": "IPA",
            "IPA (868 MHz)": "IPA",
            "water film": "LIQUID_WATER",
        }
        for r in rows:
            max_f0_err = max(max_f0_err, abs(float(r["s1p_f0_ant_MHz"]) - float(r["fdtd_f0_ant_MHz"])))
            if r["fdtd_tilt_dB"]:
                max_tilt_err = max(max_tilt_err, abs(float(r["s1p_tilt_dB"]) - float(r["fdtd_tilt_dB"])))
                max_lvl_err = max(max_lvl_err, abs(float(r["s1p_level_dBm"]) - float(r["fdtd_level_dBm"])))
            med = r["medium"]
            if med in expected_cls:
                assert r["classified_state"] == expected_cls[med], (
                    f"Misclassified {med}: got {r['classified_state']}, expected {expected_cls[med]}"
                )
        assert max_f0_err <= 0.50, f"De-embedded f0 round-trip error {max_f0_err:.2f} MHz > 0.50 MHz"
        assert max_tilt_err <= 0.02 and max_lvl_err <= 0.02, (
            f"Round-trip drift exceeded 0.02 dB (tilt={max_tilt_err:.3f}, level={max_lvl_err:.3f})"
        )
        print(
            f"[CST-POST PASS] Round-trip Touchstone + Pi-filter de-embed + bridge self-check passed "
            f"(max_df0={max_f0_err:.2f} MHz, max_dtilt={max_tilt_err:.2f} dB, max_dlvl={max_lvl_err:.2f} dB)."
        )
        return 0

    return evaluate_s1p_directory(Path(args.results_dir), port_mode=args.mode, out_report_dir=Path(args.results_dir))


if __name__ == "__main__":
    sys.exit(main())
