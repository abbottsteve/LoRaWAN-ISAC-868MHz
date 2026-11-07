# PCBWay Turnkey Fabrication, Stencil & Panelization Specification (`Rev E.5`)

| Document Control | Value |
| :--- | :--- |
| **Project / Assembly** | Dual-Function 868 MHz LoRaWAN ISAC Antenna-Sensor Node (`ISAC_868_KiCad9`) |
| **Hardware Revision** | **`Rev E.5`** (Independent Principal Turnkey Pre-Tapeout Audit Closure — Zero-Blocker Tier-1 Release) |
| **Rule Deck SHA-256 Lock** | `ff1d145fc6dc1ce66f936c706389190a03c52649462288b6d8774e5a09a1cc60` (`tools/rules_isac.lock.json`, `57/57` DRC severities = `error`) |
| **IPC Acceptance Class** | **IPC-6012E Class 2** (Bare PCB) / **IPC-A-610H Class 2/3** (PCBA, Class 3 voiding on `U1`/`U2`) |
| **BOM / Placement Scope** | **`92` Total Footprints**: **`67` Populated Components (`100%` Pure-SMD Top Rows** in `ISAC_868_Turnkey_CPL_Top.csv`, **`0` THT Parts** across `38` populated BOM lines), **`10` DNP** (`8` BOM lines: `C_SMPS3, D_RF, J1, J2, J3, J4, J5, R_DIV1, R_DIV2, R_VUART` — **`0` `F_Paste.gtp` flashes**), **`15` `BOARD_ONLY`** (`AE1, FID1..5, H1..4, TP1..5`), **Single-Sided Top SMT Only (`B_Paste.gbp` intentionally omitted)** |

---

## 1. Bare-Board Fabrication & RF Geometry Specification

| Parameter | Mandatory Specification | Tolerance / PCBWay CAM Notes |
| :--- | :--- | :--- |
| **Single-Board Outline** | **`90.00 mm × 40.00 mm`** (`R = 2.00 mm` rounded corners) | `±0.10 mm` CNC routed profile (`Edge.Cuts`) |
| **Layer Count & Finished Thickness** | **2 Layers** (`F.Cu`, `B.Cu`), **`1.60 mm`** finished thickness | **`+0.03 / -0.10 mm` (`1.50–1.63 mm` finished)**, **`1.51 mm` nominal FR-4 dielectric core** (guarantees zero interference with Molex `73251-1153` `1.65 mm` fork max on bench VNA builds and tightens `AE1` core dispersion) |
| **Base Laminate & Dielectric** | **Standard FR-4 (`Tg ≥ 150 °C`)** (Shengyi `S1000-2M` / Kingboard `KB-6165F` or eq.) | `εr = 4.4 ± 0.2 @ 868 MHz` (verified `|S11| ≤ -10.21 dB` across all three `εr ∈ {4.2, 4.4, 4.6}` corners!), `tan δ ≤ 0.02 @ 1 GHz` |
| **Finished Copper Weight** | **`1 oz` (`35 µm` / `0.035 mm`)** on `F.Cu` and `B.Cu` | Minimum finished PTH copper wall `≥ 20 µm` |
| **Surface Finish** | **IPC-4552 ENIG (`1–3 µin Au` / `0.025–0.076 µm` over `120–240 µin Ni`) — MANDATORY** | **STRICTLY NO HASL / LF-HASL / OSP / Immersion Tin** (planar bare-`ENIG` sensing window & pogo-pin pads) |
| **Solder Mask (`NSMD` Pre-Applied)** | **Green LPI** on `F.Mask` and `B.Mask` — **MANDATORY** | **`0.035 mm` (`1.4 mil`) global NSMD mask expansion** (`0.025 mm` local on `U1`/`U2`, `0.000 mm` on `AE1` window) **ALREADY APPLIED IN `F_Mask.gts`!** CAM **MUST plot `F_Mask.gts` `1:1` (`0.00 mm` additional swell)**, preserving **`≥ 0.180 mm` (`7.1 mil`) Green LPI solder-mask dams** on `U1` (`0.60 mm` pitch) and **`≥ 0.200 mm`** on `U2` (`0.50 mm` pitch) |
| **Via Protection** | **100% Tented Vias** explicitly configured on `F.Mask` and `B.Mask` (**`131` vias**, `0.60/0.30 mm`; all `F.Cu` `GND` islands `≥ 2` vias; `CPWG` stitch pitch `≤ 3.40 mm`) | **Zero Via-in-Pad (NO VIPPO / epoxy plug surcharge required)** |
| **Intentional RF Parasitic Cutout** | **`2.20 × 2.20 mm` Copper Keepout Void** on **BOTH `F.Cu` and `B.Cu`** under `/BR_S` (`X_gbr = [33.40..35.60] mm, Y_gbr = [13.62..15.82] mm`) | Reduces `/BR_S` bridge sense-node capacitance to `0.1305 pF`. **CAM MUST NOT pour copper into this void!** |
| **Silkscreen** | **White LPI** on `F.SilkS` (`+` West / `-` East local `J2` direct-solder polarity markers) and `B.SilkS` (`+`/`-` mirrored beside `J2` PTH pads + `J2:1=GND 2=+VBAT 4.35V`, `J4: SWD (DNP)`, `J5: UART (DNP)` legends + `Rev E.5` banner + `UNIT S/N & DevEUI` write-on box with **`0` via overlaps**) | `≥ 0.15 mm` stroke width; **0% silkscreen in `X_gbr ≥ 50.0 mm` antenna aperture** |
| **Minimum Track / Space** | `0.20 mm` actual min signal width (`0.15 mm` rule floor) / `0.18 mm` clearance | `0.28 mm` exact coplanar RF gap on `GND_COUNTERPOISE` |
| **Minimum Drill / Annular Ring** | `0.30 mm` (`12 mil`) finished PTH drill / `0.15 mm` (`6 mil`) annular ring | **`4 × Ø2.700 mm` NPTH ISO 273 medium-fit `M2.5` mounting holes (`H1..H4`)** |
| **Optical SMT Fiducials** | **`5 × Ø1.00 mm Cu / Ø2.00 mm Mask`** bare-`ENIG` targets (`FID1..FID5`, `≥ 4.50 mm` conveyor clamp clearance) | `3` global (`FID1` `(4.50, 32.00)`, `FID2` `(46.50, 35.50)`, `FID3` `(30.50, 6.80)`) + `2` local `U1` diagonal (`FID4` `(10.30, 29.10)`, `FID5` `(23.20, 14.20)`), `0.000 mm²` foreign Cu in `Ø2.00 mm` mask |
| **Controlled Impedance Order** | **NO IMPEDANCE CONTROL (`ImpedanceControlled = False` — RF Geometry as Drawn, No Coupon or TDR Test)** | `F.Cu` **`W = 1.08 mm`**, **`Gap = 0.28 mm`** over `1.51 mm` `B.Cu` yields **`Z0 = 51.90 Ω` nominal 2D-FVM (`51.2–57.1 Ω` stackup envelope)**; max segment `11.18 mm = 0.056 λ_g` (`RL ≥ 26.8 dB`). **Do NOT resize `F.Cu` RF traces!** |
| **Electrical Test** | **100% Flying-Probe Netlist Continuity & Isolation Test** | `250 V` IPC-9252 test against Gerber X2 / IPC-D-356 netlist |

> **MANDATORY WRITTEN PCBWAY CAM HOLD & CONFIRMATION CHECKLIST:**
> Before releasing bare-board etching or SMT stencil cutting, obtain **written PCBWay CAM confirmation** on:
> 1. **Plot `F_Mask.gts` `1:1` (`0.00 mm` Additional CAM Swell — NSMD Clearances Pre-Applied):** Confirm CAM does **not** add further global mask expansion or gang-relief stripping on top of the `0.035 mm` (`0.025 mm` on `U1`/`U2`) NSMD clearances already baked into `F_Mask.gts`, preserving `≥ 0.180 mm` finished Green LPI dams on `U1` (`LGA-73`) and `≥ 0.200 mm` on `U2` (`DFN-8`).
> 2. **IPC-4552 ENIG Finish + Continuous Bare-ENIG Sensing Window (`X_gbr = [73.40..87.80] mm, Y_gbr = [6.65..20.80] mm`):** Confirm the single continuous rectangular `F.Mask` opening (`14.40 × 14.15 mm`) exposes bare ENIG comb fingers + bare FR-4 with **zero LPI mask ridges, zero silkscreen ink (`X_gbr ≥ 50.0 mm`), and zero `F.Paste` apertures**.
> 3. **Tightened `1.60 mm +0.03/-0.10 mm` (`1.50–1.63 mm`) 2-Layer Standard `FR-4` Stackup (`Impedance Control = NO`) & `/BR_S` Cutout:** Confirm finished board thickness stays `≤ 1.63 mm` (`1.51 mm` core), zero CAM width modification on `W = 1.08 mm` RF traces, preservation of the `2.20 × 2.20 mm` `F.Cu`/`B.Cu` void at `X_gbr = [33.40..35.60], Y_gbr = [13.62..15.82] mm`, and zero vendor UL/date markings inside `X_gbr = 50.00..90.00 mm` (place UL/date codes on `B.SilkS` inside `X_gbr = 8.0..45.0 mm`).
> 4. **Panelization Drawing Approval:** Approve 4-up tab-routed panel drawing confirming zero mouse-bite tabs in `X_gbr = 50.00..90.00 mm` (antenna aperture) or adjacent to `J2` (`X = 8.9..10.9`).

---

## 2. SMT Stencil, Component Sourcing Lock & Reflow Assembly Specification

### 2.1 Single-Sided Top Framed `0.10 mm` (`100 µm`) Electropolished Stainless-Steel Stencil (`IPC-7525B`)

| Stencil Attribute | Mandatory Value & Engineering Proof (`No CAM Shrink — Reductions Pre-Applied in F_Paste.gtp`) |
| :--- | :--- |
| **Stencil Count & Side** | **1 Stencil ONLY — Top Side (`ISAC_868_KiCad9-F_Paste.gtp`)**. `ISAC_868_KiCad9-B_Paste.gbp` is **intentionally omitted** from the Gerber archive so CAM cannot quote or cut a redundant bottom stencil; **NO bottom-side stencil or second reflow pass**! |
| **Foil Material & Thickness** | **Type-304 Fine-Grain Stainless Steel, `0.10 mm` (`100 µm` / `4.0 mil`) exact thickness**, framed (`IPC-7525B` compliant for `0.50 mm` DFN + `0.60 mm` LGA + `0402`) |
| **Cutting, Wall Treatment & CAM Rule** | **Fiber-Laser Cut + Electropolished + Hydrophobic Nano-Coating** (`Ra < 0.3 µm`). **NO CAM SHRINK — cut `F_Paste.gtp` `1:1` exactly as drawn!** |
| **`U1` (`RAK3172LP-SiP` `LGA-73` Perimeter Pads `1..64`)** | **`0.30 × 1.10 mm`** aperture (`-0.035 mm` inset per side on `0.37 × 1.17 mm` pads): **Area Ratio `AR = 1.179`** (`0.300 mm` inter-aperture stencil web eliminates `0.60 mm`-pitch solder bridging) |
| **`U1` Central `3 × 3` LGA Ground Matrix (`Pads 65..73`)** | **`9 × [1.20 × 1.20 mm]`** apertures on `1.60 × 1.60 mm` lands (**`56.25%` (`56.3%`) paste coverage**, preventing LGA package float & perimeter open joints; `4` interstitial vias are tented outside lands) |
| **`U2` (`LT5538IDD#TRPBF` `DFN-8` Perimeter Pads `1..8`)** | **`0.82 × 0.22 mm`** aperture (`(solder_paste_margin -0.015)` on `0.85 × 0.25 mm` pads): **Area Ratio `AR = 0.867–0.897`** (`> 0.66` IPC-7525B minimum $\rightarrow$ `> 88%` transfer efficiency) |
| **`U2` `Pad 9` (`1.65 × 2.38 mm` Exposed RF/Thermal Pad)** | **`2 × 2` window-pane apertures: `4 × [0.57 × 0.86 mm]`** = **`1.961 mm² / 3.927 mm² = 49.93%` (`50.0%` target coverage)** eliminating `DFN-8` package float |
| **`DNP` Footprints (`C_SMPS3, D_RF, J1, J2, J3, J4, J5, R_DIV1, R_DIV2, R_VUART`) & `AE1`** | **`0` Flashes in `F_Paste.gtp`** (`0` paste on PTH `J2..J5`, `J1`, `AE1`, and `*_DNP_NoPaste` footprints). **NEVER derive stencil apertures from `F.Mask`!** |

### 2.2 Justified `NO SUBSTITUTION` Sourcing Lock (`6` Parts) & Verified Tier-1 BOM (`46` Lines: `38` Pop + `8` DNP)

- **Strict `NO SUBSTITUTION` Parts (`6` Functional/Pinout-Unique Designators):** PCBWay Procurement **MUST NOT** substitute alternates without written sign-off on:
  1. **`U1` (`RAKwireless RAK3172LP-SIP-8-SM-NI`, SKU `305049`):** EU868 `RFO_LP` `+14 dBm` `LGA-73` SiP ONLY — **NEVER substitute `RAK3172-SiP` (`RFO_HP` `+22 dBm`)**. Procure from **RAKwireless Store / Mouser (`910-RAK3172LPSIP8SMN`) / DigiKey**.
  2. **`U2` (`Analog Devices LT5538IDD#TRPBF`):** **8 mm Tape-and-Reel (`#TRPBF`)** calibrated `19.0 mV/dB`, `-88.8 dBm` intercept `DFN-8` RF detector (`V_CC = 3.0–5.25 V` fed from `VBAT` via `Q1`; note `#PBF` is a 37-pc shipping tube requiring custom tube feeder).
  3. **`U3` (`TI TPS7A0233DBVR`, LCSC `C2873330`):** `25 nA` $I_Q$ nanopower `SOT-23-5` (`DBV` pinout `1=IN, 2=GND, 3=EN, 4=NC, 5=OUT`).
  4. **`Q1` (`TI TPS22919DCKR`, Authorized DigiKey/Mouser):** `SC-70-6` controlled-slew load switch with `QOD` discharge.
  5. **`Q2` (`Nexperia NX3008CBKS,115`, LCSC `C456076`):** `SOT-363` complementary N+P MOSFET pair.
  6. **`J1` (`Molex 73251-1153`, `DNP = Yes` on Enclosed Field SKU — NO generic SMA substitution on Bench VNA Units):** `1.60 mm` (`0.062"`) brass gold-plated edge-straddle SMA jack.
- **Orderable Precision RF Bridge, Wirewound Power Inductor & Harmonic Pi-Network Parts:**
  - **`L_SMPS` (`15 µH ±10%`, `Murata LQH2MCN150K02L`, LCSC `C86089`):** True wirewound ferrite DC-DC power inductor (`Isat = 300 mA`, `R_DC = 1.1 Ω`) — **NEVER substitute multilayer EMI ferrite beads**!
  - **`R1` (`8.2 Ω ±0.1%`):** **`Yageo RT0402BRD078R2L`** (`1/16 W 0402 ±25 ppm/°C` Thin-Film; `R2=681 Ω, R3=3.57 kΩ, R_TERM=56 Ω, R_B1=R_B2=4.7 kΩ` Susumu `RG1005P` `0.1%`).
  - **Populated Parasitic-Pre-Distorted Elliptic Pi-Network:** `C_M1 = 3.6 pF ±0.05 pF` (`Murata GJM1555C1H3R6WB01D`), `L_M1 = 8.2 nH ±2%` (`Murata LQW15AN8N2G00D`) `|| C_MZ = 0.5 pF ±0.05 pF` (`Murata GJM1555C1HR50WB01D`), `C_M2 = 4.3 pF ±0.05 pF` (`Murata GJM1555C1H4R3WB01D`), providing **`≥ 37.2 dB`** harmonic suppression at `2f0` (`1.733 GHz`) and **`≥ 60.1 dB`** at `3f0` (`2.600 GHz`) AND `|S11| ≤ -10.21 dB` across `εr ∈ {4.2, 4.4, 4.6}`.

### 2.3 100% Pure-SMD Automated Reflow SOP (`Zero` Secondary THT Operations at PCBWay!)

1. **Moisture Sensitivity Handling (`IPC/JEDEC J-STD-033D`):** `U1` (`RAK3172LP-SIP-8-SM-NI`) is **MSL-3 (`168 h` floor life at `≤ 30 °C / 60% RH`)**; dry-bake `U1` at `125 °C ± 5 °C` for `24 hours` if HIC `10%` spot is pink or floor life exceeded.
2. **Solder Paste & Wash:** **Lead-Free SAC305, Type-4 (`20–38 µm`), No-Clean `ROL0`**. **NO Aqueous / Ultrasonic Wash** (`SW1` `Omron B3U-1000P` is unsealed); wipe `AE1` (`X_gbr = 73.4..87.8 mm`) with `99.9%` IPA + lint-free swab prior to packing.
3. **Automated Top Pick-and-Place (`fab/cpl/ISAC_868_Turnkey_CPL_Top.csv` = `67` Pure SMD Rows, `0` THT Parts):** Run automated high-speed SMD pick-and-place using `ISAC_868_Turnkey_CPL_Top.csv` and reflow per `IPC/JEDEC J-STD-020E` (`Peak 240–245 °C`, `TAL 45–65 s`).
4. **Zero Turnkey THT Soldering (`J1, J2, J3, J4, J5` are ALL `DNP = Yes`):** Leave `J2` (`Pad 1` Square PTH at `(10.900, 36.150)` = **`GND`**, `Pad 2` Round PTH at `(8.900, 36.150)` = **`/VBAT_RAW`**) and `J3, J4, J5` as clean bare-`ENIG` PTH rings for box-build direct battery wire soldering (inserted from `B.Cu` upward into `J2`, keeping the waterproof enclosure top cover `100%` uniform flat at `+8.50 mm`) and pogo-pin factory flashing/calibration!
5. **First-Article RF Bench Units (`SN01..SN05` within Gate 8 Pilot Lot):** Hand-solder `J1` (`Molex 73251-1153`) post-reflow per `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv` for calibrated 1-port VNA (`R_DIV2`) and conducted harmonic spectrum (`R_DIV1`) verification.

### 2.4 Mandatory Inspection & Quality Gates (`AOI` + `100% AXI`)

- **100% 3D Automated Optical Inspection (`AOI`):** Verify presence, Pin-1 orientation (`U1, U2, U3, Q1, Q2, Q3, D_VBAT, D_RST, D_3V3, D_SWD, D_UART`), fillet quality across all `67` pure-SMD parts, and verify all `10` DNP exclusions (`C_SMPS3, D_RF, J1, J2, J3, J4, J5, R_DIV1, R_DIV2, R_VUART` remain unpopulated with clean open PTH barrels).
- **100% 2D/3D Automated X-Ray Inspection (`AXI`) on `U1` (`LGA-73`) & `U2` (`DFN-8-1EP`):** Aggregate voiding `< 25%` (`< 15%` target), `0` perimeter bridges.

---

## 3. 2×2 Breakaway Tab-Routed Panelization Specification

- **Panel Format:** `2 Columns × 2 Rows` (`4` boards per panel; `2.00 mm` router kerf + `8.00 mm` perimeter rails $\rightarrow$ **`198.00 mm × 98.00 mm`**; **STRICTLY NO V-SCORING (`0%` V-Cut)**).
- **STRICT MOUSE-BITE KEEP-OUT ACROSS ENTIRE `X_gbr = 50.00..90.00 mm` ANTENNA APERTURE:**
  - **Top Edge (`Y_gbr = 40.00 mm`):** `X_gbr = 20.00 mm`, `44.00 mm` | **Bottom Edge (`Y_gbr = 0.00 mm`):** `X_gbr = 4.50 mm`, `44.00 mm` | **Left Edge (`X_gbr = 0.00 mm`):** `Y_gbr = 6.00 mm`, `30.00 mm` | **Right Edge (`X_gbr = 90.00 mm`):** `0` tabs.

---

## 4. Direct Battery Wire Soldering (`J2 = DNP`), Pogo-Pin Provisioning & 2-Point Factory Calibration

1. **`J2` Direct Bottom-Side (`B.Cu`) Battery Wire Soldering (`Pad 1 Square = BLACK GND`, `Pad 2 Round = RED +VBAT_RAW`; `3.00–4.20 V` Op, `4.35 V DC MAX` — `NO 5V PSU`):** During box-build, insert stripped/tinned `24–26 AWG` silicone battery leads upward from `B.Cu` (`z = -1.60 mm`, guided by mirrored `B.SilkS` `J2:1=GND 2=+VBAT 4.35V` legend) into `J2`'s `Ø0.75 mm` bare-`ENIG` PTH barrels (`≥ 75%` vertical barrel fill per `IPC-A-610 Class 3`, trim top fillet `≤ +1.50 mm` for `+5.00 mm` clearance below the flat roof, and anchor wire insulation to `B.Cu` with `DOWSIL 3145` neutral-cure RTV silicone; when trimming a factory LiPo plug, cut **one wire at a time**!). `Q3` (`AO3401A` ideal diode, `< 6 mV` drop) protects the node if leads are accidentally swapped.
2. **Pogo-Pin Back-Feed Protection (`J4.1`, `J5.1`, `J3.2`):** `J4.1` (`VAPP_SENSE`) isolated via `R_VAPP = 1.0 kΩ`, `J5.1` (`VUART`) isolated via `R_VUART = DNP`, `J3.2` (`BOOT_HI`) limited via `R_BHI = 10 kΩ`, clamped by `D_3V3` (`PESD5V0S1BA,115`), with bottom-side pogo legends `J4: SWD (DNP)` and `J5: UART (DNP)`.
3. **Per-Unit Key Provisioning, 2-Point Factory Cal & Secret Vault (`tools/production_flash.sh`):** Contact bare-`ENIG` PTH rings of `J4` (`SWD`) via pogo fixture, flash IEEE-validated `DevEUI / JoinEUI / AppKey` + Point 1 Dry-Air tare (`--cal-dry-mv v1,v2,v3`) + Point 2 `Al2O3` reference intercept offset (`--cal-ref-cdb`, `level_dbm_x100 - (-2619)` in `0.01 dB`, e.g. `0` nominal) to `0x0803E000` with `--lock-rdp1` (`IWDG_SW=1`, `IWDG_STOP=0`, `BOR_LEV=3`, `nSWBOOT0=1` [hardware `PH3/BOOT0` pin active], `RDP=0xBB` Level 1, post-unlock `UID64` SWD readback verified non-zero prior to lock, and `0600` ledger in `provisioning_vault/provisioned_units_secret.csv`).

---

## 5. Deliverable Package Cross-Reference (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)

| File Path | Purpose |
| :--- | :--- |
| `ISAC_868_KiCad9.kicad_pcb` / `ISAC_868_KiCad9.kicad_dru` | Locked `Rev E.5` KiCad 9 PCB layout (`92` footprints, `131` tented vias, `0` DRC/ERC violations) |
| `fab/bom/ISAC_868_Turnkey_BOM.csv` | RFC-4180 10-column Turnkey BOM (`38` populated lines / `67` pure-SMD parts + `8` DNP lines / `10` parts; `6` `NO SUBSTITUTION` locks) |
| `fab/cpl/ISAC_868_Turnkey_CPL_Top.csv` | `67` pure-SMD top placements (`0` THT parts) + `CPL_README.md` |
| `fab/mechanical/ISAC_868_PCBA.step` & `ISAC_868_*.stl` (`3` STLs) | Full 3D populated STEP assembly + watertight 2-manifold `Rev E.5` uniform-flat-roof (`95.7 × 45.7 × 16.1 mm`, `-1.44 mm` compliant skirt) UV-stabilized `ASA/PETG` waterproof enclosure (`0.80 mm` open-East deck + `25 µm` `3M 467MP` + symmetric `360°` `1.80 × 0.76 mm` Parker `ORD 5700` silicone O-ring gland [`23.3%` squeeze, `68.3%` fill] + `4 × M2.5 × 22 mm` EPDM-sealed corner screws, `0` PCB-bay roof slots) |
