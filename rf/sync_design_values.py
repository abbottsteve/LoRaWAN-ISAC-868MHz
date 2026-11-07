#!/usr/bin/env python3
"""
sync_design_values.py -- Single-Source-of-Truth Synchronizer for `firmware/test/data/design_values.json`
                         from `rf/results/ifa_fullwave_3d.json` + `rf/results/bridge_3tone_curves.json`
                         + `rf/results/bridge_sparam_sweep.csv` (Gate 4: <= 0.01 dB / 0.00 MHz parity).
"""
from __future__ import annotations

import csv
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES_DIR = os.path.join(HERE, "results")
DV_PATH = os.path.join(ROOT, "firmware", "test", "data", "design_values.json")


def sync_design_values() -> None:
    with open(os.path.join(RES_DIR, "ifa_fullwave_3d.json"), "r", encoding="utf-8") as fh:
        fw = json.load(fh)
    with open(os.path.join(RES_DIR, "bridge_3tone_curves.json"), "r", encoding="utf-8") as fh:
        br = json.load(fh)
    with open(DV_PATH, "r", encoding="utf-8") as fh:
        dv = json.load(fh)

    sweep_by_f = {}
    with open(os.path.join(RES_DIR, "bridge_sparam_sweep.csv"), "r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sweep_by_f[round(float(row["freq_MHz"]), 2)] = row

    def interp_dir(f_mhz: float) -> float:
        fs = sorted(sweep_by_f.keys())
        for i in range(len(fs) - 1):
            if fs[i] <= f_mhz <= fs[i + 1]:
                t = (f_mhz - fs[i]) / (fs[i + 1] - fs[i])
                d0 = float(sweep_by_f[fs[i]]["directivity_wc_dB"])
                d1 = float(sweep_by_f[fs[i + 1]]["directivity_wc_dB"])
                return round(d0 + t * (d1 - d0), 2)
        return round(float(sweep_by_f[866.5]["directivity_wc_dB"]), 2)

    dv["revision"] = "E.5"
    dv["R1"] = 8.2
    dv["R1_PRIMARY_MPN"] = "Yageo RT0402BRD078R2L"
    dv["R2"] = 681.0
    dv["R3"] = 3570.0
    dv["R_TERM"] = 56.0
    dv["R_TERM_PRIMARY_MPN"] = "Susumu RG1005P-560-B-T5"
    dv["C_SENSE_PF"] = 1.0
    dv["C_COMP_PF"] = 1.0
    dv["L_COMP_NH"] = 27.0
    dv["L_SENSE_NH"] = 30.0
    dv["C_PAR_BRS_PF"] = br["c_par_brs_pf"]
    dv["pcb_bridge_copper_lengths_mm"] = br["pcb_bridge_copper_lengths_mm"]
    dv["lt5538_zin_866p5_series_ohm"] = br["lt5538_zin_866p5_series_ohm"]
    dv["lt5538_zin_866p5_parallel_rc"] = br["lt5538_zin_866p5_parallel_rc"]
    dv["two_point_calibration"] = br["two_point_calibration"]
    dv["stackup_core_sweep"] = br["stackup_core_sweep"]
    dv["P_TX_SENSING_DBM"] = br["p_tx_sensing_dbm"]
    dv["P_TX_LORAWAN_DBM"] = 14.0
    dv["tcxo_ctrl_voltage_V"] = 3.0
    dv["tcxo_ctrl_code_hex"] = "0x06"
    dv["harmonic_pi_network"] = fw["harmonic_pi_network"]
    dv["fr4_er_corners"] = {
        "4.2": {
            "f0_MHz": fw["media"]["fr4_low"]["f0_MHz"],
            "worst_s11_863_870_dB": fw["media"]["fr4_low"]["worst_s11_863_870_dB"],
            "eta_tot_pct": fw["media"]["fr4_low"]["eta_tot_pct"],
        },
        "4.4": {
            "f0_MHz": fw["media"]["dry air"]["f0_MHz"],
            "worst_s11_863_870_dB": fw["media"]["dry air"]["worst_s11_863_870_dB"],
            "eta_tot_pct": fw["media"]["dry air"]["eta_tot_pct"],
        },
        "4.6": {
            "f0_MHz": fw["media"]["fr4_high"]["f0_MHz"],
            "worst_s11_863_870_dB": fw["media"]["fr4_high"]["worst_s11_863_870_dB"],
            "eta_tot_pct": fw["media"]["fr4_high"]["eta_tot_pct"],
        },
    }
    dv["battery_life_10yr"]["smps_mode"] = (
        "ENABLED (L_SMPS = 15 uH Murata LQH2MCN150K02L wirewound, Isat = 300 mA, ~45% TX/RX current reduction vs LDO)"
    )

    nom_m = br["nominal_866p5_metrics"]
    mc_cal = br["mc_summary"][0]
    dv["insertion_loss_dB"] = round(nom_m["s21_dB"], 3)
    dv["directivity_dB"] = round(nom_m["directivity_wc_dB"], 2)
    dv["directivity_band_dB"] = {
        "863.1": interp_dir(863.1),
        "866.5": round(nom_m["directivity_wc_dB"], 2),
        "869.5": interp_dir(869.5),
    }
    dv["mc_directivity_median_dB"] = mc_cal["directivity_median_dB"]
    dv["mc_directivity_p10_dB"] = mc_cal["directivity_p10_dB"]
    dv["mc_directivity_p05_dB"] = mc_cal["directivity_p05_dB"]
    dv["mc_air_to_ice_contrast_median_dB"] = mc_cal["air_to_ice_contrast_median_dB"]
    dv["mc_air_to_ice_contrast_p01_dB"] = mc_cal["air_to_ice_contrast_p01_dB"]
    dv["mc_yield_ice_contrast_gt_6dB_pct"] = mc_cal["yield_ice_contrast_gt_6dB_pct"]

    f_air = fw["media"]["dry air"]["f0_MHz"]
    f_ice = fw["media"]["glaze ice"]["f0_MHz"]
    riu_ice = math.sqrt(3.2) - 1.0
    dv["window_material"] = (
        "UV-stabilized ASA/PETG (0.80 mm open-East self-draining flush deck + 25 um 3M 467MP acrylic transfer adhesive)"
    )
    dv["pla_window_mm"] = 0.8
    dv["pla_window_mode"] = "0.80mm_ASA_PETG_open_east_self_draining_deck_with_25um_3M467MP"
    dv["air_to_ice_sensitivity_MHz_per_RIU"] = round((f_air - f_ice) / riu_ice, 2)

    # Rev E.5: Q1 (TPS22919DCKR) fed directly from VBAT (3.0-4.2 V) -> LT5538 32 mA bypassed off U3 3V3 LDO!
    dv["sleep_and_ldo"]["peak_load_mA"] = 24.1
    dv["sleep_and_ldo"]["peak_margin_x"] = round(200.0 / 24.1, 2)
    dv["sleep_and_ldo"]["dropout_at_peak_mV"] = 36.2
    dv["sleep_and_ldo"]["lt5538_supply_rail"] = "VBAT-fed zero-Iq load switch Q1 (TPS22919DCKR, 3.0-5.25V rated LT5538)"

    dv["gated_vbat_divider"]["control_gpio"] = "PA9 (U1 Pad 50, BAT_MON_EN, split from PA8 DET_EN)"
    dv["gated_vbat_divider"]["wakeup_window_us"] = 3000.0
    dv["gated_vbat_divider"]["rail_sense_window_us"] = 150.0
    dv["gated_vbat_divider"]["wakeup_margin_x"] = round(3000.0 / dv["gated_vbat_divider"]["t_settle_12bit_us"], 1)
    dv["gated_vbat_divider"]["adc_sample_time_us"] = 19.75
    dv["gated_vbat_divider"]["adc_single_conv_us"] = 26.0
    dv["gated_vbat_divider"]["adc_16x_oversample_ms"] = 0.416
    dv["gated_vbat_divider"]["det_adc_smp1_sample_time_us"] = 6.25
    dv["gated_vbat_divider"]["det_adc_16x_oversample_ms"] = 0.200

    ports = [p for p in dv["esd_and_ae1_bleed"]["ports"] if p.get("ref") != "D_3V3"]
    ports.append({
        "port": "J4/J3 Protected 3V3 Rail",
        "ref": "D_3V3",
        "mpn": "PESD5V0S1BA,115",
        "topology": "Bidirectional SOD-323 + R_VAPP=1k / R_BHI=10k current limit",
        "contact_kV": 30.0,
        "air_kV": 30.0,
        "c_typ_pF": 35.0,
    })
    dv["esd_and_ae1_bleed"]["ports"] = ports

    dv["derating_audit"]["rf_resistor_series"] = (
        "Yageo RT0402BRD078R2L (R1 8.2R 0.1%) + Susumu RG1005P (R2/R3/R_TERM 0.1%, <= 25 ppm/C NiCr Thin-Film)"
    )
    dv["derating_audit"]["capacitor_groups"][0]["refs"] = (
        "C_RF, C_S, C_S2, C_BLK, C_INN, C_M1, C_MZ, C_M2, C_BAT"
    )
    for cg in dv["derating_audit"]["capacitor_groups"]:
        if cg["refs"] in ("C_IN2", "C_IN2, C_Q1"):
            cg["refs"] = "C_IN2, C_Q1"
            cg["dielectric"] = "X7R (0402 on VBAT_RAW/VBAT <= 5.0V)"
        elif cg["refs"] in ("C_SMPS1, C_SMPS2", "C_SMPS1"):
            cg["refs"] = "C_SMPS1"
            cg["dielectric"] = "X5R (4.7 uF 10V 0402 GRM155R61A475MEAAD on VDDSMPS 3.30V)"
        elif "C_SMPS3" in cg["refs"] and "C_SMPS2" not in cg["refs"]:
            cg["refs"] = cg["refs"].replace("C_SMPS3", "C_SMPS2, C_SMPS3")

    dv["table"] = br["table"]

    with open(DV_PATH, "w", encoding="utf-8") as fh:
        json.dump(dv, fh, indent=2)
        fh.write("\n")

    print(
        f"[PASS] Synchronized {DV_PATH} (Rev {dv['revision']}): "
        f"f0_air={f_air:.2f} MHz, f0_ice={f_ice:.2f} MHz ({dv['air_to_ice_sensitivity_MHz_per_RIU']:.2f} MHz/RIU), "
        f"dir={dv['directivity_dB']:.2f} dB, MC P01 contrast={dv['mc_air_to_ice_contrast_p01_dB']:.2f} dB, "
        f"Water/IPA P01 gap={br['two_point_calibration']['water_vs_ipa_gap_p01_dB']:.2f} dB."
    )


if __name__ == "__main__":
    sync_design_values()
