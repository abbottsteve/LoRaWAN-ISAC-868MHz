# Pick-and-Place (CPL) Orientation & Pin-1 Reference Guide (`Rev E.5`)

## 1. Coordinate System, Single-Sided SMT Assembly & Rotation Convention

Pick-and-Place (`CPL`), Excellon Drill, and Gerber X2 files for `ISAC_868_KiCad9` (`Rev E.5`) share a single Auxiliary / Drill-File Origin (`AuxOrigin`) at the bottom-left corner of the `90.000 × 40.000 mm` board outline (`Sheet X0 = 103.500 mm, Sheet Y = 120.000 mm`):

- **`PosX` (`X_gbr`):** `0.000 mm` (Left edge) $\rightarrow$ `+90.000 mm` (Right antenna edge), positive East (`+dx`).
- **`PosY` (`Y_gbr`):** `0.000 mm` (Bottom edge, `dy = 40.000 mm`) $\rightarrow$ `+40.000 mm` (Top edge, `dy = 0.000 mm`), positive North (`40.000 - dy`).
- **Placement Side:** Top side (`F.Cu` / `top`) only — no components sit on `B.Cu`, and `ISAC_868_KiCad9-B_Paste.gbp` is omitted from the Gerber archive so no bottom stencil is required.
- **Single-Pass SMD Assembly (`67` Populated SMD Parts, `0` THT Parts):**
  1. `fab/cpl/ISAC_868_Turnkey_CPL_Top.csv` (`67` rows): Lists all `67` populated SMD components reflowed via the `0.10 mm` top stencil (`U2 = LT5538IDD#TRPBF` in 8 mm tape-and-reel). No through-hole wave or hand soldering is required during SMT assembly.
  2. **Battery Pads `J2`, Debug Pogo Pads `J3, J4, J5` & Bench SMA `J1` (`DNP = Yes`):** Excluded from the turnkey placement file (`0` `F_Paste.gtp` flashes). During box-build, `24–26 AWG` silicone battery leads solder upward from `B.Cu` into `J2`'s bare-`ENIG` `Ø0.75 mm` PTH barrels (`Pad 1` Square at `(10.900, 36.150)` = `BLACK / GND`, `Pad 2` Round at `(8.900, 36.150)` = `RED / +VBAT_RAW`, `4.35 V DC MAX`, labeled `J2:1=GND 2=+VBAT 4.35V` on `B.SilkS`). Companion bench coordinates for `J1..J5` are provided in `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv`.
- **Rotation Convention (`Rot [0, 360)`):** Counter-clockwise (`CCW`) positive in degrees viewed from above `F.Cu` (`+Z`), normalized to `[0.0°, 360.0°)` (`-90.0°` in KiCad $\equiv$ `270.0°`).

> **CAM Note on Tape-and-Reel Offsets & Pad Centroids:**
> 1. Rotations follow IPC-7351B / KiCad 9 footprint zero-orientations. Please verify physical Pin-1 dots, bevels, and tabs against the Gerber Pad-1 `(X_gbr, Y_gbr)` coordinates in Section 2 before first-article reflow.
> 2. Every `(PosX, PosY)` coordinate in `ISAC_868_Turnkey_CPL_Top.csv` (`67` rows) matches the `F_Cu.gtl` copper pad-flash bounding-box midpoint (`0.000 mm` offset across all `67` parts).

---

## 2. Polarized IC, MOSFET, ESD & Switch Pin-1 Table

Coordinates below are extracted from `ISAC_868_KiCad9.kicad_pcb` (`Rev E.5`) in Gerber coordinates `(X_gbr, Y_gbr)` [mm]:

| Ref | MPN | Package / Footprint | CPL Origin `(PosX, PosY)` [mm] | `Rot [0, 360)` | `Pad 1` Gerber `(X, Y)` [mm] | Physical Pin-1 Orientation in Top View (`+Y_gbr` = Up, `+X_gbr` = Right) |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| `U1` | `RAK3172LP-SIP-8-SM-NI` | `LGA-73` (`12×12 mm`, `P0.6 mm`) | `(18.250, 22.100)` | `0.0°` | `(12.600, 26.600)` | Pin-1 laser dot at top-left (`-X_gbr, +Y_gbr`, aligned to `F.SilkS` corner triangle). `Pad 37 (RF_OUT)` faces Right (`+X_gbr`). |
| `U2` | `LT5538IDD#TRPBF` | `DFN-8-1EP` (`3×3 mm`, `P0.5 mm`, 8mm T&R) | `(40.650, 13.950)` | `0.0°` | `(39.200, 14.700)` | Pin-1 dot / chamfer at top-left (`Pads 1..4` along Left `-X_gbr` edge top-to-bottom; `Pads 5..8` along Right `+X_gbr` edge bottom-to-top). |
| `U3` | `TPS7A0233DBVR` | `SOT-23-5` (`DBV`) | `(24.350, 33.800)` | `0.0°` | `(23.213, 34.750)` | Pin-1 (`IN`) at top-left (`3` pins on Left `-X_gbr`: `1=IN` top, `2=GND` mid, `3=EN` bot; `2` pins on Right `+X_gbr`: `4=NC` bot, `5=OUT` top). |
| `Q1` | `TPS22919DCKR` | `SOT-363` (`SC-70-6`) | `(38.500, 6.000)` | `0.0°` | `(37.613, 6.650)` | Pin-1 (`VIN -> VBAT`) bar/dot at top-left (`Pads 1..3` on Left `-X_gbr`: `1=VBAT, 2=GND, 3=PA8 DET_EN`; `Pads 4..6` on Right `+X_gbr`). |
| `Q2` | `NX3008CBKS,115` | `SOT-363` (`SC-70-6`) | `(12.200, 32.550)` | `0.0°` | `(11.312, 33.200)` | Pin-1 (`S1/GND`) bar/dot at top-left (`Pads 1..3` on Left `-X_gbr`: `1=GND, 2=PA9 BAT_MON_EN, 3=VBAT_SW`; `Pads 4..6` on Right `+X_gbr`). |
| `Q3` | `AO3401A` | `SOT-23` (PMOS Ideal Diode) | `(17.350, 35.900)` | `90.0°` | `(16.400, 34.963)` | Pin-1 (`Gate -> GND`) at bottom-left, `Pin 2 (Source -> VBAT)` at bottom-right `(18.300, 34.963)`, center `Pin 3 (Drain -> VBAT_RAW)` pointing up (`+Y_gbr`) at `(17.350, 36.838)`. |
| `D_VBAT` | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(14.450, 35.700)` | `270.0°` | `(14.450, 36.750)` | Bidirectional TVS (`Pad 1` `VBAT_RAW` up at `(14.450, 36.750)`, `Pad 2` `GND` down at `(14.450, 34.650)`). |
| `D_RST` | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(6.300, 12.450)` | `0.0°` | `(5.250, 12.450)` | Bidirectional TVS (`Pad 1` `RST` left at `(5.250, 12.450)`, `Pad 2` `GND` right at `(7.350, 12.450)`). |
| `D_3V3` | `PESD5V0S1BA,115` | `D_SOD-323` (Bi-Dir TVS) | `(33.200, 4.200)` | `270.0°` | `(33.200, 5.250)` | Bidirectional TVS on `3V3` (`Pad 1` `3V3` up at `(33.200, 5.250)`, `Pad 2` `GND` down at `(33.200, 3.150)`). |
| `D_SWD` | `PESD5V0U2BT,215` | `SOT-23` (Dual TVS Array) | `(12.310, 6.850)` | `90.0°` | `(11.360, 5.912)` | Pin-1 (`SWDIO`) at bottom-left, `Pin 2 (SWCLK)` at bottom-right `(13.260, 5.912)`, center `Pin 3 (GND)` pointing up (`+Y_gbr`). |
| `D_UART` | `PESD5V0U2BT,215` | `SOT-23` (Dual TVS Array) | `(26.350, 6.850)` | `90.0°` | `(25.400, 5.912)` | Pin-1 (`UART_TX`) at bottom-left, `Pin 2 (UART_RX)` at bottom-right `(27.300, 5.912)`, center `Pin 3 (GND)` pointing up (`+Y_gbr`). |
| `SW1` | `B3U-1000P` | `SW_SPST_B3U-1000P` | `(2.600, 11.500)` | `270.0°` | `(2.600, 13.200)` | Gull-wing terminals oriented North/South (`Pad 1` `RST` up at `(2.600, 13.200)`, `Pad 2` `GND` down at `(2.600, 9.800)`). |

---

## 3. Optical SMT Alignment Fiducials (`FID1..FID5`)

| Fiducial | Role | Copper / Mask Opening | Gerber `(X_gbr, Y_gbr)` [mm] | Board `(dx, dy)` [mm] |
| :--- | :--- | :--- | :---: | :---: |
| `FID1` | Global Corner #1 (Top-Left, `4.50 mm` rail margin) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(4.500, 32.000)` | `(4.500, 8.000)` |
| `FID2` | Global Corner #2 (Top-Right, `4.50 mm` rail margin) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(46.500, 35.500)` | `(46.500, 4.500)` |
| `FID3` | Global Corner #3 (Bottom-Center) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(30.500, 6.800)` | `(30.500, 33.200)` |
| `FID4` | Local `U1` Target #1 (`LGA-73` NW Diagonal) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(10.300, 29.100)` | `(10.300, 10.900)` |
| `FID5` | Local `U1` Target #2 (`LGA-73` SE Diagonal) | `Ø1.00 mm Cu` / `Ø2.00 mm Mask` | `(23.200, 14.200)` | `(23.200, 25.800)` |

---

## 4. Do-Not-Populate (`DNP`) Exclusions (`10` Parts — `0` Paste Flashes)

The `10` footprints below remain unpopulated during SMT assembly (`DNP = Yes` in `fab/bom/ISAC_868_Turnkey_BOM.csv`, excluded from `ISAC_868_Turnkey_CPL_Top.csv`, `0` flashes in `F_Paste.gtp`):

1. `C_SMPS3` `(7.550, 17.100)` — Optional `0402` `100 nF` bypass on `/VFBSMPS` (`DNP` per `STM32WLE5JC` `DS13105` Table 33; `C_SMPS2 = 470 nF` sets `Cout`).
2. `D_RF` `(35.950, 28.500)` — Optional `SOD-523` (`ESD9B5.0ST5G`, `0.5 pF`) RF ESD clamp on `/SMA_C`.
3. `J1` `(34.500, 35.240)` — Optional `Molex 73251-1153` edge-launch SMA jack (hand-soldered on bench VNA units only).
4. `J2` `(9.900, 36.150)` — `1×2` `2.00 mm` battery PTH solder pads (`Pad 1` Square `(10.900, 36.150)` = `GND`, `Pad 2` Round `(8.900, 36.150)` = `+VBAT_RAW`; soldered from `B.Cu` during box-build).
5. `J3` `(2.400, 20.500)` — `1×2` `BOOT` bare-`ENIG` PTH pogo-pin pads.
6. `J4` `(8.500, 3.000)` — `1×5` `SWD` bare-`ENIG` PTH pogo-pin pads (`Pad 1 VAPP_SENSE` $\to$ `Pad 5 NRST`).
7. `J5` `(22.540, 3.000)` — `1×4` `UART` bare-`ENIG` PTH pogo-pin pads (`Pad 1 VUART_ISO` $\to$ `Pad 4 GND`).
8. `R_DIV1` `(33.480, 21.120)` — Optional `0402` conducted PA test diverter at `/BR_P` (`DNP` for normal operation).
9. `R_DIV2` `(35.520, 21.120)` — Optional `0402` 1-port VNA diverter at `/BR_Q` (`DNP` for normal operation).
10. `R_VUART` `(20.600, 5.550)` — Optional `0402` `J5.1` `VUART` jumper (`DNP` so external USB-UART adapters cannot back-feed `3V3`).
