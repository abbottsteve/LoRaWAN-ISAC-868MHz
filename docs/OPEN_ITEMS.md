# `ISAC_868` `Rev E.5` — Pilot Bring-Up & Pre-Compliance Tracker

**Author:** Stephen K. Boachie  
**Hardware Revision:** `Rev E.5` (`fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`)  
**Current Hardware Status:** A 5-unit `Rev E.5` pilot batch is currently in turnkey fabrication and SMT assembly. All CAD files, 3D FDTD / 2D-FVM electromagnetic models, distributed bridge Monte-Carlo simulations, enclosure STLs, and bare-metal `STM32WLE5JC` firmware are complete in this repository. The six engineering items below track physical lab characterization and regulatory pre-scans to be completed on the incoming pilot boards prior to larger builds.

---

## Open Verification Items

| ID | Scope | Bench / Vendor Verification Task | Milestone |
| :---: | :---: | :--- | :--- |
| `O-01` | Bare-Board & Stencil EQ | Confirm PCBWay CAM engineering questions on `1.60 mm +0.03/-0.10 mm` (`1.50–1.63 mm`) finished thickness, single-sided `0.10 mm` (`100 µm`) electropolished top stencil (`1:1` `F_Paste.gtp`, `B_Paste.gbp` omitted), IPC-4552 `ENIG` finish, `0.035 mm` global / `0.025 mm` `U1,U2` NSMD mask clearances (`≥ 0.180 mm` LPI dams), bare-`ENIG` `AE1` sensing window (`[73.40..87.80] × [6.65..20.80] mm`), `/BR_S` `2.20 × 2.20 mm` copper cutout, `67`-row SMD CPL, and `U1` MSL-3 handling. | Pre-SMT CAM Sign-Off |
| `O-02` | Conducted RF & 1-Port VNA | Measure calibrated 1-port VNA `S11` across `750–960 MHz` (`J1` + `R_DIV2`), verify 2-point factory calibration (`--cal-dry-mv` + `--cal-ref-cdb`, `P01 ≥ 8 dB` ice contrast and `≥ 0.50 dB` Water/IPA separation), and measure conducted `+14 dBm` / `+4 dBm` harmonics (`2f0, 3f0 ≤ -36 dBm`) through the elliptic Pi-filter (`C_M1=3.6p, L_M1=8.2n||C_MZ=0.5p, C_M2=4.3p`). | Pilot Bring-Up Day 2 |
| `O-03` | ETSI / CE-RED Pre-Compliance | Run chamber radiated spurious/ERP pre-scan per ETSI EN 300 220-2 (`0.1%` duty on `863.1 MHz` `g1` and `1.0%` on EU868), EN 301 489-1/-3 ESD (`±4 kV` contact / `±8 kV` air on the `0.80 mm` `ASA/PETG` window), and LoRaWAN 1.0.3 EU868 link-layer conformance. | Post-Bring-Up Pre-Scan |
| `O-04` | Power, TCXO & Sleep Profile | Record 1-hour Joulescope `JS220` current profile across `STOP2` (`BOR0` and `BOR3`, `PA2/PA3` Analog High-Z), `3.0 V` `DIO3` TCXO (`0x06`) startup, `VBAT`-fed `Q1` `3.0 ms` settle, `PA9` `150 µs` battery sense, `+4 dBm` CW sweep, `L_SMPS = LQH2MCN150K02L` (`Isat = 300 mA`) efficiency, and `SF7/SF9/SF12` uplinks from `4.20 V` down to `3.00 V` (`-20 °C` and `+25 °C`). | Pilot Bring-Up Day 1 |
| `O-05` | NVM Power-Cut & Provisioning | Validate `550 µs` `SysTick->CVR` dwell and dual-`SMPR` ADC timing on silicon, run a `1,000`-cycle randomized power-cut persistence test (`DevNonce`, `FCntUp`), and test `UID64` + 2-point calibration provisioning (`provisioning_vault/`) and `--lock-rdp1` recovery via `J4.5` (`NRST`) pogo pins. | Pilot Bring-Up Day 1–2 |
| `O-06` | Enclosure Fit & IP65 Spray | Verify mechanical fit and water runoff on the UV-stabilized `ASA/PETG` enclosure (`0.80 mm` open-East window bonded with `25 µm` `3M 467MP` transfer tape, Parker `ORD 5700` `1.80 × 0.76 mm` EPDM O-ring face seal, `M2.5 × 22 mm` corner fasteners) and `302535` 1S LiPo pouch clearance. | Pilot Box-Build |
