# Loaded-Antenna LoRaWAN EU868 Link Budget & Wet-Radome `SF12` Recovery (`Rev E.5`)

**Author:** Stephen K. Boachie  
**Hardware Revision:** `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Model Inputs:** `rf/results/ifa_fullwave_3d.json`, `rf/results/bridge_3tone_curves.json`, `firmware/src/main_target.c`, `firmware/src/isac_lorawan_eu868.c`

---

## 1. Shared-Aperture Trade-Off Under Dielectric Loading

Because `AE1` (`IFA_868MHz_ISAC_40x20mm`) shares its interdigital fringing-field region (`X_gbr = [74.00..87.00] mm`) between 3-tone CW reflectometry (`+4.0 dBm`) and LoRaWAN Class A uplinks (`+14.0 dBm`), high-permittivity or lossy layers (`2.0 mm` glaze ice, polar fluid, or water film on the `0.80 mm` `ASA/PETG` window) shift $f_0$ downward (`869.0 MHz → 776.0 MHz`) and reduce radiation efficiency.

3D Yee-grid FDTD simulations (`rf/ifa_enclosure_mom.py`, modeling IPC-4552 `ENIG` sheet resistance $R_s = 23.74\text{ m}\Omega/\square$ and substrate/radome dielectric loss) cascaded with the bridge and elliptic harmonic filter (`rf/bridge_sparam_mc.py`) give the realized ERP penalty at `868.1 MHz` (`+14.0 dBm` `SX1262` `RFO_LP`, `-0.80 dB` bridge insertion loss, `-0.35 dB` filter insertion loss):

| Surface State (`FPort = 10`) | Superstrate (`2.0 mm` on `0.80 mm` `ASA`) | $f_0$ [MHz] | Cascaded `|S11|` (`866.5 MHz`) | Mismatch Loss $1 - |\Gamma|^2$ [dB] | FDTD Total Efficiency $\eta_{\text{tot}}$ | Realized ERP Penalty vs. Dry Air [dB] | Adaptive Uplink `SF` (`main_target.c`) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `0 = DRY_AIR` | Unloaded Dry Air (`εr = 1.00`) | `869.0` | `-20.83 dB` | `-0.04 dB` | `45.5%` (`-3.42 dB`) | `0.0 dB` (`+9.4 dBm` ERP) | `SF7` (`DR5`, `41 ms` ToA) |
| `1 = OIL` | PTFE / Mineral Oil (`εr = 2.10`) | `849.0` | `-7.14 dB` | `-0.93 dB` | `35.4%` (`-4.51 dB`) | `-1.1 dB` (`+8.3 dBm` ERP) | `SF7` (`DR5`, `41 ms` ToA) |
| `2 = GLAZE_ICE` | `2.0 mm` Glaze Ice (`εr = 3.20 - j0.003`) | `834.5` | `-2.89 dB` | `-3.14 dB` | `13.4%` (`-8.73 dB`) | `-5.3 dB` (`+4.1 dBm` ERP) | `SF9` (`DR3`, `+5.0 dB` PG, `165 ms` ToA) |
| `3 = IPA` | Lossy Polar Fluid (`εr = 6.29 - j6.09`) | `794.0` | `-2.19 dB` | `-3.99 dB` | `4.8%` (`-13.19 dB`) | `-9.8 dB` (`-0.4 dBm` ERP) | `SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA) |
| `4 = LIQUID_WATER` | Continuous `2.0 mm` Water (`εr = 79.9 - j3.81`) | `776.0` | `-0.72 dB` | `-8.12 dB` | `9.6%` (`-10.18 dB`) | `-6.8 dB` (`+2.6 dBm` ERP) | `SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA) |
| `15 = FAULT` | Diagnostic / Jammer-Blanked State | — | — | — | — | Conservative Fallback | `SF12` (`DR0`, `+12.5 dB` PG, `1,319 ms` ToA) |

---

## 2. EU868 Maximum Coupling Loss (MCL) & Adaptive Spreading Factor

Against a standard 8-channel outdoor EU868 gateway (`SX1302/SX1303`, `NF = 6 dB`, `+2.15 dBi` omni antenna, `-124.5 dBm` sensitivity at `SF7BW125` vs. `-137.0 dBm` at `SF12BW125`):

1. **Dry Air (`SF7 / DR5`):** `+9.4 dBm` ERP into `-124.5 dBm` gateway sensitivity gives a `133.9 dB` link budget (`~4–7 km` suburban non-line-of-sight).
2. **Uncompensated Wet Radome (`SF7`):** A `-9.8 dB` lossy-fluid detuning loss drops the link budget to `124.1 dB`.
3. **Self-Draining Window + Adaptive `SF9` / `SF12` Promotion:**
   - Mechanically, the flush East edge (`0.00 mm` lip) lets liquid water run off the `0.80 mm` sensing deck instead of pooling into thick standing layers.
   - In firmware (`main_target.c`), classifying `GLAZE_ICE` steps uplinks to `SF9` (`+5.0 dB` processing gain), while `IPA`, `LIQUID_WATER`, or `FAULT` promotes uplinks to `SF12` (`DR0`, `+12.5 dB` processing gain).
   - That `+12.5 dB` chirp gain offsets the `-6.8 dB` to `-9.8 dB` antenna penalty, restoring an effective `136.6–139.6 dB` MCL while keeping airtime at `0.147%` (`5.28 s/hr` at a `15-min` period, well within the `1.0%` EU868 limit).

---

## 3. Unpowered Detector Linearity & ETSI `EN 300 220` Duty Compliance

1. **Unpowered `LT5538` Voltage Swing During `+14 dBm` LoRaWAN TX (`rf/bridge_loss.py`):**
   - During LoRaWAN transmissions, `Q1` holds `U2` (`LT5538IDD#TRPBF`) unpowered (`3V3_DET = 0.00 V` via `250 Ω` `QOD`) to save `28 mA`.
   - Series capacitor `C_S2` (`1.0 pF` into `R_TERM = 56 Ω || Z_IN+`) divides the coupled RF voltage so that at `+14.0 dBm` PA output, `U2` `IN+` (`Pin 2`) sees `3.3 mV_pk` into `50 Ω` and `39.5 mV_pk` at `VSWR 6:1` (`|Γ| = 0.714`)—roughly `8.8×` below ESD diode conduction (`~350 mV`), avoiding passive intermodulation.
2. **ETSI `EN 300 220-1 / -2` Harmonics & CW Duty Cycle:**
   - **Harmonic Suppression (`EN 300 220-1` Table 7, `≤ -36 dBm`):** The 3rd-order elliptic low-pass Pi-filter (`C_M1 = 3.6 pF`, `L_M1 = 8.2 nH || C_MZ = 0.5 pF`, `C_M2 = 4.3 pF`) attenuates `2f0` (`1.733 GHz`) by `≥ 37.2 dB` and `3f0` (`2.600 GHz`) by `≥ 60.1 dB` across dry and wet VSWR corners.
   - **CW Reflectometry Airtime (`ERC/REC 70-03` Annex 1):** Each `+4.0 dBm` (`2.5 mW`) CW tone dwells for `~1.22 ms` (`< 5 ms/hr = 0.00014%` per tone at a `15-min` reporting interval), staying well below the `0.1%` (`3.6 s/hr`) Sub-band `g1` (`863.1 MHz`) and `1.0%` (`36 s/hr`) Sub-band `g`/`g3` (`866.5 / 869.5 MHz`) limits enforced by rolling 1-hour airtime counters.
3. **LoRaWAN `1.0.3` §7 Join Back-Off & §5.4 `RXParamSetupReq` (`0x05`):**
   - `ISAC_LoRaWAN_NextJoinDelayMs()` enforces Tier 1 (`< 1 h`: `≤ 36 s`), Tier 2 (`1–11 h`: `≤ 36 s / 10 h`), and Tier 3 (`> 11 h`: `17,281 s` base + `0..30 s` jitter, `< 8.2 s / 24 h ≤ 8.7 s / 24 h` at `SF12`) when gateways are unreachable, and `ISAC_LoRaWAN_ProcessMacCommands()` implements sticky `RXParamSetupAns` (`0x05`) acknowledgments.
