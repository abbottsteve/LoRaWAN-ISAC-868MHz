# CST Studio Suite 3D Antenna & Radome Model (`Rev E.5`)

Parameterized 3D full-wave electromagnetic simulation package for the **ISAC_868 (Rev E.5)** shared-aperture Inverted-F + Interdigital Evanescent-Field Antenna (`AE1`), 50 × 40 mm ground counterpoise, 4-element elliptic harmonic Pi-filter (`C_M1`, `L_M1 || C_MZ`, `C_M2`), 25 µm 3M 467MP adhesive layer, self-draining 0.80 mm ASA/PETG radome, and dispersive dielectric superstrates in **SIMULIA CST Studio Suite (2022–2026)**.

![CST Studio Suite 3D Simulation Architecture](previews/CST_Simulation_Model_Blueprint.png)

---

## 1. Purpose & Geometry Provenance

While [`rf/fdtd_3d_ant.c`](../rf/fdtd_3d_ant.c) provides an open-source OpenMP Yee-grid FDTD solver for automated verification, this CST Studio Suite model supports three complementary analyses ahead of pilot VNA correlation:
1. **Conformal Subcell Meshing (`PBA` / `TST`):** Resolves rounded trace ends, the 0.28 mm CPWG coplanar gap, and the 25 µm 3M 467MP transfer-tape layer without staircase discretization.
2. **Independent Solver Cross-Checks:** Evaluates the same geometry under CST's Time-Domain hexahedral (`FIT`, 0.70–3.00 GHz) and Frequency-Domain 2nd-order curved tetrahedral (`FEM`, adaptive energy refinement at 866.5 MHz) formulations.
3. **3D Farfield & Circuit Co-Simulation:** Extracts 3D radiation patterns, dielectric/conductor loss partitioning across EU868 tones (863.1, 866.5, 869.5 MHz) and ETSI EN 300 220-1 harmonics (1.733 GHz, 2.600 GHz), and Design Studio schematic co-simulation with vendor `.s2p` passives.

All copper polygons, 0402 land pads, CPWG clearances, and 0.60/0.30 mm stitching vias are extracted read-only from the frozen Rev E.5 layout ([`ISAC_868_KiCad9.kicad_pcb`](../ISAC_868_KiCad9.kicad_pcb) and [`IFA_868MHz_ISAC_40x20mm.kicad_mod`](../ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod)) by [`generate_cst_package.py`](generate_cst_package.py) in the board's right-handed manufacturing coordinate system:
- **Origin (0, 0, 0) mm:** Bottom-left corner of the 90.00 × 40.00 mm PCB on the top FR-4 / `F.Cu` interface (`KiCad AuxOrigin = (103.500, 120.000) mm`).
- **+X (0..90 mm):** East toward the `AE1` radiator and open-East self-draining sensing deck.
- **+Y (0..40 mm):** North across the 40 mm board width (`AE1` feed spine centered on Y = 20.000 mm).
- **+Z (mm):** Vertical normal above the FR-4 top face (`F.Cu` = 0..+0.035 mm, FR-4 = -1.510..0.000 mm, `B.Cu` = -1.545..-1.510 mm).

---

## 2. Directory Layout

```text
cst_studio/
├── README.md                                     # Model setup, material parameters & workflow notes
├── generate_cst_package.py                       # Extracts KiCad Rev E.5 copper -> VBA macros, DXFs & plots
├── macros/
│   ├── ISAC_868_Complete_Antenna_MWS.bas         # Primary CST Microwave Studio 3D builder (TD-FIT, 0.70-3.00 GHz)
│   ├── ISAC_868_Setup_FEM_CrossCheck.bas         # CST Tetrahedral Frequency-Domain (FEM) adaptive cross-check
│   ├── ISAC_868_Sweep_All_Superstrates.bas       # 10-case CST batch sweep -> Touchstone .s1p + Farfields
│   └── ISAC_868_FrontEnd_CoSim_DS.bas            # CST Design Studio (DS) bridge + Murata .s2p + LT5538 setup
├── cad_exports/
│   ├── AE1_and_Filter_F_Cu.dxf                   # Closed R2000 polylines of AE1, CPWG launch, pads & F.Cu GND
│   ├── Counterpoise_B_Cu.dxf                     # B.Cu ground plane with 2.20 x 2.20 mm /BR_S relief
│   ├── Bare_ENIG_Window_F_Mask.dxf               # [73.40..87.80] x [6.65..20.80] mm solder-mask sensing window
│   ├── PCB_Outline_EdgeCuts.dxf                  # 90.00 x 40.00 mm (R = 2.00 mm) board outline + H1..H4 NPTH
│   └── geometry_manifest.json                    # Extracted pad/via coordinates & SHA-256 provenance
├── python/
│   ├── run_cst_batch.py                          # Headless cst.interface / cst.results driver + VBA syntax checker
│   └── postprocess_cst_results.py                # Touchstone .s1p -> Pi-filter de-embed + Rev E.5 bridge evaluator
├── previews/
│   └── CST_Simulation_Model_Blueprint.png        # 4-panel CST geometry, mesh, stackup & Debye permittivity view
└── results/
    └── fdtd_reference/                           # 3D-FDTD reference .s1p curves & post-processor self-check
```

---

## 3. Physical Stackup, Surface Impedance & Dispersive Materials

### 3.1 Z-Axis Mechanical & Dielectric Stackup (`enclosure_en = 1`)
Boolean `Solid.Insert` operations in [`ISAC_868_Complete_Antenna_MWS.bas`](macros/ISAC_868_Complete_Antenna_MWS.bas) carve copper fingers, vias, solder mask, transfer adhesive, and fasteners sequentially so adjacent solids share conformal interfaces without intersecting volumes:

| Layer / Component | CST Component:Solid | Z-Span [mm] | Material Model (0.70–3.00 GHz) |
| :--- | :--- | :---: | :--- |
| **Enclosure Base Tray** | `Enclosure:ASA_Base_Tray` | -7.600 .. -1.600 (4.0 mm air cavity -5.60..-1.60) | `ASA_PETG_Radome` ($\varepsilon_r = 3.05, \tan\delta = 0.012$) |
| **Perimeter O-Ring** | `Enclosure:EPDM_ORing_Outer` | -2.360 .. -1.440 (continuous perimeter gland) | `EPDM_ORing_5700` ($\varepsilon_r = 2.55, \tan\delta = 0.010$) |
| **Bottom Solder Mask** | `PCB_Mask:Bot_LPI_Mask` | -1.580 .. -1.510 | `SolderMask_LPI` ($\varepsilon_r = 3.40, \tan\delta = 0.025$) |
| **Bottom `B.Cu` Plane** | `PCB_Copper:Bot_GND_Counterpoise` | -1.545 .. -1.510 (X = 0.45..50.00) | `Copper_ENIG_IPC4552` ($R_s = 23.74\text{ m}\Omega/\square$) |
| **2-Layer FR-4 Core** | `PCB_Substrate:FR4_Core` | -1.510 .. 0.000 | `FR4_ISAC_Core` ($\varepsilon_r = 4.40 \pm 0.20, \tan\delta = 0.020$) |
| **Top `F.Cu` & `AE1` IDE** | `PCB_Copper:AE1_*`, `Top_GND_*` | 0.000 .. +0.035 | `Copper_ENIG_IPC4552` ($\sigma_{\text{eq}} = 1.24 \times 10^7\text{ S/m}$) |
| **Top LPI Solder Mask** | `PCB_Mask:Top_LPI_Mask` | 0.000 .. +0.070 (open over [73.4..87.8]×[6.65..20.8]) | `SolderMask_LPI` ($\varepsilon_r = 3.40, \tan\delta = 0.025$) |
| **3M 467MP Bondline** | `Enclosure:Adhesive_467MP` | 0.000 .. +0.060 (25 µm above `AE1` fingers + trench fill) | `Adhesive_3M_467MP` ($\varepsilon_r = 2.80, \tan\delta = 0.015$) |
| **Sensing Window & Lid** | `Enclosure:ASA_Upper_Lid` | +0.060 .. +0.860 (0.80 mm open-East window; +8.50 mm roof) | `ASA_PETG_Radome` ($\varepsilon_r = 3.05, \tan\delta = 0.012$) |
| **Test Superstrate Film** | `Superstrate:Superstrate_Film` | +0.860 .. +2.860 (`h_superstrate = 2.00` mm default) | Parametric `superstrate_id = 0..5` (Table 3.2) |

> **IPC-4552 ENIG Surface Loss (`use_enig_loss = 1`):** Electroless nickel (4.5 µm NiP, $\rho \approx 7.5 \times 10^{-7}\ \Omega\cdot\text{m}, \mu_r \approx 2.0$) beneath 0.05 µm immersion gold raises RF surface resistance at 866.5 MHz from 7.7 mΩ/sq (annealed copper) to 23.74 mΩ/sq. Because current crowds along the edges of the 1.30 mm interdigital fingers and IFA shorting stub, modeling pure copper over-predicts unloaded Q and radiation efficiency by roughly 4–6%. Setting `use_enig_loss = 0` in CST's Parameter List isolates the NiP conductor loss contribution directly.

### 3.2 Broadband 1st-Order Debye Superstrate Models (0.70–3.00 GHz)
Polar fluids exhibit strong dipolar relaxation across 0.7–3.0 GHz. Rather than constant-conductivity approximations, `Superstrate_IPA_Debye` and `Superstrate_Water_Debye` use CST's causal `Debye1st` model:

| `superstrate_id` | CST Material | Dispersion Type | Parameters | $\varepsilon_r^*(868\text{ MHz})$ |
| :---: | :--- | :---: | :--- | :---: |
| **0** | `Superstrate_DryAir` | Normal | $\varepsilon_r = 1.00$ | $1.00 - j0.000$ |
| **1** | `Superstrate_Oil_PTFE` | `ConstTanD` | $\varepsilon_r = 2.10, \tan\delta = 0.0001$ | $2.10 - j0.0002$ |
| **2** | `Superstrate_GlazeIce` | `ConstTanD` | $\varepsilon_r = 3.20, \tan\delta = 0.00094$ | $3.20 - j0.003$ |
| **3** | `Superstrate_Alumina` | `ConstTanD` | $\varepsilon_r = 9.80, \tan\delta = 0.00020$ | $9.80 - j0.002$ |
| **4** | `Superstrate_IPA_Debye` | `Debye1st` | $\varepsilon_s = 19.90, \varepsilon_\infty = 3.20, \tau = 408.0\text{ ps}$ | $6.29 - j6.090$ |
| **5** | `Superstrate_Water_Debye` | `Debye1st` | $\varepsilon_s = 80.10, \varepsilon_\infty = 4.90, \tau = 9.30\text{ ps}$ | $79.91 - j3.810$ |

---

## 4. Port Planes, Meshing & Convergence Settings

### 4.1 Selectable Port Reference Planes (`excitation_mode`)
- **`excitation_mode = 1` (Default — `/BR_Q` Plane Downstream of Bridge `R1`):** Places 50 Ω `DiscreteFacePort 1` at X = 41.20 mm, Y = 20.00 mm and populates 3D `LumpedElement` RLC branches (`C_M1` = 3.6 pF, `L_M1` = 8.2 nH, `C_MZ` = 0.50 pF, `C_M2` = 4.3 pF including 0402 ESR/ESL) across their KiCad pads and 0.60/0.30 mm shunt ground vias. This captures pad-to-ground fringing, shunt via inductance, and harmonic rejection at 1.733 GHz and 2.600 GHz in a single 3D solve.
- **`excitation_mode = 0` (`AE1` Feed Plane at `/ANT_FEED`):** Places 50 Ω `DiscreteFacePort 1` directly at `AE1` Pad 1 (X = 49.40 mm, Y = 20.00 mm) with the Pi-filter omitted. Use this setting when comparing against a 1-port VNA calibrated at `AE1` (0 Ω jumper across `L_M1`, shunt capacitors open) or when cascading vendor Murata `.s2p` Touchstone models in CST Design Studio ([`ISAC_868_FrontEnd_CoSim_DS.bas`](macros/ISAC_868_FrontEnd_CoSim_DS.bas)).

### 4.2 Local Hexahedral Mesh Refinement Zones
Three `MeshSettings` groups concentrate cells in high-gradient regions while keeping total cell count around 350k–550k:
1. **`MeshZone_IDE_and_Window` (0.25 × 0.20 × 0.08 mm):** Places 6 cells across each 1.20 mm interdigital gap and 10 vertical cells across the 0.80 mm ASA/PETG window to resolve evanescent field decay into the superstrate.
2. **`MeshZone_Port_and_Filter` (0.15 × 0.09 × 0.18 mm):** Places at least 3 cells across each 0.28 mm CPWG coplanar gap and resolves the 0402 filter pad gaps.
3. **`MeshZone_FR4_Substrate` (0.80 × 0.80 × 0.25 mm):** Enforces at least 6 vertical cells across the 1.51 mm FR-4 core.

### 4.3 Steady-State Convergence (`-45 dB`)
Cascading `AE1` with the 0.50 pF elliptic notch stores reactive energy near 869 MHz and 1.733 GHz. Stopping the transient solver at -30 dB or -40 dB leaves roughly ±0.25 dB of DFT truncation ripple across `f1..f3`, perturbing differential `Tilt` and `Notch`. The macro sets `.SteadyStateLimit "-45"` with 28 pulse widths and 1,151 frequency samples (2.0 MHz step across 0.70–3.00 GHz).

---

## 5. Execution Workflows

### Workflow A — Interactive CST Studio Suite GUI (Windows / Linux)
1. Launch **CST Studio Suite** and create an empty **3D Microwave & RF → Antennas → Planar** project.
2. Open **Home → Macros → File → Open VBA Macro Editor**, load [`macros/ISAC_868_Complete_Antenna_MWS.bas`](macros/ISAC_868_Complete_Antenna_MWS.bas), and press **F5 (Run)**.
3. Inspect the 3D solids and mesh (**Mesh → Mesh View**). Adjust `superstrate_id`, `enclosure_en`, `battery_mode`, `h_superstrate`, `h_window`, or `fastener_metal_en` in **View → Parameter List** (`F7` to rebuild).
4. Run **Home → Start Simulation** (`Time Domain Solver`).
5. **Overlaying 3D-FDTD Reference Curves:** Drag any `.s1p` file from [`results/fdtd_reference/`](results/fdtd_reference/) (for example `02_dry_air_fdtd_ref.s1p` or `07_glaze_ice_fdtd_ref.s1p`) onto **1D Results → S-Parameters** in the CST Navigation Tree to compare $\lvert\Gamma_{\text{in}}(f)\rvert$ at `/BR_Q`.
6. **10-Scenario Batch Sweep:** Run [`macros/ISAC_868_Sweep_All_Superstrates.bas`](macros/ISAC_868_Sweep_All_Superstrates.bas) to solve all 10 benchmark cases and export `.s1p` plus 866.5 MHz Farfield ASCII files into `<project_folder>/cst_exports/`.
7. **Tetrahedral FEM Cross-Check:** On a project copy, run [`macros/ISAC_868_Setup_FEM_CrossCheck.bas`](macros/ISAC_868_Setup_FEM_CrossCheck.bas) and start the **Frequency Domain Solver** (730–940 MHz, 2nd-order curved tetrahedra, adaptive energy threshold $\Delta S \le 0.005$ at 866.5 MHz).

### Workflow B — Headless Python CLI (`cst.interface`) & Post-Processing
```bash
# 1. Offline VBA syntax & CST History-block balance verification (no CST license needed)
PYTHONDONTWRITEBYTECODE=1 python3 cst_studio/python/run_cst_batch.py --check-macros

# 2. Verify Touchstone .s1p serialization, Pi-filter de-embedding & 3-tone bridge post-processor
PYTHONDONTWRITEBYTECODE=1 python3 cst_studio/python/postprocess_cst_results.py --verify-pipeline

# 3. Solve all 10 scenarios headlessly on a licensed CST workstation -> cst_studio/results/*.s1p
PYTHONDONTWRITEBYTECODE=1 python3 cst_studio/python/run_cst_batch.py \
  --cst-root "/opt/cst/CST_Studio_Suite_2026" \
  --all

# 4. Evaluate Rev E.5 bridge + LT5538 3-tone classifier on CST exports -> cst_vs_fdtd_comparison.md
PYTHONDONTWRITEBYTECODE=1 python3 cst_studio/python/postprocess_cst_results.py \
  --results-dir cst_studio/results \
  --mode 1
```

---

## 6. 3D-FDTD Reference Targets (`rf/results/ifa_fullwave_3d.json`)

When comparing CST `FIT` and `FEM` runs against the in-repository Yee-grid FDTD baseline (self-check summary in [`results/fdtd_reference/fdtd_touchstone_selfcheck.md`](results/fdtd_reference/fdtd_touchstone_selfcheck.md)), conformal PBA edge treatment typically shifts unloaded $f_0$ by ±4–8 MHz—within half the FR-4 $\varepsilon_r = 4.4 \pm 0.2$ laminate tolerance—while preserving the dielectric detuning trajectory. Both reflection reference planes are listed below (`AE1` Pad 1 standalone $\lvert\Gamma_{\text{ant}}\rvert$ vs. Pi-filter-cascaded $\lvert\Gamma_{\text{in}}\rvert$ at `/BR_Q`):

| Case Tag | Scenario ($h_{\text{sup}} = 2.0\text{ mm}$) | FDTD $f_0$ [MHz] | $\lvert\Gamma_{\text{ant}}\rvert_{866.5}$ @ `AE1` [dB] | $\lvert\Gamma_{\text{in}}\rvert_{866.5}$ @ `/BR_Q` [dB] | $\eta_{\text{tot}}$ [%] | Tilt [dB] | Level [dBm] | Expected Firmware Class |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `01_bare_pcb` | Bare PCB (`enclosure_en=0`) | 940.0 | -0.78 | -1.34 | 14.2% | — | — | *(Unenclosed VNA check)* |
| `02_dry_air` | Enclosed Dry Air ($\varepsilon_r'=1.00$) | 869.0 | -23.69 | -20.83 | 45.5% | -3.44 | -45.66 | `DRY_AIR` (`SF7`) |
| `06_oil_ptfe` | Oil / PTFE ($\varepsilon_r'=2.10$) | 849.0 | -7.04 | -7.14 | 35.4% | -1.23 | -33.26 | `OIL` (`SF7`) |
| `07_glaze_ice` | Glaze Ice ($\varepsilon_r'=3.20$) | 834.5 | -2.55 | -2.89 | 13.4% | -0.01 | -28.63 | `GLAZE_ICE` (`SF9`) |
| `08_alumina_al2o3` | Alumina Al<sub>2</sub>O<sub>3</sub> ($\varepsilon_r'=9.80$) | 783.0 | -0.36 | -0.53 | 5.1% | +1.56 | -26.19 | `IPA` *(Point-2 Cal Ref)* |
| `09_ipa_debye` | IPA (`Debye1st`, $6.29 - j6.09$) | 794.0 | -1.63 | -2.19 | 4.8% | +1.45 | -27.75 | `IPA` (`SF12`) |
| `10_water_debye` | Water (`Debye1st`, $79.9 - j3.81$) | 776.0 | -0.46 | -0.72 | 9.6% | +1.22 | -26.35 | `LIQUID_WATER` (`SF12`) |
