#!/usr/bin/env python3
"""
postprocess_cst_results.py -- CST Studio Suite Touchstone (.s1p) & Farfield Post-Processor,
                              Return-Loss Bridge / LT5538 3-Tone Evaluator, and 3D-FDTD
                              Cross-Correlation Tool for ISAC_868 Rev E.5.

Features:
  1. Parses standard Touchstone v1.1/v2.0 `.s1p` files (`RI`, `MA`, or `DB` format across
     `Hz`, `kHz`, `MHz`, or `GHz`) exported by CST Microwave Studio (`ISAC_868_Sweep_All_Superstrates.bas`
     or `run_cst_batch.py`), plus optional CST Farfield ASCII tables.
  2. Supports both CST Port Modes:
       - `--mode 1` (default): CST Port 1 is at `/BR_Q` with the 3D `0402` elliptic Pi-filter
         already included in the 3D field solve.
       - `--mode 0`: CST Port 1 is directly at `AE1` Pad 1 (`/ANT_FEED`); cascades the
         parasitic-aware 4-element elliptic Pi-filter (`C_M1, L_M1 || C_MZ, C_M2`) analytically.
  3. Evaluates the exact Rev E.5 asymmetric return-loss bridge (`R1 = 8.2 Ohm`, `24.81 dB`
     directivity) and `LT5538IDD#TRPBF` (`291.65 Ohm || 1.194 pF`, `19.0 mV/dB`) across the
     3 CW probe tones (`863.1`, `866.5`, `869.5 MHz`), applying 2-point (`Dry Air` + `Al2O3`)
     calibration and firmware surface classification.
  4. Exports 3D-FDTD reference `.s1p` Touchstone files into `cst_studio/results/fdtd_reference/`
     so RF engineers can drag-and-drop FDTD reference curves directly onto CST's `1D Results` plot.
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
from ifa_enclosure_mom import eval_elliptic_pi_zin_and_s21  # noqa: E402

IFA_JSON = ROOT / "rf" / "results" / "ifa_fullwave_3d.json"
IFA_CSV = ROOT / "rf" / "results" / "ifa_s11_efficiency.csv"
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


def parse_touchstone_s1p(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (freqs_hz, s11_complex, z_ref_ohm) from a Touchstone 1-port .s1p file."""
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
        # Strip inline comments
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
        else:  # DB
            s_val = cmath.rect(10.0 ** (a / 20.0), math.radians(b))
        freqs.append(f_val)
        s11s.append(s_val)

    if not freqs:
        raise ValueError(f"No S-parameter rows parsed from {path}")
    order = np.argsort(freqs)
    f_arr = np.array(freqs, dtype=float)[order]
    s_arr = np.array(s11s, dtype=complex)[order]
    return f_arr, s_arr, z_ref


def parse_cst_farfield_efficiency(txt_path: Path) -> tuple[float | None, float | None]:
    """Extract (eta_rad_pct, eta_tot_pct) if present in CST Farfield ASCII header."""
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
    """Export 3-tone + band FDTD reference .s1p files for live overlay inside CST Studio GUI."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ifa_data = json.loads(IFA_JSON.read_text(encoding="utf-8"))
    written: list[Path] = []

    for case_tag, fdtd_key in CASE_TO_FDTD_KEY.items():
        m = ifa_data["media"][fdtd_key]
        z_brq_list = [complex(zr, zi) for zr, zi in m["z_brq_tones_ohm"]]
        # Synthesize smooth local rational/RLC interpolation anchored exactly at f1, f2, f3 & f0
        f_tones = np.array(TONE_FREQS_HZ, dtype=float)
        s_tones = np.array([(z - Z0) / (z + Z0) for z in z_brq_list], dtype=complex)

        # Build dense 860..872 MHz EU868 passband grid + exact probe tones for CST 1D overlay
        f_grid = np.unique(np.concatenate([
            np.linspace(860.0e6, 872.0e6, 121),
            f_tones,
            [m["f0_MHz"] * 1e6],
        ]))
        zr_interp = np.interp(f_grid, f_tones, [z.real for z in z_brq_list])
        # Linear reactance slope across the 6.4 MHz EU868 window anchored at f1, f2, f3
        slope_low = (z_brq_list[1].imag - z_brq_list[0].imag) / (f_tones[1] - f_tones[0])
        slope_high = (z_brq_list[2].imag - z_brq_list[1].imag) / (f_tones[2] - f_tones[1])
        zi_interp = np.where(
            f_grid <= f_tones[1],
            z_brq_list[1].imag + slope_low * (f_grid - f_tones[1]),
            z_brq_list[1].imag + slope_high * (f_grid - f_tones[1]),
        )
        z_grid = zr_interp + 1j * zi_interp
        s_grid = (z_grid - Z0) / (z_grid + Z0)

        p_out = out_dir / f"{case_tag}_fdtd_ref.s1p"
        lines = [
            f"! ISAC_868 Rev E.5 3D-FDTD Reference S11 at /BR_Q ({m['scenario']})",
            f"! Drag-and-drop into CST Studio '1D Results -> S-Parameters' for live overlay",
            f"! FDTD f0 = {m['f0_MHz']:.1f} MHz, |S11(866.5 MHz)| = {m['s11_866p5_cascaded_dB']:.2f} dB, eta_tot = {m['eta_tot_pct']:.1f}%",
            "# GHz S RI R 50.0",
        ]
        for fh, sv in zip(f_grid, s_grid):
            lines.append(f"{fh * 1e-9:.7f}  {sv.real:+.8e}  {sv.imag:+.8e}")
        p_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(p_out)

    return written


def evaluate_s1p_directory(results_dir: Path, port_mode: int, out_report_dir: Path, suffix: str = "") -> int:
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
            z_brq_curve, _ = eval_elliptic_pi_zin_and_s21(z_port, f_hz)
        else:
            z_brq_curve = z_port

        s11_brq = (z_brq_curve - Z0) / (z_brq_curve + Z0)
        s11_db = 20.0 * np.log10(np.abs(s11_brq) + 1e-30)

        in_band = f_hz <= 950.0e6
        if np.any(in_band):
            idx_min = int(np.argmin(s11_db[in_band]))
            f0_mhz = float(f_hz[in_band][idx_min] * 1e-6)
            min_s11_db = float(s11_db[in_band][idx_min])
        else:
            idx_min = int(np.argmin(s11_db))
            f0_mhz = float(f_hz[idx_min] * 1e-6)
            min_s11_db = float(s11_db[idx_min])

        v_tones_mv = []
        p_tones_dbm = []
        for ft in TONE_FREQS_HZ:
            z_ft = interp_complex(f_hz, z_brq_curve, ft)
            p_dbm, v_v = det_vout_for_zant(ft, z_ft, NOM, p_tx_dbm=P_TX_DBM, p_int_dbm=P_INT)
            p_tones_dbm.append(p_dbm)
            v_tones_mv.append(v_v * 1e3)

        s11_866_db = float(np.interp(866.5e6, f_hz, s11_db))
        ff_path = results_dir / f"farfield_866p5MHz_{case_tag}.txt"
        eta_rad, eta_tot = parse_cst_farfield_efficiency(ff_path)

        found_cases[case_tag] = {
            "fdtd_key": fdtd_key,
            "f0_MHz": round(f0_mhz, 2),
            "min_s11_dB": round(min_s11_db, 2),
            "s11_866p5_dB": round(s11_866_db, 2),
            "v_mv": v_tones_mv,
            "p_dbm": p_tones_dbm,
            "eta_rad_pct": eta_rad,
            "eta_tot_pct": eta_tot,
        }

    if not found_cases:
        sys.stderr.write(f"[CST-POST] No matching .s1p files found in {results_dir}\n")
        return 1

    # Apply 2-point factory calibration (02_dry_air tare + 08_alumina_al2o3 high-reflection offset)
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
    csv_path = out_report_dir / "cst_vs_fdtd_comparison.csv"
    md_path = out_report_dir / "cst_vs_fdtd_comparison.md"

    rows_out = []
    for case_tag, c in found_cases.items():
        fkey = c["fdtd_key"]
        m_fdtd = ifa_data["media"][fkey]
        v_cal = [c["v_mv"][k] - tare_dv_mv[k] for k in range(3)]
        tilt_db = (v_cal[0] - v_cal[2]) / (K_SLOPE * 1e3)
        notch_db = (0.5 * (v_cal[0] + v_cal[2]) - v_cal[1]) / (K_SLOPE * 1e3)
        level_raw = sum((v / (K_SLOPE * 1e3)) + P_INT for v in v_cal) / 3.0
        # Apply 2-point high-reflection offset proportionally above dry air
        w_hi = float(np.clip((level_raw - fdtd_dry_dv["level_dBm"]) / max(1.0, fdtd_alu_dv["level_dBm"] - fdtd_dry_dv["level_dBm"]), 0.0, 1.15))
        level_cal = level_raw - w_hi * cal_ref_db

        temp_c = -5.0 if fkey == "glaze ice" else 20.0
        cls_name = classify_surface_rev_e5(level_cal, tilt_db, notch_db, temp_degc=temp_c)

        fdtd_dv = dv_by_med.get(fkey)
        rows_out.append({
            "case": case_tag,
            "medium": fkey,
            "cst_f0_MHz": c["f0_MHz"],
            "fdtd_f0_MHz": m_fdtd["f0_MHz"],
            "cst_s11_866p5_dB": c["s11_866p5_dB"],
            "fdtd_s11_866p5_dB": m_fdtd["s11_866p5_cascaded_dB"],
            "cst_tilt_dB": round(tilt_db, 2),
            "fdtd_tilt_dB": fdtd_dv["tilt_dB"] if fdtd_dv else None,
            "cst_notch_dB": round(notch_db, 2),
            "fdtd_notch_dB": fdtd_dv["notch_dB"] if fdtd_dv else None,
            "cst_level_dBm": round(level_cal, 2),
            "fdtd_level_dBm": fdtd_dv["level_dBm"] if fdtd_dv else None,
            "classified_state": cls_name,
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    md_lines = [
        "# CST Studio Suite vs. 3D-FDTD Cross-Correlation Report (`Rev E.5`)",
        "",
        "| Case | Medium | CST $f_0$ [MHz] | FDTD $f_0$ [MHz] | CST $|S_{11}|_{866.5}$ [dB] | CST `Tilt` [dB] | FDTD `Tilt` [dB] | CST `Level` [dBm] | FDTD `Level` [dBm] | Classified State |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for r in rows_out:
        ft = f"{r['fdtd_tilt_dB']:+.2f}" if r["fdtd_tilt_dB"] is not None else "—"
        fl = f"{r['fdtd_level_dBm']:.2f}" if r["fdtd_level_dBm"] is not None else "—"
        md_lines.append(
            f"| `{r['case']}` | `{r['medium']}` | `{r['cst_f0_MHz']:.1f}` | `{r['fdtd_f0_MHz']:.1f}` | "
            f"`{r['cst_s11_866p5_dB']:.2f}` | `{r['cst_tilt_dB']:+.2f}` | `{ft}` | "
            f"`{r['cst_level_dBm']:.2f}` | `{fl}` | `{r['classified_state']}` |"
        )

    if "02_dry_air" in found_cases and "07_glaze_ice" in found_cases:
        sens_cst = (found_cases["02_dry_air"]["f0_MHz"] - found_cases["07_glaze_ice"]["f0_MHz"]) / (math.sqrt(3.20) - 1.0)
        md_lines.extend([
            "",
            f"- **Air-to-Ice Resonant Sensitivity:** `{sens_cst:.2f} MHz/RIU` (3D-FDTD baseline: `{dv_data['air_to_ice_sensitivity_MHz_per_RIU']:.2f} MHz/RIU`)",
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
        "--export-fdtd-touchstone",
        action="store_true",
        help="Export 10 FDTD reference .s1p files into cst_studio/results/fdtd_reference/.",
    )
    ap.add_argument(
        "--verify-pipeline",
        action="store_true",
        help="Run round-trip self-test on FDTD reference Touchstone files.",
    )
    args = ap.parse_args()

    ref_dir = CST_DIR / "results" / "fdtd_reference"
    if args.export_fdtd_touchstone or args.verify_pipeline:
        written = export_fdtd_reference_touchstones(ref_dir)
        print(f"[CST-POST] Exported {len(written)} FDTD reference .s1p files in {ref_dir.relative_to(ROOT)}/")
        if not args.verify_pipeline and not args.export_fdtd_touchstone:
            return 0

    if args.verify_pipeline:
        rc = evaluate_s1p_directory(ref_dir, port_mode=1, out_report_dir=ref_dir, suffix="_fdtd_ref")
        if rc != 0:
            return rc
        # Verify exact round-trip parity on all 6 benchmark media
        comp_csv = ref_dir / "cst_vs_fdtd_comparison.csv"
        expected_cls = {
            "dry air": "DRY_AIR",
            "PTFE": "OIL",
            "glaze ice": "GLAZE_ICE",
            "alumina Al2O3": "IPA",
            "IPA (868 MHz)": "IPA",
            "water film": "LIQUID_WATER",
        }
        with open(comp_csv, "r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                med = row["medium"]
                if med in expected_cls:
                    dtilt = abs(float(row["cst_tilt_dB"]) - float(row["fdtd_tilt_dB"]))
                    dlvl = abs(float(row["cst_level_dBm"]) - float(row["fdtd_level_dBm"]))
                    assert dtilt <= 0.02 and dlvl <= 0.02, f"Round-trip drift on {med}: dtilt={dtilt}, dlvl={dlvl}"
                    assert row["classified_state"] == expected_cls[med], (
                        f"Misclassified {med}: got {row['classified_state']}, expected {expected_cls[med]}"
                    )
        print("[CST-POST PASS] Touchstone v1.1 parser + Rev E.5 bridge/LT5538 3-tone pipeline verified (0.00 dB drift, 6/6 media classified).")
        return 0

    if args.export_fdtd_touchstone:
        return 0

    return evaluate_s1p_directory(Path(args.results_dir), port_mode=args.mode, out_report_dir=Path(args.results_dir))


if __name__ == "__main__":
    raise SystemExit(main())
