# Loaded-Antenna LoRaWAN EU868 Link Budget & Wet-Radome `SF12` (`DR0`) Recovery (`Rev E.5`)

**Hardware Revision:** `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Solver Ground Truth:** `rf/results/ifa_fullwave_3d.json`, `rf/results/bridge_3tone_curves.json`, `firmware/src/main_target.c`, `firmware/src/isac_lorawan_eu868.c`

---

## 1. Fundamental Dual-Function ISAC Trade-Off Under Lossy Dielectric Loading

Because `AE1` (`IFA_868MHz_ISAC_40x20mm`) shares its evanescent comb-capacitor aperture (`X_gbr = [74.00..87.00] mm`) between 3-tone CW reflectometry (`+4.0 dBm`) and LoRaWAN Class A uplinks (`+14.0 dBm`), high-permittivity / high-loss superstrates (`2.0 mm` Glaze Ice, IPA, or Liquid Water film on the self-draining open-East `0.80 mm` UV-stabilized `ASA/PETG` sensing window) intentionally detune `f0` downward (`869.0 MHz → 776.0 MHz`) and absorb near-field reactive energy.

Full-wave 3D Yee-grid Maxwell FDTD (`rf/ifa_enclosure_mom.py`, including exact IPC-4552 `ENIG` `NiP/Au` RF sheet resistance $R_s = 23.74\text{ m}\Omega/\square$ and volumetric FR-4/ASA loss) + cascaded bridge/harmonic-filter `[S]` analysis (`rf/bridge_sparam_mc.py`) quantify the exact realized-gain penalty at `868.1 MHz` (`+14.0 dBm` conducted `SX1262` `RFO_LP` output, `-0.80 dB` bridge insertion loss, `-0.35 dB` elliptic pi-filter insertion loss):

| Surface State (`FPort = 10`) | Superstrate (`2.0 mm` on `0.80 mm` `ASA`) | $f_0$ [MHz] | Cascaded `|S11|` (`866.5 MHz`) | Mismatch Loss $1 - |\Gamma|^2$ [dB] | FDTD Total Efficiency $\eta_{\text{tot}}$ | Realized ERP Penalty vs. Dry Air [dB] | Adaptive Uplink `SF` (`main_target.c`) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`0 = DRY_AIR`** | Unloaded Dry Air (`εr = 1.00`) | `869.0` | `-20.83 dB` | `-0.04 dB` | `45.5%` (`-3.42 dB`) | **`0.0 dB` (Baseline `+9.4 dBm` ERP)** | **`SF7` (`DR5`, `41 ms` ToA)** |
| **`1 = OIL`** | PTFE / Mineral Oil (`εr = 2.10`) | `849.0` | `-7.14 dB` | `-0.93 dB` | `35.4%` (`-4.51 dB`) | **`-1.1 dB` (`+8.3 dBm` ERP)** | **`SF7` (`DR5`, `41 ms` ToA)** |
| **`2 = GLAZE_ICE`** | `2.0 mm` Glaze Ice (`εr = 3.20 - j0.003`) | `834.5` | `-2.89 dB` | `-3.14 dB` | `13.4%` (`-8.73 dB`) | **`-5.3 dB` (`+4.1 dBm` ERP)** | **`SF9` (`DR3`, `+5.0 dB` PG, `165 ms` ToA)** |
| **`3 = IPA`** | Lossy Polar Fluid (`εr = 6.29 - j6.09`) | `794.0` | `-2.19 dB` | `-3.99 dB` | `4.8%` (`-13.19 dB`) | **`-9.8 dB` (`-0.4 dBm` ERP)** | **`SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA)** |
| **`4 = LIQUID_WATER`** | Continuous `2.0 mm` Water (`εr = 79.9 - j3.81`) | `776.0` | `-0.72 dB` | `-8.12 dB` | `9.6%` (`-10.18 dB`) | **`-6.8 dB` (`+2.6 dBm` ERP)** | **`SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA)** |
| **`15 = FAULT`** | Diagnostic / Out-of-Envelope State | — | — | — | — | Worst-Case Assumed | **`SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA)** |

---

## 2. End-to-End EU868 Maximum Coupling Loss (MCL) & Adaptive `SF12` Recovery

Assuming a standard 8-channel outdoor EU868 LoRaWAN gateway (`SX1302/SX1303`, `NF = 6 dB`, `+2.15 dBi` omni antenna, `-124.5 dBm` sensitivity at `SF7BW125` vs. **`-137.0 dBm`** at `SF12BW125`, `+12.5 dB` LoRa chirp processing gain):

1. **Dry Air (`SF7 / DR5`):** `+9.4 dBm` ERP $\to$ `-124.5 dBm` gateway sensitivity = **`133.9 dB` link budget** (`~4–7 km` suburban NLoS / `> 12 km` LoS).
2. **Worst-Case Lossy Polar / Wet-Radome Film WITHOUT Adaptation (`SF7`):** `-9.8 dB` lossy-fluid penalty reduces link budget to `124.1 dB`.
3. **Worst-Case Wet-Radome Film WITH `Rev E.5` Self-Draining Open-East Deck + Adaptive `SF12` (`DR0`) Fallback:**
   - Mechanically, the `Rev E.5` lid eliminates the `1.20 mm` retention pocket along the East roof edge (`0.00 mm` dam), preventing standing `> 1.5 mm` rainwater pools from accumulating over `AE1`.
   - Electronically, the telemetry scheduler (`firmware/src/main_target.c` + `ISAC_LoRaWAN_SendClassA()` in `firmware/src/isac_lorawan_eu868.c`) automatically promotes the uplink spreading factor when `state ∈ {IPA, LIQUID_WATER, FAULT}` (`ε_est ≥ 4.5`) from `SF7` (`DR5`) to **`SF12` (`DR0`, `-137.0 dBm` sensitivity)**.
   - The **`+12.5 dB` chirp processing gain** more than offsets the `-6.8 dB` to `-9.8 dB` wet-radome penalty, yielding a **`136.6–139.6 dB` effective link budget** (`+2.7 dB` above unloaded Dry-Air `SF7`!) while strictly respecting the rolling 1-hour EU868 `1.0%` (`36,000 ms/hr`) duty-cycle guard (`1,319 ms` ToA every `900 s` = `5.28 s/hr = 0.147%` duty cycle, **`6.8×` margin** below `1.0%`).

---

## 3. Unpowered `U2` (`LT5538`) LoRaWAN TX Linearity Proof & ETSI `EN 300 220` / LoRaWAN `1.0.3` Compliance

1. **Zero Nonlinear Clipping on Unpowered `LT5538` During `+14 dBm` LoRaWAN TX (`rf/bridge_loss.py`):**
   - During LoRaWAN uplinks, `Q1` (`TPS22919DCKR`) holds `U2` (`LT5538IDD#TRPBF`) unpowered (`3V3_DET = 0.00 V` via `250 Ω` `QOD`) to save `28 mA`.
   - Because `C_S2` (`1.0 pF` series capacitive divider into `R_TERM = 56 Ω || Z_IN+(LT5538)`) attenuates the bridge output voltage swing, exact 8-node complex nodal + distributed microstrip `[Y]` evaluation (`rf/bridge_loss.py`) proves that at `+14.0 dBm` PA output, `U2` `IN+` (`Pin 2`) experiences only **`3.3 mV_pk`** in matched Dry Air (`50 Ω`), **`16.2–17.3 mV_pk`** at `30–100 Ω`, and **`39.5 mV_pk`** even under severe **`VSWR 6:1`** (`|Γ| = 0.714` continuous water immersion) — **`8.8×` below** the `~350 mV` CMOS/ESD diode conduction threshold, guaranteeing **zero passive harmonic intermodulation or ESD-diode clipping**.
2. **ETSI `EN 300 220-1 / -2` Harmonic & Unmodulated CW Duty-Cycle Legality:**
   - **Conducted/Radiated Harmonics (`EN 300 220-1` Table 7 `≤ -36 dBm`):** Populated 3rd-order elliptic low-pass pi-filter (`C_M1 = 3.6 pF`, `L_M1 = 8.2 nH || C_MZ = 0.5 pF`, `C_M2 = 4.3 pF`) suppresses `2f0` (`1.733 GHz`) by **`≥ 37.2 dB`** and `3f0` (`2.600 GHz`) by **`≥ 60.1 dB`** across Dry Air and Water VSWR extremes (`< -50 dBm` conducted at `+14 dBm` LoRa / `< -60 dBm` at `+4 dBm` CW).
   - **3-Tone CW Sensing Airtime (`ERC/REC 70-03` Annex 1 Sub-bands `g1` / `g` / `g3`):** Each `+4.0 dBm` (`2.5 mW` $\ll$ `25 mW` ERP limit) CW tone dwells for `1.17 ms` (`4.68 ms/hr = 0.00013%` per tone at `15-min` telemetry cadence), providing **`769×` margin** below the `0.1%` (`3.6 s/hr`) Sub-band `g1` (`863.1 MHz`) limit and **`7,690×` margin** below the `1.0%` (`36 s/hr`) Sub-band `g`/`g3` (`866.5 / 869.5 MHz`) limits, enforced in real time by dual rolling 1-hour airtime ledgers.
3. **LoRaWAN `1.0.3` §7 Long-Term `JoinRequest` Backoff & §5.4 `RXParamSetupReq` (`0x05`):**
   - `ISAC_LoRaWAN_NextJoinDelayMs()` enforces Tier 1 (`< 1 h`: `≤ 36 s`), Tier 2 (`1–11 h`: `≤ 36 s / 10 h`), and **Tier 3 (`> 11 h`: `17,281 s` = `4.80 h` base interval + `0..30 s` jitter $\Rightarrow$ `< 8.18 s / 24 h ≤ 8.7 s / 24 h` even at worst-case `SF12` `1,646.6 ms` ToA)** when gateways are unreachable, and `ISAC_LoRaWAN_BuildJoinRequest()` handles `RXParamSetupReq` (`0x05`) + sticky `RXParamSetupAns` (`FOpt` reporting).
