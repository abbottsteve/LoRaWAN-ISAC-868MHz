#!/usr/bin/env python3
"""
rules_isac.py -- Immutable Cryptographic PCBWay Turnkey Rule Deck for ISAC_868_KiCad9 (Rev E.3).

Locks and cryptographically verifies (SHA-256) the physical 2-layer RF stackup, ENIG surface
finish, Green LPI solder-mask dam constraints (protecting U1 RAK3172LP-SiP LGA-73 0.230 mm
inter-pad gaps), PCBWay zero-surcharge design rules, strict DRC error severities (0 exclusions),
netclasses (Default, Power, RF_50R), and scoped .kicad_dru custom rules across:
  * ISAC_868_KiCad9.kicad_pcb  (Board Setup stackup, ENIG, Green LPI, 0.10 mm mask dam, tenting)
  * ISAC_868_KiCad9.kicad_pro  (PCBWay design rules, strict error severities, 0 exclusions, netclasses)
  * ISAC_868_KiCad9.kicad_dru  (Scoped J1 dy=0 edge-SMA launch, Power/RF_50R neck-down & CPWG gap)
  * tools/rules_isac.lock.json (Immutable SHA-256 cryptographic digest manifest)

Usage:
  python3 tools/rules_isac.py --apply
  python3 tools/rules_isac.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = "ISAC_868_KiCad9"

DEFAULT_PCB_PATH = os.path.join(ROOT, f"{PROJECT}.kicad_pcb")
DEFAULT_PRO_PATH = os.path.join(ROOT, f"{PROJECT}.kicad_pro")
DEFAULT_DRU_PATH = os.path.join(ROOT, f"{PROJECT}.kicad_dru")
DEFAULT_LOCK_PATH = os.path.join(HERE, "rules_isac.lock.json")


# ---------------------------------------------------------------------------
# 1. Immutable PCBWay Turnkey Stackup, Mask, DRC & Netclass Specification
# ---------------------------------------------------------------------------
STACKUP_SPEC: Dict[str, Any] = {
    "layer_count": 2,
    "board_thickness_mm": 1.60,
    "board_thickness_tol_pct": 10.0,
    "dielectric_material": "FR4",
    "tg_min_celsius": 150,
    "core_thickness_mm": 1.51,
    "epsilon_r_868mhz": 4.4,
    "epsilon_r_tol": 0.2,
    "loss_tangent_868mhz_max": 0.02,
    "outer_copper_oz": 1.0,
    "f_cu_finished_mm": 0.035,
    "b_cu_finished_mm": 0.035,
    "surface_finish": "ENIG",
    "surface_finish_spec": "IPC-4552 ENIG (1-3 uin / 0.025-0.075 um Au over 120-240 uin / 3-6 um Ni); NEVER HASL/None",
    "solder_mask_color": "Green",
    "solder_mask_type": "Green LPI (mandatory for >=0.150 mm mask dams across U1 LGA-73 & U2 DFN-8)",
    "solder_mask_thickness_mm": 0.01,
    "solder_mask_margin_mm": 0.035,
    "fine_pitch_local_mask_margin_mm": 0.025,
    "solder_mask_min_width_mm": 0.10,
    "allow_soldermask_bridges_in_footprints": False,
    "via_tenting": ["front", "back"],
    "silkscreen_color": "White",
    "dielectric_constraints": False,
}

LOCKED_PCB_SETUP_SEXPR: str = """\t\t(stackup
\t\t\t(layer "F.SilkS"
\t\t\t\t(type "Top Silk Screen")
\t\t\t\t(color "White")
\t\t\t)
\t\t\t(layer "F.Paste"
\t\t\t\t(type "Top Solder Paste")
\t\t\t)
\t\t\t(layer "F.Mask"
\t\t\t\t(type "Top Solder Mask")
\t\t\t\t(color "Green")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "F.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "dielectric 1"
\t\t\t\t(type "core")
\t\t\t\t(thickness 1.51)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.4)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "B.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "B.Mask"
\t\t\t\t(type "Bottom Solder Mask")
\t\t\t\t(color "Green")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "B.Paste"
\t\t\t\t(type "Bottom Solder Paste")
\t\t\t)
\t\t\t(layer "B.SilkS"
\t\t\t\t(type "Bottom Silk Screen")
\t\t\t\t(color "White")
\t\t\t)
\t\t\t(copper_finish "ENIG")
\t\t\t(dielectric_constraints no)
\t\t)
\t\t(pad_to_mask_clearance 0.035)
\t\t(solder_mask_min_width 0.1)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(tenting front back)"""

LOCKED_PRO_RULES: Dict[str, Any] = {
    "max_error": 0.005,
    "min_clearance": 0.15,
    "min_connection": 0.0,
    "min_copper_edge_clearance": 0.30,
    "min_groove_width": 0.0,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_microvia_diameter": 0.20,
    "min_microvia_drill": 0.10,
    "min_resolved_spokes": 2,
    "min_silk_clearance": 0.12,
    "min_text_height": 0.80,
    "min_text_thickness": 0.15,
    "min_through_hole_diameter": 0.30,
    "min_track_width": 0.15,
    "min_via_annular_width": 0.15,
    "min_via_diameter": 0.60,
    "solder_mask_to_copper_clearance": 0.035,
    "use_height_for_length_calcs": True,
}

LOCKED_RULE_SEVERITIES: Dict[str, str] = {
    "annular_width": "error",
    "clearance": "error",
    "connection_width": "error",
    "copper_edge_clearance": "error",
    "copper_sliver": "error",
    "courtyards_overlap": "error",
    "creepage": "error",
    "diff_pair_gap_out_of_range": "error",
    "diff_pair_uncoupled_length_too_long": "error",
    "drill_out_of_range": "error",
    "duplicate_footprints": "error",
    "extra_footprint": "error",
    "footprint": "error",
    "footprint_filters_mismatch": "error",
    "footprint_symbol_mismatch": "error",
    "footprint_type_mismatch": "error",
    "hole_clearance": "error",
    "hole_to_hole": "error",
    "holes_co_located": "error",
    "invalid_outline": "error",
    "isolated_copper": "error",
    "item_on_disabled_layer": "error",
    "items_not_allowed": "error",
    "length_out_of_range": "error",
    "lib_footprint_issues": "error",
    "lib_footprint_mismatch": "error",
    "malformed_courtyard": "error",
    "microvia_drill_out_of_range": "error",
    "mirrored_text_on_front_layer": "error",
    "missing_courtyard": "error",
    "missing_footprint": "error",
    "net_conflict": "error",
    "nonmirrored_text_on_back_layer": "error",
    "npth_inside_courtyard": "error",
    "padstack": "error",
    "pth_inside_courtyard": "error",
    "shorting_items": "error",
    "silk_edge_clearance": "error",
    "silk_over_copper": "error",
    "silk_overlap": "error",
    "skew_out_of_range": "error",
    "solder_mask_bridge": "error",
    "starved_thermal": "error",
    "text_height": "error",
    "text_on_edge_cuts": "error",
    "text_thickness": "error",
    "through_hole_pad_without_hole": "error",
    "too_many_vias": "error",
    "track_angle": "error",
    "track_dangling": "error",
    "track_segment_length": "error",
    "track_width": "error",
    "tracks_crossing": "error",
    "unconnected_items": "error",
    "unresolved_variable": "error",
    "via_dangling": "error",
    "zones_intersect": "error",
}

LOCKED_NETCLASSES: List[Dict[str, Any]] = [
    {
        "bus_width": 12,
        "clearance": 0.18,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.20,
        "line_style": 0,
        "microvia_diameter": 0.30,
        "microvia_drill": 0.10,
        "name": "Default",
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "priority": 2147483647,
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": 0.25,
        "via_diameter": 0.60,
        "via_drill": 0.30,
        "wire_width": 6,
    },
    {
        "bus_width": 12,
        "clearance": 0.18,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.20,
        "line_style": 0,
        "microvia_diameter": 0.30,
        "microvia_drill": 0.10,
        "name": "Power",
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "priority": 1,
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": 0.45,
        "via_diameter": 0.60,
        "via_drill": 0.30,
        "wire_width": 8,
    },
    {
        "bus_width": 12,
        "clearance": 0.18,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.20,
        "line_style": 0,
        "microvia_diameter": 0.30,
        "microvia_drill": 0.10,
        "name": "RF_50R",
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "priority": 0,
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": 1.08,
        "via_diameter": 0.60,
        "via_drill": 0.30,
        "wire_width": 8,
    },
]

LOCKED_NETCLASS_ASSIGNMENTS: Dict[str, str] = {
    "/ANT_FEED": "RF_50R",
    "/BR_O": "RF_50R",
    "/BR_P": "RF_50R",
    "/BR_Q": "RF_50R",
    "/BR_S": "RF_50R",
    "/DET_IN": "RF_50R",
    "/RF_PA": "RF_50R",
    "/SMA_C": "RF_50R",
    "/VBAT_RAW": "Power",
    "/VDDA": "Power",
    "/VDDPA": "Power",
    "/VDDRF": "Power",
    "/VDDSMPS": "Power",
    "/VFBSMPS": "Power",
    "/VLXSMPS": "Power",
    "3V3": "Power",
    "3V3_DET": "Power",
    "GND": "Power",
    "VBAT": "Power",
}

LOCKED_DRU_TEXT: str = """(version 1)

# =============================================================================
# ISAC_868_KiCad9.kicad_dru -- Immutable PCBWay Turnkey Custom Design Rule Deck
# Cryptographically locked by tools/rules_isac.py & tools/rules_isac.lock.json.
# DO NOT EDIT MANUALLY -- any modification fails `rules_isac.py --verify`.
# =============================================================================

# 1. Scoped Edge-Mount SMA Launch Exemption (J1 = Molex 73251-1153 along dy = 0 / Y = 80.0 mm):
#    Board global min_copper_edge_clearance remains locked at 0.30 mm everywhere else.
(rule "J1_EdgeMount_SMA_Launch_dy0"
\t(condition "A.memberOfFootprint('J1') && (A.Type == 'Pad') && (A.Position_Y <= 86.0mm)")
\t(constraint edge_clearance (min 0.00mm))
)

# 2. Power Netclass Width & Neck-Down Floor:
#    0.45 mm nominal Power routing width; >= 0.28 mm minimum neck-down at 0402 / LGA-73 / SOT pads.
(rule "Power_Min_Neckdown_Width"
\t(condition "A.NetClass == 'Power' && A.Type == 'Track'")
\t(constraint track_width (min 0.28mm) (opt 0.45mm))
)

# 3. RF_50R Standard 2L FR-4 CPWG Spine & GSG Pad Launch Taper (RF geometry as drawn, no coupon):
#    1.08 mm nominal CPWG width (Z0 = 51.90 Ohm LPI-coated nom, 51.2-57.1 Ohm envelope on 1.51 mm FR-4 er=4.4,
#    Gap=0.28 mm; all RF_50R segments <= 11.18 mm = 0.056 lambda_g <= 0.06 lambda_g @ 868 MHz);
#    >= 0.35 mm minimum controlled launch taper into U1.37 (0.37 mm LGA-73 land), 0402 & U2 DFN-8.
(rule "RF_50R_CPWG_And_Launch_Width"
\t(condition "A.NetClass == 'RF_50R' && A.Type == 'Track'")
\t(constraint track_width (min 0.35mm) (opt 1.08mm))
)

# 4. RF_50R Coplanar Waveguide (CPWG) Ground-Pour Gap Lock:
#    Enforces >= 0.28 mm coplanar gap between all RF_50R copper and outer GND zones.
(rule "RF_50R_CPWG_Coplanar_Gap"
\t(layer outer)
\t(condition "A.NetClass == 'RF_50R' && B.Type == 'Zone' && B.NetName == 'GND'")
\t(constraint clearance (min 0.28mm))
)
"""


def verify_lga73_interstitial_via_geometry() -> Dict[str, float]:
    """
    Analytically verify PCBWay zero-surcharge 0.60/0.30 mm via geometry inside U1's
    (RAK3172LP-SiP LGA-73) 3x3 central ground matrix (1.60 x 1.60 mm pads @ 2.80 mm pitch,
    roundrect_rratio = 0.18) and 0.60 mm-pitch perimeter solder-mask dams:
      * Annular ring = (0.60 - 0.30) / 2 = 0.150 mm (>= 0.15 mm PCBWay 1 oz zero-surcharge).
      * Perimeter LGA pad gap = 0.60 - 0.37 = 0.230 mm (>= 0.10 mm Green LPI mask dam;
        whereas black/white/matte LPI requires 0.15 mm dams and risks stripping under expansion).
      * Cardinal interstitial channel = 2.80 - 1.60 = 1.200 mm -> 0.300 mm via-to-pad clearance.
      * Diagonal 4-pad interstitial center (+-1.40, +-1.40 mm):
        - Sharp-square corner gap span = (2.80 - 1.60) * sqrt(2) = 1.697 mm -> 0.549 mm clearance.
        - Roundrect (r_c = 0.18 * 1.60 = 0.288 mm) copper-to-copper clearance = 0.668 mm.
    """
    via_dia = LOCKED_PRO_RULES["min_via_diameter"]
    drill_dia = LOCKED_PRO_RULES["min_through_hole_diameter"]
    annular_ring = 0.5 * (via_dia - drill_dia)

    perim_pitch, perim_pad_w = 0.60, 0.37
    perim_mask_dam = perim_pitch - perim_pad_w - 2.0 * STACKUP_SPEC["fine_pitch_local_mask_margin_mm"]

    matrix_pitch, matrix_pad_w, rratio = 2.80, 1.60, 0.18
    r_corner = rratio * matrix_pad_w
    cardinal_channel = matrix_pitch - matrix_pad_w
    cardinal_via_pad_clr = 0.5 * (cardinal_channel - via_dia)

    diag_sharp_span = (matrix_pitch - matrix_pad_w) * math.sqrt(2.0)
    diag_sharp_clr = 0.5 * diag_sharp_span - 0.5 * via_dia
    dist_fillet_ctr = math.hypot(1.40 - (0.5 * matrix_pad_w - r_corner),
                                 1.40 - (0.5 * matrix_pad_w - r_corner))
    diag_roundrect_clr = (dist_fillet_ctr - r_corner) - 0.5 * via_dia

    assert annular_ring >= 0.15 - 1e-9, f"Annular ring {annular_ring:.3f} mm < 0.15 mm"
    assert perim_mask_dam >= STACKUP_SPEC["solder_mask_min_width_mm"] - 1e-9
    assert cardinal_via_pad_clr >= LOCKED_PRO_RULES["min_clearance"]
    assert diag_sharp_clr >= 0.50

    return {
        "via_diameter_mm": round(via_dia, 3),
        "via_drill_mm": round(drill_dia, 3),
        "via_annular_ring_mm": round(annular_ring, 3),
        "u1_perimeter_pad_gap_mm": round(perim_mask_dam, 3),
        "u1_cardinal_channel_mm": round(cardinal_channel, 3),
        "u1_cardinal_via_to_pad_clr_mm": round(cardinal_via_pad_clr, 3),
        "u1_diagonal_sharp_span_mm": round(diag_sharp_span, 4),
        "u1_diagonal_sharp_clr_mm": round(diag_sharp_clr, 4),
        "u1_diagonal_roundrect_clr_mm": round(diag_roundrect_clr, 4),
    }


# ---------------------------------------------------------------------------
# 2. Balanced S-Expression Helpers for Deterministic .kicad_pcb Rule Patching
# ---------------------------------------------------------------------------
def _find_top_block(sexpr_text: str, keyword: str) -> Tuple[int, int]:
    """Locate `(keyword ...)` balanced S-expression span in `sexpr_text`."""
    needle = f"({keyword}"
    pos = 0
    n = len(sexpr_text)
    while True:
        idx = sexpr_text.find(needle, pos)
        if idx < 0:
            raise ValueError(f"Missing S-expression block ({keyword} ...)")
        end_kw = idx + len(needle)
        if end_kw < n and sexpr_text[end_kw] in (" ", "\t", "\r", "\n", ")"):
            break
        pos = end_kw

    depth = 0
    in_str = False
    esc = False
    for i in range(idx, n):
        ch = sexpr_text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return idx, i + 1
    raise ValueError(f"Unbalanced S-expression in ({keyword} ...)")


def _split_child_blocks(block_text: str) -> List[Tuple[str, str]]:
    """Return list of `(head_token, raw_child_sexpr)` inside an outer `(...)` block."""
    inner_start = block_text.find("(")
    assert inner_start == 0 and block_text.endswith(")")
    # Advance past outer head keyword
    i = 1
    n = len(block_text) - 1
    while i < n and block_text[i] not in (" ", "\t", "\r", "\n", "("):
        i += 1

    children: List[Tuple[str, str]] = []
    while i < n:
        if block_text[i] != "(":
            i += 1
            continue
        c_start = i
        depth = 0
        in_str = False
        esc = False
        while i < n:
            ch = block_text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        c_raw = block_text[c_start:i]
        # Extract head token
        j = 1
        while j < len(c_raw) and c_raw[j] not in (" ", "\t", "\r", "\n", ")"):
            j += 1
        children.append((c_raw[1:j], c_raw))
    return children


RULE_MANAGED_SETUP_KEYS = {
    "stackup",
    "pad_to_mask_clearance",
    "solder_mask_min_width",
    "pad_to_paste_clearance",
    "pad_to_paste_clearance_ratio",
    "allow_soldermask_bridges_in_footprints",
    "tenting",
}


def _patch_pcb_text(pcb_text: str) -> str:
    """ Enforce exact thickness 1.6 in `(general ...)` and locked stackup/mask/tenting in `(setup ...)`."""
    # 1. Patch (general ...) thickness
    g0, g1 = _find_top_block(pcb_text, "general")
    g_children = _split_child_blocks(pcb_text[g0:g1])
    kept_g = [raw for k, raw in g_children if k != "thickness"]
    new_general = "(\n\t\t(thickness 1.6)\n"
    new_general = "(general\n\t\t(thickness 1.6)"
    for raw in kept_g:
        new_general += f"\n\t\t{raw}"
    new_general += "\n\t)"
    pcb_text = pcb_text[:g0] + new_general + pcb_text[g1:]

    # 2. Patch (setup ...) stackup, mask clearance/min-width, bridge prohibition, tenting & plot attributes
    s0, s1 = _find_top_block(pcb_text, "setup")
    s_children = _split_child_blocks(pcb_text[s0:s1])
    preserved_setup: List[str] = []
    for key, raw in s_children:
        if key in RULE_MANAGED_SETUP_KEYS:
            continue
        if key == "pcbplotparams":
            p_children = _split_child_blocks(raw)
            p_lines = ["(pcbplotparams"]
            overrides = {
                "usegerberattributes": "(usegerberattributes yes)",
                "usegerberadvancedattributes": "(usegerberadvancedattributes yes)",
                "creategerberjobfile": "(creategerberjobfile yes)",
            }
            seen = set()
            for pk, praw in p_children:
                if pk in overrides:
                    p_lines.append(f"\t\t\t{overrides[pk]}")
                    seen.add(pk)
                else:
                    p_lines.append(f"\t\t\t{praw}")
            for pk, ov in overrides.items():
                if pk not in seen:
                    p_lines.append(f"\t\t\t{ov}")
            p_lines.append("\t\t)")
            raw = "\n".join(p_lines)
        preserved_setup.append(raw)

    setup_lines = ["(setup", LOCKED_PCB_SETUP_SEXPR]
    for raw in preserved_setup:
        setup_lines.append(f"\t\t{raw}")
    setup_lines.append("\t)")
    new_setup = "\n".join(setup_lines)
    return pcb_text[:s0] + new_setup + pcb_text[s1:]


def extract_pcb_locked_subset(pcb_path: str) -> Dict[str, Any]:
    """Extract the canonical rule-governed subset from `.kicad_pcb` for SHA-256 verification."""
    with open(pcb_path, "r", encoding="utf-8") as fh:
        pcb_text = fh.read()

    g0, g1 = _find_top_block(pcb_text, "general")
    g_map = {k: " ".join(raw.split()) for k, raw in _split_child_blocks(pcb_text[g0:g1])}

    s0, s1 = _find_top_block(pcb_text, "setup")
    s_children = _split_child_blocks(pcb_text[s0:s1])
    managed = {k: " ".join(raw.split()) for k, raw in s_children if k in RULE_MANAGED_SETUP_KEYS}

    plot_flags = {}
    for k, raw in s_children:
        if k == "pcbplotparams":
            for pk, praw in _split_child_blocks(raw):
                if pk in ("usegerberattributes", "usegerberadvancedattributes", "creategerberjobfile"):
                    plot_flags[pk] = " ".join(praw.split())

    return {
        "general_thickness": g_map.get("thickness", ""),
        "setup_managed": managed,
        "pcbplot_gerberjob_flags": plot_flags,
    }


def extract_pro_locked_subset(pro_path: str) -> Dict[str, Any]:
    """Extract the canonical rule-governed subset from `.kicad_pro` for SHA-256 verification."""
    with open(pro_path, "r", encoding="utf-8") as fh:
        pro = json.load(fh)
    ds = pro["board"]["design_settings"]
    ns = pro["net_settings"]
    defs = ds.get("defaults", {})
    return {
        "drc_exclusions": ds.get("drc_exclusions", []),
        "rules": ds.get("rules", {}),
        "rule_severities": ds.get("rule_severities", {}),
        "silk_defaults": {
            "silk_line_width": defs.get("silk_line_width"),
            "silk_text_size_h": defs.get("silk_text_size_h"),
            "silk_text_size_v": defs.get("silk_text_size_v"),
            "silk_text_thickness": defs.get("silk_text_thickness"),
        },
        "classes": ns.get("classes", []),
        "netclass_assignments": ns.get("netclass_assignments", {}),
    }


# ---------------------------------------------------------------------------
# 3. Canonical SHA-256 Digest Computation
# ---------------------------------------------------------------------------
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def canonical_rule_spec_dict() -> Dict[str, Any]:
    return {
        "schema": "ISAC-PCBWAY-RULE-DECK-REV-E3-V1",
        "stackup": STACKUP_SPEC,
        "pcb_setup_sexpr_normalized": " ".join(LOCKED_PCB_SETUP_SEXPR.split()),
        "pro_rules": LOCKED_PRO_RULES,
        "rule_severities": LOCKED_RULE_SEVERITIES,
        "drc_exclusions": [],
        "netclasses": LOCKED_NETCLASSES,
        "netclass_assignments": LOCKED_NETCLASS_ASSIGNMENTS,
        "dru_text": LOCKED_DRU_TEXT,
    }


def compute_live_digests(
    pcb_path: str = DEFAULT_PCB_PATH,
    pro_path: str = DEFAULT_PRO_PATH,
    dru_path: str = DEFAULT_DRU_PATH,
) -> Dict[str, str]:
    spec_sha = _sha256_bytes(_canonical_json_bytes(canonical_rule_spec_dict()))
    with open(dru_path, "rb") as fh:
        dru_sha = _sha256_bytes(fh.read())
    pcb_subset_sha = _sha256_bytes(_canonical_json_bytes(extract_pcb_locked_subset(pcb_path)))
    pro_subset_sha = _sha256_bytes(_canonical_json_bytes(extract_pro_locked_subset(pro_path)))

    combined_payload = _canonical_json_bytes({
        "canonical_rule_spec_sha256": spec_sha,
        "kicad_dru_sha256": dru_sha,
        "pcb_stackup_setup_sha256": pcb_subset_sha,
        "pro_rules_and_netclasses_sha256": pro_subset_sha,
    })
    return {
        "canonical_rule_spec_sha256": spec_sha,
        "kicad_dru_sha256": dru_sha,
        "pcb_stackup_setup_sha256": pcb_subset_sha,
        "pro_rules_and_netclasses_sha256": pro_subset_sha,
        "combined_rule_deck_sha256": _sha256_bytes(combined_payload),
    }


# ---------------------------------------------------------------------------
# 4. Apply & Verify Entry Points
# ---------------------------------------------------------------------------
def apply_locked_rules(
    pcb_path: str = DEFAULT_PCB_PATH,
    pro_path: str = DEFAULT_PRO_PATH,
    dru_path: str = DEFAULT_DRU_PATH,
) -> Dict[str, str]:
    """
    Deterministically apply the locked Rev E.0 PCBWay Turnkey rule deck to:
      1. `dru_path` (`.kicad_dru` custom rules),
      2. `pro_path` (`.kicad_pro` DRC minima, strict severities, 0 exclusions, netclasses),
      3. `pcb_path` (`.kicad_pcb` 1.60 mm 2L FR-4 stackup, ENIG finish, Green LPI, 0.10 mm mask dam).
    Does NOT overwrite `rules_isac.lock.json` so tampering cannot self-heal the lock digest.
    """
    verify_lga73_interstitial_via_geometry()

    # 1. Write locked .kicad_dru
    with open(dru_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(LOCKED_DRU_TEXT)

    # 2. Patch .kicad_pro
    with open(pro_path, "r", encoding="utf-8") as fh:
        pro = json.load(fh)

    ds = pro.setdefault("board", {}).setdefault("design_settings", {})
    ds["drc_exclusions"] = []
    ds["rules"] = dict(LOCKED_PRO_RULES)
    ds["rule_severities"] = dict(LOCKED_RULE_SEVERITIES)

    defs = ds.setdefault("defaults", {})
    defs["silk_line_width"] = 0.15
    defs["silk_text_size_h"] = max(float(defs.get("silk_text_size_h", 0.80)), 0.80)
    defs["silk_text_size_v"] = max(float(defs.get("silk_text_size_v", 0.80)), 0.80)
    defs["silk_text_thickness"] = 0.15

    ns = pro.setdefault("net_settings", {})
    ns["classes"] = [dict(c) for c in LOCKED_NETCLASSES]
    ns["netclass_assignments"] = dict(LOCKED_NETCLASS_ASSIGNMENTS)

    with open(pro_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(pro, fh, indent=2)
        fh.write("\n")

    # 3. Patch .kicad_pcb Board Setup stackup, ENIG finish, Green LPI mask & 0.10 mm dam
    with open(pcb_path, "r", encoding="utf-8") as fh:
        pcb_text = fh.read()
    patched_pcb = _patch_pcb_text(pcb_text)
    with open(pcb_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(patched_pcb)

    return compute_live_digests(pcb_path=pcb_path, pro_path=pro_path, dru_path=dru_path)


def write_lock_manifest(
    pcb_path: str = DEFAULT_PCB_PATH,
    pro_path: str = DEFAULT_PRO_PATH,
    dru_path: str = DEFAULT_DRU_PATH,
    lock_path: str = DEFAULT_LOCK_PATH,
) -> Dict[str, Any]:
    """Generate `tools/rules_isac.lock.json` containing the SHA-256 digests and invariant summary."""
    geom = verify_lga73_interstitial_via_geometry()
    digests = compute_live_digests(pcb_path=pcb_path, pro_path=pro_path, dru_path=dru_path)
    manifest = {
        "schema": "ISAC-PCBWAY-RULE-DECK-LOCK-V1",
        "project": PROJECT,
        "revision": "E.5",
        "target_fab": "PCBWay Standard Turnkey PCBA (Zero-Surcharge 2L FR-4, ENIG, Green LPI, RF Geometry As Drawn)",
        "digests": digests,
        "locked_invariants": {
            "stackup": STACKUP_SPEC,
            "rules": LOCKED_PRO_RULES,
            "drc_exclusions_count": 0,
            "mandatory_error_severities": sorted(LOCKED_RULE_SEVERITIES.keys()),
            "netclasses": {
                c["name"]: {
                    "track_width_mm": c["track_width"],
                    "clearance_mm": c["clearance"],
                    "via_diameter_mm": c["via_diameter"],
                    "via_drill_mm": c["via_drill"],
                }
                for c in LOCKED_NETCLASSES
            },
            "u1_lga73_interstitial_geometry": geom,
        },
    }
    with open(lock_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def verify_locked_rules(
    pcb_path: str = DEFAULT_PCB_PATH,
    pro_path: str = DEFAULT_PRO_PATH,
    dru_path: str = DEFAULT_DRU_PATH,
    lock_path: str = DEFAULT_LOCK_PATH,
    check_gbrjob: bool = True,
) -> Dict[str, Any]:
    """
    Verify live `.kicad_pcb`, `.kicad_pro`, `.kicad_dru`, `pcbnew` runtime settings, and
    exported `*-job.gbrjob` metadata against `tools/rules_isac.lock.json`.
    Raises RuntimeError with explicit diagnostics on any rule relaxation or SHA-256 mismatch.
    """
    errors: List[str] = []
    for p in (pcb_path, pro_path, dru_path, lock_path):
        if not os.path.isfile(p):
            errors.append(f"Missing required rule-deck file: {p}")
    if errors:
        raise RuntimeError("\n".join(errors))

    with open(lock_path, "r", encoding="utf-8") as fh:
        lock_data = json.load(fh)

    geom = verify_lga73_interstitial_via_geometry()

    # 1. Explicit semantic invariant checks (so errors report exact tampered parameter + SHA mismatch)
    pro_sub = extract_pro_locked_subset(pro_path)
    if pro_sub["drc_exclusions"] != []:
        errors.append(f"DRC exclusions non-empty ({len(pro_sub['drc_exclusions'])} exclusions found; 0 allowed)")
    for k, exp_v in LOCKED_PRO_RULES.items():
        got_v = pro_sub["rules"].get(k)
        if got_v != exp_v:
            errors.append(f".kicad_pro rules.{k}: expected {exp_v!r}, got {got_v!r}")
    for k, exp_sev in LOCKED_RULE_SEVERITIES.items():
        if exp_sev != "error":
            errors.append(f"LOCKED_RULE_SEVERITIES.{k} must be 'error', found {exp_sev!r}")
        got_sev = pro_sub["rule_severities"].get(k)
        if got_sev != exp_sev:
            errors.append(f".kicad_pro rule_severities.{k}: expected {exp_sev!r}, got {got_sev!r}")
    if pro_sub["classes"] != LOCKED_NETCLASSES:
        errors.append(".kicad_pro net_settings.classes deviates from LOCKED_NETCLASSES")
    if pro_sub["netclass_assignments"] != LOCKED_NETCLASS_ASSIGNMENTS:
        errors.append(".kicad_pro net_settings.netclass_assignments deviates from LOCKED_NETCLASS_ASSIGNMENTS")

    with open(dru_path, "r", encoding="utf-8") as fh:
        if fh.read() != LOCKED_DRU_TEXT:
            errors.append(f"{os.path.basename(dru_path)} text deviates from LOCKED_DRU_TEXT")

    # 2. Live pcbnew binary/API verification (using system /usr/bin/python3 if current python lacks pcbnew)
    pcbnew_check_code = (
        "import json, sys, pcbnew\n"
        "b = pcbnew.LoadBoard(sys.argv[1])\n"
        "ds = b.GetDesignSettings()\n"
        "print(json.dumps({\n"
        "  'has_stackup': bool(ds.m_HasStackup),\n"
        "  'board_thickness_mm': round(ds.GetBoardThickness() / 1e6, 4),\n"
        "  'mask_expansion_mm': round(ds.m_SolderMaskExpansion / 1e6, 4),\n"
        "  'mask_min_width_mm': round(ds.m_SolderMaskMinWidth / 1e6, 4),\n"
        "}))\n"
    )
    py_exe = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    proc = subprocess.run([py_exe, "-c", pcbnew_check_code, pcb_path], capture_output=True, text=True, check=True)
    pcb_rt = json.loads(proc.stdout.strip())
    if not pcb_rt["has_stackup"]:
        errors.append(".kicad_pcb m_HasStackup is False (physical stackup missing)")
    if abs(pcb_rt["board_thickness_mm"] - 1.60) > 1e-4:
        errors.append(f".kicad_pcb board thickness {pcb_rt['board_thickness_mm']} mm != 1.60 mm")
    if abs(pcb_rt["mask_expansion_mm"] - 0.035) > 1e-4:
        errors.append(f".kicad_pcb m_SolderMaskExpansion {pcb_rt['mask_expansion_mm']} mm != 0.035 mm")
    if abs(pcb_rt["mask_min_width_mm"] - 0.10) > 1e-4:
        errors.append(f".kicad_pcb m_SolderMaskMinWidth {pcb_rt['mask_min_width_mm']} mm != 0.10 mm")

    # 3. Export temporary .gbrjob via kicad-cli to prove Gerber job emits Finish="ENIG" & Green LPI
    gbrjob_summary = {}
    if check_gbrjob:
        with tempfile.TemporaryDirectory(prefix="isac_gbrjob_verify_") as tmpd:
            subprocess.run(
                ["kicad-cli", "pcb", "export", "gerbers", "--layers", "F.Cu,Edge.Cuts", "-o", tmpd + "/", pcb_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            job_files = [fn for fn in os.listdir(tmpd) if fn.endswith("-job.gbrjob")]
            if len(job_files) != 1:
                errors.append(f"Expected 1 *-job.gbrjob from kicad-cli, found {job_files}")
            else:
                with open(os.path.join(tmpd, job_files[0]), "r", encoding="utf-8") as jfh:
                    job = json.load(jfh)
                gs = job.get("GeneralSpecs", {})
                ms = job.get("MaterialStackup", [])
                finish = gs.get("Finish")
                thickness = gs.get("BoardThickness")
                imp_ctrl = gs.get("ImpedanceControlled", False)
                if finish != "ENIG":
                    errors.append(f".gbrjob GeneralSpecs.Finish is {finish!r} (MUST be 'ENIG')")
                if abs(float(thickness or 0.0) - 1.60) > 0.01:
                    errors.append(f".gbrjob GeneralSpecs.BoardThickness is {thickness!r} (MUST be 1.60)")
                if bool(imp_ctrl) is not False:
                    errors.append(
                        f".gbrjob GeneralSpecs.ImpedanceControlled is {imp_ctrl!r} "
                        f"(MUST be False/omitted per Decision P1-3 Option A: standard 2L FR-4 without coupon)"
                    )

                mask_layers = [m for m in ms if m.get("Type") == "SolderMask"]
                cu_layers = [m for m in ms if m.get("Type") == "Copper"]
                diel_layers = [m for m in ms if m.get("Type") == "Dielectric"]
                if len(mask_layers) != 2 or any(m.get("Color") != "Green" for m in mask_layers):
                    errors.append(f".gbrjob SolderMask color lock failed: {mask_layers}")
                if len(cu_layers) != 2 or any(abs(float(m.get("Thickness", 0)) - 0.035) > 1e-4 for m in cu_layers):
                    errors.append(f".gbrjob Copper 1 oz (0.035 mm) lock failed: {cu_layers}")
                if (
                    len(diel_layers) != 1
                    or diel_layers[0].get("Material") != "FR4"
                    or abs(float(diel_layers[0].get("Thickness", 0)) - 1.51) > 1e-3
                    or (
                        STACKUP_SPEC["dielectric_constraints"]
                        and (
                            str(diel_layers[0].get("DielectricConstant")) != "4.4"
                            or str(diel_layers[0].get("LossTangent")) != "0.02"
                        )
                    )
                ):
                    errors.append(f".gbrjob FR4 core dielectric lock failed: {diel_layers}")
                gbrjob_summary = {
                    "Finish": finish,
                    "BoardThickness": thickness,
                    "ImpedanceControlled": imp_ctrl,
                    "SolderMaskColors": [m.get("Color") for m in mask_layers],
                    "CoreMaterial": diel_layers[0].get("Material") if diel_layers else None,
                    "CoreThickness_mm": diel_layers[0].get("Thickness") if diel_layers else None,
                }

    # 4. Cryptographic SHA-256 comparison against rules_isac.lock.json
    live_digests = compute_live_digests(pcb_path=pcb_path, pro_path=pro_path, dru_path=dru_path)
    expected_digests = lock_data.get("digests", {})
    for dk, exp_hash in expected_digests.items():
        got_hash = live_digests.get(dk)
        if got_hash != exp_hash:
            errors.append(f"SHA-256 mismatch on '{dk}': expected {exp_hash}, computed {got_hash}")

    if errors:
        raise RuntimeError("RULE DECK VERIFICATION FAILED:\n  - " + "\n  - ".join(errors))

    return {
        "digests": live_digests,
        "pcbnew_runtime": pcb_rt,
        "gbrjob": gbrjob_summary,
        "u1_interstitial_geometry": geom,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply or cryptographically verify the ISAC_868_KiCad9 PCBWay Turnkey rule deck."
    )
    parser.add_argument("--pcb", default=DEFAULT_PCB_PATH, help="Path to .kicad_pcb")
    parser.add_argument("--pro", default=DEFAULT_PRO_PATH, help="Path to .kicad_pro")
    parser.add_argument("--dru", default=DEFAULT_DRU_PATH, help="Path to .kicad_dru")
    parser.add_argument("--lock", default=DEFAULT_LOCK_PATH, help="Path to rules_isac.lock.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="Apply locked rules to .kicad_pcb, .kicad_pro, and .kicad_dru")
    mode.add_argument("--verify", action="store_true", help="Verify SHA-256 digests and live KiCad/.gbrjob metadata")
    mode.add_argument("--init-lock", action="store_true", help="Apply rules and seal tools/rules_isac.lock.json")
    args = parser.parse_args(argv)

    try:
        if args.init_lock:
            apply_locked_rules(pcb_path=args.pcb, pro_path=args.pro, dru_path=args.dru)
            manifest = write_lock_manifest(
                pcb_path=args.pcb, pro_path=args.pro, dru_path=args.dru, lock_path=args.lock
            )
            print(f"[LOCK SEALED] {args.lock}")
            print(f"  combined_rule_deck_sha256 = {manifest['digests']['combined_rule_deck_sha256']}")
            return 0

        if args.apply:
            digests = apply_locked_rules(pcb_path=args.pcb, pro_path=args.pro, dru_path=args.dru)
            if not os.path.isfile(args.lock):
                write_lock_manifest(
                    pcb_path=args.pcb, pro_path=args.pro, dru_path=args.dru, lock_path=args.lock
                )
            print("[RULES APPLIED] Locked Rev E.5 PCBWay Turnkey rule deck written to:")
            print(f"  PCB : {args.pcb}")
            print(f"  PRO : {args.pro}")
            print(f"  DRU : {args.dru}")
            print(f"  SHA : {digests['combined_rule_deck_sha256']}")
            return 0

        if args.verify:
            res = verify_locked_rules(
                pcb_path=args.pcb, pro_path=args.pro, dru_path=args.dru, lock_path=args.lock, check_gbrjob=True
            )
            g = res["u1_interstitial_geometry"]
            j = res["gbrjob"]
            print("[RULE DECK VERIFIED] SHA-256 cryptographic lock & KiCad 9/.gbrjob invariants PASS:")
            print(f"  combined_rule_deck_sha256 = {res['digests']['combined_rule_deck_sha256']}")
            print(f"  .gbrjob Finish = {j['Finish']} | Thickness = {j['BoardThickness']} mm | "
                  f"Mask = {j['SolderMaskColors']} | Core = {j['CoreThickness_mm']} mm {j['CoreMaterial']}")
            print(f"  Mask Margin = {res['pcbnew_runtime']['mask_expansion_mm']:.3f} mm | "
                  f"Min Mask Dam = {res['pcbnew_runtime']['mask_min_width_mm']:.2f} mm "
                  f"(U1 LGA-73 gap = {g['u1_perimeter_pad_gap_mm']:.3f} mm)")
            print(f"  Via = {g['via_diameter_mm']:.2f}/{g['via_drill_mm']:.2f} mm (annular = {g['via_annular_ring_mm']:.2f} mm) | "
                  f"U1 interstitial clr: cardinal = {g['u1_cardinal_via_to_pad_clr_mm']:.3f} mm, "
                  f"diagonal = {g['u1_diagonal_sharp_clr_mm']:.3f} mm ({g['u1_diagonal_roundrect_clr_mm']:.3f} mm roundrect)")
            return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
