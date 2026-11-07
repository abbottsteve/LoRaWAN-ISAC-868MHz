# ISAC 868 MHz LoRaWAN Antenna-Sensor — System Design & Manufacturing Summary (`Rev E.5`)

**Hardware Revision:** `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Rule-Deck Lock SHA-256:** `ff1d145fc6dc1ce66f936c706389190a03c52649462288b6d8774e5a09a1cc60`  
**Target Radio / MCU:** `RAKwireless RAK3172LP-SIP-8-SM-NI` (`STM32WLE5JC` + `SX1262` `RFO_LP` + **`3.0 V` `DIO3` TCXO `0x06`**, `EU868`)

---

## 1. Executive Architecture Overview

`ISAC_868_KiCad9` (`Rev E.5`) integrates **868 MHz LoRaWAN Class A wireless telemetry (`+14.0 dBm` TX with adaptive `SF7/SF9/SF12` wet-radome link recovery)** and **evanescent surface-permittivity sensing (`+4.0 dBm` 3-tone CW reflectometry at `863.1 / 866.5 / 869.5 MHz`, `< 1.2 ms/tone`)** onto a single `90.00 × 40.00 × 1.60 mm` (`+0.03/-0.10 mm`) 2-layer standard `FR-4` (`1.51 mm` core, `1 oz` `ENIG`) pure-SMD PCBA (`67` populated SMD parts, `0` THT parts) housed inside a **100% uniform-flat-roof (`Z = +8.50 mm`, `-1.44 mm` compliant skirt), open-East self-draining `0.80 mm` UV-stabilized `ASA/PETG`** waterproof sensing-window enclosure (`95.7 × 45.7 × 16.1 mm`, unbroken `360°` Parker `ORD 5700` `1.80 × 0.76 mm` EPDM O-ring face-seal groove [`0.92 mm` gland: `23.3%` squeeze, `68.3%` fill] + wall-gusseted `M2.5 × 22 mm` EPDM-sealed corner bosses + `0` PCB-bay roof slots) bonded with **`25 µm` `3M 467MP`** acrylic transfer adhesive (`0.00 mm` air gap).

1. **Full-Wave 3D Maxwell FDTD Antenna-Transducer (`AE1`) + Parasitic-Pre-Distorted Elliptic Harmonic Pi-Filter:**
   - Synthesized from 3D Yee-grid FDTD (`rf/fdtd_3d_ant.c` + `rf/ifa_enclosure_mom.py`, modeling exact IPC-4552 `ENIG` `NiP/Au` RF sheet resistance $R_s = 23.74\text{ m}\Omega/\square$ and volumetric substrate loss): enclosed Dry Air resonance **`f0 = 869.00 MHz`**, raw antenna `|S11|(866.5) = -23.69 dB` (`-20.83 dB` cascaded), **all three FR-4 permittivity corners (`εr ∈ {4.2, 4.4, 4.6}`) satisfy `|S11| ≤ -10.21 dB` across `863–870 MHz`**, total radiated efficiency **`η_tot = 45.5%`** (`η_rad = 50.0%`), and **`43.73 MHz/RIU`** Air-to-Ice resonance shift (`869.0 MHz → 834.5 MHz`).
   - Populated parasitic-pre-distorted 3rd-order elliptic low-pass pi-network (`C_M1 = 3.6 pF` `GJM1555C1H3R6WB01D`, `L_M1 = 8.2 nH` `LQW15AN8N2G00D` `|| C_MZ = 0.5 pF` `GJM1555C1HR50WB01D`, `C_M2 = 4.3 pF` `GJM1555C1H4R3WB01D`) suppresses `2f0` (`1.733 GHz`) by **`≥ 37.2 dB`** and `3f0` (`2.600 GHz`) by **`≥ 60.1 dB`** across Dry Air and Water VSWR extremes (`ETSI EN 300 220-1` `≤ -36 dBm`).
   - Continuous bare-`ENIG` `F.Mask` window (`X_gbr = [73.40..87.80] mm, Y_gbr = [6.65..20.80] mm`, `0` silkscreen in `X_gbr ≥ 50.0 mm`) eliminates LPI mask ridges under the self-draining `0.80 mm` flush deck.
2. **ADI `LT5538IDD#TRPBF`-Terminated Distributed Microstrip Return-Loss Bridge & 2-Point Calibrated Classifier:**
   - Orderable **`Yageo RT0402BRD078R2L`** (`8.2 Ω ±0.1%`) series sense resistor `R1`, `0.1%` Susumu `RG1005P` arms (`R2 = 681 Ω, R3 = 3.57 kΩ, R_TERM = 56 Ω`), `±2%` Murata `LQW15AN` inductors (`L_Q = 27 nH, L_S = 30 nH`), `±0.05 pF` `GJM1555C1H` capacitors (`C_S = C_S2 = 1.0 pF`), and ADI `LT5538IDD#TRPBF` (8 mm T&R) Table 1 `IN+` complex load (`R_par = 291.65 Ω || C_par = 1.194 pF` at `866.5 MHz`).
   - Compact `1.44 mm` `/BR_S` micro-cluster over a **`2.20 × 2.20 mm` `F.Cu`+`B.Cu` ground cutout** (`X_gbr = [33.40..35.60], Y_gbr = [13.62..15.82] mm`, `C_par = 0.1305 pF < 0.15 pF`, distributed PCB microstrip phases included) achieves **`-0.802 dB`** insertion loss, **`24.81 dB`** `50 Ω` directivity at `866.5 MHz`, and **`17.60 dB` `P01` Air-to-Ice contrast** (`100.0%` `≥ 6 dB` yield across `2,000` Monte-Carlo trials).
   - Stepping CW sensing TX power to **`+4.0 dBm`** keeps `LT5538IDD#TRPBF` (`U2`) input strictly `≤ -25.40 dBm` (`+12.40 dB` linear headroom below `-13 dBm` compression; unpowered `+14 dBm` LoRa TX keeps `U2 IN+ ≤ 39.5 mV_pk << 350 mV` ESD knee across `VSWR 6:1`), and **2-point factory calibration** (Point 1 Dry-Air `Vout` tare + Point 2 `Al2O3` high-`εr` level reference `cal_ref_cdb`, plus `0.015 dB/°C` combined thermal residual compensation) achieves **`99.72%` binary `Water vs IPA` yield (`P01` separation = `0.65 dB ≥ 0.50 dB`)** and **`99.45%` 4-hazard yield**.
3. **Zero-Dropout `VBAT`-Fed Detector Power Tree, Direct-Soldered `J2 = DNP` Battery Pads, `3.0 V` TCXO, `Isat = 300 mA` Wirewound SMPS & Split `PA8/PA9` Gating:**
   - `J2` (`B2B-PH-K-S`) is marked **`DNP = Yes`** so the Turnkey PCBA is **100% single-pass automated top-side SMT (`67` pure-SMD placements in `ISAC_868_Turnkey_CPL_Top.csv`, `0` THT headers)** and `24–26 AWG` silicone battery leads solder directly upward from `B.Cu` into bare-`ENIG` `Ø0.75 mm` PTH pads (**`Pad 1` Square = `BLACK / GND`, `Pad 2` Round = `RED / +VBAT_RAW`**, `4.35 V DC MAX` [`NO 5V PSU`], `DOWSIL 3145` RTV strain relief), eliminating the `+11.50 mm` roof bulge for a **100% uniform flat waterproof top cover (`+8.50 mm`)**; `Q3` (`AO3401A` P-MOSFET ideal diode, `< 6 mV` drop), `U3` (`TPS7A0233DBVR` `25 nA` LDO, total derated `C_OUT_eff ≈ 13.8 µF ≤ 22 µF`), **`Q1` (`TPS22919DCKR` + `C_Q1 = 100 nF`) fed directly from `VBAT`** (`3.0–4.35 V` zero-dropout supply to `LT5538`, cutting `U3` peak load to **`24.1 mA = 8.30×` margin**!), **`L_SMPS = LQH2MCN150K02L`** (`15 µH` wirewound power inductor, `Isat = 300 mA`), and **`Q2` (`NX3008CBKS,115`) split onto `PA9` (`BAT_MON_EN`, `U1 Pad 50` + `R_BPD = 100 kΩ`)**.
   - Firmware configures `DIO3` TCXO to RAKwireless-mandated **`3.0 V` (`0x06`)**, leaves `PA2/PA3` in `Analog High-Z` (`ISAC_DEBUG_UART=0`), marks `J2/J3/J4/J5` **`DNP = Yes`** (retaining bare-`ENIG` PTH solder/pogo-pin pads with `B.SilkS` legends inside the sealed enclosure), enforces LoRaWAN `1.0.3` §7 Join backoff (`17.281 s` Tier-3) + §5.4 `RXParamSetupReq` (`0x05`) + commit-last NVM with 72-bit Flash `ECCD` `NMI` self-healing, promotes uplinks to `SF12` (`DR0`) under wet-radome loading, and logs per-unit `UID64` + 2-point cal into `provisioning_vault/provisioned_units_secret.csv` (`--lock-rdp1`).

---

## 2. Verified `Rev E.5` Key Metrics (`firmware/test/data/design_values.json`)

| Subsystem Metric | Verified Value | Acceptance Requirement |
| :--- | :---: | :---: |
| **PCB / Assembly Counts** | `92` footprints (`67` pure-SMD pop, `0` THT; `10` DNP incl. `J2`; `15` `BOARD_ONLY`), `131` tented vias | `0` ERC, `0` DRC, `0` DNP paste |
| **IPC-4552 `ENIG` NSMD Mask & CPWG `Z0`** | `0.035 mm` global / `0.025 mm` `U1,U2` NSMD (`≥ 0.180 mm` dams); `Z0 = 51.90 Ω` (`51.2–57.1 Ω`, `RL ≥ 26.8 dB`) | `ImpedanceControlled = False` |
| **Bridge Through Loss & `50 Ω` Directivity** | `|S21| = -0.802 dB`, `Directivity(866.5) = 24.81 dB` (`C_par = 0.1305 pF`) | `≥ 22.0 dB` (`< 0.15 pF`) |
| **2-Point Calibrated `2,000`-Trial MC Yield** | Air-to-Ice **`P01 = 17.60 dB`** (`100%` yield); `Water vs IPA` **`P01 = 0.65 dB` (`99.72%` yield)** | `P01 ≥ 8.0 dB` / `≥ 0.50 dB` |
| **Enclosed `AE1` Resonance, `εr` Corners & `η_tot`** | `f0 = 869.0 MHz`, `|S11|(866.5) = -20.83 dB`, `εr∈{4.2,4.4,4.6}` worst `|S11| ≤ -10.21 dB`, `η_tot = 45.5%` | `|S11| ≤ -10.0 dB` all `εr` |
| **Harmonic Pi-Filter Attenuation (`2f0` / `3f0`)** | `37.20 dB` (`1.733 GHz`) / `60.08 dB` (`2.600 GHz`) enclosed (`37.46 / 60.65 dB` water) | `≥ 28 dB` / `≥ 45 dB` |
| **Uniform Flat Waterproof Enclosure (`95.7 × 45.7 × 16.1 mm`)** | Flat `+8.50 mm` roof (`-1.44 mm` compliant skirt) + `0.80 mm` open-East `ASA/PETG` deck + `25 µm` `3M 467MP` + `1.80 × 0.76 mm` Parker `ORD 5700` O-ring (`23.3%` squeeze, `68.3%` fill, `M2.5 × 22 mm` EPDM-sealed corner screws, `0` roof slots) | `0` 3D collisions (`77` items) |

---

## 3. Full-Wave 3D FDTD 3-Tone Benchmark Table (`+4.0 dBm` CW Sensing, 2-Point Calibrated)

| External Superstrate (`2.0 mm` on `0.80 mm` `ASA/PETG`) | $\varepsilon_r^*$ (`868 MHz`) | $f_{\text{res}}$ [MHz] | Cascaded `|S11|` (`f1 / f2 / f3`) [dB] | `P_det` (`f1 / f2 / f3`) [dBm] | `Tilt` [dB] | `Notch` [dB] | `Level` [dBm] | `FPort 10` State |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Dry Air** | `1.00 - j0.000` | `869.0` | `-18.79 / -20.83 / -18.33` | `-45.75 / -48.92 / -42.31` | `-3.44` | `+4.88` | `-45.66` | `0 = DRY_AIR` |
| **PTFE / Oil** | `2.10 - j0.0002` | `849.0` | `-8.72 / -7.14 / -5.99` | `-33.83 / -33.36 / -32.60` | `-1.23` | `+0.15` | `-33.26` | `1 = OIL` |
| **Glaze Ice** | `3.20 - j0.003` | `834.5` | `-3.65 / -2.89 / -2.32` | `-28.61 / -28.66 / -28.60` | `-0.01` | `+0.06` | `-28.63` | `2 = GLAZE_ICE` |
| **Alumina (`Al2O3`)** | `9.80 - j0.002` | `783.0` | `-0.36 / -0.53 / -0.69` | `-25.40 / -26.21 / -26.96` | `+1.56` | `+0.03` | `-26.19` | `3 = IPA` (Cal Ref) |
| **IPA (`868 MHz`)** | `6.29 - j6.090` | `794.0` | `-2.27 / -2.19 / -2.12` | `-27.01 / -27.77 / -28.46` | `+1.45` | `+0.04` | `-27.75` | `3 = IPA` |
| **Water Film** | `79.9 - j3.810` | `776.0` | `-0.71 / -0.72 / -0.71` | `-25.73 / -26.38 / -26.95` | `+1.22` | `+0.04` | `-26.35` | `4 = LIQUID_WATER` |

---

## 4. Visual Inspection Sheets (`Rev E.5` PCBA & Self-Draining Weatherproof `ASA/PETG` Enclosure)

![ISAC_868 Rev E.5 3D Top Render](ISAC_868_3D_Top.png)

![ISAC_868 Rev E.5 3D Isometric Render](ISAC_868_3D_Iso.png)

![ISAC_868 Rev E.5 3D Bottom Render](ISAC_868_3D_Bottom.png)

![ISAC_868 Rev E.5 3D Enclosure Exploded and Cutaway Renders](ISAC_868_Enclosure_3D_Exploded.png)

![ISAC_868 Rev E.5 Enclosure Blueprint](ISAC_868_Enclosure_0p80mm_Blueprint.png)
