# PCB Fabrication, Stencil & Turnkey SMT Assembly Specification (`Rev E.5`)

| Document Control | Value |
| :--- | :--- |
| **Project / Assembly** | Dual-Function 868 MHz LoRaWAN ISAC Sensor Node (`ISAC_868_KiCad9`) |
| **Author** | Stephen K. Boachie |
| **Hardware Revision** | `Rev E.5` — Pilot & Turnkey Production Specification |
| **IPC Acceptance Class** | IPC-6012E Class 2 (Bare PCB) / IPC-A-610H Class 2 (Class 3 X-ray voiding target `< 25%` on `U1`/`U2`) |
| **BOM / Placement Scope** | `92` footprints total: `67` populated top-side SMD parts (`38` BOM lines in `ISAC_868_Turnkey_CPL_Top.csv`, `0` THT parts), `10` `DNP` (`8` BOM lines: `C_SMPS3, D_RF, J1..J5, R_DIV1, R_DIV2, R_VUART` — `0` `F_Paste.gtp` flashes), `15` `BOARD_ONLY` (`AE1, FID1..5, H1..4, TP1..5`); single-sided top SMT (`B_Paste.gbp` omitted) |

---

## 1. Bare-Board Fabrication Parameters

| Parameter | Specification | Tolerance / CAM Notes |
| :--- | :--- | :--- |
| **Single-Board Outline** | `90.00 mm × 40.00 mm` (`R = 2.00 mm` corners) | `±0.10 mm` CNC routed profile (`Edge.Cuts`) |
| **Layer Count & Thickness** | 2 Layers (`F.Cu`, `B.Cu`), `1.60 mm` finished thickness | `+0.03 / -0.10 mm` (`1.50–1.63 mm` finished, `1.51 mm` nominal FR-4 core; ensures smooth fit for `Molex 73251-1153` `1.65 mm` fork on bench VNA units) |
| **Base Laminate** | Standard FR-4 (`Tg ≥ 150 °C`, Shengyi `S1000-2M` / Kingboard `KB-6165F` or eq.) | `εr = 4.4 ± 0.2 @ 868 MHz` (`|S11| ≤ -10.21 dB` across `εr ∈ {4.2, 4.4, 4.6}`), `tan δ ≤ 0.02 @ 1 GHz` |
| **Copper Weight** | `1 oz` (`35 µm`) finished on `F.Cu` and `B.Cu` | Minimum PTH barrel wall `≥ 20 µm` |
| **Surface Finish** | IPC-4552 `ENIG` (`1–3 µin Au` over `120–240 µin Ni`) | Required for planar bare-`ENIG` sensing comb fingers and pogo-pin pads (do not substitute HASL or OSP) |
| **Solder Mask (`NSMD`)** | Green LPI on `F.Mask` and `B.Mask` | `0.035 mm` global NSMD mask clearance (`0.025 mm` local on `U1`/`U2`, `0.000 mm` on `AE1` window) is pre-applied in `F_Mask.gts`. Plot `F_Mask.gts` `1:1` (`0.00 mm` extra CAM swell) to retain `≥ 0.180 mm` LPI dams on `U1` and `≥ 0.200 mm` on `U2` |
| **Via Tenting** | Tented vias on `F.Mask` and `B.Mask` (`131` vias, `0.60/0.30 mm`) | No via-in-pad (no VIPPO / resin plugging required) |
| **RF Bridge Copper Cutout** | `2.20 × 2.20 mm` copper cutout on both `F.Cu` and `B.Cu` under `/BR_S` (`X_gbr = [33.40..35.60] mm, Y_gbr = [13.62..15.82] mm`) | Intentional parasitic-reduction cutout (`C_par = 0.1305 pF`); leave open as drawn |
| **Silkscreen** | White LPI on `F.SilkS` and `B.SilkS` | `≥ 0.15 mm` stroke width; keep `X_gbr ≥ 50.0 mm` antenna region free of silkscreen and vendor date/UL stamps (place fab markings on `B.SilkS` within `X_gbr = 8.0..45.0 mm`) |
| **Minimum Track / Space** | `0.20 mm` min signal track / `0.18 mm` clearance | `0.28 mm` coplanar RF gap on `GND_COUNTERPOISE` |
| **Minimum Drill / Ring** | `0.30 mm` PTH drill / `0.15 mm` annular ring | `4 × Ø2.700 mm` NPTH `M2.5` mounting holes (`H1..H4`) |
| **Optical Fiducials** | `5 × Ø1.00 mm Cu / Ø2.00 mm Mask` targets (`FID1..FID5`, `≥ 4.50 mm` clamp clearance) | `3` global (`FID1..FID3`) + `2` local `U1` diagonal (`FID4, FID5`) |
| **Impedance Control** | `ImpedanceControlled = False` (fabricate trace widths as drawn; no TDR coupon required) | `F.Cu` `W = 1.08 mm`, `Gap = 0.28 mm` over `1.51 mm` `B.Cu` gives `Z0 = 51.90 Ω` nominal (`max length 11.18 mm = 0.056 λ_g`) |
| **Electrical Test** | 100% flying-probe continuity & isolation test | `250 V` IPC-9252 against Gerber X2 / IPC-D-356 netlist |

> **Pre-Etch CAM Confirmation Items:**
> 1. Plot `F_Mask.gts` `1:1` (`0.00 mm` extra CAM expansion) so the `0.180 mm` / `0.200 mm` Green LPI dams on `U1` (`LGA-73`) and `U2` (`DFN-8`) are preserved.
> 2. Confirm IPC-4552 `ENIG` finish and the continuous bare-`ENIG` `F.Mask` sensing window at `X_gbr = [73.40..87.80] mm, Y_gbr = [6.65..20.80] mm` with no silkscreen or fab stamps in `X_gbr ≥ 50.0 mm`.
> 3. Keep `W = 1.08 mm` RF traces unmodified (`Impedance Control = NO`), preserve the `2.20 × 2.20 mm` `F.Cu`/`B.Cu` cutout at `X_gbr = [33.40..35.60], Y_gbr = [13.62..15.82] mm`, and hold finished thickness within `1.50–1.63 mm`.
> 4. Keep breakaway routing tabs out of the `X_gbr = 50.00..90.00 mm` antenna region and away from `J2` (`X_gbr = 8.9..10.9 mm`).

---

## 2. SMT Stencil, Component Sourcing & Reflow Assembly

### 2.1 Single-Sided Top `0.10 mm` (`100 µm`) Stainless-Steel Stencil (`IPC-7525B`)

| Stencil Attribute | Specification (`Cut F_Paste.gtp 1:1`) |
| :--- | :--- |
| **Stencil Count & Side** | Top stencil only (`ISAC_868_KiCad9-F_Paste.gtp`); `B_Paste.gbp` is omitted |
| **Foil Thickness & Finish** | Type-304 stainless steel, `0.10 mm` (`100 µm` / `4.0 mil`), laser-cut and electropolished, cut `1:1` from `F_Paste.gtp` |
| **`U1` (`LGA-73` Perimeter `1..64`)** | `0.30 × 1.10 mm` apertures (`-0.035 mm` inset on `0.37 × 1.17 mm` lands; `AR = 1.179`, `0.300 mm` web) |
| **`U1` Central `3 × 3` GND (`65..73`)** | `9 × [1.20 × 1.20 mm]` apertures on `1.60 × 1.60 mm` lands (`56.3%` coverage) |
| **`U2` (`DFN-8` Perimeter `1..8`)** | `0.82 × 0.22 mm` apertures (`-0.015 mm` inset on `0.85 × 0.25 mm` lands; `AR = 0.87–0.90`) |
| **`U2` `Pad 9` Exposed Pad** | `2 × 2` window-pane apertures: `4 × [0.57 × 0.86 mm]` (`49.9%` coverage on `1.65 × 2.38 mm` pad) |
| **`DNP` Footprints & `AE1`** | `0` flashes in `F_Paste.gtp` (derive stencil strictly from `F_Paste.gtp`, never `F.Mask`) |

### 2.2 Component Sourcing Notes (`38` Populated BOM Lines + `8` DNP Lines)

- **Do-Not-Substitute Functional ICs (`U1, U2, U3, Q1, Q2`) & Bench Connector (`J1`):**
  1. `U1` (`RAKwireless RAK3172LP-SIP-8-SM-NI`, SKU `305049`): EU868 `RFO_LP` `+14 dBm` `LGA-73` SiP (do not substitute `RAK3172-SiP` `RFO_HP`).
  2. `U2` (`Analog Devices LT5538IDD#TRPBF`): 8 mm tape-and-reel `DFN-8` RF log detector (`19.0 mV/dB`, `-88.8 dBm` intercept).
  3. `U3` (`TI TPS7A0233DBVR`, LCSC `C2873330`): `25 nA` $I_Q$ `SOT-23-5` (`DBV` pinout `1=IN, 2=GND, 3=EN, 4=NC, 5=OUT`).
  4. `Q1` (`TI TPS22919DCKR`): `SC-70-6` controlled-slew load switch with `QOD` discharge.
  5. `Q2` (`Nexperia NX3008CBKS,115`, LCSC `C456076`): `SOT-363` complementary N+P MOSFET pair.
  6. `J1` (`Molex 73251-1153`, `DNP = Yes` on sealed builds): `1.60 mm` edge-launch SMA jack for bench VNA characterization.
- **Precision RF & Power Passives:**
  - `L_SMPS` (`15 µH ±10%`, `Murata LQH2MCN150K02L`, LCSC `C86089`): Wirewound DC-DC power inductor (`Isat = 300 mA`, `R_DC = 1.1 Ω`; do not substitute multilayer ferrite EMI beads).
  - `R1` (`8.2 Ω ±0.1%`, `Yageo RT0402BRD078R2L`) and `0.1%` Susumu `RG1005P` resistors (`R2 = 681 Ω, R3 = 3.57 kΩ, R_TERM = 56 Ω, R_B1 = R_B2 = 4.7 kΩ`).
  - Elliptic harmonic filter: `C_M1 = 3.6 pF` (`GJM1555C1H3R6WB01D`), `L_M1 = 8.2 nH` (`LQW15AN8N2G00D`) `|| C_MZ = 0.5 pF` (`GJM1555C1HR50WB01D`), `C_M2 = 4.3 pF` (`GJM1555C1H4R3WB01D`).

### 2.3 Reflow & Inspection Notes

1. **MSL-3 Pre-Bake (`IPC/JEDEC J-STD-033D`):** `U1` (`RAK3172LP-SIP-8-SM-NI`) is MSL-3 (`168 h` floor life at `≤ 30 °C / 60% RH`); bake at `125 °C` for `24 h` if floor life has expired.
2. **Paste & Cleaning:** SAC305 Type-4 no-clean `ROL0` paste, standard `J-STD-020E` lead-free profile (`240–245 °C` peak, `45–65 s` TAL). Avoid aqueous/ultrasonic wash because tactile switch `SW1` (`B3U-1000P`) is unsealed; swab the bare-`ENIG` `AE1` window (`X_gbr = 73.4..87.8 mm`) with `99.9%` IPA before packing.
3. **Through-Hole Footprints (`J1..J5 = DNP`):** Leave `J1..J5` unpopulated with open bare-`ENIG` PTH barrels.
4. **AOI & X-Ray (`AXI`):** Run 3D AOI across all `67` SMD placements (`10` DNP parts unpopulated) and 2D/3D X-ray on `U1` (`LGA-73`) and `U2` (`DFN-8-1EP`) checking `< 25%` thermal/GND pad voiding and zero bridges.

---

## 3. Recommended 2×2 Tab-Routed Panelization

- **Format:** `2 × 2` array (`4` boards per panel, `2.00 mm` router kerf + `8.00 mm` rails = `198.00 × 98.00 mm`), tab-routed (no V-scoring).
- **Tab Placement (Keep `X_gbr = 50.00..90.00 mm` Antenna Zone Clear):**
  - Top edge (`Y_gbr = 40.00 mm`): `X_gbr = 20.00 mm`, `44.00 mm` | Bottom edge (`Y_gbr = 0.00 mm`): `X_gbr = 4.50 mm`, `44.00 mm` | Left edge (`X_gbr = 0.00 mm`): `Y_gbr = 6.00 mm`, `30.00 mm` | Right edge (`X_gbr = 90.00 mm`): `0` tabs.

---

## 4. Box-Build Wiring, Pogo Flashing & 2-Point Calibration

1. **Direct Battery Leads (`J2 = DNP`):** Insert `24–26 AWG` silicone leads upward from `B.Cu` into `J2` (`Pad 1` Square = `BLACK / GND`, `Pad 2` Round = `RED / +VBAT_RAW`, `4.35 V DC MAX`), trim top solder fillets `≤ +1.50 mm`, and strain-relieve wire insulation on `B.Cu` with `DOWSIL 3145` neutral-cure RTV silicone (when removing a factory LiPo plug, cut one wire at a time).
2. **SWD Provisioning & 2-Point Calibration (`tools/production_flash.sh`):** Contact `J4` (`SWD`) via a 5-pin pogo fixture to write per-unit `DevEUI / JoinEUI / AppKey` plus Point-1 Dry-Air tare (`--cal-dry-mv v1,v2,v3`) and Point-2 `Al2O3` reference offset (`--cal-ref-cdb`) to `0x0803E000`, logging keys with `0600` permissions in `provisioning_vault/provisioned_units_secret.csv`.

---

## 5. Manufacturing Archive Contents (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)

| File Path | Contents |
| :--- | :--- |
| `ISAC_868_KiCad9.kicad_pcb` / `ISAC_868_KiCad9.kicad_dru` | `Rev E.5` KiCad 9 PCB layout (`92` footprints, `131` tented vias, `0` DRC/ERC violations) |
| `fab/bom/ISAC_868_Turnkey_BOM.csv` | Turnkey BOM (`38` populated lines / `67` SMD parts + `8` DNP lines / `10` parts) |
| `fab/cpl/ISAC_868_Turnkey_CPL_Top.csv` | `67` top-side SMD placements (`0` THT parts) + `CPL_README.md` |
| `fab/mechanical/ISAC_868_PCBA.step` & `ISAC_868_*.stl` | Populated 3D STEP model + watertight `ASA/PETG` enclosure STLs (`0.80 mm` open-East window, Parker `ORD 5700` O-ring groove, `M2.5 × 22 mm` corner bosses) |
