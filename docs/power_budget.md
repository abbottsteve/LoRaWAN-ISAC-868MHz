# Power Budget, Rail Isolation & SAR ADC Timing Analysis (`Rev E.5`)

**Author:** Stephen K. Boachie  
**Hardware Revision:** `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)

| Subsystem | `Rev E.5` Design Choice | Reference |
| :--- | :--- | :--- |
| Radio / TCXO & Buck Supply | 3.0 V `DIO3` TCXO (`0x06` per `RAK3172LP-SiP` spec); `L_SMPS` = `LQH2MCN150K02L` (15 µH wirewound, $I_{\text{sat}} = 300\text{ mA}$); +4 dBm CW sensing vs. +14 dBm LoRaWAN TX | [`docs/datasheet/`](datasheet/) & [`docs/SOURCES.md`](SOURCES.md) |
| Detector Power Path | `Q1` (`TPS22919DCKR`) fed directly from `VBAT` (3.0–4.35 V), offloading `LT5538`'s 28 mA pulse from the 3.3 V `U3` LDO (8.3× current margin on `U3`) | TI `SLVSF86` & ADI `LT5538` Rev A |
| Battery Input (`J2` = DNP) | 1S Li-ion/LiPo (3.00–4.20 V, 302535 pouch) or 3.6 V $\text{Li-SOCl}_2$ (`ER14335M`), 24–26 AWG silicone leads soldered from `B.Cu` to `J2` (Pad 1 Square = `GND`, Pad 2 Round = `+VBAT_RAW`, 4.35 V DC max) | `DOWSIL 3145` RTV strain relief |
| Reverse-Polarity Stage | `Q3` (`AO3401A` SOT-23 P-MOSFET ideal diode: Drain=`VBAT_RAW`, Source=`VBAT`, Gate=`GND`, $R_{DS(\text{on})} \le 85\text{ m}\Omega$ at $V_{GS}=-2.5\text{ V}$) | 3.0–5.5 mV forward drop under TX pulse |
| Debug Pogo Isolation | `J3, J4, J5` = DNP; `R_VAPP` = 1.0 kΩ (`3V3 -> J4.1`), `R_VUART` = DNP (`J5.1` isolated), `R_BHI` = 10 kΩ (`3V3 -> J3.2`), `D_3V3` (`PESD5V0S1BA,115`) | Prevents bench 3.3 V debuggers from back-charging `VBAT` |

---

## 1. Split-Rail Power Topology

```text
J2 = DNP (Bottom-Side Soldered 1S LiPo / 3.6 V Li-SOCl2 Leads: Pad 1 Square = GND, Pad 2 Round = /VBAT_RAW [3.00–4.20 V; 4.35 V DC MAX])
 ├── D_VBAT (PESD5V0S1BA,115, V_RWM = 5.0 V, I_RM = 5 nA typ @ 4.2 V)  [Bidirectional ESD Clamp]
 └── Q3 (AO3401A PMOS Ideal Diode: Drain=VBAT_RAW, Source=VBAT, Gate=GND, R_DS(on) <= 85 mΩ)
      ├── TP3 (/VBAT) + C_BULK1 + C_BULK2 (2 × 47 µF 10V X5R 0805) + C_IN1 (10 µF) + C_IN2 (100 nF)
      ├── Q1 (TPS22919DCKR + C_Q1=100nF, PA8 DET_EN + R_PD=100k, 3.0 ms settle) -> TP2 (3V3_DET = VBAT_SW) -> U2 (LT5538IDD#TRPBF, 3.0–5.25 V rated)
      ├── Q2 (NX3008CBKS Gated VBAT Switch, PA9 BAT_MON_EN + R_BPD=100k + R_BG=470k) -> R_B1/R_B2 (4.7k/4.7k) -> PB4 (ADC_IN3, 150 µs window)
      └── U3 (TPS7A0233DBVR 3.30 V Nanopower LDO, I_OUT = 200 mA, I_Q = 25 nA typ, Peak Load = 24.1 mA, Derated C_OUT_eff ≈ 13.8 µF <= 22 µF Max)
           ├── TP1 (3V3) + D_3V3 (PESD5V0S1BA,115)
           ├── R_VAPP (1.0 kΩ) -> J4.1 (Pogo)  |  R_VUART (DNP) -x- J5.1  |  R_BHI (10 kΩ) -> J3.2
           └── U1 (RAK3172LP-SiP: VDD1/VDD2/VBAT/VDDSMPS + 15 µH Wirewound L_SMPS + 3.0 V DIO3 TCXO [0x06] + FB_PA/FB_RF/FB_VDDA)
```

---

## 2. Active & Sleep Load Currents (+4 dBm CW / +14 dBm LoRaWAN)

| Operating State | Supply Rail | Typical Current | Max Current | Datasheet Basis |
| :--- | :---: | :---: | :---: | :--- |
| `U1` CW Sensing +4 dBm (`RFO_LP`, SMPS ON, 1.17 ms/tone) | `3V3` (`VDDSMPS` + `VDDPA`) | 14.2 mA | 16.5 mA | ST `DS13105 Rev 12` Table 29, p. 71 (+4 dBm keeps `LT5538` 12.4 dB below compression) |
| `U1` LoRaWAN TX +14 dBm (`RFO_LP`, SMPS ON, 3.0 V TCXO) | `3V3` (`VDDSMPS` + `VDDPA`) | 24.1 mA | 26.5 mA (48.0 mA LDO) | ST `DS13105 Rev 12` Table 29, p. 71 (`Q1 = 0` during LoRaWAN TX) |
| `U1` LoRa RX (BW = 125 kHz, 3.0 V TCXO) | `3V3` | 6.1 mA | 11.5 mA | ST `DS13105 Rev 12` Table 28, p. 70 |
| `U1` MCU Run (4 MHz MSI + 2 MHz ADC + `VREFINT` + `TSEN`) | `3V3` + `VDDA` | 1.4 mA | 2.2 mA | ST `DS13105 Rev 12` Table 25 & Table 78 |
| `U2` (`LT5538IDD#TRPBF`) Active Detector (`PA8=1`, 3.0 ms settle) | `VBAT -> Q1` (`3V3_DET`) | 28.0 mA (@ 3.7 V) | 32.0 mA | ADI `LT5538` Rev A (3.0–5.25 V supply; bypasses `U3`) |
| Gated `VBAT` Divider (`PA9=1` for 150 µs window) | `VBAT` (via `Q2`) | 0.40 mA (@ 3.7 V) | 0.45 mA (@ 4.2 V) | 0.06 µC per sample; off during CW sweep and `STOP2` |
| Peak Load on `U3` (`TPS7A0233DBVR` 3.3 V 200 mA LDO) | `VBAT -> U3` | 15.6 mA (CW) / 24.1 mA (LoRa TX) | 26.5 mA | 8.3× nominal margin below 200 mA; $V_{\text{DO}} = 36.2\text{ mV}$ at 24.1 mA, preserving 3.0 V TCXO regulation down to 3.10 V cell voltage |
| Predicted `STOP2` Board Current (`BOR3`, `PA2/PA3` High-Z) | `VBAT` (`U3 + Q1 + Q2`) | 2.85–3.25 µA *(to verify in `O-04`)* | 4.45 µA | Sum of `D_VBAT` (5 nA), `Q1` off-state (10 nA typ), `U3` (25 nA typ), and `U1` `STOP2 + BOR3` |

---

## 3. `Q1` (`TPS22919DCKR`) Turn-On Timing vs. 3.0 ms Firmware Guard

From TI `TPS22919` (`SLVSF86B` §6.6, $V_{\text{IN}} = 3.0\text{–}4.2\text{ V}$, $C_L = 1.1\,\mu\text{F}$ across `C_DET2 + C_DET1`, `C_Q1` = 100 nF input bypass):
- Typical turn-on delay plus rise time is $t_d + t_r = 520\,\mu\text{s} + 540\,\mu\text{s} = 1.06\text{ ms}$ (1.60 ms max over temperature), with $V_{\text{IH}} = 1.0\text{ V}$ driven cleanly by 3.3 V `PA8` (`DET_EN`).
- Because `LT5538IDD#TRPBF` operates directly across $V_{\text{CC}} = 3.0\text{–}5.25\text{ V}$ with PSRR $> 45\text{ dB}$, feeding `Q1.1` from `VBAT` avoids LDO dropout during cold battery pulses while holding `3V3` near 3.26 V for `RAK3172LP-SiP`'s internal 3.0 V `DIO3` TCXO regulator (`0x06`).

---

## 4. `STM32WLE5JC` Dual-`SMPR` ADC Timing & LDO Output Capacitance

1. **`U1` Pin 8 (`PA15 / ADC_IN11`, `/DET_ADC`, `TP4`):** Routed 4.04 mm clear of `L_SMPS`. The post-detector RC filter ($R_{\text{LPF}} = 1.00\text{ k}\Omega$, $C_{\text{LPF}} = 100\text{ nF}$, $\tau = 100\,\mu\text{s}$) settles to 99.6% within the 550 µs ($5.5\tau$) per-tone dwell. Sampled using `SMP1 = 12.5` ADC cycles (6.25 µs at 2 MHz `PCLK/2`), completing 16× hardware oversampling in 200 µs.
2. **`ADC_IN13` (`VREFINT`) & `ADC_IN12` (`TSEN` Die Temperature):** Sampled using `SMP2 = 39.5` ADC cycles (19.75 µs $\ge$ 12 µs `DS13105` minimum) for per-tone ratiometric `VDDA` tracking and 0.015 dB/°C residual thermal slope compensation (`Tilt` and `Notch` cancel common-mode intercept drift directly).
3. **`U3` (`TPS7A0233DBVR`) Effective Output Capacitance (`SBVS345H` §6.3, 0.47–22 µF Window):** Accounting for 3.30 V DC-bias derating on Murata `GRM` X5R/X7R MLCCs across `3V3` and the `BLM15AG121SN1D` ferrite branches (18.7 µF nominal), total derated effective capacitance is $C_{\text{OUT,eff}} \approx 13.8\,\mu\text{F}$, leaving 37% margin below TI's 22 µF stability ceiling.
4. **`U1` Pin 50 (`PA9 / BAT_MON_EN`) $\to$ Pin 15 (`PB4 / ADC_IN3`):** `ISAC_HAL_ReadBatteryMv()` asserts `PA9 = 1` for 150 µs ($> 7 \times 21.2\,\mu\text{s}$ RC time constants on $R_{\text{Th}} = 2.35\text{ k}\Omega, C_{\text{BAT}} = 1.0\text{ nF}$), acquires 16× oversampled `PB4` and `VREFINT`, and immediately returns `PA9` low (`R_BPD` = 100 kΩ).
