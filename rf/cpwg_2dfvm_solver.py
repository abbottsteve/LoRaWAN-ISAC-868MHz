#!/usr/bin/env python3
"""
cpwg_2dfvm_solver.py -- Non-Uniform 2D Finite-Volume Laplace Cross-Sectional
                        Solver for the ISAC Rev E.5 868 MHz CPWG Spine.

Models the finished 2-layer stackup on a graded tensor-product mesh whose node
lines align with each dielectric/conductor interface:
  - Finished board thickness : 1.60 mm nominal (+/-10%)
  - FR-4 dielectric core     : h_core = 1.51 mm, eps_r in {4.2, 4.4, 4.6}
  - Outer copper weight      : 1 oz finished = 35 um (0.035 mm)
  - Conformal LPI solder mask: t_mask in {0, 10, 17.5, 25, 35} um, eps_r = 3.8
  - Trace width & CPW gap    : W = 1.08 mm, S = 0.28 mm (0.28 mm GND zone clearance)
  - Longest continuous line  : L_max = 11.18 mm (<= 0.056 lambda_g at 868 MHz)

Benchmarks the zero-thickness FVM limit against Wadell / Ghione-Naldi elliptic-integral
conformal mapping (< 1.0% delta) and exports:
  - rf/results/cpwg_2dfvm_results.csv
  - rf/results/cpwg_2dfvm_summary.json
  - rf/results/cpwg_2dfvm_cross_section.png
"""
from __future__ import annotations

import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.special import ellipk

C0 = 299792458.0
EPS0 = 8.8541878128e-12

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)


def wadell_cpwg(w_m: float, s_m: float, h_m: float, er: float) -> tuple[float, float]:
    """Exact Wadell / Ghione-Naldi conformal mapping for zero-thickness bare CPWG."""
    k = w_m / (w_m + 2.0 * s_m)
    kp = math.sqrt(max(0.0, 1.0 - k * k))
    k3 = math.tanh(math.pi * w_m / (4.0 * h_m)) / math.tanh(math.pi * (w_m + 2.0 * s_m) / (4.0 * h_m))
    k3p = math.sqrt(max(0.0, 1.0 - k3 * k3))
    r1 = float(ellipk(k * k) / ellipk(kp * kp))
    r3 = float(ellipk(k3 * k3) / ellipk(k3p * k3p))
    q = r3 / (r1 + r3)
    eeff = 1.0 + q * (er - 1.0)
    z0 = (60.0 * math.pi / math.sqrt(eeff)) / (r1 + r3)
    return z0, eeff


def solve_cpwg_nonuniform_fvm(
    w_mm: float = 1.08,
    s_mm: float = 0.28,
    h_mm: float = 1.51,
    er: float = 4.4,
    t_cu_mm: float = 0.035,
    t_mask_mm: float = 0.0175,
    er_mask: float = 3.8,
    gw_mm: float = 6.0,
    top_mm: float = 8.0,
) -> tuple[float, float]:
    """
    Exact half-domain PMC-symmetric (x >= 0) non-uniform tensor-product 2D-FVM Laplace solver.
    Every geometric boundary (x = w/2, x = w/2 + s, y = h, y = h + t_cu, y = h + t_cu + t_mask)
    falls on an exact grid coordinate.
    """
    half_w = 0.5 * w_mm
    x_gnd0 = half_w + s_mm
    x_gnd1 = x_gnd0 + gw_mm
    x_max = x_gnd1 + 2.0

    # Fine 5 um step across trace edge & CPWG slot, graded outward
    xs_parts = [
        np.linspace(0.0, half_w - 0.08, 24, endpoint=False),
        np.linspace(half_w - 0.08, x_gnd0 + 0.08, int(round((s_mm + 0.16) / 0.005)) + 1),
        np.geomspace(0.008, gw_mm - 0.08, 42) + (x_gnd0 + 0.08),
        np.linspace(x_gnd1 + 0.1, x_max, 12),
    ]
    x = np.unique(np.round(np.concatenate([[0.0, half_w, x_gnd0, x_gnd1], *xs_parts]), 7))

    # Vertical coordinate y (mm): 0 = B.Cu ground plane, h_mm = top of FR-4 core
    y_cu_top = h_mm + t_cu_mm
    # Conformal LPI solder mask coats the FR-4 slot to height h_mm + t_mask_mm and coats top/sidewalls of Cu
    y_sm_slot = h_mm + t_mask_mm
    y_sm_trace = y_cu_top + (0.75 * t_mask_mm if t_mask_mm > 0 else 0.0)
    y_top_fine = max(y_cu_top, y_sm_slot, y_sm_trace) + 0.08

    ys_sub = h_mm - np.geomspace(0.004, h_mm, 48)[::-1]
    ys_sub[0] = 0.0
    ys_fine = np.linspace(h_mm - 0.06, y_top_fine, int(round((y_top_fine - (h_mm - 0.06)) / 0.0025)) + 1)
    ys_air = y_top_fine + np.geomspace(0.005, top_mm, 44)
    key_y = [0.0, h_mm, y_cu_top, y_sm_slot, y_sm_trace]
    y = np.unique(np.round(np.concatenate([key_y, ys_sub, ys_fine, ys_air]), 7))

    nx = len(x)
    ny = len(y)
    dx = np.diff(x)  # (nx - 1,)
    dy = np.diff(y)  # (ny - 1,)
    xc = 0.5 * (x[:-1] + x[1:])
    yc = 0.5 * (y[:-1] + y[1:])
    XC, YC = np.meshgrid(xc, yc)  # (ny - 1, nx - 1)

    fixed_mask = np.zeros((ny, nx), dtype=bool)
    V0 = np.zeros((ny, nx), dtype=float)
    # Bottom ground plane (y = 0), far top boundary, far right boundary -> 0 V
    fixed_mask[0, :] = True
    fixed_mask[-1, :] = True
    fixed_mask[:, -1] = True

    sig_cols = x <= half_w + 1e-8
    gnd_cols = (x >= x_gnd0 - 1e-8) & (x <= x_gnd1 + 1e-8)
    cu_rows = (y >= h_mm - 1e-8) & (y <= y_cu_top + 1e-8)

    for jr in np.where(cu_rows)[0]:
        fixed_mask[jr, sig_cols] = True
        V0[jr, sig_cols] = 1.0
        fixed_mask[jr, gnd_cols] = True
        V0[jr, gnd_cols] = 0.0

    free_flat = ~fixed_mask.ravel()
    n_free = int(free_flat.sum())
    node_id = np.arange(ny * nx).reshape(ny, nx)
    free_map = -np.ones(ny * nx, dtype=int)
    free_map[free_flat] = np.arange(n_free)

    def _cap_per_m(er_sub: float, er_sm: float) -> float:
        cell_eps = np.ones((ny - 1, nx - 1), dtype=float)
        cell_eps[YC < h_mm] = er_sub

        if t_mask_mm > 0 and er_sm > 1.0:
            # Conformal LPI mask fills slot up to h_mm + t_mask_mm, coats Cu sidewalls by 0.8*t_mask_mm,
            # and coats Cu top surface by 0.75*t_mask_mm:
            in_slot_mask = (YC >= h_mm) & (YC <= y_sm_slot)
            on_sig_top = (XC <= half_w + 0.8 * t_mask_mm) & (YC >= h_mm) & (YC <= y_sm_trace)
            on_gnd_top = (XC >= x_gnd0 - 0.8 * t_mask_mm) & (XC <= x_gnd1) & (YC >= h_mm) & (YC <= y_sm_trace)
            cell_eps[in_slot_mask | on_sig_top | on_gnd_top] = er_sm

        # Exact FVM edge conductances on half-domain x >= 0:
        # Horizontal edge (j, i) -> (j, i+1) has length dx[i] and dual height 0.5*dy[j-1] + 0.5*dy[j]
        ch_half = np.zeros((ny, nx - 1), dtype=float)
        ch_half[1:, :] += 0.5 * cell_eps * (dy[:, None] / dx[None, :])
        ch_half[:-1, :] += 0.5 * cell_eps * (dy[:, None] / dx[None, :])

        # Vertical edge (j, i) -> (j+1, i) has length dy[j] and dual width 0.5*dx[i-1] + 0.5*dx[i]
        # Note: at col 0 (PMC plane x = 0), half-domain cell width is 0.5*dx[0]; mirror across x=0 doubles
        # both horizontal outgoing flux and vertical conductance in node equation, OR equivalently we minimize
        # the half-domain Dirichlet functional E_half = 0.5 * sum(ch_half * dVx^2 + cv_half * dVy^2), whose
        # exact Euler-Lagrange stationarity condition dE_half / dV_{j,i} = 0 uses ch_half and cv_half directly!
        cv_half = np.zeros((ny - 1, nx), dtype=float)
        cv_half[:, 1:] += 0.5 * cell_eps * (dx[None, :] / dy[:, None])
        cv_half[:, :-1] += 0.5 * cell_eps * (dx[None, :] / dy[:, None])

        diag = np.zeros((ny, nx), dtype=float)
        diag[:, :-1] += ch_half
        diag[:, 1:] += ch_half
        diag[:-1, :] += cv_half
        diag[1:, :] += cv_half

        rows_l = [np.arange(n_free)]
        cols_l = [np.arange(n_free)]
        vals_l = [diag.ravel()[free_flat]]
        rhs = np.zeros(n_free, dtype=float)

        for n1, n2, ww in (
            (node_id[:, :-1].ravel(), node_id[:, 1:].ravel(), ch_half.ravel()),
            (node_id[:-1, :].ravel(), node_id[1:, :].ravel(), cv_half.ravel()),
        ):
            for src, dst in ((n1, n2), (n2, n1)):
                f_s = free_flat[src]
                f_d = free_flat[dst]
                both = f_s & f_d
                if np.any(both):
                    rows_l.append(free_map[src[both]])
                    cols_l.append(free_map[dst[both]])
                    vals_l.append(-ww[both])
                to_fix = f_s & (~f_d)
                if np.any(to_fix):
                    np.add.at(rhs, free_map[src[to_fix]], ww[to_fix] * V0.ravel()[dst[to_fix]])

        A = sp.csr_matrix(
            (np.concatenate(vals_l), (np.concatenate(rows_l), np.concatenate(cols_l))),
            shape=(n_free, n_free),
        )
        sol = spla.spsolve(A, rhs)
        Vf = V0.ravel().copy()
        Vf[free_flat] = sol
        Vg = Vf.reshape(ny, nx)

        dVx = np.diff(Vg, axis=1)
        dVy = np.diff(Vg, axis=0)
        energy_half = float(np.sum(ch_half * (dVx ** 2)) + np.sum(cv_half * (dVy ** 2)))
        # Full symmetric CPWG capacitance per unit length C = 2 * C_half = 2 * EPS0 * energy_half / (1.0 V)^2
        return 2.0 * EPS0 * energy_half

    c_air = _cap_per_m(1.0, 1.0)
    c_diel = _cap_per_m(er, er_mask)
    z0 = 1.0 / (C0 * math.sqrt(c_air * c_diel))
    eeff = c_diel / c_air
    return z0, eeff


def run_cpwg_audit() -> dict:
    w_mm = 1.08
    s_mm = 0.28
    er_mask = 3.8
    f0_hz = 868.0e6
    l_max_mm = 11.18

    cases = [
        ("Wadell conformal (t_cu=0, bare, er=4.4, h=1.51mm)", "analytical", 1.51, 4.4, 0.0, 0.0),
        ("2D-FVM zero-thickness check (t_cu=0, bare, er=4.4)", "fvm", 1.51, 4.4, 0.0, 0.0),
        ("2D-FVM 1oz Cu bare ENIG (t_cu=35um, no mask, er=4.4)", "fvm", 1.51, 4.4, 0.035, 0.0),
        ("2D-FVM 1oz Cu + 10um LPI mask (er=4.4, thin mask)", "fvm", 1.51, 4.4, 0.035, 0.010),
        ("2D-FVM 1oz Cu + 17.5um LPI mask (NOMINAL Rev E.2)", "fvm", 1.51, 4.4, 0.035, 0.0175),
        ("2D-FVM 1oz Cu + 25um LPI mask (er=4.4, med mask)", "fvm", 1.51, 4.4, 0.035, 0.025),
        ("2D-FVM 1oz Cu + 35um LPI mask (er=4.4, thick mask)", "fvm", 1.51, 4.4, 0.035, 0.035),
        ("2D-FVM Stackup Corner Low-er / Thick-Core (er=4.2, h=1.66mm, 10um LPI)", "fvm", 1.66, 4.2, 0.035, 0.010),
        ("2D-FVM Stackup Corner Nom-Core Low-er (er=4.2, h=1.51mm, 17.5um LPI)", "fvm", 1.51, 4.2, 0.035, 0.0175),
        ("2D-FVM Stackup Corner Nom-Core High-er (er=4.6, h=1.51mm, 17.5um LPI)", "fvm", 1.51, 4.6, 0.035, 0.0175),
        ("2D-FVM Stackup Corner High-er / Thin-Core (er=4.6, h=1.36mm, 35um LPI)", "fvm", 1.36, 4.6, 0.035, 0.035),
    ]

    rows = []
    for label, mode, h_mm, er, t_cu, t_sm in cases:
        if mode == "analytical":
            z0, eeff = wadell_cpwg(w_mm * 1e-3, s_mm * 1e-3, h_mm * 1e-3, er)
        else:
            z0, eeff = solve_cpwg_nonuniform_fvm(
                w_mm=w_mm, s_mm=s_mm, h_mm=h_mm, er=er,
                t_cu_mm=t_cu, t_mask_mm=t_sm, er_mask=er_mask if t_sm > 0 else 1.0,
            )

        lambda_g_mm = (C0 / f0_hz) * 1e3 / math.sqrt(eeff)
        elec_len_lg = l_max_mm / lambda_g_mm
        theta = 2.0 * math.pi * elec_len_lg
        zin = z0 * (50.0 + 1j * z0 * math.tan(theta)) / (z0 + 1j * 50.0 * math.tan(theta))
        gam = abs((zin - 50.0) / (zin + 50.0))
        rl_db = -20.0 * math.log10(gam + 1e-30)
        il_db = -10.0 * math.log10(1.0 - gam * gam)

        rows.append({
            "case": label,
            "h_core_mm": round(h_mm, 3),
            "er_fr4": round(er, 2),
            "t_cu_um": round(t_cu * 1e3, 1),
            "t_mask_um": round(t_sm * 1e3, 1),
            "z0_ohm": round(z0, 2),
            "eeff": round(eeff, 3),
            "lambda_g_868_mm": round(lambda_g_mm, 1),
            "l_max_lambda_g": round(elec_len_lg, 4),
            "seg_return_loss_dB": round(rl_db, 1),
            "seg_mismatch_il_dB": round(il_db, 4),
        })

    csv_path = os.path.join(OUT_DIR, "cpwg_2dfvm_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    ws = np.linspace(0.85, 1.35, 17)
    zs_nom = [
        solve_cpwg_nonuniform_fvm(w_mm=float(wv), s_mm=s_mm, h_mm=1.51, er=4.4, t_cu_mm=0.035, t_mask_mm=0.0175)[0]
        for wv in ws
    ]
    zs_low = [
        solve_cpwg_nonuniform_fvm(w_mm=float(wv), s_mm=s_mm, h_mm=1.66, er=4.2, t_cu_mm=0.035, t_mask_mm=0.010)[0]
        for wv in ws
    ]
    zs_high = [
        solve_cpwg_nonuniform_fvm(w_mm=float(wv), s_mm=s_mm, h_mm=1.36, er=4.6, t_cu_mm=0.035, t_mask_mm=0.035)[0]
        for wv in ws
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.1), dpi=160)
    ax1.fill_between(ws, zs_high, zs_low, color="#bbdefb", alpha=0.55,
                     label="PCBWay FR-4 Tolerance Envelope (er=4.2..4.6, h+/-10%, LPI 10..35um)")
    ax1.plot(ws, zs_nom, lw=2.2, color="#0d47a1", label="Nominal 2D-FVM (h=1.51mm, er=4.4, 35um Cu + 17.5um LPI)")
    ax1.axhline(50.0, color="#2e7d32", ls="--", lw=1.2, label="50.0 Ohm Reference")
    ax1.axvline(w_mm, color="#c62828", ls=":", lw=1.5, label=f"Drawn W = {w_mm:.2f} mm (Z0 = {rows[4]['z0_ohm']:.2f} Ohm)")
    ax1.set_xlabel("CPWG Center Conductor Width W (mm) [Gap S = 0.28 mm]")
    ax1.set_ylabel("Characteristic Impedance Z0 (Ohm)")
    ax1.set_title("A. Non-Uniform 2D-FVM CPWG Z0 vs. Width & Stackup")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=7.0, loc="upper right")

    t_masks = [0.0, 10.0, 17.5, 25.0, 35.0]
    z_masks = [rows[2]["z0_ohm"], rows[3]["z0_ohm"], rows[4]["z0_ohm"], rows[5]["z0_ohm"], rows[6]["z0_ohm"]]
    ax2.plot(t_masks, z_masks, "o-", lw=2.0, color="#6a1b9a", label="2D-FVM (1 oz = 35 um Cu)")
    ax2.axhline(rows[0]["z0_ohm"], color="#ef6c00", ls="--", lw=1.3,
                label=f"Wadell t_cu=0 Bare ({rows[0]['z0_ohm']:.2f} Ohm)")
    ax2.axhline(50.0, color="#2e7d32", ls=":", lw=1.2, label="50.0 Ohm Target")
    ax2.set_xlabel("Conformal LPI Solder Mask Thickness over Gap/Trace (um)")
    ax2.set_ylabel("Z0 (Ohm) [W=1.08, S=0.28, h=1.51 mm]")
    ax2.set_title("B. Finite Copper Sidewall + LPI Mask Pull-Down")
    ax2.set_ylim(48.5, 58.5)
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7.5, loc="upper right")

    fig.tight_layout(pad=1.1)
    png_path = os.path.join(OUT_DIR, "cpwg_2dfvm_cross_section.png")
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

    fvm_physical = [r for r in rows if r["t_cu_um"] > 0]
    summary = {
        "geometry": {"w_mm": w_mm, "s_mm": s_mm, "l_max_mm": l_max_mm, "stitching_pitch_max_mm": 3.40},
        "nominal_rev_e2": rows[4],
        "wadell_zero_thickness_bare": rows[0],
        "fvm_zero_thickness_agreement_pct": round(abs(rows[1]["z0_ohm"] - rows[0]["z0_ohm"]) / rows[0]["z0_ohm"] * 100.0, 2),
        "physical_1oz_envelope_ohm": [
            min(r["z0_ohm"] for r in fvm_physical),
            max(r["z0_ohm"] for r in fvm_physical),
        ],
        "worst_case_segment_return_loss_dB": min(r["seg_return_loss_dB"] for r in fvm_physical),
        "worst_case_segment_mismatch_il_dB": max(r["seg_mismatch_il_dB"] for r in fvm_physical),
        "cases": rows,
    }
    json_path = os.path.join(OUT_DIR, "cpwg_2dfvm_summary.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    assert summary["fvm_zero_thickness_agreement_pct"] < 1.0, (
        f"Zero-thickness FVM vs Wadell delta {summary['fvm_zero_thickness_agreement_pct']}% >= 1.0%"
    )
    assert summary["worst_case_segment_return_loss_dB"] >= 23.0
    print(
        f"[PASS] CPWG 2D-FVM Audit: Wadell(t=0)={rows[0]['z0_ohm']:.2f} Ohm vs FVM(t=0)={rows[1]['z0_ohm']:.2f} Ohm "
        f"({summary['fvm_zero_thickness_agreement_pct']:.2f}% delta); "
        f"Nominal 1oz+17.5um LPI Z0 = {rows[4]['z0_ohm']:.2f} Ohm "
        f"(envelope {summary['physical_1oz_envelope_ohm'][0]:.2f}..{summary['physical_1oz_envelope_ohm'][1]:.2f} Ohm, "
        f"RL >= {summary['worst_case_segment_return_loss_dB']:.1f} dB across {l_max_mm} mm)."
    )
    return summary


if __name__ == "__main__":
    run_cpwg_audit()
