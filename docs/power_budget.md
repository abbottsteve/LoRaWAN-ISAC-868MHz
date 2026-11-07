# Power Budget, Battery Chemistry, Header Isolation & SAR ADC Impedance Specification (`Rev E.5`)

| Control Item | Verified `Rev E.5` Engineering Specification | Primary Datasheet Evidence |
| :--- | :--- | :--- |
| **Design Protections Verified** | **`3.0 V` `DIO3` TCXO (`0x06`, `RAK3172LP-SiP` Mandated)**, **`Q1`/`LT5538` Fed Directly from `VBAT` (`0 mV` LDO Dropout, `8.30×` `U3` Margin)**, **`L_SMPS = LQH2MCN150K02L` (`Isat = 300 mA` Wirewound)**, **Split `PA8` (`DET_EN`) / `PA9` (`BAT_MON_EN`)**, **`J2 = DNP` Direct Bottom-Soldered Battery Pads (`Pad 1 Square=BLACK GND, Pad 2 Round=RED +VBAT_RAW`)**, **`PA2/PA3` Analog High-Z (`ISAC_DEBUG_UART=0`)**, **`+4 dBm` CW Sensing vs `+14 dBm` LoRaWAN TX** | Archived PDFs in [`docs/datasheet/`](datasheet/) & [`docs/SOURCES.md`](SOURCES.md) |
| **Primary Battery Chemistry** | **1S Rechargeable Li-ion / LiPo Cell (`3.7 V` nom, `3.00–4.20 V` operating window; `302535` `250–300 mAh` pouch cell in Option A tray or `ER14335M` `3.6 V` `Li-SOCl2` in Option B bay, `24–26 AWG` silicone leads soldered directly from `B.Cu` to `J2` `Pad 1=GND, Pad 2=+VBAT_RAW` with `DOWSIL 3145` RTV strain relief)** | `J2` operational DC ceiling **`4.35 V DC MAX` (`NO 5V PSU` — `PA9` `BAT_MON_EN` via `R_B1/R_B2` limits `PB4` `ADC_IN3` `≤ 2.175 V`; `D_VBAT` `5.0 V` TVS clamp)** |
| **Reverse-Polarity Stage** | **`Q3` (`Alpha & Omega AO3401A`, `SOT-23` P-MOSFET Ideal Diode: Drain=`VBAT_RAW`, Source=`VBAT`, Gate tied directly to `GND`, $R_{DS(\text{on})} \le 85\text{ m\Omega}$ @ $V_{GS}=-2.5\text{ V}$)** | Pulse forward drop **`3.0–5.5 mV`** (`0` gate resistors on `Q3`; `R_BG = 470 kΩ` pulls up `Q2` PMOS gate!) |
| **Header Back-Feed Protection** | **`J3, J4, J5 = DNP`** (bare-`ENIG` pogo pads inside sealed housing), **`R_VAPP = 1.0 kΩ`** (`3V3 → J4.1`), **`R_VUART = DNP 0 Ω`** (`J5.1` isolated), **`R_BHI = 10 kΩ`** (`3V3 → J3.2`), **`D_3V3` (`PESD5V0S1BA,115`)** | Eliminates external `3.3 V` FTDI / ST-LINK reverse-charging of `J2` LiPo via `U3` body diode + `Q3` |

---

## 1. `Rev E.5` Zero-Dropout Power Rail & Split-GPIO Protection Topology

```text
J2 = DNP (Direct Bottom-Side Soldered 1S LiPo / 3.6V Li-SOCl2 Leads: Pad 1 Square = BLACK GND, Pad 2 Round = RED /VBAT_RAW [3.00–4.20 V; 4.35 V DC MAX — NO 5V PSU])
 ├── D_VBAT (PESD5V0S1BA,115, V_RWM = 5.0 V, I_RM = 5 nA typ @ 4.2 V)  [Bidirectional ESD Clamp]
 └── Q3 (AO3401A PMOS Ideal Diode: Drain=VBAT_RAW, Source=VBAT, Gate=GND, R_DS(on) <= 85 mΩ)
      ├── TP3 (/VBAT DC Test Point) + C_BULK1 + C_BULK2 (2 × 47 µF 10V X5R 0805) + C_IN1 (10 µF) + C_IN2 (100 nF)
      ├── Q1 (TPS22919DCKR + C_Q1=100nF, PA8 DET_EN + R_PD=100k, 3.0 ms settle) -> TP2 (3V3_DET = VBAT_SW 3.00–4.35 V) -> U2 (LT5538IDD#TRPBF, 3.0–5.25 V rated!)
      ├── Q2 (NX3008CBKS Gated VBAT Switch, PA9 BAT_MON_EN + R_BPD=100k + R_BG=470k) -> R_B1/R_B2 (4.7k/4.7k) -> PB4 (ADC_IN3, 150 µs window)
      └── U3 (TPS7A0233DBVR 3.30 V Nanopower LDO, I_OUT = 200 mA, I_Q = 25 nA typ, Peak Load = 24.1 mA [8.30x Margin!], Total Derated C_OUT_eff ≈ 13.8 µF <= 22 µF Max across 3V3 + FB_VDDA/FB_PA/FB_RF)
           ├── TP1 (3V3) + D_3V3 (PESD5V0S1BA,115)
           ├── R_VAPP (1.0 kΩ) -> J4.1 (Pogo)  |  R_VUART (DNP) -x- J5.1  |  R_BHI (10 kΩ) -> J3.2
           └── U1 (RAK3172LP-SiP: VDD1/VDD2/VBAT/VDDSMPS + 15 µH Wirewound L_SMPS [LQH2MCN150K02L, Isat=300mA] + 3.0 V DIO3 TCXO [0x06] + FB_PA/FB_RF/FB_VDDA)
```

---

## 2. Datasheet-Verified Active & Sleep Load Currents (`+4 dBm` CW / `+14 dBm` LoRaWAN)

| Subsystem & Operating State | Supply Rail | Typical Current | Worst-Case / Max Current | Exact Vendor Document Citation |
| :--- | :---: | :---: | :---: | :--- |
| **`U1` Sub-GHz CW Sensing `+4 dBm` (`RFO_LP`, SMPS ON, `1.17 ms/tone`)** | `3V3` (`VDDSMPS` + `VDDPA`) | **`14.2 mA`** | `16.5 mA` | ST `DS13105 Rev 12` **Table 29, p. 71** (`RFO_LP` stepped down to `+4 dBm` for `+12.40 dB` `LT5538` compression headroom) |
| **`U1` Sub-GHz LoRaWAN TX `+14 dBm` (`RFO_LP`, SMPS ON, `3.0 V` TCXO)** | `3V3` (`VDDSMPS` + `VDDPA`) | **`24.1 mA`** | `26.5 mA` (`48.0 mA` LDO) | ST `DS13105 Rev 12` **Table 29, p. 71** + `RAK3172LP-SiP` `3.0 V` TCXO (`0x06`; `Q1 = 0` during LoRa TX) |
| **`U1` Sub-GHz LoRa RX (`BW = 125 kHz`, `3.0 V` TCXO)** | `3V3` | **`6.1 mA`** (SMPS) | `11.5 mA` | `DS13105 Rev 12` **Table 28, p. 70** |
| **`U1` MCU Run (`4 MHz` MSI + `2 MHz` ADC + `VREFINT` + `TSEN`)** | `3V3` + `VDDA` | **`1.4 mA`** | `2.2 mA` | `DS13105 Rev 12` **Table 25 & Table 78** |
| **`U2` (`LT5538IDD#TRPBF`) Active RF Detector (`PA8=1`, `3.0 ms` settle)** | **`VBAT -> Q1`** (`3V3_DET`) | **`28.0 mA`** (@ `3.7 V`) | `32.0 mA` | Analog Devices `LT5538` Rev A (`3.0–5.25 V` supply rating; **bypasses `U3` LDO completely!**) |
| **Gated `VBAT` Divider (`PA9=1` for `150 µs` only)** | `VBAT` (via `Q2`) | **`0.40 mA`** (@ `3.7 V`) | `0.45 mA` (@ `4.2 V`) | Split onto `PA9` (`BAT_MON_EN`): active for `150 µs` (`0.06 µC`), **`0 nA` during CW sweep & `STOP2`!** |
| **Peak Load on `U3` (`TPS7A0233DBVR` `3.3 V` `200 mA` LDO)** | `VBAT -> U3` | **`15.6 mA`** (CW) / **`24.1 mA`** (LoRa TX) | **`26.5 mA`** (SMPS ON) | **`8.30×` nominal (`7.55×` max) margin** below `200 mA` `U3` rating; dropout `V_DO = 36.2 mV` @ `24.1 mA`, keeping `3.0 V` `DIO3` TCXO in full regulation down to `V_cell = 3.10 V` at `-20 °C`! |
| **Total Predicted `STOP2` Board Current (`BOR3`, `PA2/PA3` High-Z)** | `VBAT` (`U3 + Q1 + Q2`) | **`2.85 µA` – `3.25 µA`** *(unmeasured — Gate `O-04`)* | **`4.45 µA`** | Includes `D_VBAT` (`5 nA`) + `Q1` `TPS22919` off-state (`10 nA` typ) + `U3` (`25 nA`) + `U1` `STOP2 + BOR3` |

---

## 3. `Q1` (`TPS22919DCKR` on `VBAT`) Slew-Rate Turn-On vs. `3.0 ms` Firmware Settle

Per TI `TPS22919` datasheet (`SLVSF86B` §6.6, `VIN = 3.0–4.2 V VBAT, C_L = 1.1 µF` `C_DET2 + C_DET1`, `C_Q1 = 100 nF` input bypass):
* Typical `t_d + t_r = 520 µs + 540 µs = 1,060 µs` (`1.06 ms`); worst-case cold `t_ON(max) = 1,600 µs` (`1.60 ms`), and `V_IH = 1.0 V` is cleanly driven by `3.3 V` `PA8` (`DET_EN`).
* Because `LT5538IDD#TRPBF` is specified for `V_CC = 3.0 V to 5.25 V` with `PSRR > 45 dB` (`ΔV_OUT < 0.2 mV` across `3.0–4.2 V`), feeding `Q1.1` directly from `VBAT` eliminates cold-pulse LDO dropout on `LT5538` AND preserves `3.26 V` on `3V3` so `RAK3172LP-SiP`'s internal `3.0 V` `DIO3` LDO (`0x06`) never browns out!

---

## 4. `STM32WLE5JC` Dual-`SMPR` 12-Bit SAR ADC Timing & Independent `PA9` Battery Sense

1. **`U1` Pin `8` (`PA15`):** Confirmed **`ADC_IN11`** (`/DET_ADC`, `TP4`), routed with `4.04 mm ≥ 4.00 mm` separation from `L_SMPS`. $R_{\text{LPF}} = 1.00\text{ k\Omega}$, `C_LPF = 100 nF` ($\tau = 100\,\mu\text{s}$; `550 µs = 5.5 τ` dwell per tone $\to$ `99.6%` settled). Sampled with **`SMP1 = 12.5` ADC cycles (`6.25 µs` S&H at `2 MHz` `PCLK/2`)**, completing `16×` oversampling in **`200 µs`** (`1.17 ms` total CW TX per tone).
2. **`ADC_IN13` (`VREFINT`) & `ADC_IN12` (`TSEN` Internal Die Temp):** Sampled via **`SMP2 = 39.5` ADC cycles (`19.75 µs ≥ 12 µs` `DS13105` minimum)** for exact `VDDA` ratiometric scaling and small `0.015 dB/°C` combined `SX1262 RFO_LP + LT5538` thermal residual correction (ADI `LT5538` Rev A log conformance is natively temperature-compensated within `< ±0.5 dB` across `-40..+85 °C` at `880 MHz`, and differential `Tilt`/`Notch` cancel intercept drift to `0.00 dB`).
3. **`U3` (`TPS7A0233DBVR`) Total Output Capacitance Stability Margin (`SBVS345H` §6.3 `0.47–22 µF` Effective `C_OUT`):** Accounting for `3.30 V` DC bias derating on Murata `GRM` X5R/X7R MLCCs across `3V3` (`C_OUT1=1µF`, `C_OUT2=100nF`, `C_U1A=4.7µF`, `C_U1B/C=2×100nF`, `C_VBAT=1µF`, `C_SMPS1=4.7µF` via `0 Ω` `FB_SMPS`) plus `BLM15AG121SN1D` (`R_DC = 0.25 Ω` at LDO loop crossover `< 100 kHz`) branches (`C_VDDA1=4.7µF`, `C_VDDA2=1µF`, `C_VREF=100nF`, `C_PAV=1µF`, `C_RFV=1µF` = `18.7 µF` nominal), total DC-bias-derated effective capacitance at `3.30 V` is **`C_OUT_eff ≈ 13.8 µF`**, providing a clean **`37%` phase-margin safety cushion** below TI's `22 µF` recommended ceiling.
4. **`U1` Pin `50` (`PA9`, `BAT_MON_EN`) -> Pin `15` (`PB4`, `ADC_IN3`):** `ISAC_HAL_ReadBatteryMv()` asserts `PA9 = 1` independently for **`150 µs`** (`> 7 × 21.23 µs` `12-bit` RC settle on `R_Th = 2.35 kΩ, C_BAT = 1.0 nF`), samples `16×` oversampled `PB4` + `VREFINT`, and immediately de-asserts `PA9 = 0` (`R_BPD = 100 kΩ` pulldown).
