# CST Studio Suite vs. 3D-FDTD Cross-Correlation Report (`Rev E.5`)

| Case | Medium | CST $f_0$ [MHz] | FDTD $f_0$ [MHz] | CST $|S_{11}|_{866.5}$ [dB] | CST `Tilt` [dB] | FDTD `Tilt` [dB] | CST `Level` [dBm] | FDTD `Level` [dBm] | Classified State |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `01_bare_pcb` | `bare` | `940.0` | `940.0` | `-1.34` | `+0.93` | `—` | `-26.87` | `—` | `LIQUID_WATER` |
| `02_dry_air` | `dry air` | `865.8` | `869.0` | `-20.83` | `-3.44` | `-3.44` | `-45.66` | `-45.66` | `DRY_AIR` |
| `03_enclosed_lipo` | `lipo` | `865.8` | `869.0` | `-20.81` | `-3.45` | `—` | `-45.64` | `—` | `DRY_AIR` |
| `04_fr4_low_4p2` | `fr4_low` | `869.5` | `879.0` | `-12.67` | `+1.73` | `—` | `-36.59` | `—` | `OIL` |
| `05_fr4_high_4p6` | `fr4_high` | `862.0` | `859.5` | `-12.76` | `-4.57` | `—` | `-40.06` | `—` | `OIL` |
| `06_oil_ptfe` | `PTFE` | `849.0` | `849.0` | `-7.14` | `-1.23` | `-1.23` | `-33.27` | `-33.26` | `OIL` |
| `07_glaze_ice` | `glaze ice` | `863.1` | `834.5` | `-2.89` | `-0.01` | `-0.01` | `-28.63` | `-28.63` | `GLAZE_ICE` |
| `08_alumina_al2o3` | `alumina Al2O3` | `872.0` | `783.0` | `-0.53` | `+1.56` | `+1.56` | `-26.19` | `-26.19` | `IPA` |
| `09_ipa_debye` | `IPA (868 MHz)` | `863.1` | `794.0` | `-2.19` | `+1.45` | `+1.45` | `-27.75` | `-27.75` | `IPA` |
| `10_water_debye` | `water film` | `872.0` | `776.0` | `-0.72` | `+1.22` | `+1.22` | `-26.35` | `-26.35` | `LIQUID_WATER` |

- **Air-to-Ice Resonant Sensitivity:** `3.42 MHz/RIU` (3D-FDTD baseline: `43.73 MHz/RIU`)
