# Component & Regulatory Reference Register (`Rev E.5`)

**Author:** Stephen K. Boachie

Schematic pin assignments, PCB land patterns, stencil paste reductions, MCU register offsets, supply current budgets, and EU868 regulatory limits in `ISAC_868_KiCad9` (`Rev E.5`) are derived from the primary vendor documents listed below. Core silicon and SiP datasheets are archived locally in [`docs/datasheet/`](datasheet/) with SHA-256 checksums.

---

## 1. Locally Archived Silicon & SiP Datasheets (`docs/datasheet/`)

| Component | Document Title & Revision | Local Path | SHA-256 Checksum | Key Sections Used |
| :--- | :--- | :--- | :--- | :--- |
| `U1` (`RAK3172LP-SIP-8-SM-NI`, SKU `305049`) | *RAK3172-SiP / RAK3172LP-SiP WisDuo LPWAN SiP Datasheet* (`13` pp.) | [`docs/datasheet/RAK3172LP-SiP_Datasheet.pdf`](datasheet/RAK3172LP-SiP_Datasheet.pdf) | `11754c585ad1a53b3aa8f622b774cc2ef93c3470a54bdf8f7b2e01030505b038` | Pin table (pp. 4–7; `PA9` = Pin `50`, `PA8` = Pin `51`), `3.0 V` internal `DIO3` TCXO supply (`0x06`), operating current (`+14 dBm` TX, `2.1 µA` sleep, pp. 8–9), Figure 4 LGA-73 land pattern (`0.0000 mm` pad match in [`u1_footprint_verification.md`](reports/u1_footprint_verification.md), p. 10) |
| `U1` MCU+Radio (`STM32WLE5JC`) | *STM32WLE5xx / STM32WLE4xx Multiprotocol LPWAN 32-bit MCU Datasheet* — ST `DS13105 Rev 12` (`149` pp.) | [`docs/datasheet/DS_stm32wle5c8.pdf`](datasheet/DS_stm32wle5c8.pdf) | `5fe4da96db4768bb74ffb6d02a40bc4db9ce8685e7485f8eab4643b333fcaa33` | §3.9.1 SMPS sequencing note (p. 27), Table 18 ADC channel map (`PA15=ADC_IN11`, `PB4=ADC_IN3`, `ADC_IN12=TSEN`, `ADC_IN13=VREFINT`), Table 29 TX current (`23.5 mA` SMPS, p. 71), Table 33 SMPS `15 µH` inductor & `Cout = 470 nF` (p. 75), §5.3.23 `TS_CAL1/TS_CAL2` |
| `U1` Peripherals (`STM32WLE5JC`) | *STM32WLx5xx Reference Manual* — ST `RM0453 Rev 6` (`1438` pp.) | [`docs/datasheet/ST reference manual (RM0453).pdf`](datasheet/ST%20reference%20manual%20(RM0453).pdf) | `3ca429d1c2050527dc54c506ed8c45c800863915b13ff65c57a81361e9c3b2a5` | §3.4.2–3.4.3 Option bytes (`RDP`, `BOR_LEV`, `IWDG_STOP`) & 72-bit Flash `ECCD` `NMI` handling (`FLASH_ECCR`, pp. 110–114), §5.10.57 `SUBGHZ_SMPSC0R.CLKDE` (`0x0916`, p. 223), §6.6.8 `PWR_CR5.SMPSEN` (`0x5800041C`, p. 271), §16.4.8 `ADC_SMPR` |

---

## 2. Active, Passive, Connector & Regulatory References

| Designator(s) | MPN & Manufacturer | Vendor Datasheet / Standard | Verified Parameters |
| :--- | :--- | :--- | :--- |
| `U2` | `LT5538IDD#TRPBF` (Analog Devices) | *LT5538 40 MHz to 3.8 GHz RF Power Detector*, Rev. A (`5538fa`) | 8 mm T&R `3 × 3 mm` `DFN-8-1EP` (`0.50 mm` pitch, `V_CC = 3.0–5.25 V` via `Q1`), Table 1 `IN+` impedance (`63.48 - j120.35 Ω` $\equiv$ `291.65 Ω || 1.194 pF` at `866.5 MHz`), `19.0 mV/dB` slope, `-88.8 dBm` intercept at `25 °C` |
| `U3` | `TPS7A0233DBVR` (Texas Instruments) | *TPS7A02 Nanopower IQ (25 nA), 200-mA LDO*, `SBVS345H` | `SOT-23-5` (`1=IN, 2=GND, 3=EN, 4=NC, 5=OUT`), `I_Q = 25 nA` typ, `V_DO = 36.2 mV` typ at `24.1 mA`, `0.47–22 µF` effective `C_OUT` (`C_OUT_eff ≈ 13.8 µF` derated) |
| `Q1` | `TPS22919DCKR` (Texas Instruments) | *TPS22919 1.6-V to 5.5-V, 1.5-A Load Switch*, `SLVSF86A` | `SC-70-6` (`1=VIN -> VBAT, 2=GND, 3=ON -> PA8, 4=NC, 5=QOD, 6=VOUT -> 3V3_DET`), `C_Q1 = 100 nF`, `V_IH = 1.0 V`, `t_ON ≤ 1.60 ms` (`3.00 ms` firmware guard), `250 Ω` `QOD` discharge |
| `Q2` | `NX3008CBKS,115` (Nexperia) | *NX3008CBKS TrenchMOS Complementary N/P-Channel MOSFET*, Rev. 2 | `SOT-363`: N-ch (`1=S1, 2=G1 -> PA9 BAT_MON_EN, 6=D1`), P-ch (`4=S2, 5=G2, 3=D2`), `R_BPD = 100 kΩ`, `I_DSS < 100 nA`, high-side battery sense switch |
| `Q3` | `AO3401A` (Alpha & Omega) | *AO3401A 30V P-Channel MOSFET*, Rev. 10 | `SOT-23-3` (`1=Gate -> GND, 2=Source -> VBAT, 3=Drain -> VBAT_RAW`), `R_DS(on) <= 85 mΩ` at `V_GS = -2.5 V` |
| `L_SMPS` | `LQH2MCN150K02L` (Murata) | *Murata LQH2MCN_02 Wirewound Ferrite Power Inductors* (`LCSC C86089`) | `0805` (`2.0 × 1.6 × 0.9 mm`), `15 µH ±10%` wirewound DC-DC inductor, `Isat = 300 mA`, `R_DC = 1.1 Ω`, `SRF = 30 MHz` |
| `D_VBAT, D_RST, D_3V3` | `PESD5V0S1BA,115` (Nexperia) | *PESD5V0S1BA Bidirectional ESD Protection Diode*, Rev. 4 | `SOD-323`, `V_RWM = 5.0 V`, `I_RM = 5 nA` typ, `IEC 61000-4-2 ±30 kV` contact |
| `D_SWD, D_UART` | `PESD5V0U2BT,215` (Nexperia) | *PESD5V0U2BT Low-Capacitance Double ESD Diode*, Rev. 3 | `SOT-23` (`1=I/O1, 2=I/O2, 3=GND`), `C_d = 2.9 pF` typ, `V_RWM = 5.0 V`, `IEC 61000-4-2 ±10 kV` |
| `D_RF` (`DNP`) | `ESD9B5.0ST5G` (onsemi) | *ESD9B5.0ST5G Micro-Packaged RF ESD Diode*, Rev. 12 | `SOD-523`, `C_j = 0.50 pF` typ at `1 MHz`, `V_RWM = 5.0 V` (`DNP` on `SMA_C` for optional VNA port protection) |
| `C_BULK1/2`, `C_SMPS1/2`, `C_IN1` | `GRM21BR61A476ME15L`, `GRM155R61A475MEAAD`, `GRM155R71C474KA01D`, `GRM188R61E106MA73D` (Murata) | *Murata SimSurfing Characteristic Curves* | `C_SMPS1 = 4.7 µF` (`VDDSMPS`), `C_SMPS2 = 470 nF ±10% 16V X7R` (`VFBSMPS` per `DS13105` Table 33); `C_SMPS3 = DNP` |
| `J2` & `J1` (`DNP`) | `B2B-PH-K-S` (JST) & `73251-1153` (Molex) | *JST PH Spec (`1=GND, 2=VBAT_RAW`)*; *Molex `SD-73251-115` (`1.60 mm` Edge SMA)* | `J1..J5 = DNP` on the sealed SMD build (`J2` bare-`ENIG` PTH pads soldered from `B.Cu`; bench hand-solder coordinates in `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv`) |
| EU868 SRD & LoRaWAN | ETSI `EN 300 220-2 V3.2.1`, CEPT `ERC/REC 70-03` Annex 1, `LoRaWAN L2 1.0.3` + `RP002-1.0.4` | ETSI / ECO / LoRa Alliance Specifications | Sub-band `g1` (`863–865 MHz`, `0.1%` duty $\le 3.6\text{ s/h}$), `g` (`865–868 MHz`, `1%` duty); Tier-3 Join backoff `17,281 s` (`< 8.2 s / 24 h`); lab EMC pre-scan tracked in [`OPEN_ITEMS.md`](OPEN_ITEMS.md) (`O-03`) |
