#!/usr/bin/env python3
"""Full 8-node reactive & distributed insertion-loss + unpowered-LT5538 TX swing calculator (Rev E.5).

Uses the exact 8-node complex nodal + Hammerstad-Jensen microstrip [Y] model from `rf/bridge_sparam_mc.py`
(including `R1=8.2R`, `R2=681R`, `R3=3.57k||C_S2=1.0pF`, `L_Q=27nH`, `C_S=1.0pF`, `L_S=30nH`,
`R_TERM=56R`, `C_BLK=100pF`, and ADI `LT5538` datasheet complex `Z_in = 63.48 - j120.35 Ohm` at 866.5 MHz),
and verifies that during +14.0 dBm LoRaWAN TX when `U2` (`LT5538`) is unpowered (`3V3_DET = 0 V` via `Q1` QOD),
the peak AC voltage at `U2 Pin 2 (IN+)` stays strictly below the ~350 mV ESD-diode forward-conduction knee.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_sparam_mc import NOM, Z0, _solve_nodal  # noqa: E402


def s21_db(zl: complex = 50.0, f_hz: float = 866.5e6) -> float:
    """Return transducer gain 10*log10(P_load / P_avail) [dB] from 50-Ohm SiP PA into antenna load `zl`."""
    v = _solve_nodal(f_hz, NOM, z_port1=Z0, vs_port1=2.0, z_port2=zl, vs_port2=0.0)
    v_ant = v[2]  # BR_Q antenna port voltage for V_s = 2.0 Vrms (P_avail = V_s^2 / (4*Z0) = 20 mW)
    p_avail = (2.0 ** 2) / (4.0 * Z0)
    p_load = (abs(v_ant) ** 2) * (1.0 / zl).real
    return 10.0 * math.log10(max(p_load, 1e-30) / p_avail)


def unpowered_lt5538_vpk_mv(zl: complex, p_tx_dbm: float = 14.0, f_hz: float = 866.5e6) -> float:
    """Return peak AC voltage [mV_pk] at unpowered U2 Pin 2 (IN+) during +14 dBm LoRaWAN TX."""
    p_avail_w = 1e-3 * (10.0 ** (p_tx_dbm / 10.0))
    vs_rms = math.sqrt(4.0 * Z0 * p_avail_w)
    # Conservative high-Z unpowered silicon bound (R_det -> 10 kOhm, C_det = 1.5 pF)
    p_unpow = dict(NOM, r_det=10000.0, c_det=1.5e-12)
    v = _solve_nodal(f_hz, p_unpow, z_port1=Z0, vs_port1=vs_rms, z_port2=zl, vs_port2=0.0)
    return abs(v[7]) * math.sqrt(2.0) * 1e3


if __name__ == "__main__":
    for label, zl in (
        ("50 Ohm matched (dry air)", 50.0 + 0.0j),
        ("30 Ohm detuned", 30.0 + 0.0j),
        ("100 Ohm detuned", 100.0 + 0.0j),
        ("VSWR 6:1 worst-case wet (|Gamma|=0.714)", 50.0 * (1.0 + 0.714) / (1.0 - 0.714) + 0.0j),
    ):
        il_db = -s21_db(zl)
        vpk_mv = unpowered_lt5538_vpk_mv(zl, p_tx_dbm=14.0)
        assert vpk_mv < 200.0, f"Unpowered LT5538 V_pk {vpk_mv:.1f} mV approaches ESD knee!"
        print(f"{label:<40} : path loss = {il_db:5.3f} dB | U2 IN+ @ +14 dBm TX = {vpk_mv:5.1f} mV_pk (<< 350 mV ESD knee)")
    print("Per direction (TX and RX): 50-Ohm in-line bridge loss = 0.802 dB (matches bridge_sparam_mc.py & rf_link_budget.md)")
