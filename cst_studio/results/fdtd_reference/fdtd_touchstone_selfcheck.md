# 3D-FDTD Reference Touchstone (`.s1p`) & Bridge Post-Processor Self-Check (`Rev E.5`)

> **Note:** This table verifies Touchstone `.s1p` serialization, Pi-filter de-embedding, and 3-tone return-loss bridge post-processing against the in-repo 3D-FDTD baseline (`rf/results/ifa_fullwave_3d.json`). No CST Studio Suite solver data are included here; when CST exports are placed in `cst_studio/results/`, running `postprocess_cst_results.py` generates `cst_studio/results/cst_vs_fdtd_comparison.md`.

| Case | Medium | Parsed .s1p $f_0$ [MHz] | FDTD $f_0$ [MHz] | Parsed .s1p $\lvert\Gamma_{\text{ant}}\rvert_{866.5}$ [dB] | Parsed .s1p $\lvert\Gamma_{\text{in}}\rvert_{866.5}$ [dB] | Parsed .s1p Tilt [dB] | FDTD Tilt [dB] | Parsed .s1p Level [dBm] | FDTD Level [dBm] | Firmware Class |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `01_bare_pcb` | bare | 940.0 | 940.0 | -0.78 | -1.34 | +0.93 | — | -26.87 | — | `— (Unenclosed VNA)` |
| `02_dry_air` | dry air | 869.0 | 869.0 | -23.69 | -20.83 | -3.44 | -3.44 | -45.66 | -45.66 | `DRY_AIR` |
| `03_enclosed_lipo` | lipo | 869.0 | 869.0 | -23.68 | -20.81 | -3.45 | — | -45.64 | — | `DRY_AIR` |
| `04_fr4_low_4p2` | fr4_low | 879.0 | 879.0 | -10.01 | -12.67 | +1.73 | — | -36.59 | — | `— (FR-4 er=4.2 Corner)` |
| `05_fr4_high_4p6` | fr4_high | 859.5 | 859.5 | -14.42 | -12.76 | -4.57 | — | -40.06 | — | `— (FR-4 er=4.6 Corner)` |
| `06_oil_ptfe` | PTFE | 849.0 | 849.0 | -7.04 | -7.14 | -1.23 | -1.23 | -33.27 | -33.26 | `OIL` |
| `07_glaze_ice` | glaze ice | 834.5 | 834.5 | -2.55 | -2.89 | -0.01 | -0.01 | -28.63 | -28.63 | `GLAZE_ICE` |
| `08_alumina_al2o3` | alumina Al2O3 | 783.0 | 783.0 | -0.36 | -0.53 | +1.56 | +1.56 | -26.19 | -26.19 | `IPA` |
| `09_ipa_debye` | IPA (868 MHz) | 794.0 | 794.0 | -1.63 | -2.19 | +1.45 | +1.45 | -27.75 | -27.75 | `IPA` |
| `10_water_debye` | water film | 776.0 | 776.0 | -0.46 | -0.72 | +1.22 | +1.22 | -26.35 | -26.35 | `LIQUID_WATER` |

- **Air-to-Ice Resonant Sensitivity (`AE1` feed plane):** 43.73 MHz/RIU (3D-FDTD baseline: 43.73 MHz/RIU)
