# ISAC_868 `Rev E.5` — First-Article (`5–10` Boards) Prototype Bring-Up Plan, Test-Point Map & Gate 8 Volume Hold

**Document ID:** `ISAC-SOP-BRINGUP-E5`  
**Date:** `2026-11-05`  
**Applicable Hardware:** `ISAC_868_KiCad9` **`Rev E.5`** (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Status:** **PRE-BENCH TEMPLATE & MANDATORY GATE 8 VOLUME RELEASE HOLD** *(All measured columns intentionally blank pending physical delivery of the 5–10 unit PCBWay pilot lot — Open Items `O-01`..`O-06`)*.

---

## 1. Required Test Equipment & Clean DC Test-Point Map

### 1.1 Instrument List

| Instrument | Minimum Specification | Purpose |
| :--- | :--- | :--- |
| **Bench Source-Measure / PSU** | `0–4.350 V` (`NO 5V PSU` on `J2`!), `0–500 mA` current limit, programmable output resistance (`0–1 Ω`) | Safe first power-up (`4.35 V DC MAX` operational ceiling), standard `1=GND, 2=VBAT_RAW` & reverse-polarity check, `3.00 V` LiPo cutoff & droop sweep |
| **Source-Measure Current Profiler** | Joulescope `JS220` or Nordic `PPK2` (`10 nA`–`1 A` dynamic range, `≥ 100 kS/s`) | `STOP2` sleep current (`O-04`), `3.0 ms` `VBAT`-fed `Q1` settle + `PA9` `150 µs` battery sense + `< 1.2 ms/tone` `+4 dBm` CW charge, `+14 dBm` LoRaWAN TX |
| **Digital Storage Oscilloscope** | `≥ 200 MHz` BW, `2×` passive `10×` probes + `1×` low-inductance spring-ground probe | `VBAT / 3V3 / 3V3_DET / DET_ADC` waveform verification (`3.0 V` TCXO headroom on `3V3`, `3.0 ms` `Q1` rise, `550 µs` tone dwell) |
| **Vector Network Analyzer (VNA)** | `100 MHz – 3 GHz` (`NanoVNA-V2 Plus4`, `LibreVNA`, or Keysight/R&S), SMA `SOL` cal kit | 1-port `S11` of `AE1` + elliptic pi-filter (`J1` + `R_DIV2`), bare/enclosed/LiPo/ice/water (`O-02`) |
| **Spectrum Analyzer + `20 dB` Attenuator** | `9 kHz – 6 GHz` (`RBW 100 kHz`), calibrated SMA cable | Conducted `+14 dBm` LoRa / `+4 dBm` CW fundamental & `2f0 / 3f0` harmonic spur verification (`O-02`) |
| **SWD Debugger + Pogo Fixture** | ST-LINK/V3MINIE or J-Link (`5`-pin `2.54 mm` pogo clip onto `J4` bare-`ENIG` PTH rings) | `tools/production_flash.sh`, 2-point cal (`--cal-dry-mv` + `--cal-ref-cdb`) + `provisioning_vault/` ledger, `g_selftest_report` readback (`O-05`) |

### 1.2 Clean DC Test-Point Reference (`TP1..TP5` — Zero RF Bridge Test Points!)

To eliminate `1.54 pF` parasitic bridge loading, **zero test pads exist on `/BR_P`, `/BR_Q`, `/BR_S`, or `/BR_O`**. All `5` `Ø1.00 mm` bare-`ENIG` test pads sit strictly on DC / low-frequency rails:

| Test Pad | Schematic Net | Gerber `(X_gbr, Y_gbr)` [mm] | Nominal Expected Value / Waveform |
| :---: | :--- | :---: | :--- |
| **`TP1`** | `3V3` | `(28.200, 28.750)` | `3.300 V ± 33 mV` (`U3` `TPS7A0233DBVR` always-on output; `≤ 24.1 mA` peak load = `8.30×` margin) |
| **`TP2`** | `3V3_DET` | `(42.100, 3.800)` | `0.000 V` in `STOP2` (`Q1` `QOD` active); rises to `VBAT` (`3.0–4.35 V` zero-dropout supply to `LT5538`) within `1.6 ms` (`3.0 ms` guard) when `PA8 = 1` |
| **`TP3`** | `VBAT` | `(15.350, 30.200)` | `V_J2 - (< 6 mV)` forward (`Q3` `AO3401A` ideal diode); `0.000 V` if `J2` reversed (`-4.20 V`) |
| **`TP4`** | `/DET_ADC` | `(45.300, 4.200)` | Filtered `LT5538IDD#TRPBF` analog log output (`0.76 V` dry-air null @ `866.5 MHz` $\to$ `1.14 V` glaze ice @ `+4 dBm` CW) |
| **`TP5`** | `GND` | `(31.200, 28.750)` | Low-inductance DMM negative & oscilloscope spring-clip ground reference |

---

## 2. Step-by-Step Bring-Up Sequence (`5–10` Pilot Boards)

### Phase A — Unpowered Visual, X-Ray & Impedance Inspection (Before Applying Power)
1. **Incoming Visual & Lot Serialization:** Record unit serial (`SN01..SN10`) and verify `B.SilkS` traceability box (`UNIT S/N` & `DEVEUI` at `X_gbr = 12.5..36.7 mm`, outside `X_gbr ≥ 50 mm` RF aperture), `+`/`-` polarity silkscreen on both `F.SilkS` and `B.SilkS` (`J2:1=GND 2=+VBAT 4.35V`), and `J4: SWD (DNP)` / `J5: UART (DNP)` pogo legends on `B.SilkS`. Inspect `U1` (`LGA-73`, `56.3%` GND paste X-ray voiding `< 25%`), `U2` (`LT5538IDD#TRPBF` `DFN-8-1EP` `50%` EP voiding `< 25%`), `L_SMPS` (`LQH2MCN150K02L` wirewound), `Q1/Q2` (`SOT-363`), `Q3` (`SOT-23`), and `J2` bare-`ENIG` PTH rings (`Pad 1` Square Right = `GND`, `Pad 2` Round Left = `/VBAT_RAW`, `4.35 V DC MAX` — **NEVER apply a `5.0 V` bench supply**). Confirm `C_SMPS3, D_RF, J1, J2, J3, J4, J5, R_DIV1, R_DIV2, R_VUART` (`10` parts) are **unpopulated (`DNP`)** (`67` populated pure-SMD parts, `0` THT parts), `C_M1=3.6p, L_M1=8.2n, C_MZ=0.5p, C_M2=4.3p` are populated, and the bare-`ENIG` `AE1` window (`X_gbr = [73.40..87.80], Y_gbr = [6.65..20.80] mm`) has zero LPI mask ridge or silkscreen ink.
2. **DMM Rail-to-GND Resistance Check (`TP5 = GND`):**
   - `J2.2` (`/VBAT_RAW`) to `TP5` (`J2.1 = GND`): expect `> 1 MΩ` (`Q3` drain-to-body high impedance).
   - `TP3` (`VBAT`) to `TP5`: expect `> 100 kΩ` (`Q1, Q2` off, `U3` nanopower input).
   - `TP1` (`3V3`) to `TP5`: expect `> 50 kΩ` (charging `C_OUT1/C_U1A`).
   - `TP2` (`3V3_DET`) to `TP5`: expect `≈ 200 Ω–10 kΩ` (`Q1` `TPS22919` `QOD` bleed resistor, rising `> 100 kΩ` when off).

### Phase B — Safe Rail Bring-Up, Reverse-Polarity, Back-Feed Protection & `STOP2` Sleep (`O-04`)
3. **Reverse-Polarity (`Q3` `AO3401A`) & Header Isolation Check:**
   - Apply `-4.20 V` (`10 mA` limit) on `J2.2` relative to `J2.1`: verify `I_J2 < 1 µA` and `TP3` (`VBAT`) `= 0.000 V ± 2 mV`.
   - Confirm `J5.1` (`VUART`) measures `> 10 MΩ` (`OL`) to `TP1` (`3V3`) (`R_VUART = DNP`) and `J4.1` (`VAPP_SENSE`) measures `1.00 kΩ ± 1%` (`R_VAPP`) to `TP1`.
4. **Nominal `3.70 V` Power-Up:** Apply `+3.700 V` (`100 mA` limit) to `J2` (`Pin 2 = +, Pin 1 = -`). Verify `TP3` (`VBAT`) `≥ 3.695 V` (`< 5 mV` `Q3` drop) and `TP1` (`3V3`) `= 3.300 V ± 33 mV`.
5. **Per-Unit Key Provisioning, 2-Point Factory Cal & Persistent Vault (`O-05`):** Engage `5`-pin `2.54 mm` SWD pogo fixture onto `J4` (`Pins 1..5`). First flash engineering diagnostic bring-up with `--uncalibrated-bench --no-rdp` to read `g_selftest_report` and `g_last_telemetry` inside the assembled `0.80 mm` `ASA/PETG` enclosure in Dry Air (Point 1 `v1,v2,v3` mV triplet) and with a sintered `2.0 mm` `Al2O3` ceramic reference block placed on the sensing window (Point 2 `level_dbm_x100`, nominal `-2619` c-dBm $\rightarrow$ signed offset `cal_ref_cdb = level_dbm_x100 - (-2619)` in `[-1200..+1200]` `0.01 dB` units, `0` nominal), then seal per-unit credentials + 2-point calibration into `0x0803E000` and `provisioning_vault/provisioned_units_secret.csv` (`--no-rdp` on `SN01..SN03`; `--lock-rdp1` for `RDP1` on `SN04..SN10`):
   ```bash
   ./tools/production_flash.sh \
     --deveui 70B3D57ED0060001 \
     --joineui 70B3D57ED0000001 \
     --cal-dry-mv 818,758,883 \
     --cal-ref-cdb 0 \
     --no-rdp
   ```
6. **Precision `STOP2`, `3.0 V` TCXO & Split `PA8/PA9` Current Profile (`O-04`):** Insert Joulescope `JS220` in series with `J2` at `3.70 V` and `4.20 V`. Verify `STOP2` mean current (`≤ 3.5 µA` `BOR0` / `≤ 5.0 µA` `BOR3` with `PA2/PA3` in Analog High-Z and `3.0 V` `DIO3` TCXO `0x06` off in sleep), oscilloscope-verify `TP2` (`3V3_DET`) reaches full `VBAT` plateau `≥ 1.0 ms` prior to CW tone #1 (`PA8` `3.0 ms` settle while `PA9` pulses independently for `150 µs`), and confirm clean TX inhibit below `3.00 V`.

### Phase C — Conducted RF Power/Harmonics & VNA `S11` Antenna/Enclosure Characterization (`O-02`)
7. **Conducted Fundamental & Harmonic Spectrum (`SN01` Diagnostic Board):** Hand-solder `J1` (`Molex 73251-1153` onto narrowed `1.15 mm` low-parasitic `/SMA_C` launch per `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv`).
   - *PA Output Check:* Depopulate `C_S` (`1.0 pF`) and install `0 Ω` on zero-stub `R_DIV1` (`R_DIV2 = DNP`). Measure `+4.0 ± 1.0 dBm` CW sensing tone and `+14.0 ± 1.0 dBm` LoRaWAN carrier (minus `-0.80 dB` `R1`+CPWG loss).
   - *Post-Elliptic-Filter Harmonic Check:* Restore `C_S = 1.0 pF`, `R_DIV1 = DNP`; connect `50 Ω` spectrum analyzer after `C_M2` and verify conducted `2f0` (`1733 MHz`) and `3f0` (`2599.5 MHz`) are **`≤ -36 dBm`** (`≥ 37 dB` `2f0` and `≥ 60 dB` `3f0` filter attenuation).
8. **1-Port VNA `AE1` + Elliptic Pi-Network Sweep (`SN02..SN05`):** Depopulate `R1` (`8.2 Ω`) and install `0 Ω` on zero-stub `R_DIV2` (connecting `J1` into `C_M1 = 3.6 pF, L_M1 = 8.2 nH || C_MZ = 0.5 pF, C_M2 = 4.3 pF` + `AE1`). Perform 1-port `SOL` calibration at `J1` and sweep `750–960 MHz`:
   - State 1: Enclosed in `Rev E.5` `0.80 mm` self-draining `ASA/PETG` lid (`25 µm` `3M 467MP` window bond) + `302535` LiPo installed (`|S11| ≤ -10.0 dB` across `863–870 MHz`, `f0 = 869.0 ± 5.0 MHz`).
   - State 2 & 3: Apply `2.0 mm` Glaze Ice (`-5 °C` block) and `2.0 mm` Water film on exterior window; verify downward resonance shift (`~ -34.5 MHz` ice, `~ -93.0 MHz` water). Dedicate non-`J1` units `SN06..SN10` for sealed IP65 enclosure verification.

### Phase D — End-to-End 2-Point Calibrated Classification, Adaptive `SF12` & 1,000-Cycle NVM Test (`O-05`)
9. **End-to-End Calibrated 3-Tone Sensing & Adaptive LoRaWAN Uplink:** Solder `26 AWG` silicone battery leads directly from `B.Cu` upward into `J2` (`Pad 1` Square = `BLACK / GND`, `Pad 2` Round = `RED / +VBAT_RAW`, trimming factory LiPo plug **one wire at a time**, anchoring with `DOWSIL 3145` neutral-cure RTV strain relief) and seal `SN06..SN10` inside the uniform-flat-roof (`95.7 × 45.7 × 16.1 mm`, `z_top = +8.50 mm` flat, `-1.44 mm` compliant skirt) `Rev E.5` `ASA/PETG` waterproof enclosure with unbroken `360°` Parker `ORD 5700` silicone/EPDM O-ring (`1.80 × 0.76 mm` groove + `0.16 mm` compliant gap = `0.92 mm` gland, `23.3%` squeeze, `68.3%` fill; `4 × M2.5 × 22 mm` Nylon corner screws + `8 ×` captive EPDM sealing washers, `0` PCB-bay roof slots). Verify `OTAA` Join on ChirpStack/TTN EU868, record `FPort = 10` decoded telemetry across Dry Air (`0`, `SF7`), Mineral Oil / PTFE (`1`, `SF7`), Glaze Ice (`2`, `SF9`), IPA (`3`, `SF12`), and Water (`4`, `SF12`), confirming `Water vs IPA` separation `≥ 0.50 dB`, and verify `863.1 MHz` Sub-Band `g1` airtime caps cleanly at `≤ 3,600 ms/hr` (`0.1%`).
10. **1,000-Cycle Power-Interrupt & `RDP1` Unlock Verification:** Cycle power `1,000` times at randomized `50 ms – 5 s` intervals during join/uplink on `SN06` (`--lock-rdp1` enabled). Confirm `0` `DevNonce` or `FCntUp` regressions, then verify `STM32_Programmer_CLI -c port=SWD mode=UR -ob RDP=0xAA` recovery via `J4.5` (`NRST`) pogo pin.

---

## 3. First-Article Pass / Fail Measurement Record (Fillable)

| Check ID | Parameter | Test Condition | Acceptance Criterion | Measured (`SN01..10`) | Pass / Fail |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **B-01** | Standard `J2` & Reverse-Polarity Isolation | `V_J2 = -4.20 V`; `J5.1` DMM | `I_J2 < 1 µA`, `TP3 = 0.000 ± 0.002 V`; `J5.1 = OL` | *Pending `O-04`* | `[ ]` |
| **B-02** | Forward `Q3` Drop & `TP1` (`3V3`) | `V_J2 = 3.700 V`, idle | `V_J2 - TP3 < 10 mV`, `TP1 = 3.300 ± 0.033 V` | *Pending `O-04`* | `[ ]` |
| **B-03** | Boot Self-Test (`3.0 V` TCXO) & `3.0 ms` `TP2` Rise | `V_J2 = 3.700 V`, SWD + DSO | `passed == 1`, `smps_rdy_ok == 1`, `TP2 = VBAT` flat `≥ 1 ms` pre-CW | *Pending `O-05`* | `[ ]` |
| **B-04** | `STOP2` Sleep Current (`O-04`) | `V_J2 = 3.70 V`, `60 s` JS220 | `≤ 3.5 µA` (`BOR0`) / `≤ 5.0 µA` (`BOR3`) | *Pending `O-04`* | `[ ]` |
| **B-05** | Cold-Cutoff Droop & `3.0 V` TCXO Headroom | `V_J2 = 3.10 V` (`0.5 Ω` R_s) $\to$ `2.95 V` | `TP1 ≥ 3.05 V` @ `3.10 V` (`24.1 mA` load); TX inhibited `< 3.00 V` | *Pending `O-04`* | `[ ]` |
| **B-06** | Conducted Power & `2f0 / 3f0` Spurs | `+4 dBm` CW / `+14 dBm` LoRa | Fundamental `±1.0 dB`; conducted `2f0, 3f0 ≤ -36 dBm` | *Pending `O-02`* | `[ ]` |
| **B-07** | Enclosed `ASA/PETG` + LiPo Return Loss | `J1` + `R_DIV2=0R`, SOL cal | `|S11| ≤ -10.0 dB` across `863.0–870.0 MHz` | *Pending `O-02`* | `[ ]` |
| **B-08** | 2-Point Calibrated Ice & Water/IPA Contrast | Dry + `Al2O3` cal + Ice/Water/IPA | Ice contrast `≥ 8.0 dB`; `Water vs IPA` gap `≥ 0.50 dB` | *Pending `O-02`* | `[ ]` |
| **B-09** | Uniform-Flat Waterproof Lid, `0.80 mm` Deck & Parker `ORD 5700` Seal | Micrometer + IP65/IP67 spray/runoff | Flat `+8.50 mm` roof, `0.80 ± 0.05 mm` deck, `0` standing water, `360°` `1.80 × 0.76 mm` O-ring seal (`23.3%` squeeze, `4 × M2.5 × 22 mm` EPDM-sealed corner screws, `0` roof slots) | *Pending `O-06`* | `[ ]` |
| **B-10** | 1,000-Cycle NVM Power-Cut & `RDP1` | Random relay cuts + `J4.5` `NRST` | `0` `DevNonce`/`FCnt` regressions; `UR` unlock OK | *Pending `O-05`* | `[ ]` |

---

## 4. Mandatory Gate 8 — First-Article Pilot Lot (`5–10` Boards) Volume Production Hold Rule

> **MANDATORY MANUFACTURING RELEASE RULE (`Gate 8`):**  
> Initial PCBWay Turnkey authorization for `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip` **MUST be capped strictly at a `5–10` board Engineering First-Article Pilot Lot**.  
> **Volume turnkey production (`> 10` units) is HARD-BLOCKED until all three physical pilot verification gates below are measured, passed, and signed off in Section 3:**
>
> 1. **Gate 8A — Calibrated 1-Port VNA `J1` Return Loss (`Check B-07`):** Enclosed `0.80 mm` self-draining UV-stabilized `ASA/PETG` + `25 µm` `3M 467MP` bonded assembly with `302535` LiPo installed achieves measured **`|S11| ≤ -10.0 dB` across `863.0–870.0 MHz`** across `≥ 5` pilot units.
> 2. **Gate 8B — Conducted `2f0 / 3f0` Harmonic Spur Compliance (`Check B-06`):** Spectrum-analyzer conducted emissions at `2f0` (`1.733 GHz`) and `3f0` (`2.600 GHz`) at `+14.0 dBm` TX verified **`≤ -36.0 dBm`** (`ETSI EN 300 220-1` Table 7).
> 3. **Gate 8C — Joulescope `JS220` `STOP2` Deep-Sleep, `3.0 V` TCXO & `Q1` Settle Verification (`Checks B-03, B-04`):** Measured 60-second `STOP2` current verified **`≤ 3.5 µA` (`BOR0`) / `≤ 5.0 µA` (`BOR3`)** at `3.70 V, 25 °C` with zero rail back-feed or brownout anomalies.
>
> **Pilot Sign-Off Block (Complete Prior to Volume `> 10` Unit Release):**
> - Pilot Lot Order / Date Code: `____________________`
> - Lead RF / Hardware Engineer Signature & Date: `____________________`
> - Lead Firmware / DFM Engineer Signature & Date: `____________________`
