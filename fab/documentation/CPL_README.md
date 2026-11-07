# Pick-and-Place (CPL) Zero-Orientation, Pure-SMD Assembly & Pin-1 Verification Guide (`Rev E.5`)

## 1. Coordinate System, 100% Pure-SMD Turnkey Assembly & Rotation Convention (Gerber X2 / Auxiliary Origin)

All Pick-and-Place (`CPL`), Excellon Drill, and Gerber X2 files for `ISAC_868_KiCad9` (`Rev E.5`) share a single locked **Auxiliary / Drill-File Origin (`AuxOrigin`)** located at the **Bottom-Left Corner** of the `90.000 × 40.000 mm` single-board outline (`Sheet X0 = 103.500 mm, Sheet Y = 120.000 mm`):

- **`PosX` (`X_gbr`):** `0.000 mm` (Left edge) $\rightarrow$ `+90.000 mm` (Right antenna edge), positive East (`+dx`).
- **`PosY` (`Y_gbr`):** `0.000 mm` (Bottom edge, `dy = 40.000 mm`) $\rightarrow$ `+40.000 mm` (Top edge, `dy = 0.000 mm`), positive North (`40.000 - dy`).
- **Placement Side:** **100% Top Side (`F.Cu` / `top`)** — zero components on `B.Cu`, and `ISAC_868_KiCad9-B_Paste.gbp` is **intentionally omitted** from the Gerber archive so CAM never cuts a bottom stencil.
- **100% Pure-SMD Turnkey PCBA (`67` Populated SMD Parts, `0` THT Parts):**
  1. **`fab/cpl/ISAC_868_Turnkey_CPL_Top.csv` (`67` Rows — `100%` Pure SMD, `0` THT Parts):** Contains the complete set of `67` populated components reflowed via the `0.10 mm` top stencil (`U2 = LT5538IDD#TRPBF` in 8 mm tape-and-reel). **Zero secondary THT wave/selective/hand-soldering is required at PCBWay!**
  2. **Battery Direct-Solder Pads `J2`, Debug Pogo Pads `J3, J4, J5` & Bench SMA `J1` (`DNP = Yes` on Sealed Field SKU):** Excluded from the turnkey placement table (`0` `F_Paste.gtp` flashes). During final box-build, `24–26 AWG` silicone battery leads solder directly from `B.Cu` upward into `J2`'s bare-`ENIG` `Ø0.75 mm` PTH barrels (`Pad 1` Square at `(10.900, 36.150)` = **`BLACK / GND`**, `Pad 2` Round at `(8.900, 36.150)` = **`RED / +VBAT_RAW`**, **`4.35 V DC MAX` — `NO 5V PSU`**, marked `J2:1=GND 2=+VBAT 4.35V` on `B.SilkS`), keeping the enclosure top cover `100%` uniform flat (`+8.50 mm`) and fully waterproof (`J4: SWD (DNP)` and `J5: UART (DNP)` labeled on `B.SilkS`; see companion reference `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv` outside the Turnkey ZIP).
- **Rotation Convention (`Rot [0, 360)`):** Counter-clockwise (`CCW`) positive in degrees viewed from above `F.Cu` (`+Z`), normalized to `[0.0°, 360.0°)` (`-90.0°` raw KiCad $\equiv$ `270.0°`).

> **CRITICAL CAM INSTRUCTION ON TAPE-REEL ROTATION OFFSETS & PAD-BBOX CENTROIDS:**
> 1. All rotations follow **IPC-7351B / KiCad 9 native footprint zero-orientations**. **PCBWay SMT engineers MUST verify physical Pin-1 dots, bevels, and tabs directly against the exact Gerber Pad-1 `(X_gbr, Y_gbr)` coordinates in Section 2** prior to first-article reflow!
> 2. Every `(PosX, PosY)` coordinate in `ISAC_868_Turnkey_CPL_Top.csv` (`67` rows) equals the **exact `F_Cu.gtl` copper pad-flash bounding-box midpoint (`0.000 mm` delta across all `67` populated SMD parts)**.

---

## 2. Polarized IC, MOSFET, ESD & Switch Verification Table (`67` Populated Pure-SMD Parts)

Every coordinate below is extracted programmatically from `ISAC_868_KiCad9.kicad_pcb` (`Rev E.5`) in exact **Gerber coordinates `(X_gbr, Y_gbr)` [mm]**:

| Ref | MPN | Package / Footprint | CPL Origin `(PosX, PosY)` [mm] | `Rot [0, 360)` (KiCad Raw) | Exact `Pad 1` Gerber `(X, Y)` [mm] | Physical Pin-1 / Tab / Shroud Orientation in Top View (`+Y_gbr` = Up / Top Edge, `+X_gbr` = Right) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`U1`** | `RAK3172LP-SIP-8-SM-NI` | `LGA-73` (`12×12 mm`, `P0.6 mm`) | `(18.250, 22.100)` | **`0.0°`** (`0.0°`) | `(12.600, 26.600)` | **Pin-1 Laser Dot at TOP-LEFT** (`-X_gbr, +Y_gbr`, aligned to `F.SilkS` corner triangle). `Pad 37 (RF_OUT)` faces Right (`+X_gbr`). |
| **`U2`** | `LT5538IDD#TRPBF` | `DFN-8-1EP` (`3×3 mm`, `P0.5 mm`, 8mm T&R) | `(40.650, 13.950)` | **`0.0°`** (`0.0°`) | `(39.200, 14.700)` | **Pin-1 Laser Dot / Chamfer at TOP-LEFT** (`Pads 1..4` along Left `-X_gbr` edge top-to-bottom; `Pads 5..8` along Right `+X_gbr` edge bottom-to-top). |
| **`U3`** | `TPS7A0233DBVR` | `SOT-23-5` (`DBV`) | `(24.350, 33.800)` | **`0.0°`** (`0.0°`) | `(23.213, 34.750)` | **Pin-1 (`IN`) at TOP-LEFT** (`3` pins on Left `-X_gbr`: `1=IN` top, `2=GND` mid, `3=EN` bot; `2` pins on Right `+X_gbr`: `4=NC` bot, `5=OUT` top). |
| **`Q1`** | `TPS22919DCKR` | `SOT-363` (`SC-70-6`) | `(38.500, 6.000)` | **`0.0°`** (`0.0°`) | `(37.613, 6.650)` | **Pin-1 (`VIN -> VBAT`) Bar/Dot at TOP-LEFT** (`Pads 1..3` on Left `-X_gbr`: `1=VBAT, 2=GND, 3=PA8 DET_EN`; `Pads 4..6` on Right `+X_gbr`). |
| **`Q2`** | `NX3008CBKS,115` | `SOT-363` (`SC-70-6`) | `(12.200, 32.550)` | **`0.0°`** (`0.0°`) | `(11.312, 33.200)` | **Pin-1 (`S1/GND`) Bar/Dot at TOP-LEFT** (`Pads 1..3` on Left `-X_gbr`: `1=GND, 2=PA9 BAT_MON_EN, 3=VBAT_SW`; `Pads 4..6` on Right `+X_gbr`). |
| **`Q3`** | `AO3401A` | `SOT-23` (PMOS Ideal Diode) | `(17.350, 35.900)` | **`90.0°`** (`90.0°`) | `(16.400, 34.963)` | **Pin-1 (`Gate -> GND`) at BOTTOM-LEFT**, `Pin 2 (Source -> VBAT)` at **BOTTOM-RIGHT** `(18.300, 34.963)`, single center **Pin-3 (`Drain -> VBAT_RAW`) pointing UP (`+Y_gbr`)** at `(17.350, 36.838)`. |
| **`D_VBAT`** | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(14.450, 35.700)` | **`270.0°`** (`-90.0°`) | `(14.450, 36.750)` | Symmetrical bidirectional TVS clamp (`Pad 1` `VBAT_RAW` UP at `(14.450, 36.750)`, `Pad 2` `GND` DOWN at `(14.450, 34.650)`). |
| **`D_RST`** | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(6.300, 12.450)` | **`0.0°`** (`0.0°`) | `(5.250, 12.450)` | Symmetrical bidirectional TVS clamp (`Pad 1` `RST` LEFT at `(5.250, 12.450)`, `Pad 2` `GND` RIGHT at `(7.350, 12.450)`). |
| **`D_3V3`** | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(33.200, 4.200)` | **`270.0°`** (`-90.0°`) | `(33.200, 5.250)` | Symmetrical bidirectional TVS clamp on `3V3` (`Pad 1` `3V3` UP at `(33.200, 5.250)`, `Pad 2` `GND` DOWN at `(33.200, 3.150)`). |
| **`D_SWD`** | `PESD5V0U2BT,215` | `SOT-23` (Dual TVS Array) | `(12.310, 6.850)` | **`90.0°`** (`90.0°`) | `(11.360, 5.912)` | **Pin-1 (`SWDIO`) at BOTTOM-LEFT**, `Pin 2 (SWCLK)` at **BOTTOM-RIGHT** `(13.260, 5.912)`, single center **Pin-3 (`GND`) pointing UP (`+Y_gbr`)**. |
| **`D_UART`** | `PESD5V0U2BT,215` | `SOT-23` (Dual TVS Array) | `(26.350, 6.850)` | **`90.0°`** (`90.0°`) | `(25.400, 5.912)` | **Pin-1 (`UART_TX`) at BOTTOM-LEFT**, `Pin 2 (UART_RX)` at **BOTTOM-RIGHT** `(27.300, 5.912)`, single center **Pin-3 (`GND`) pointing UP (`+Y_gbr`)**. |
| **`SW1`** | `B3U-1000P` | `SW_SPST_B3U-1000P` | `(2.600, 11.500)` | **`270.0°`** (`-90.0°`) | `(2.600, 13.200)` | SMD Gull-Wing Terminals oriented **North/South** (`Pad 1` `RST` UP at `(2.600, 13.200)`, `Pad 2` `GND` DOWN at `(2.600, 9.800)`). |

---

## 3. Optical SMT Alignment Fiducials (`FID1..FID5` — Excluded from BOM/CPL, `≥ 4.50 mm` Edge Clamp Margin)

| Fiducial | Role | Copper / Mask Opening | Gerber `(X_gbr, Y_gbr)` [mm] | Board `(dx, dy)` [mm] |
| :--- | :--- | :--- | :--- | :--- |
| **`FID1`** | Global Electronics Bay Corner #1 (Top-Left, `4.50 mm` clamp margin) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(4.500, 32.000)` | `(4.500, 8.000)` |
| **`FID2`** | Global Electronics Bay Corner #2 (Top-Right, `4.50 mm` clamp margin) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(46.500, 35.500)` | `(46.500, 4.500)` |
| **`FID3`** | Global Electronics Bay Corner #3 (Bottom-Center) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(30.500, 6.800)` | `(30.500, 33.200)` |
| **`FID4`** | Local Fine-Pitch Target #1 (`U1` `LGA-73` NW Diagonal) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(10.300, 29.100)` | `(10.300, 10.900)` |
| **`FID5`** | Local Fine-Pitch Target #2 (`U1` `LGA-73` SE Diagonal) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(23.200, 14.200)` | `(23.200, 25.800)` |

---

## 4. Mandatory Do-Not-Populate (`DNP`) Exclusions (`10` Parts — `0` Paste Flashes)

The following **`10` footprints MUST remain unpopulated** during turnkey assembly (`DNP = Yes` in `fab/bom/ISAC_868_Turnkey_BOM.csv`, excluded from `ISAC_868_Turnkey_CPL_Top.csv`, producing **`0` flashes in `F_Paste.gtp`**):

1. **`C_SMPS3`** `(7.550, 17.100)` — Optional `0402` `100 nF` HF bypass on `/VFBSMPS` (`DNP = Yes` per `STM32WLE5JC` `DS13105` Table 33 `15 µH` SMPS loop-stability envelope; `C_SMPS2 = 470 nF` provides exact `Cout = 470 nF ±20%`).
2. **`D_RF`** `(35.950, 28.500)` — Optional `SOD-523` (`ESD9B5.0ST5G`, `0.5 pF`) RF ESD clamp on `/SMA_C` (`DNP` by default).
3. **`J1`** `(34.500, 35.240)` — Optional `Molex 73251-1153` edge-straddle SMA jack (`DNP = Yes` on enclosed field SKU; hand-solder post-reflow on bench VNA units only).
4. **`J2`** `(9.900, 36.150)` — `1×2` `2.00 mm` battery PTH solder target (`DNP = Yes` on enclosed field SKU — bare-`ENIG` `Ø0.75 mm` PTH barrels for direct bottom-side `B.Cu` battery lead soldering: `Pad 1` Square `(10.900, 36.150)` = **`BLACK / GND`**, `Pad 2` Round `(8.900, 36.150)` = **`RED / +VBAT_RAW`**; optional `JST B2B-PH-K-S` on bench builds).
5. **`J3`** `(2.400, 20.500)` — `1×2` `BOOT` bare-`ENIG` PTH pogo-pin target (`DNP = Yes` on sealed field SKU — eliminates roof apertures).
6. **`J4`** `(8.500, 3.000)` — `1×5` `SWD` bare-`ENIG` PTH pogo-pin target (`Pad 1 VAPP_SENSE` `(8.500, 3.000)` $\to$ `Pad 5 NRST` `(18.660, 3.000)`; `DNP = Yes` on sealed field SKU).
7. **`J5`** `(22.540, 3.000)` — `1×4` `UART` bare-`ENIG` PTH pogo-pin target (`Pad 1 VUART_ISO` `(22.540, 3.000)` $\to$ `Pad 4 GND` `(30.160, 3.000)`; `DNP = Yes` on sealed field SKU).
8. **`R_DIV1`** `(33.480, 21.120)` — Optional `0402` zero-stub conducted PA test / harmonic spectrum diverter at `/BR_P` (**MUST be DNP for LoRaWAN operation**).
9. **`R_DIV2`** `(35.520, 21.120)` — Optional `0402` zero-stub VNA antenna port diverter at `/BR_Q` (**MUST be DNP for LoRaWAN operation**).
10. **`R_VUART`** `(20.600, 5.550)` — Optional `0402` `J5.1` `VUART` jumper (**MUST be DNP by default** so an external `3.3 V` USB-UART adapter cannot back-feed `3V3` / `VBAT`).
