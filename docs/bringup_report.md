# `ISAC_868` `Rev E.5` — First-Article (`5–10` Board) Pilot Bring-Up Procedure

**Author:** Stephen K. Boachie  
**Hardware Revision:** `ISAC_868_KiCad9` `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Scope:** Step-by-step bench bring-up procedure, DC test-point map, and fillable pass/fail log for the initial `5–10` board pilot lot (`Open Items O-01..O-06`). Measured columns are left blank until pilot boards arrive from assembly.

---

## 1. Required Lab Equipment & DC Test-Point Map

### 1.1 Instrument List

| Instrument | Recommended Rating | Role During Bring-Up |
| :--- | :--- | :--- |
| Bench Source-Measure / PSU | `0–4.350 V` (`4.35 V` max on `J2`), `0–500 mA` current limit | Controlled first power-up, reverse-polarity check, and `3.00 V` cutoff / droop sweep |
| Current Profiler | Joulescope `JS220` or Nordic `PPK2` (`10 nA`–`1 A`, `≥ 100 kS/s`) | `STOP2` sleep current (`O-04`), `3.0 ms` `Q1` turn-on, `150 µs` battery sense, CW & LoRaWAN TX charge |
| Digital Storage Oscilloscope | `≥ 200 MHz` BW, `10×` passive probes + spring ground clip | `VBAT / 3V3 / 3V3_DET / DET_ADC` rail timing (`3.0 V` TCXO headroom, `3.0 ms` `Q1` rise, `550 µs` LPF settle) |
| Vector Network Analyzer (VNA) | `100 MHz – 3 GHz` (`NanoVNA-V2`, `LibreVNA`, or benchtop VNA) + SMA SOL kit | 1-port `S11` of `AE1` + elliptic Pi-filter (`J1` + `R_DIV2`) across air, enclosure, ice, and water (`O-02`) |
| Spectrum Analyzer + `20 dB` Pad | `9 kHz – 6 GHz` (`RBW 100 kHz`), phase-stable SMA cable | Conducted `+14 dBm` LoRa / `+4 dBm` CW carrier and `2f0 / 3f0` harmonic suppression (`O-02`) |
| SWD Probe + Pogo Fixture | ST-LINK/V3MINIE or J-Link with `5`-pin `2.54 mm` pogo clip on `J4` | `tools/production_flash.sh`, 2-point calibration (`--cal-dry-mv`, `--cal-ref-cdb`), `g_selftest_report` inspection |

### 1.2 DC Test-Point Reference (`TP1..TP5`)

To avoid adding ~`1.5 pF` of pad capacitance to the RF reflectometer, no test points are placed on `/BR_P`, `/BR_Q`, `/BR_S`, or `/BR_O`. All five `Ø1.00 mm` bare-`ENIG` test points sit on DC or baseband nodes:

| Test Pad | Schematic Net | Gerber `(X_gbr, Y_gbr)` [mm] | Expected Voltage / Waveform |
| :---: | :--- | :---: | :--- |
| `TP1` | `3V3` | `(28.200, 28.750)` | `3.300 V ± 33 mV` (`U3` `TPS7A0233DBVR` output; `24.1 mA` peak load) |
| `TP2` | `3V3_DET` | `(42.100, 3.800)` | `0.000 V` in `STOP2` (`Q1` `QOD` active); rises to `VBAT` (`3.0–4.35 V`) within `1.6 ms` when `PA8 = 1` |
| `TP3` | `VBAT` | `(15.350, 30.200)` | `V_J2 - (< 6 mV)` forward (`Q3` `AO3401A` ideal diode); `0.000 V` if `J2` is reversed (`-4.20 V`) |
| `TP4` | `/DET_ADC` | `(45.300, 4.200)` | Filtered `LT5538IDD#TRPBF` log output (`~0.76 V` dry-air null at `866.5 MHz`, `~1.14 V` glaze ice at `+4 dBm` CW) |
| `TP5` | `GND` | `(31.200, 28.750)` | Low-inductance DMM negative and oscilloscope spring-clip ground reference |

---

## 2. Step-by-Step Bring-Up Sequence (`5–10` Pilot Boards)

### Phase A — Unpowered Visual, X-Ray & Resistance Checks
1. **Incoming Inspection & Serialization:** Label pilot units (`SN01..SN10`) in the `B.SilkS` traceability box (`X_gbr = 12.5..36.7 mm`). Check `J2` polarity markings (`Pad 1` Square = `GND`, `Pad 2` Round = `/VBAT_RAW`, `4.35 V DC MAX` — do not connect a `5.0 V` supply), `U1` (`LGA-73`) and `U2` (`DFN-8-1EP`) X-ray voiding (`< 25%`), wirewound `L_SMPS` (`LQH2MCN150K02L`), populated elliptic filter parts (`C_M1=3.6p, L_M1=8.2n, C_MZ=0.5p, C_M2=4.3p`), unpopulated `DNP` footprints (`C_SMPS3, D_RF, J1..J5, R_DIV1, R_DIV2, R_VUART`), and clean bare-`ENIG` comb fingers in the `AE1` window (`[73.40..87.80] × [6.65..20.80] mm`).
2. **DMM Rail-to-GND Resistance (`TP5 = GND`):**
   - `J2.2` (`/VBAT_RAW`) to `TP5`: expect `> 1 MΩ`.
   - `TP3` (`VBAT`) to `TP5`: expect `> 100 kΩ`.
   - `TP1` (`3V3`) to `TP5`: expect `> 50 kΩ` once bypass capacitors settle.
   - `TP2` (`3V3_DET`) to `TP5`: expect `~200 Ω–10 kΩ` (`Q1` `QOD` bleed path when unpowered).

### Phase B — Rail Bring-Up, Reverse-Polarity & `STOP2` Sleep Current (`O-04`, `O-05`)
3. **Reverse-Polarity & Header Back-Feed Isolation:**
   - Apply `-4.20 V` (`10 mA` current limit) to `J2.2` relative to `J2.1`: verify `I_J2 < 1 µA` and `TP3 = 0.000 V ± 2 mV`.
   - Verify `J5.1` (`VUART`) reads open (`> 10 MΩ`) to `TP1` (`R_VUART = DNP`) and `J4.1` (`VAPP_SENSE`) reads `1.00 kΩ ± 1%` (`R_VAPP`) to `TP1`.
4. **Nominal `3.70 V` Power-Up:** Apply `+3.700 V` (`100 mA` limit) to `J2` (`Pin 2 = +, Pin 1 = -`). Confirm `TP3 ≥ 3.695 V` and `TP1 = 3.300 V ± 33 mV`.
5. **Firmware Flashing & 2-Point Calibration (`O-05`):** Connect the 5-pin SWD pogo clip to `J4`. Flash an initial bench image with `--uncalibrated-bench --no-rdp` to read `g_selftest_report` and capture the enclosed Dry-Air detector voltages (`v1,v2,v3` in mV) plus the sintered `2.0 mm` `Al2O3` ceramic reference block reading (`cal_ref_cdb = level_dbm_x100 - (-2619)` in `0.01 dB` units). Re-provision the calibration constants and unit keys into `0x0803E000`:
   ```bash
   ./tools/production_flash.sh \
     --deveui 70B3D57ED0060001 \
     --joineui 70B3D57ED0000001 \
     --cal-dry-mv 818,758,883 \
     --cal-ref-cdb 0 \
     --no-rdp
   ```
6. **Sleep & Active Current Profile (`O-04`):** Place a Joulescope `JS220` in series with `J2` at `3.70 V` and `4.20 V`. Confirm `STOP2` mean sleep current (`≤ 3.5 µA` at `BOR0` / `≤ 5.0 µA` at `BOR3`), verify on an oscilloscope that `TP2` (`3V3_DET`) reaches `VBAT` at least `1.0 ms` before CW tone #1 (`3.0 ms` `PA8` guard), and verify TX inhibit below `3.00 V`.

### Phase C — Conducted RF Harmonics & 1-Port VNA Characterization (`O-02`)
7. **Conducted Output Power & Harmonics (`SN01` Bench Unit):** Hand-solder `J1` (`Molex 73251-1153`) per `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv`.
   - *PA Output:* Depopulate `C_S` (`1.0 pF`) and fit `0 Ω` at `R_DIV1` (`R_DIV2 = DNP`). Measure `+4.0 ± 1.0 dBm` CW sensing output and `+14.0 ± 1.0 dBm` LoRaWAN carrier (accounting for `-0.80 dB` series bridge loss).
   - *Post-Filter Harmonics:* Restore `C_S = 1.0 pF` and `R_DIV1 = DNP`; measure conducted `2f0` (`1.733 GHz`) and `3f0` (`2.600 GHz`) after `C_M2` and verify both remain `≤ -36 dBm` (`ETSI EN 300 220-1` Table 7).
8. **1-Port VNA Return-Loss Sweep (`SN02..SN05`):** Depopulate `R1` (`8.2 Ω`), fit `0 Ω` on `R_DIV2`, run 1-port `SOL` calibration at `J1`, and sweep `750–960 MHz`:
   - Enclosed in the `0.80 mm` `ASA/PETG` lid (`25 µm` `3M 467MP` window bond) with `302535` LiPo installed: verify `|S11| ≤ -10.0 dB` across `863–870 MHz` (`f0 = 869.0 ± 5.0 MHz`).
   - With `2.0 mm` glaze ice (`-5 °C`) and `2.0 mm` liquid water on the window: verify expected downward resonance shifts (`~ -34.5 MHz` ice, `~ -93.0 MHz` water). Reserve `SN06..SN10` (without `J1`) for sealed enclosure testing.

### Phase D — Sealed Telemetry, Adaptive `SF12` & Power-Interrupt Stress (`O-05`, `O-06`)
9. **Sealed Classification & LoRaWAN Uplink:** Solder `26 AWG` silicone battery leads upward from `B.Cu` into `J2` (`Pad 1` Square = `BLACK / GND`, `Pad 2` Round = `RED / +VBAT_RAW`, trimming factory plugs one wire at a time and anchoring insulation with `DOWSIL 3145` neutral-cure RTV), then assemble `SN06..SN10` into the `ASA/PETG` housing with the Parker `ORD 5700` O-ring and `M2.5 × 22 mm` corner screws + EPDM washers. Verify OTAA join on EU868, check `FPort = 10` state classification across Dry Air (`0`, `SF7`), Oil/PTFE (`1`, `SF7`), Glaze Ice (`2`, `SF9`), IPA (`3`, `SF12`), and Water (`4`, `SF12`), and confirm `863.1 MHz` Sub-band `g1` duty stays `≤ 3,600 ms/hr` (`0.1%`).
10. **1,000-Cycle Brownout & `RDP1` Recovery:** Cycle power `1,000` times at random `50 ms – 5 s` intervals during join/uplink on `SN06` (`--lock-rdp1` enabled). Confirm zero `DevNonce` or `FCntUp` regressions, then test `STM32_Programmer_CLI -c port=SWD mode=UR -ob RDP=0xAA` unlock via `J4.5` (`NRST`).

---

## 3. First-Article Pass / Fail Log

| Check ID | Parameter | Condition | Acceptance Target | Measured (`SN01..10`) | Pass / Fail |
| :---: | :--- | :--- | :--- | :---: | :---: |
| `B-01` | Reverse-Polarity & UART Isolation | `V_J2 = -4.20 V`; `J5.1` DMM | `I_J2 < 1 µA`, `TP3 = 0.000 ± 0.002 V`; `J5.1 = OL` | *Pending `O-04`* | `[ ]` |
| `B-02` | Forward `Q3` Drop & `3V3` Rail | `V_J2 = 3.700 V`, idle | `V_J2 - TP3 < 10 mV`, `TP1 = 3.300 ± 0.033 V` | *Pending `O-04`* | `[ ]` |
| `B-03` | Boot Self-Test & `TP2` Rise | `V_J2 = 3.700 V`, SWD + DSO | `passed == 1`, `smps_rdy_ok == 1`, `TP2 = VBAT` `≥ 1 ms` pre-CW | *Pending `O-05`* | `[ ]` |
| `B-04` | `STOP2` Deep-Sleep Current | `V_J2 = 3.70 V`, `60 s` JS220 | `≤ 3.5 µA` (`BOR0`) / `≤ 5.0 µA` (`BOR3`) | *Pending `O-04`* | `[ ]` |
| `B-05` | Cold-Cutoff Droop & TCXO Headroom | `V_J2 = 3.10 V` (`0.5 Ω` R_s) $\to$ `2.95 V` | `TP1 ≥ 3.05 V` at `3.10 V`; TX inhibited `< 3.00 V` | *Pending `O-04`* | `[ ]` |
| `B-06` | Conducted Power & `2f0 / 3f0` Harmonics | `+4 dBm` CW / `+14 dBm` LoRa | Fundamental `±1.0 dB`; conducted `2f0, 3f0 ≤ -36 dBm` | *Pending `O-02`* | `[ ]` |
| `B-07` | Enclosed `ASA/PETG` + LiPo Return Loss | `J1` + `R_DIV2=0R`, SOL cal | `|S11| ≤ -10.0 dB` across `863.0–870.0 MHz` | *Pending `O-02`* | `[ ]` |
| `B-08` | 2-Point Calibrated Ice & Water/IPA Contrast | Dry + `Al2O3` cal + Ice/Water/IPA | Ice contrast `≥ 8.0 dB`; `Water vs IPA` gap `≥ 0.50 dB` | *Pending `O-02`* | `[ ]` |
| `B-09` | `0.80 mm` Window Runoff & O-Ring Seal | Micrometer + IP65 spray test | `0.80 ± 0.05 mm` window, clean East drainage, dry interior | *Pending `O-06`* | `[ ]` |
| `B-10` | 1,000-Cycle Power-Cut & `RDP1` Unlock | Relay cycling + `J4.5` `NRST` | `0` `DevNonce`/`FCnt` regressions; `UR` unlock verified | *Pending `O-05`* | `[ ]` |

---

## 4. Pilot Bring-Up Sign-Off Checklist

Before ordering quantities beyond the initial `5–10` board Pilot lot, verify and sign off the three core hardware checks in Section 3:

1. **Enclosed Antenna Return Loss (`B-07`):** Enclosed `0.80 mm` `ASA/PETG` + `25 µm` `3M 467MP` assembly with battery installed meets `|S11| ≤ -10.0 dB` across `863.0–870.0 MHz` on at least 5 pilot boards.
2. **Conducted Harmonic Suppression (`B-06`):** Conducted `2f0` (`1.733 GHz`) and `3f0` (`2.600 GHz`) emissions at `+14.0 dBm` TX remain `≤ -36.0 dBm` (`ETSI EN 300 220-1` Table 7).
3. **Sleep & Rail Regulation (`B-03`, `B-04`):** 60-second `STOP2` sleep current meets `≤ 3.5 µA` (`BOR0`) / `≤ 5.0 µA` (`BOR3`) at `3.70 V, 25 °C` with clean `Q1` turn-on and no brownout resets.

- Pilot Batch / Date Code: `____________________`
- Hardware / RF Sign-Off & Date: `____________________`
- Embedded Firmware Sign-Off & Date: `____________________`
