# ISAC 868 MHz LoRaWAN Antenna-Sensor — System Design & Manufacturing Summary (`Rev E.5`)

**Author:** Stephen K. Boachie  
**Hardware Revision:** `Rev E.5` (`Hardware Revision E.5`, `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Target Radio / MCU:** `RAKwireless RAK3172LP-SIP-8-SM-NI` (`STM32WLE5JC` + `SX1262` `RFO_LP`, `3.0 V` `DIO3` TCXO `0x06`, `EU868`)  
**License:** Apache License 2.0

---

## 1. Architecture Overview

`ISAC_868_KiCad9` (`Rev E.5`) combines **868 MHz LoRaWAN Class A wireless telemetry** (`+14.0 dBm` TX with adaptive `SF7/SF9/SF12` wet-radome link recovery) and **near-field surface-permittivity sensing** (`+4.0 dBm` 3-tone CW reflectometry at `863.1 / 866.5 / 869.5 MHz`, `< 1.25 ms/tone` with Listen-Before-Sense ambient RF blanking) on a single `90.00 × 40.00 × 1.60 mm` (`+0.03/-0.10 mm`) 2-layer `FR-4` (`1.51 mm` core, `1 oz` `ENIG`) PCBA (`67` populated top-side SMD parts, `0` THT parts). The board mounts inside a flat-roof (`Z = +8.50 mm`, `-1.44 mm` compliant skirt), open-East self-draining `0.80 mm` UV-stabilized `ASA/PETG` enclosure (`95.7 × 45.7 × 16.1 mm`) sealed by a continuous `360°` Parker `ORD 5700` EPDM O-ring (`1.80 × 0.76 mm` groove, `23.3%` squeeze, `68.3%` gland fill) and bonded across the sensing aperture with `25 µm` `3M 467MP` acrylic transfer adhesive.

1. **Shared IFA + Interdigital Antenna (`AE1`) & Elliptic Harmonic Pi-Filter:**
   - Synthesized with a 3D Yee-grid FDTD solver (`rf/fdtd_3d_ant.c` + `rf/ifa_enclosure_mom.py`, modeling IPC-4552 `ENIG` `NiP/Au` sheet resistance $R_s = 23.74\text{ m}\Omega/\square$ and substrate/radome dielectric loss). In enclosed Dry Air, resonance sits at `f0 = 869.00 MHz` with raw `|S11|(866.5) = -23.69 dB` (`-20.83 dB` cascaded), `|S11| ≤ -10.21 dB` across `863–870 MHz` over all three FR-4 permittivity corners (`εr ∈ {4.2, 4.4, 4.6}`), total efficiency `η_tot = 45.5%` (`η_rad = 50.0%`), and `43.73 MHz/RIU` Air-to-Ice sensitivity (`869.0 MHz → 834.5 MHz`).
   - A 3rd-order elliptic low-pass Pi-filter (`C_M1 = 3.6 pF` `GJM1555C1H3R6WB01D`, `L_M1 = 8.2 nH` `LQW15AN8N2G00D` `|| C_MZ = 0.5 pF` `GJM1555C1HR50WB01D`, `C_M2 = 4.3 pF` `GJM1555C1H4R3WB01D`) attenuates `2f0` (`1.733 GHz`) by `≥ 37.2 dB` and `3f0` (`2.600 GHz`) by `≥ 60.1 dB` across Dry Air and Water VSWR loads (`ETSI EN 300 220-1` `≤ -36 dBm`).
   - A continuous bare-`ENIG` `F.Mask` opening (`X_gbr = [73.40..87.80] mm, Y_gbr = [6.65..20.80] mm`, no silkscreen in `X_gbr ≥ 50.0 mm`) avoids solder-mask ridges beneath the bonded `0.80 mm` sensing deck.

2. **Asymmetric Microstrip Return-Loss Bridge & 2-Point Calibrated Reflectometer:**
   - Uses a thin-film `Yageo RT0402BRD078R2L` (`8.2 Ω ±0.1%`) inline sense resistor `R1`, `0.1%` Susumu `RG1005P` reference arms (`R2 = 681 Ω, R3 = 3.57 kΩ, R_TERM = 56 Ω`), `±2%` Murata `LQW15AN` inductors (`L_Q = 27 nH, L_S = 30 nH`), `±0.05 pF` `GJM1555C1H` capacitors (`C_S = C_S2 = 1.0 pF`), and an Analog Devices `LT5538IDD#TRPBF` logarithmic detector (`IN+` complex load `291.65 Ω || 1.194 pF` at `866.5 MHz`).
   - Placing a `2.20 × 2.20 mm` `F.Cu`+`B.Cu` ground cutout beneath `/BR_S` (`C_par = 0.1305 pF < 0.15 pF`) yields `-0.802 dB` through loss, `24.81 dB` `50 Ω` directivity at `866.5 MHz`, and `17.60 dB` `P01` Air-to-Ice contrast across `2,000` Monte-Carlo trials.
   - Running CW sensing at `+4.0 dBm` keeps `LT5538IDD#TRPBF` (`U2`) input `≤ -25.40 dBm` (`+12.40 dB` below `-13 dBm` compression), while unpowered `+14 dBm` LoRaWAN uplinks produce `≤ 39.5 mV_pk` at `U2 IN+` across `VSWR 6:1`. Two-point factory calibration (Dry-Air `Vout` tare + `Al2O3` high-`εr` level reference `cal_ref_cdb`, paired with `0.015 dB/°C` residual thermal compensation, TX-off Listen-Before-Sense jammer blanking, and `-9 dBm` soft-ramp CW quenching) achieves `99.72%` `Water vs IPA` yield (`P01` separation `0.65 dB ≥ 0.50 dB`).

3. **Split-Rail Power Tree, Direct-Soldered Battery Pads & Freestanding C11 Firmware:**
   - `J2` (`B2B-PH-K-S`) and debug headers `J1, J3, J4, J5` are marked `DNP = Yes` so turnkey assembly is single-pass top-side SMT (`67` SMD parts). During box-build, `24–26 AWG` silicone battery leads solder upward from `B.Cu` into `J2`'s bare-`ENIG` `Ø0.75 mm` PTH pads (`Pad 1` Square = `GND`, `Pad 2` Round = `+VBAT_RAW`, `4.35 V DC MAX`, `DOWSIL 3145` RTV strain relief).
   - `Q3` (`AO3401A` P-MOSFET ideal diode, `< 6 mV` drop) feeds `U3` (`TPS7A0233DBVR` `25 nA` LDO, `C_OUT_eff ≈ 13.8 µF ≤ 22 µF`), `Q1` (`TPS22919DCKR` + `C_Q1 = 100 nF`) powers `LT5538` directly from `VBAT` (keeping `U3` peak load at `24.1 mA`, `8.30×` below `200 mA`), `L_SMPS = LQH2MCN150K02L` (`Isat = 300 mA`) supports the internal `SX1262` buck converter, and `Q2` (`NX3008CBKS,115`) gates battery sensing on `PA9` (`150 µs` window).
   - Freestanding C11 firmware (`15,948 B` Flash, `408 B` RAM) configures `DIO3` TCXO to `3.0 V` (`0x06`), holds unused pins (`PA2/PA3`) in Analog High-Z during `STOP2`, enforces LoRaWAN `1.0.3` §7 Join backoff (`17,281 s` Tier-3) and §5.4 `RXParamSetupReq`, persists session state in commit-last dual-page Flash NVM with 72-bit `ECCD` `NMI` self-healing, and records per-unit `UID64` + 2-point calibration in `provisioning_vault/`.

---

## 2. Summary Specifications (`firmware/test/data/design_values.json`)

| Subsystem Metric | Design / Simulated Value | Target |
| :--- | :---: | :---: |
| PCB & Assembly Counts | `92` footprints (`67` SMD pop, `0` THT; `10` DNP incl. `J2`; `15` `BOARD_ONLY`), `131` tented vias | `0` ERC, `0` DRC, `0` DNP paste |
| Surface Finish, Mask & CPWG `Z0` | IPC-4552 `ENIG`; `0.035 mm` global / `0.025 mm` `U1,U2` NSMD (`≥ 0.180 mm` dams); `Z0 = 51.90 Ω` (`51.2–57.1 Ω`, `RL ≥ 26.8 dB`) | `ImpedanceControlled = False` |
| Bridge Through Loss & Directivity | `|S21| = -0.802 dB`, `Directivity(866.5) = 24.81 dB` (`C_par = 0.1305 pF`) | `≥ 22.0 dB` (`< 0.15 pF`) |
| 2-Point Calibrated `2,000`-Trial MC | Air-to-Ice `P01 = 17.60 dB` (`100%` yield); `Water vs IPA` `P01 = 0.65 dB` (`99.72%` yield) | `P01 ≥ 8.0 dB` / `≥ 0.50 dB` |
| Enclosed `AE1` Match & Efficiency | `f0 = 869.0 MHz`, `|S11|(866.5) = -20.83 dB`, `εr∈{4.2,4.4,4.6}` worst `|S11| ≤ -10.21 dB`, `η_tot = 45.5%` | `|S11| ≤ -10.0 dB` all `εr` |
| Harmonic Pi-Filter (`2f0` / `3f0`) | `37.20 dB` (`1.733 GHz`) / `60.08 dB` (`2.600 GHz`) enclosed (`37.46 / 60.65 dB` water) | `≥ 28 dB` / `≥ 45 dB` |
| Weatherproof Enclosure (`95.7 × 45.7 × 16.1 mm`) | Flat `+8.50 mm` roof + `0.80 mm` open-East `ASA/PETG` deck + `25 µm` `3M 467MP` + Parker `ORD 5700` O-ring (`23.3%` squeeze, `68.3%` fill, `M2.5 × 22 mm` corner screws) | Watertight 2-manifold (`0` 3D clashes) |

---

## 3. 3D FDTD 3-Tone Benchmark Table (`+4.0 dBm` CW Sensing, 2-Point Calibrated)

| External Superstrate (`2.0 mm` on `0.80 mm` `ASA/PETG`) | $\varepsilon_r^*$ (`868 MHz`) | $f_{\text{res}}$ [MHz] | Cascaded `|S11|` (`f1 / f2 / f3`) [dB] | `P_det` (`f1 / f2 / f3`) [dBm] | `Tilt` [dB] | `Notch` [dB] | `Level` [dBm] | `FPort 10` State |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| Dry Air | `1.00 - j0.000` | `869.0` | `-18.79 / -20.83 / -18.33` | `-45.75 / -48.92 / -42.31` | `-3.44` | `+4.88` | `-45.66` | `0 = DRY_AIR` |
| PTFE / Oil | `2.10 - j0.0002` | `849.0` | `-8.72 / -7.14 / -5.99` | `-33.83 / -33.36 / -32.60` | `-1.23` | `+0.15` | `-33.26` | `1 = OIL` |
| Glaze Ice | `3.20 - j0.003` | `834.5` | `-3.65 / -2.89 / -2.32` | `-28.61 / -28.66 / -28.60` | `-0.01` | `+0.06` | `-28.63` | `2 = GLAZE_ICE` |
| Alumina (`Al2O3`) | `9.80 - j0.002` | `783.0` | `-0.36 / -0.53 / -0.69` | `-25.40 / -26.21 / -26.96` | `+1.56` | `+0.03` | `-26.19` | `3 = IPA` (Cal Ref) |
| IPA (`868 MHz`) | `6.29 - j6.090` | `794.0` | `-2.27 / -2.19 / -2.12` | `-27.01 / -27.77 / -28.46` | `+1.45` | `+0.04` | `-27.75` | `3 = IPA` |
| Water Film | `79.9 - j3.810` | `776.0` | `-0.71 / -0.72 / -0.71` | `-25.73 / -26.38 / -26.95` | `+1.22` | `+0.04` | `-26.35` | `4 = LIQUID_WATER` |

---

## 4. CAD & Mechanical Renderings (`Rev E.5`)

![ISAC_868 Rev E.5 3D Top Render](ISAC_868_3D_Top.png)

![ISAC_868 Rev E.5 3D Isometric Render](ISAC_868_3D_Iso.png)

![ISAC_868 Rev E.5 3D Bottom Render](ISAC_868_3D_Bottom.png)

![ISAC_868 Rev E.5 3D Enclosure Exploded and Cutaway Renders](ISAC_868_Enclosure_3D_Exploded.png)

![ISAC_868 Rev E.5 Enclosure Blueprint](ISAC_868_Enclosure_0p80mm_Blueprint.png)
