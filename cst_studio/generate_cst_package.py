#!/usr/bin/env python3
"""
KiCad-to-CST Studio Suite 3D model exporter for ISAC_868_KiCad9 (Rev E.5).

Reads copper polygons, CPWG feed geometry, 0402 harmonic Pi-filter pads, GND
stitching/return vias, bare-ENIG solder-mask window, and ASA/PETG enclosure
dimensions from `ISAC_868_KiCad9.kicad_pcb` and `ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod`
(read-only, without modifying the frozen Rev E.5 hardware files) and generates:

  1. cst_studio/macros/ISAC_868_Complete_Antenna_MWS.bas
       Native CST Microwave Studio 3D VBA macro (Time-Domain FIT solver, 0.70-3.00 GHz,
       parametric superstrates with 1st-order Debye dispersion, ENIG surface loss,
       local hexahedral subgrids, E/H/Surface-Current/Loss/Farfield monitors).
  2. cst_studio/macros/ISAC_868_Setup_FEM_CrossCheck.bas
       CST Tetrahedral Frequency-Domain (FEM) solver cross-check macro with curved
       elements and adaptive mesh refinement at 866.5 MHz.
  3. cst_studio/macros/ISAC_868_Sweep_All_Superstrates.bas
       Automated 10-scenario CST VBA parameter sweep exporting Touchstone v1.1 (.s1p)
       and Farfield efficiency/gain tables into cst_studio/results/.
  4. cst_studio/macros/ISAC_868_FrontEnd_CoSim_DS.bas
       CST Design Studio (DS) schematic co-simulation macro cascading the 3D EM block
       with Murata S-parameter / RLC filter blocks, the asymmetric return-loss bridge,
       and the Analog Devices LT5538 input load (291.65 Ohm || 1.194 pF).
  5. cst_studio/cad_exports/*.dxf & geometry_manifest.json
       Clean R2000 closed-LWPOLYLINE DXF layers in right-handed AuxOrigin coordinates
       [0..90] x [0..40] mm for optional manual CAD verification in CST.
  6. cst_studio/previews/CST_Simulation_Model_Blueprint.png
       4-panel engineering blueprint illustrating the CST 3D geometry, port & lumped
       element layout, local hexahedral mesh refinement zones, and Debye superstrates.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as MplPolygon, Rectangle
import numpy as np
import pcbnew
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "rf"))

from ifa_enclosure_mom import enig_sheet_resistance_ohm, parse_ae1_kicad_mod_gbr  # noqa: E402

PCB_PATH = ROOT / "ISAC_868_KiCad9.kicad_pcb"
MOD_PATH = ROOT / "ISAC.pretty" / "IFA_868MHz_ISAC_40x20mm.kicad_mod"

MACROS_DIR = HERE / "macros"
CAD_DIR = HERE / "cad_exports"
PREVIEWS_DIR = HERE / "previews"
RESULTS_DIR = HERE / "results"

for d in (MACROS_DIR, CAD_DIR, PREVIEWS_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_kicad_rf_geometry():
    """Read exact RF copper polygons, pads, and vias from ISAC_868_KiCad9.kicad_pcb."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    aux = board.GetDesignSettings().GetAuxOrigin()
    ox, oy = pcbnew.ToMM(aux.x), pcbnew.ToMM(aux.y)

    def gbr_xy(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (round(x_mm - ox, 4), round(oy - y_mm, 4))

    def gbr_pt(pt) -> tuple[float, float]:
        return gbr_xy(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y))

    # 1. Parse AE1 exact polygons from .kicad_mod (driven arm + grounded return bar)
    poly_ae1_union, _ = parse_ae1_kicad_mod_gbr(str(MOD_PATH))
    poly_ae1_simp = poly_ae1_union.simplify(0.004, preserve_topology=True)
    ae1_parts = list(poly_ae1_simp.geoms) if isinstance(poly_ae1_simp, MultiPolygon) else [poly_ae1_simp]
    # Sort so part with Pad 1 (50.0, 20.0) is first (Driven_Arm), Pad 2b (50.0, 5.5) is second (Return_Bar)
    ae1_parts.sort(key=lambda g: (0 if g.buffer(0.05).contains(Point(50.0, 20.0)) else 1))
    assert len(ae1_parts) == 2, f"Expected 2 AE1 copper polygons, got {len(ae1_parts)}"
    ae1_driven_poly, ae1_return_poly = ae1_parts[0], ae1_parts[1]

    # 2. Extract exact pads for C_M1, L_M1, C_MZ, C_M2, AE1, H1..H4
    pads_info: dict[str, dict[str, dict]] = {}
    for ref in ("C_M1", "L_M1", "C_MZ", "C_M2", "AE1", "H1", "H2", "H3", "H4"):
        fp = board.FindFootprintByReference(ref)
        assert fp is not None, f"Missing footprint {ref}"
        pads_info[ref] = {}
        idx_dup = 0
        for pad in fp.Pads():
            pnum = pad.GetNumber() or "NPTH"
            key = pnum if pnum not in pads_info[ref] else f"{pnum}_{idx_dup}"
            idx_dup += 1
            px, py = gbr_pt(pad.GetPosition())
            sx, sy = pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y)
            rot = pad.GetOrientationDegrees()
            if abs(rot % 180.0 - 90.0) < 1.0:
                sx, sy = sy, sx
            pads_info[ref][key] = {
                "x": round(px, 4),
                "y": round(py, 4),
                "w": round(sx, 4),
                "h": round(sy, 4),
                "net": pad.GetNetname(),
            }

    # 3. Build exact F.Cu signal polygons for /BR_Q (from X=41.20 launch plane) and /ANT_FEED
    brq_shapes = []
    ant_shapes = []
    gnd_stub_shapes = []

    for ref, pdict in pads_info.items():
        if ref in ("C_M1", "L_M1", "C_MZ", "C_M2"):
            for p in pdict.values():
                b = box(p["x"] - 0.5 * p["w"], p["y"] - 0.5 * p["h"], p["x"] + 0.5 * p["w"], p["y"] + 0.5 * p["h"])
                if p["net"] == "/BR_Q":
                    brq_shapes.append(b)
                elif p["net"] == "/ANT_FEED":
                    ant_shapes.append(b)
                elif p["net"] == "GND":
                    gnd_stub_shapes.append(b)

    vias_gnd: list[tuple[float, float, float, float]] = []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            vx, vy = gbr_pt(t.GetPosition())
            if t.GetNetname() == "GND" and vx >= 41.0:
                od = round(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), 4)
                drl = round(pcbnew.ToMM(t.GetDrillValue()), 4)
                vias_gnd.append((vx, vy, od, drl))
        else:
            if board.GetLayerName(t.GetLayer()) != "F.Cu":
                continue
            x1, y1 = gbr_pt(t.GetStart())
            x2, y2 = gbr_pt(t.GetEnd())
            w = pcbnew.ToMM(t.GetWidth())
            net = t.GetNetname()
            if net == "/BR_Q" and max(x1, x2) >= 41.20:
                # Clip West end cleanly at X = 41.20 mm port launch plane
                seg = LineString([(x1, y1), (x2, y2)]).buffer(0.5 * w, cap_style=1, join_style=1)
                brq_shapes.append(seg.intersection(box(41.20, 0.0, 90.0, 40.0)))
            elif net == "/ANT_FEED":
                seg = LineString([(x1, y1), (x2, y2)]).buffer(0.5 * w, cap_style=1, join_style=1)
                ant_shapes.append(seg)
            elif net == "GND" and max(x1, x2) >= 42.0:
                seg = LineString([(x1, y1), (x2, y2)]).buffer(0.5 * w, cap_style=1, join_style=1)
                gnd_stub_shapes.append(seg)

    # Also add AE1 Pad 2a/2b ground vias / straps explicitly if not in board tracks
    vias_gnd.sort(key=lambda v: (round(v[0], 3), round(v[1], 3)))

    brq_poly = unary_union(brq_shapes).simplify(0.004, preserve_topology=True)
    ant_feed_poly = unary_union(ant_shapes).simplify(0.004, preserve_topology=True)
    gnd_stubs_poly = unary_union(gnd_stub_shapes).simplify(0.004, preserve_topology=True)

    # 4. Extract exact F.Cu GND Zone 20 cutout in X in [40.5..49.40], Y in [17.5..24.5]
    # so the CPWG S=0.28 mm gap and 0402 filter clearance match KiCad's filled copper!
    fcu_gnd_polys = []
    bcu_gnd_polys = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetNetname() == "GND" and not z.GetIsRuleArea():
            for lyr, acc in ((pcbnew.F_Cu, fcu_gnd_polys), (pcbnew.B_Cu, bcu_gnd_polys)):
                if z.GetLayerSet().Contains(lyr):
                    ps = z.GetFilledPolysList(lyr)
                    for oi in range(ps.OutlineCount()):
                        outline = ps.Outline(oi)
                        ext = [gbr_pt(outline.GetPoint(pi)) for pi in range(outline.GetPointCount())]
                        holes = []
                        for hi in range(ps.HoleCount(oi)):
                            h_pts = [gbr_pt(ps.HolePoint(oi, hi, pi)) for pi in range(ps.HolePointCount(oi, hi))]
                            if len(h_pts) >= 3:
                                holes.append(h_pts)
                        if len(ext) >= 3:
                            p = Polygon(ext, holes).buffer(0)
                            if not p.is_empty:
                                acc.append(p)

    fcu_gnd_full = unary_union(fcu_gnd_polys).simplify(0.01, preserve_topology=True)
    bcu_gnd_full = unary_union(bcu_gnd_polys).simplify(0.01, preserve_topology=True)

    # Compute the exact RF channel void in F.Cu counterpoise [0.45..49.40]x[0.45..39.55] around the RF launch
    rf_window = box(40.80, 17.80, 49.45, 24.20)
    fcu_rf_cutout = rf_window.difference(fcu_gnd_full).difference(gnd_stubs_poly).simplify(
        0.008, preserve_topology=True
    )

    return {
        "pcb_sha256": sha256_file(PCB_PATH),
        "mod_sha256": sha256_file(MOD_PATH),
        "ae1_driven_poly": ae1_driven_poly,
        "ae1_return_poly": ae1_return_poly,
        "brq_poly": brq_poly,
        "ant_feed_poly": ant_feed_poly,
        "gnd_stubs_poly": gnd_stubs_poly,
        "fcu_gnd_full": fcu_gnd_full,
        "bcu_gnd_full": bcu_gnd_full,
        "fcu_rf_cutout": fcu_rf_cutout,
        "pads": pads_info,
        "vias_gnd": vias_gnd,
    }


# ==============================================================================
# DXF R2000 Minimal Writer (Zero External Dependencies, Verified Closed Polylines)
# ==============================================================================

def _poly_rings(geom) -> list[tuple[list[tuple[float, float]], bool]]:
    """Return list of (ring_coords_without_closing_dup, is_hole)."""
    out = []
    if geom.is_empty:
        return out
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    for p in polys:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        ext = list(p.exterior.coords)[:-1]
        if len(ext) >= 3:
            out.append((ext, False))
        for h in p.interiors:
            hc = list(h.coords)[:-1]
            if len(hc) >= 3:
                out.append((hc, True))
    return out


def write_dxf_r12_lwpolylines(path: Path, layers_geoms: dict[str, object]) -> None:
    """Write clean AutoCAD R12/R2000 ASCII DXF with closed POLYLINE entities in mm."""
    lines = [
        "0", "SECTION",
        "2", "HEADER",
        "9", "$INSUNITS",
        "70", "4",  # 4 = Millimeters
        "0", "ENDSEC",
        "0", "SECTION",
        "2", "ENTITIES",
    ]
    for layer_name, geom in layers_geoms.items():
        for pts, _is_hole in _poly_rings(geom):
            lines.extend([
                "0", "POLYLINE",
                "8", layer_name,
                "66", "1",
                "70", "1",  # Closed polyline
                "10", "0.0",
                "20", "0.0",
                "30", "0.0",
            ])
            for x, y in pts:
                lines.extend([
                    "0", "VERTEX",
                    "8", layer_name,
                    "10", f"{x:.4f}",
                    "20", f"{y:.4f}",
                    "30", "0.0",
                ])
            lines.extend(["0", "SEQEND"])
    lines.extend(["0", "ENDSEC", "0", "EOF"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rounded_rect_poly(x0: float, y0: float, x1: float, y1: float, r: float, n_arc: int = 8) -> Polygon:
    pts = []
    corners = [
        (x1 - r, y0 + r, -0.5 * math.pi, 0.0),
        (x1 - r, y1 - r, 0.0, 0.5 * math.pi),
        (x0 + r, y1 - r, 0.5 * math.pi, math.pi),
        (x0 + r, y0 + r, math.pi, 1.5 * math.pi),
    ]
    for cx, cy, a0, a1 in corners:
        for th in np.linspace(a0, a1, n_arc):
            pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
    return Polygon(pts)


# ==============================================================================
# CST VBA Extrude Formatting Helpers
# ==============================================================================

def vba_extrude_polygon(
    name: str,
    component: str,
    material: str,
    z0_expr: str,
    height_expr: str,
    pts: list[tuple[float, float]],
) -> str:
    """Emit a CST Microwave Studio `With Extrude` history block for a 2D XY polygon."""
    body = [
        "With Extrude",
        "    .Reset",
        f'    .Name "{name}"',
        f'    .Component "{component}"',
        f'    .Material "{material}"',
        '    .Mode "pointlist"',
        f'    .Height "{height_expr}"',
        '    .Twist "0.0"',
        '    .Taper "0.0"',
        f'    .Origin "0.0", "0.0", "{z0_expr}"',
        '    .Uvector "1.0", "0.0", "0.0"',
        '    .Vvector "0.0", "1.0", "0.0"',
        f'    .Point "{pts[0][0]:.4f}", "{pts[0][1]:.4f}"',
    ]
    for x, y in pts[1:]:
        body.append(f'    .LineTo "{x:.4f}", "{y:.4f}"')
    body.append(f'    .LineTo "{pts[0][0]:.4f}", "{pts[0][1]:.4f}"')
    body.append("    .Create")
    body.append("End With")
    return "\n".join(body)


def vba_add_to_history(caption: str, inner_vba: str) -> str:
    escaped_lines = []
    for ln in inner_vba.strip().splitlines():
        esc = ln.replace('"', '""')
        escaped_lines.append(f'    sCmd = sCmd & "{esc}" & vbLf')
    joined = "\n".join(escaped_lines)
    return (
        f'    sCmd = ""\n'
        f"{joined}\n"
        f'    AddToHistory "{caption}", sCmd\n'
    )


def generate_main_mws_macro(geom: dict) -> str:
    """Build the complete parameterized CST Microwave Studio 3D VBA macro."""
    rs_enig = enig_sheet_resistance_ohm(866.5e6)
    # Equivalent conductivity at 866.5 MHz for CST Lossy Metal: Rs = sqrt(pi * f * mu0 / sigma)
    sigma_enig_eq = math.pi * 866.5e6 * (4e-7 * math.pi) / (rs_enig ** 2)

    board_poly = rounded_rect_poly(0.0, 0.0, 90.0, 40.0, 2.0, n_arc=7)
    board_pts = list(board_poly.exterior.coords)[:-1]

    ae1_drv_pts = list(geom["ae1_driven_poly"].exterior.coords)[:-1]
    ae1_ret_pts = list(geom["ae1_return_poly"].exterior.coords)[:-1]

    brq_polys = list(geom["brq_poly"].geoms) if isinstance(geom["brq_poly"], MultiPolygon) else [geom["brq_poly"]]
    ant_polys = (
        list(geom["ant_feed_poly"].geoms)
        if isinstance(geom["ant_feed_poly"], MultiPolygon)
        else [geom["ant_feed_poly"]]
    )
    stub_polys = (
        list(geom["gnd_stubs_poly"].geoms)
        if isinstance(geom["gnd_stubs_poly"], MultiPolygon)
        else [geom["gnd_stubs_poly"]]
    )
    cutout_polys = (
        list(geom["fcu_rf_cutout"].geoms)
        if isinstance(geom["fcu_rf_cutout"], MultiPolygon)
        else [geom["fcu_rf_cutout"]]
    )

    p = geom["pads"]

    blocks = []

    # 1. Units, Frequency & Background
    blocks.append(vba_add_to_history("define units", """
With Units
    .Geometry "mm"
    .Frequency "GHz"
    .Time "ns"
    .TemperatureUnit "Kelvin"
    .Voltage "V"
    .Current "A"
    .Resistance "Ohm"
    .Conductance "S"
    .Capacitance "PikoF"
    .Inductance "NanoH"
End With
"""))

    blocks.append(vba_add_to_history("define frequency range", """
Solver.FrequencyRange "f_min", "f_max"
"""))

    blocks.append(vba_add_to_history("define background", """
With Background
    .ResetBackground
    .Type "Normal"
    .Epsilon "1.0"
    .Mu "1.0"
    .XminSpace "0.0"
    .XmaxSpace "0.0"
    .YminSpace "0.0"
    .YmaxSpace "0.0"
    .ZminSpace "0.0"
    .ZmaxSpace "0.0"
End With
"""))

    blocks.append(vba_add_to_history("define boundary conditions", """
With Boundary
    .Xmin "open (add space)"
    .Xmax "open (add space)"
    .Ymin "open (add space)"
    .Ymax "open (add space)"
    .Zmin "open (add space)"
    .Zmax "open (add space)"
    .Xsymmetry "none"
    .Ysymmetry "none"
    .Zsymmetry "none"
    .ApplyInAllDirections "False"
    .OpenAddSpaceFactor "0.5"
End With
"""))

    # 2. Material Library (ENIG, Copper, FR-4, LPI Mask, 3M 467MP, ASA/PETG, EPDM, Nylon, Stainless, 6 Superstrates)
    mat_vba = f"""
With Material
    .Reset
    .Name "Copper_ENIG_IPC4552"
    .Folder "Metals"
    .Type "Lossy metal"
    .Mu "1.0"
    .Sigma "{sigma_enig_eq:.4e}"
    .Colour "0.92", "0.74", "0.22"
    .Create
End With

With Material
    .Reset
    .Name "Copper_Pure_ED"
    .Folder "Metals"
    .Type "Lossy metal"
    .Mu "1.0"
    .Sigma "5.80e7"
    .Colour "0.85", "0.45", "0.18"
    .Create
End With

With Material
    .Reset
    .Name "Stainless_A4_316"
    .Folder "Metals"
    .Type "Lossy metal"
    .Mu "1.02"
    .Sigma "1.35e6"
    .Colour "0.65", "0.68", "0.72"
    .Create
End With

With Material
    .Reset
    .Name "Al_Laminate_LiPo"
    .Folder "Metals"
    .Type "Lossy metal"
    .Mu "1.0"
    .Sigma "3.50e7"
    .Colour "0.78", "0.80", "0.84"
    .Create
End With

With Material
    .Reset
    .Name "FR4_ISAC_Core"
    .Folder "Substrates"
    .Type "Normal"
    .Epsilon "er_fr4"
    .Mu "1.0"
    .TanD "tand_fr4"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.82", "0.72", "0.42"
    .Create
End With

With Material
    .Reset
    .Name "SolderMask_LPI"
    .Folder "Substrates"
    .Type "Normal"
    .Epsilon "3.40"
    .Mu "1.0"
    .TanD "0.025"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.08", "0.44", "0.22"
    .Transparency "35"
    .Create
End With

With Material
    .Reset
    .Name "Adhesive_3M_467MP"
    .Folder "Enclosure"
    .Type "Normal"
    .Epsilon "2.80"
    .Mu "1.0"
    .TanD "0.015"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.95", "0.90", "0.55"
    .Transparency "45"
    .Create
End With

With Material
    .Reset
    .Name "ASA_PETG_Radome"
    .Folder "Enclosure"
    .Type "Normal"
    .Epsilon "er_asa"
    .Mu "1.0"
    .TanD "tand_asa"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.22", "0.26", "0.32"
    .Transparency "55"
    .Create
End With

With Material
    .Reset
    .Name "EPDM_ORing_5700"
    .Folder "Enclosure"
    .Type "Normal"
    .Epsilon "2.55"
    .Mu "1.0"
    .TanD "0.010"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.12", "0.12", "0.12"
    .Create
End With

With Material
    .Reset
    .Name "Nylon_66_Fastener"
    .Folder "Enclosure"
    .Type "Normal"
    .Epsilon "3.10"
    .Mu "1.0"
    .TanD "0.015"
    .TanDFreq "0.8665"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.88", "0.88", "0.85"
    .Create
End With

With Material
    .Reset
    .Name "Superstrate_DryAir"
    .Folder "Superstrates"
    .Type "Normal"
    .Epsilon "1.00"
    .Mu "1.0"
    .TanDGiven "False"
    .Colour "0.80", "0.92", "1.00"
    .Transparency "80"
    .Create
End With

With Material
    .Reset
    .Name "Superstrate_Oil_PTFE"
    .Folder "Superstrates"
    .Type "Normal"
    .Epsilon "2.10"
    .Mu "1.0"
    .TanD "0.0001"
    .TanDFreq "0.868"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.90", "0.78", "0.20"
    .Transparency "45"
    .Create
End With

With Material
    .Reset
    .Name "Superstrate_GlazeIce"
    .Folder "Superstrates"
    .Type "Normal"
    .Epsilon "3.20"
    .Mu "1.0"
    .TanD "0.0009375"
    .TanDFreq "0.868"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.55", "0.85", "0.98"
    .Transparency "35"
    .Create
End With

With Material
    .Reset
    .Name "Superstrate_Alumina"
    .Folder "Superstrates"
    .Type "Normal"
    .Epsilon "9.80"
    .Mu "1.0"
    .TanD "0.000204"
    .TanDFreq "0.868"
    .TanDGiven "True"
    .TanDModel "ConstTanD"
    .Colour "0.95", "0.95", "0.92"
    .Transparency "25"
    .Create
End With

' 1st-Order Debye Polar Solvent (Isopropanol @ 20 C: eps_s=19.90, eps_inf=3.20, tau=408 ps -> 6.29 - j6.09 @ 868 MHz)
With Material
    .Reset
    .Name "Superstrate_IPA_Debye"
    .Folder "Superstrates"
    .Type "Normal"
    .Mu "1.0"
    .DispModelEps "Debye1st"
    .EpsInfinity "3.20"
    .Eps0 "19.90"
    .RelaxTimeEps "408.0e-12"
    .Colour "0.72", "0.35", "0.88"
    .Transparency "40"
    .Create
End With

' 1st-Order Debye Liquid Water (@ 20 C: eps_s=80.10, eps_inf=4.90, tau=9.30 ps -> 79.91 - j3.81 @ 868 MHz)
With Material
    .Reset
    .Name "Superstrate_Water_Debye"
    .Folder "Superstrates"
    .Type "Normal"
    .Mu "1.0"
    .DispModelEps "Debye1st"
    .EpsInfinity "4.90"
    .Eps0 "80.10"
    .RelaxTimeEps "9.30e-12"
    .Colour "0.10", "0.48", "0.95"
    .Transparency "35"
    .Create
End With
"""
    blocks.append(vba_add_to_history("define RF, enclosure and Debye superstrate materials", mat_vba))

    # 3. PCB FR-4 Core (90 x 40 mm, R=2.0 mm corners, Z = [-h_fr4, 0.0], minus H1..H4 NPTH holes)
    sub_vba_parts = [
        vba_extrude_polygon(
            "FR4_Core", "PCB_Substrate", "FR4_ISAC_Core", "-h_fr4", "h_fr4", board_pts
        )
    ]
    for href in ("H1", "H2", "H3", "H4"):
        hp = p[href][next(iter(p[href]))]
        sub_vba_parts.append(f"""
With Cylinder
    .Reset
    .Name "NPTH_{href}"
    .Component "PCB_Substrate"
    .Material "Vacuum"
    .OuterRadius "{0.5 * hp['w']:.4f}"
    .InnerRadius "0.0"
    .Axis "z"
    .Zrange "-h_fr4 - 0.5", "0.5"
    .Xcenter "{hp['x']:.4f}"
    .Ycenter "{hp['y']:.4f}"
    .Segments "24"
    .Create
End With
Solid.Subtract "PCB_Substrate:FR4_Core", "PCB_Substrate:NPTH_{href}"
""")
    blocks.append(vba_add_to_history("build 90x40mm R=2mm FR-4 PCB core", "\n".join(sub_vba_parts)))

    # 4. Exact F.Cu & B.Cu Copper Geometry (AE1 Driven Arm, AE1 Return Bar, Counterpoises, CPWG, Vias)
    cu_parts = [
        'Dim sCuMat As String',
        'If use_enig_loss > 0.5 Then sCuMat = "Copper_ENIG_IPC4552" Else sCuMat = "Copper_Pure_ED"',
        vba_extrude_polygon("AE1_Driven_Arm", "PCB_Copper", "Copper_ENIG_IPC4552", "0.0", "t_cu", ae1_drv_pts),
        vba_extrude_polygon("AE1_Return_Bar", "PCB_Copper", "Copper_ENIG_IPC4552", "0.0", "t_cu", ae1_ret_pts),
    ]

    # Top GND Counterpoise [0.45..49.40] x [0.45..39.55] minus exact KiCad Zone 20 CPWG/filter cutout, /BR_S void & H1/H3
    cu_parts.append("""
With Brick
    .Reset
    .Name "Top_GND_Counterpoise"
    .Component "PCB_Copper"
    .Material "Copper_ENIG_IPC4552"
    .Xrange "0.4500", "49.4000"
    .Yrange "0.4500", "39.5500"
    .Zrange "0.0", "t_cu"
    .Create
End With

' Dual-layer /BR_S 2.20 x 2.20 mm bridge parasitic-relief cutout
With Brick
    .Reset
    .Name "BRS_Void_Top"
    .Component "PCB_Copper"
    .Material "Vacuum"
    .Xrange "33.4000", "35.6000"
    .Yrange "13.6200", "15.8200"
    .Zrange "-0.05", "t_cu + 0.05"
    .Create
End With
Solid.Subtract "PCB_Copper:Top_GND_Counterpoise", "PCB_Copper:BRS_Void_Top"
""")
    for idx_c, cpoly in enumerate(cutout_polys):
        if isinstance(cpoly, Polygon) and not cpoly.is_empty and cpoly.area > 0.02:
            cpts = list(cpoly.exterior.coords)[:-1]
            cu_parts.append(
                vba_extrude_polygon(
                    f"CPWG_Cutout_{idx_c}", "PCB_Copper", "Vacuum", "-0.05", "t_cu + 0.10", cpts
                )
            )
            cu_parts.append(
                f'Solid.Subtract "PCB_Copper:Top_GND_Counterpoise", "PCB_Copper:CPWG_Cutout_{idx_c}"'
            )

    for href in ("H1", "H3"):
        hp = p[href][next(iter(p[href]))]
        cu_parts.append(f"""
With Cylinder
    .Reset
    .Name "Clr_Top_{href}"
    .Component "PCB_Copper"
    .Material "Vacuum"
    .OuterRadius "2.8000"
    .InnerRadius "0.0"
    .Axis "z"
    .Zrange "-0.05", "t_cu + 0.05"
    .Xcenter "{hp['x']:.4f}"
    .Ycenter "{hp['y']:.4f}"
    .Segments "24"
    .Create
End With
Solid.Subtract "PCB_Copper:Top_GND_Counterpoise", "PCB_Copper:Clr_Top_{href}"
""")

    # Add GND shunt return stubs (C_M1.2 -> via, C_M2.2 -> via, AE1 Pad 2 straps) and merge into Top_GND_Counterpoise
    for idx_s, spoly in enumerate(stub_polys):
        if isinstance(spoly, Polygon) and not spoly.is_empty:
            spts = list(spoly.exterior.coords)[:-1]
            cu_parts.append(
                vba_extrude_polygon(
                    f"GND_Shunt_Stub_{idx_s}", "PCB_Copper", "Copper_ENIG_IPC4552", "0.0", "t_cu", spts
                )
            )
            cu_parts.append(
                f'Solid.Add "PCB_Copper:Top_GND_Counterpoise", "PCB_Copper:GND_Shunt_Stub_{idx_s}"'
            )

    # /ANT_FEED copper polygon (L_M1.2 -> C_M2.1 -> AE1.1)
    for idx_a, apoly in enumerate(ant_polys):
        if isinstance(apoly, Polygon) and not apoly.is_empty:
            apts = list(apoly.exterior.coords)[:-1]
            nm = "ANT_FEED_Trace" if idx_a == 0 else f"ANT_FEED_Part_{idx_a}"
            cu_parts.append(vba_extrude_polygon(nm, "PCB_Copper", "Copper_ENIG_IPC4552", "0.0", "t_cu", apts))
            if idx_a > 0:
                cu_parts.append(f'Solid.Add "PCB_Copper:ANT_FEED_Trace", "PCB_Copper:{nm}"')

    # /BR_Q copper polygon (only populated in Full Front-End Mode excitation_mode >= 0.5)
    cu_parts.append("If excitation_mode > 0.5 Then")
    for idx_b, bpoly in enumerate(brq_polys):
        if isinstance(bpoly, Polygon) and not bpoly.is_empty:
            bpts = list(bpoly.exterior.coords)[:-1]
            nm = "BR_Q_Launch" if idx_b == 0 else f"BR_Q_Part_{idx_b}"
            cu_parts.append(vba_extrude_polygon(nm, "PCB_Copper", "Copper_ENIG_IPC4552", "0.0", "t_cu", bpts))
            if idx_b > 0:
                cu_parts.append(f'Solid.Add "PCB_Copper:BR_Q_Launch", "PCB_Copper:{nm}"')
    cu_parts.append("End If")

    # Bottom GND Counterpoise [0.45..50.00] x [0.45..39.55] at Z = [-h_fr4 - t_cu, -h_fr4]
    cu_parts.append("""
With Brick
    .Reset
    .Name "Bot_GND_Counterpoise"
    .Component "PCB_Copper"
    .Material "Copper_ENIG_IPC4552"
    .Xrange "0.4500", "50.0000"
    .Yrange "0.4500", "39.5500"
    .Zrange "-h_fr4 - t_cu", "-h_fr4"
    .Create
End With

With Brick
    .Reset
    .Name "BRS_Void_Bot"
    .Component "PCB_Copper"
    .Material "Vacuum"
    .Xrange "33.4000", "35.6000"
    .Yrange "13.6200", "15.8200"
    .Zrange "-h_fr4 - t_cu - 0.05", "-h_fr4 + 0.05"
    .Create
End With
Solid.Subtract "PCB_Copper:Bot_GND_Counterpoise", "PCB_Copper:BRS_Void_Bot"
""")
    for href in ("H1", "H3"):
        hp = p[href][next(iter(p[href]))]
        cu_parts.append(f"""
With Cylinder
    .Reset
    .Name "Clr_Bot_{href}"
    .Component "PCB_Copper"
    .Material "Vacuum"
    .OuterRadius "2.8000"
    .InnerRadius "0.0"
    .Axis "z"
    .Zrange "-h_fr4 - t_cu - 0.05", "-h_fr4 + 0.05"
    .Xcenter "{hp['x']:.4f}"
    .Ycenter "{hp['y']:.4f}"
    .Segments "24"
    .Create
End With
Solid.Subtract "PCB_Copper:Bot_GND_Counterpoise", "PCB_Copper:Clr_Bot_{href}"
""")

    # Stitching & Shunt Return GND Vias (exact KiCad coordinates + AE1 Pad 2 anchors)
    all_vias = list(geom["vias_gnd"]) + [(50.0000, 13.0000, 0.60, 0.30), (50.0000, 5.5000, 0.60, 0.30)]
    for iv, (vx, vy, od, _drl) in enumerate(all_vias):
        vname = "GND_Stitching_Vias" if iv == 0 else f"Via_GND_{iv}"
        cu_parts.append(f"""
With Cylinder
    .Reset
    .Name "{vname}"
    .Component "PCB_Copper"
    .Material "Copper_ENIG_IPC4552"
    .OuterRadius "{0.5 * od:.4f}"
    .InnerRadius "0.0"
    .Axis "z"
    .Zrange "-h_fr4 - t_cu", "t_cu"
    .Xcenter "{vx:.4f}"
    .Ycenter "{vy:.4f}"
    .Segments "16"
    .Create
End With
""")
        if iv > 0:
            cu_parts.append(f'Solid.Add "PCB_Copper:GND_Stitching_Vias", "PCB_Copper:{vname}"')

    # Cleanly insert via barrels into FR-4 Core (zero overlapping volume warnings)
    cu_parts.append('Solid.Insert "PCB_Substrate:FR4_Core", "PCB_Copper:GND_Stitching_Vias"')

    # Toggle conductor material if use_enig_loss = 0
    cu_parts.append("""
If use_enig_loss < 0.5 Then
    Solid.ChangeMaterial "PCB_Copper:AE1_Driven_Arm", "Copper_Pure_ED"
    Solid.ChangeMaterial "PCB_Copper:AE1_Return_Bar", "Copper_Pure_ED"
    Solid.ChangeMaterial "PCB_Copper:Top_GND_Counterpoise", "Copper_Pure_ED"
    Solid.ChangeMaterial "PCB_Copper:Bot_GND_Counterpoise", "Copper_Pure_ED"
    Solid.ChangeMaterial "PCB_Copper:ANT_FEED_Trace", "Copper_Pure_ED"
    Solid.ChangeMaterial "PCB_Copper:GND_Stitching_Vias", "Copper_Pure_ED"
    If excitation_mode > 0.5 Then
        Solid.ChangeMaterial "PCB_Copper:BR_Q_Launch", "Copper_Pure_ED"
    End If
End If
""")
    blocks.append(vba_add_to_history("build exact KiCad Rev E.5 copper & stitching vias", "\n".join(cu_parts)))

    # 5. Green LPI Solder Mask with Exact Bare-ENIG Sensing Window [73.40..87.80]x[6.65..20.80] mm
    mask_parts = [
        vba_extrude_polygon("Top_LPI_Mask", "PCB_Mask", "SolderMask_LPI", "0.0", "t_cu + t_mask", board_pts),
        vba_extrude_polygon(
            "Bot_LPI_Mask", "PCB_Mask", "SolderMask_LPI", "-h_fr4 - t_cu - t_mask", "t_cu + t_mask", board_pts
        ),
        """
' Bare-ENIG sensing window over 5-finger IDE comb (exact F.Mask polygon [73.40..87.80]x[6.65..20.80] mm)
With Brick
    .Reset
    .Name "Bare_ENIG_Mask_Window"
    .Component "PCB_Mask"
    .Material "Vacuum"
    .Xrange "73.4000", "87.8000"
    .Yrange "6.6500", "20.8000"
    .Zrange "-0.05", "t_cu + t_mask + 0.05"
    .Create
End With
Solid.Subtract "PCB_Mask:Top_LPI_Mask", "PCB_Mask:Bare_ENIG_Mask_Window"

' Open solder mask around 0402 harmonic Pi-filter & port launch pads
With Brick
    .Reset
    .Name "RF_Filter_Mask_Relief"
    .Component "PCB_Mask"
    .Material "Vacuum"
    .Xrange "41.0000", "50.6000"
    .Yrange "18.2000", "22.9000"
    .Zrange "-0.05", "t_cu + t_mask + 0.05"
    .Create
End With
Solid.Subtract "PCB_Mask:Top_LPI_Mask", "PCB_Mask:RF_Filter_Mask_Relief"
""",
    ]
    for href in ("H1", "H2", "H3", "H4"):
        hp = p[href][next(iter(p[href]))]
        mask_parts.append(f"""
With Cylinder
    .Reset
    .Name "Mask_NPTH_{href}"
    .Component "PCB_Mask"
    .Material "Vacuum"
    .OuterRadius "1.5000"
    .InnerRadius "0.0"
    .Axis "z"
    .Zrange "-h_fr4 - 0.5", "0.5"
    .Xcenter "{hp['x']:.4f}"
    .Ycenter "{hp['y']:.4f}"
    .Segments "20"
    .Create
End With
Solid.Subtract "PCB_Mask:Top_LPI_Mask", "PCB_Mask:Mask_NPTH_{href}"
Solid.Subtract "PCB_Mask:Bot_LPI_Mask", "PCB_Mask:Mask_NPTH_{href}"
""")

    mask_parts.append("""
' Boolean Insert so copper traces displace LPI mask cleanly with zero intersecting solids
Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:AE1_Driven_Arm"
Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:AE1_Return_Bar"
Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:Top_GND_Counterpoise"
Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:ANT_FEED_Trace"
Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:GND_Stitching_Vias"
If excitation_mode > 0.5 Then
    Solid.Insert "PCB_Mask:Top_LPI_Mask", "PCB_Copper:BR_Q_Launch"
End If
Solid.Insert "PCB_Mask:Bot_LPI_Mask", "PCB_Copper:Bot_GND_Counterpoise"
Solid.Insert "PCB_Mask:Bot_LPI_Mask", "PCB_Copper:GND_Stitching_Vias"
""")
    blocks.append(vba_add_to_history("build LPI solder mask with bare-ENIG sensing window", "\n".join(mask_parts)))

    # 6. Full Rev E.5 ASA/PETG Enclosure, 25 um 3M 467MP Bondline, Open-East Self-Draining Window, O-Ring & Battery
    encl_vba = """
If enclosure_en > 0.5 Then
    ' 1. 25 um 3M 467MP void-free acrylic transfer adhesive filling inter-finger trenches + bondline
    With Brick
        .Reset
        .Name "Adhesive_467MP"
        .Component "Enclosure"
        .Material "Adhesive_3M_467MP"
        .Xrange "73.6000", "87.6000"
        .Yrange "6.8500", "20.6000"
        .Zrange "0.0", "t_cu + h_adhesive"
        .Create
    End With
    Solid.Insert "Enclosure:Adhesive_467MP", "PCB_Copper:AE1_Driven_Arm"
    Solid.Insert "Enclosure:Adhesive_467MP", "PCB_Copper:AE1_Return_Bar"

    ' 2. Upper Lid Outer Shell (uniform flat roof Z = +8.50 mm, compliant skirt Z = -1.44 mm)
    With Brick
        .Reset
        .Name "ASA_Upper_Lid"
        .Component "Enclosure"
        .Material "ASA_PETG_Radome"
        .Xrange "-2.8500", "92.8500"
        .Yrange "-2.8500", "42.8500"
        .Zrange "-1.4400", "8.5000"
        .Create
    End With

    ' Electronics bay internal air cavity (X = -0.25..50.00 mm, Z = -1.44..+6.50 mm)
    With Brick
        .Reset
        .Name "Cav_Electronics"
        .Component "Enclosure"
        .Material "Vacuum"
        .Xrange "-0.2500", "50.0000"
        .Yrange "-0.2500", "40.2500"
        .Zrange "-1.5000", "6.5000"
        .Create
    End With
    Solid.Subtract "Enclosure:ASA_Upper_Lid", "Enclosure:Cav_Electronics"

    ' Antenna bay internal air cavity (X = 50.00..90.25 mm, Z = -1.44..+4.50 mm)
    With Brick
        .Reset
        .Name "Cav_Antenna"
        .Component "Enclosure"
        .Material "Vacuum"
        .Xrange "50.0000", "90.2500"
        .Yrange "-0.2500", "40.2500"
        .Zrange "-1.5000", "4.5000"
        .Create
    End With
    Solid.Subtract "Enclosure:ASA_Upper_Lid", "Enclosure:Cav_Antenna"

    ' Step-down internal sensing boss collar [73.60..87.60]x[6.85..20.60] reaching down to 3M 467MP
    With Brick
        .Reset
        .Name "Sensing_Boss_StepDown"
        .Component "Enclosure"
        .Material "ASA_PETG_Radome"
        .Xrange "73.6000", "87.6000"
        .Yrange "6.8500", "20.6000"
        .Zrange "t_cu + h_adhesive", "4.5500"
        .Create
    End With
    Solid.Add "Enclosure:ASA_Upper_Lid", "Enclosure:Sensing_Boss_StepDown"

    ' East spillway bridge [87.60..90.25]x[6.85..20.60] clearing masked PCB margin at Z = +0.16 mm
    With Brick
        .Reset
        .Name "East_Spillway_Bridge"
        .Component "Enclosure"
        .Material "ASA_PETG_Radome"
        .Xrange "87.6000", "90.2500"
        .Yrange "6.8500", "20.6000"
        .Zrange "0.1600", "4.5500"
        .Create
    End With
    Solid.Add "Enclosure:ASA_Upper_Lid", "Enclosure:East_Spillway_Bridge"

    ' Open-East self-draining recess (0.00 mm East lip!) leaving exact h_window (0.80 mm) ASA/PETG window
    With Brick
        .Reset
        .Name "Open_East_Runoff_Cut"
        .Component "Enclosure"
        .Material "Vacuum"
        .Xrange "74.6000", "93.0000"
        .Yrange "7.6500", "20.2000"
        .Zrange "t_cu + h_adhesive + h_window", "8.6000"
        .Create
    End With
    Solid.Subtract "Enclosure:ASA_Upper_Lid", "Enclosure:Open_East_Runoff_Cut"

    ' 3. Lower Base Tray (Z = -7.60..-1.60 mm with 4.00 mm unloaded air pocket Z = -5.60..-1.60 mm)
    With Brick
        .Reset
        .Name "ASA_Base_Tray"
        .Component "Enclosure"
        .Material "ASA_PETG_Radome"
        .Xrange "-2.8500", "92.8500"
        .Yrange "-2.8500", "42.8500"
        .Zrange "-7.6000", "-1.6000"
        .Create
    End With

    With Brick
        .Reset
        .Name "Base_Air_Cavity"
        .Component "Enclosure"
        .Material "Vacuum"
        .Xrange "-0.2500", "90.2500"
        .Yrange "-0.2500", "40.2500"
        .Zrange "-5.6000", "-1.5500"
        .Create
    End With
    Solid.Subtract "Enclosure:ASA_Base_Tray", "Enclosure:Base_Air_Cavity"

    ' Parker ORD 5700 360-deg EPDM O-ring in perimeter face gland (compressed Z = -2.36..-1.44 mm)
    With Brick
        .Reset
        .Name "EPDM_ORing_Outer"
        .Component "Enclosure"
        .Material "EPDM_ORing_5700"
        .Xrange "-2.4500", "92.4500"
        .Yrange "-2.4500", "42.4500"
        .Zrange "-2.3600", "-1.4400"
        .Create
    End With
    With Brick
        .Reset
        .Name "EPDM_ORing_Inner"
        .Component "Enclosure"
        .Material "Vacuum"
        .Xrange "-0.6500", "90.6500"
        .Yrange "-0.6500", "40.6500"
        .Zrange "-2.4000", "-1.4000"
        .Create
    End With
    Solid.Subtract "Enclosure:EPDM_ORing_Outer", "Enclosure:EPDM_ORing_Inner"
    Solid.Insert "Enclosure:ASA_Base_Tray", "Enclosure:EPDM_ORing_Outer"

    ' 4 x M2.5 Corner Clamping Fasteners (Nylon 66 committed; Stainless A4-316 sensitivity toggle)
    Dim sFastMat As String
    If fastener_metal_en > 0.5 Then sFastMat = "Stainless_A4_316" Else sFastMat = "Nylon_66_Fastener"
    Dim hx(3) As Double, hy(3) As Double, idxH As Integer
    hx(0) = 3.5 : hy(0) = 3.5
    hx(1) = 86.5 : hy(1) = 3.5
    hx(2) = 3.5 : hy(2) = 36.5
    hx(3) = 86.5 : hy(3) = 36.5
    For idxH = 0 To 3
        With Cylinder
            .Reset
            .Name "Fastener_M2p5_" & CStr(idxH + 1)
            .Component "Enclosure"
            .Material sFastMat
            .OuterRadius "1.2500"
            .InnerRadius "0.0"
            .Axis "z"
            .Zrange "-7.6000", "8.5000"
            .Xcenter CStr(hx(idxH))
            .Ycenter CStr(hy(idxH))
            .Segments "16"
            .Create
        End With
        Solid.Insert "Enclosure:ASA_Upper_Lid", "Enclosure:Fastener_M2p5_" & CStr(idxH + 1)
        Solid.Insert "Enclosure:ASA_Base_Tray", "Enclosure:Fastener_M2p5_" & CStr(idxH + 1)
    Next idxH
End If

' Optional Battery Cell under X < 50 mm Counterpoise (1 = 302535 LiPo pouch, 2 = ER14335M 2/3 AA cylinder)
If battery_mode > 0.5 And battery_mode < 1.5 Then
    With Brick
        .Reset
        .Name "Battery_302535_LiPo"
        .Component "Battery"
        .Material "Al_Laminate_LiPo"
        .Xrange "10.0000", "45.0000"
        .Yrange "8.0000", "33.0000"
        .Zrange "-5.5000", "-2.5000"
        .Create
    End With
ElseIf battery_mode >= 1.5 Then
    With Cylinder
        .Reset
        .Name "Battery_ER14335M_2_3AA"
        .Component "Battery"
        .Material "Stainless_A4_316"
        .OuterRadius "7.2500"
        .InnerRadius "0.0"
        .Axis "x"
        .Xrange "11.0000", "44.5000"
        .Ycenter "19.2000"
        .Zcenter "-9.8500"
        .Segments "28"
        .Create
    End With
End If
"""
    blocks.append(
        vba_add_to_history("build Rev E.5 ASA/PETG radome, 3M 467MP, O-ring & battery", encl_vba)
    )

    # 7. Parametric Superstrate Layer (Dry Air, Oil/PTFE, Glaze Ice, Alumina, Dispersive IPA, Dispersive Water)
    sup_vba = """
If superstrate_id > 0.5 And h_superstrate > 0.001 Then
    Dim sSupMat As String
    If superstrate_id < 1.5 Then
        sSupMat = "Superstrate_Oil_PTFE"
    ElseIf superstrate_id < 2.5 Then
        sSupMat = "Superstrate_GlazeIce"
    ElseIf superstrate_id < 3.5 Then
        sSupMat = "Superstrate_Alumina"
    ElseIf superstrate_id < 4.5 Then
        sSupMat = "Superstrate_IPA_Debye"
    Else
        sSupMat = "Superstrate_Water_Debye"
    End If

    Dim zSupBase As String
    If enclosure_en > 0.5 Then
        zSupBase = "t_cu + h_adhesive + h_window"
    Else
        zSupBase = "t_cu"
    End If

    With Brick
        .Reset
        .Name "Superstrate_Film"
        .Component "Superstrate"
        .Material sSupMat
        .Xrange "74.6000", "88.0000"
        .Yrange "7.6500", "20.2000"
        .Zrange zSupBase, zSupBase & " + h_superstrate"
        .Create
    End With
End If
"""
    blocks.append(vba_add_to_history("build parametric superstrate dielectric layer", sup_vba))

    # 8. Excitation Port & 3D Lumped Elements (C_M1, L_M1 || C_MZ, C_M2)
    cm1_1, cm1_2 = p["C_M1"]["1"], p["C_M1"]["2"]
    lm1_1, lm1_2 = p["L_M1"]["1"], p["L_M1"]["2"]
    cmz_1, cmz_2 = p["C_MZ"]["1"], p["C_MZ"]["2"]
    cm2_1, cm2_2 = p["C_M2"]["1"], p["C_M2"]["2"]

    port_vba = f"""
If excitation_mode > 0.5 Then
    ' Mode 1: 50-Ohm Discrete Face Port at /BR_Q post-bridge CPWG spine (X = 41.20 mm)
    With DiscreteFacePort
        .Reset
        .PortNumber "1"
        .Type "SParameter"
        .Label "BR_Q_50Ohm_Launch"
        .Impedance "50.0"
        .VoltagePortImpedance "0.0"
        .VoltageAmplitude "1.0"
        .CurrentAmplitude "1.0"
        .SetP1 "True", "41.2000", "20.0000", "-h_fr4"
        .SetP2 "True", "41.2000", "20.0000", "0.0"
        .LocalCoordinates "False"
        .InvertDirection "False"
        .CenterEdge "True"
        .Monitor "True"
        .UseProjection "False"
        .ReverseProjection "False"
        .FaceType "Linear"
        .Create
    End With

    ' Populated Rev E.5 4-Element Elliptic Low-Pass Harmonic Pi-Network on exact 0402 pads:
    ' C_M1 = 3.6 pF (Murata GJM1555C1H3R6WB01D, ESR = 0.08 Ohm)
    With LumpedElement
        .Reset
        .SetName "C_M1_3p6pF"
        .Folder "Harmonic_Pi_Filter"
        .SetType "RLCSerial"
        .SetR "0.08"
        .SetL "0.35"
        .SetC "c_m1_pf"
        .SetGs "0.0"
        .SetI0 "1e-14"
        .SetT "300.0"
        .SetP1 "True", "{cm1_1['x']:.4f}", "{cm1_1['y'] + 0.5 * cm1_1['h']:.4f}", "t_cu"
        .SetP2 "True", "{cm1_2['x']:.4f}", "{cm1_2['y'] - 0.5 * cm1_2['h']:.4f}", "t_cu"
        .SetInvert "False"
        .SetMonitor "True"
        .SetRadius "0.12"
        .Create
    End With

    ' L_M1 = 8.2 nH (Murata LQW15AN8N2G00D wirewound, Q=42 @ 866.5 MHz -> R=0.106 Ohm)
    With LumpedElement
        .Reset
        .SetName "L_M1_8p2nH"
        .Folder "Harmonic_Pi_Filter"
        .SetType "RLCSerial"
        .SetR "r_ind_ohm"
        .SetL "l_m1_nh"
        .SetC "0.0"
        .SetGs "0.0"
        .SetI0 "1e-14"
        .SetT "300.0"
        .SetP1 "True", "{lm1_1['x'] + 0.5 * lm1_1['w']:.4f}", "{lm1_1['y']:.4f}", "t_cu"
        .SetP2 "True", "{lm1_2['x'] - 0.5 * lm1_2['w']:.4f}", "{lm1_2['y']:.4f}", "t_cu"
        .SetInvert "False"
        .SetMonitor "True"
        .SetRadius "0.15"
        .Create
    End With

    ' C_MZ = 0.50 pF (Murata GJM1555C1HR50WB01D parallel 2f0 elliptic notch zero)
    With LumpedElement
        .Reset
        .SetName "C_MZ_0p5pF"
        .Folder "Harmonic_Pi_Filter"
        .SetType "RLCSerial"
        .SetR "0.06"
        .SetL "0.25"
        .SetC "c_mz_pf"
        .SetGs "0.0"
        .SetI0 "1e-14"
        .SetT "300.0"
        .SetP1 "True", "{cmz_1['x'] + 0.5 * cmz_1['w']:.4f}", "{cmz_1['y']:.4f}", "t_cu"
        .SetP2 "True", "{cmz_2['x'] - 0.5 * cmz_2['w']:.4f}", "{cmz_2['y']:.4f}", "t_cu"
        .SetInvert "False"
        .SetMonitor "True"
        .SetRadius "0.12"
        .Create
    End With

    ' C_M2 = 4.3 pF (Murata GJM1555C1H4R3WB01D, ESR = 0.08 Ohm)
    With LumpedElement
        .Reset
        .SetName "C_M2_4p3pF"
        .Folder "Harmonic_Pi_Filter"
        .SetType "RLCSerial"
        .SetR "0.08"
        .SetL "0.35"
        .SetC "c_m2_pf"
        .SetGs "0.0"
        .SetI0 "1e-14"
        .SetT "300.0"
        .SetP1 "True", "{cm2_1['x']:.4f}", "{cm2_1['y'] + 0.5 * cm2_1['h']:.4f}", "t_cu"
        .SetP2 "True", "{cm2_2['x']:.4f}", "{cm2_2['y'] - 0.5 * cm2_2['h']:.4f}", "t_cu"
        .SetInvert "False"
        .SetMonitor "True"
        .SetRadius "0.12"
        .Create
    End With
Else
    ' Mode 0: Direct 50-Ohm Discrete Face Port at /ANT_FEED (AE1 Pad 1 VNA Reference Plane)
    With DiscreteFacePort
        .Reset
        .PortNumber "1"
        .Type "SParameter"
        .Label "AE1_Direct_Feed_50Ohm"
        .Impedance "50.0"
        .VoltagePortImpedance "0.0"
        .VoltageAmplitude "1.0"
        .CurrentAmplitude "1.0"
        .SetP1 "True", "49.4000", "20.0000", "-h_fr4"
        .SetP2 "True", "49.4000", "20.0000", "0.0"
        .LocalCoordinates "False"
        .InvertDirection "False"
        .CenterEdge "True"
        .Monitor "True"
        .UseProjection "False"
        .ReverseProjection "False"
        .FaceType "Linear"
        .Create
    End With
End If
"""
    blocks.append(vba_add_to_history("define discrete face port and 0402 harmonic Pi-filter", port_vba))

    # 9. Hexahedral Mesh Settings & 3 Local Mesh Refinement Zones
    mesh_vba = """
With Mesh
    .MeshType "PBA"
    .SetCreator "High Frequency"
End With

With MeshSettings
    .SetMeshType "Hex"
    .Set "Version", 1%
    .Set "StepsPerWaveNear", "22"
    .Set "StepsPerWaveFar", "14"
    .Set "StepsPerBoxNear", "20"
    .Set "StepsPerBoxFar", "10"
    .Set "MaxStepNear", "3.5"
    .Set "MaxStepFar", "10.0"
    .Set "ModelBoxDescrNear", "maxedge"
    .Set "ModelBoxDescrFar", "maxedge"
    .Set "RatioLimitGeometry", "20"
    .Set "MinStepGeometryX", "0.08"
    .Set "MinStepGeometryY", "0.08"
    .Set "MinStepGeometryZ", "0.025"
End With

' Local Mesh Zone 1: 5-Finger Bare-ENIG IDE Comb + 25 um Adhesive + 0.80 mm ASA/PETG Window
With MeshSettings
    With .ItemMeshSettings ("group$MeshZone_IDE_and_Window")
        .SetMeshType "Hex"
        .Set "Step", "0.25", "0.20", "0.08"
        .Set "Priority", "2"
    End With
End With
Group.Add "MeshZone_IDE_and_Window", "mesh"
Group.AddItem "solid$PCB_Copper:AE1_Driven_Arm", "MeshZone_IDE_and_Window"
Group.AddItem "solid$PCB_Copper:AE1_Return_Bar", "MeshZone_IDE_and_Window"
If enclosure_en > 0.5 Then
    Group.AddItem "solid$Enclosure:Adhesive_467MP", "MeshZone_IDE_and_Window"
End If
If superstrate_id > 0.5 And h_superstrate > 0.001 Then
    Group.AddItem "solid$Superstrate:Superstrate_Film", "MeshZone_IDE_and_Window"
End If

' Local Mesh Zone 2: CPWG Launch Gap (S=0.28 mm -> >=3 cells) & 0402 Elliptic Pi-Filter
With MeshSettings
    With .ItemMeshSettings ("group$MeshZone_Port_and_Filter")
        .SetMeshType "Hex"
        .Set "Step", "0.15", "0.09", "0.18"
        .Set "Priority", "3"
    End With
End With
Group.Add "MeshZone_Port_and_Filter", "mesh"
Group.AddItem "solid$PCB_Copper:ANT_FEED_Trace", "MeshZone_Port_and_Filter"
If excitation_mode > 0.5 Then
    Group.AddItem "solid$PCB_Copper:BR_Q_Launch", "MeshZone_Port_and_Filter"
End If

' Local Mesh Zone 3: FR-4 Substrate Vertical Resolution (>=6 Z-cells across 1.51 mm core)
With MeshSettings
    With .ItemMeshSettings ("group$MeshZone_FR4_Substrate")
        .SetMeshType "Hex"
        .Set "Step", "0.80", "0.80", "0.25"
        .Set "Priority", "1"
    End With
End With
Group.Add "MeshZone_FR4_Substrate", "mesh"
Group.AddItem "solid$PCB_Substrate:FR4_Core", "MeshZone_FR4_Substrate"
"""
    blocks.append(vba_add_to_history("configure PBA hexahedral mesh and 3 local refinement zones", mesh_vba))

    # 10. Field Monitors (3 CW Probe Tones + 2f0 & 3f0 Harmonic Farfields) & Transient Solver Settings
    mon_vba = """
' E-field, H-field & Surface Current across the 3 CW ISAC probe frequencies
Dim fProbe(2) As String, sTag(2) As String, kM As Integer
fProbe(0) = "0.8631" : sTag(0) = "f1_863p1MHz"
fProbe(1) = "0.8665" : sTag(1) = "f2_866p5MHz"
fProbe(2) = "0.8695" : sTag(2) = "f3_869p5MHz"

For kM = 0 To 2
    With Monitor
        .Reset
        .Name "e-field (" & sTag(kM) & ")"
        .Dimension "Volume"
        .Domain "Frequency"
        .FieldType "Efield"
        .MonitorValue fProbe(kM)
        .UseSubvolume "False"
        .Create
    End With

    With Monitor
        .Reset
        .Name "surface-current (" & sTag(kM) & ")"
        .Dimension "Volume"
        .Domain "Frequency"
        .FieldType "Surfacecurrent"
        .MonitorValue fProbe(kM)
        .Create
    End With

    With Monitor
        .Reset
        .Name "farfield (" & sTag(kM) & ")"
        .Domain "Frequency"
        .FieldType "Farfield"
        .MonitorValue fProbe(kM)
        .ExportFarfieldSource "False"
        .Create
    End With
Next kM

' Volumetric Power Loss Density at 866.5 MHz (quantifies FR-4 vs ASA/PETG vs ENIG vs Water/IPA loss)
With Monitor
    .Reset
    .Name "power-loss (866p5MHz)"
    .Dimension "Volume"
    .Domain "Frequency"
    .FieldType "Powerloss"
    .MonitorValue "0.8665"
    .Create
End With

' 2nd & 3rd Harmonic Farfield Monitors (1733.0 MHz & 2599.5 MHz ETSI EN 300 220-1 radiated ERP check)
With Monitor
    .Reset
    .Name "farfield (2f0_1733p0MHz)"
    .Domain "Frequency"
    .FieldType "Farfield"
    .MonitorValue "1.7330"
    .Create
End With

With Monitor
    .Reset
    .Name "farfield (3f0_2599p5MHz)"
    .Domain "Frequency"
    .FieldType "Farfield"
    .MonitorValue "2.5995"
    .Create
End With

' Time-Domain FIT Solver Setup (-45 dB energy accuracy for sharp unloaded IFA null & elliptic notch)
With Solver
    .Method "Hexahedral"
    .CalculationType "TD-S"
    .StimulationPort "1"
    .StimulationMode "All"
    .SteadyStateLimit "-45"
    .MeshAdaption "False"
    .AutoNormImpedance "False"
    .NormingImpedance "50.0"
    .CalculateModesOnly "False"
    .SParaSymmetry "False"
    .StoreTDResultsInCache "False"
    .FullDeembedding "False"
    .SuperimposePLWExcitation "False"
    .UseSensitivityAnalysis "False"
    .NumberOfPulseWidths "28"
    .FrequencySamples "1151"
End With
"""
    blocks.append(vba_add_to_history("define ISAC field monitors and -45 dB Time-Domain FIT solver", mon_vba))

    header = f"""' =============================================================================
' ISAC_868_Complete_Antenna_MWS.bas
' Complete 3D CST Microwave Studio Model for ISAC_868_KiCad9 (Hardware Rev E.5)
' Author: Stephen K. Boachie  |  License: Apache-2.0
'
' Geometry Provenance (1:1 extracted from frozen Rev E.5 KiCad layout):
'   - ISAC_868_KiCad9.kicad_pcb SHA-256: {geom["pcb_sha256"][:24]}...
'   - IFA_868MHz_ISAC_40x20mm.kicad_mod SHA-256: {geom["mod_sha256"][:24]}...
'   - Right-Handed Coordinate System: Origin (0,0,0) = Bottom-Left PCB corner
'     on F.Cu (KiCad AuxOrigin = (103.500, 120.000) mm).
'
' How to Run in CST Studio Suite (2022 / 2023 / 2024 / 2025):
'   1. Create a new empty Microwave & RF -> Antennas -> Planar project in CST.
'   2. Open Home -> Macros -> File -> Open VBA Macro Editor, load this .bas file,
'      and press F5 (Run). The macro populates the Parameter List, History List,
'      Materials, 3D Geometry, Port/Lumped Elements, Local Mesh Zones, and Monitors.
'   3. Press Home -> Start Simulation (Time Domain Solver) or run
'      macros/ISAC_868_Sweep_All_Superstrates.bas for the full 10-case benchmark.
' =============================================================================

Option Explicit

Sub Main()
    Dim sCmd As String

    ' -------------------------------------------------------------------------
    ' 1. Parametric Design Variables (editable in CST View -> Parameter List)
    ' -------------------------------------------------------------------------
    StoreDoubleParameter "f_min", 0.70
    SetParameterDescription "f_min", "Lower solver frequency [GHz] (covers 776 MHz water-loaded f0)"
    StoreDoubleParameter "f_max", 3.00
    SetParameterDescription "f_max", "Upper solver frequency [GHz] (covers 2f0=1.733 GHz & 3f0=2.600 GHz)"

    StoreDoubleParameter "excitation_mode", 1
    SetParameterDescription "excitation_mode", "1 = /BR_Q port + 3D 0402 elliptic Pi-filter; 0 = direct AE1 Pad 1 port"
    StoreDoubleParameter "enclosure_en", 1
    SetParameterDescription "enclosure_en", "1 = Full Rev E.5 ASA/PETG enclosure + 3M 467MP + O-ring; 0 = Bare PCB"
    StoreDoubleParameter "battery_mode", 0
    SetParameterDescription "battery_mode", "0 = None; 1 = 302535 LiPo pouch; 2 = ER14335M 2/3 AA cylinder"
    StoreDoubleParameter "superstrate_id", 0
    SetParameterDescription "superstrate_id", "0=DryAir, 1=Oil/PTFE, 2=GlazeIce, 3=Alumina, 4=IPA(Debye), 5=Water(Debye)"

    StoreDoubleParameter "h_superstrate", 2.00
    SetParameterDescription "h_superstrate", "Superstrate film thickness over 0.80 mm sensing window [mm]"
    StoreDoubleParameter "h_window", 0.80
    SetParameterDescription "h_window", "Committed UV-stabilized ASA/PETG open-East sensing window thickness [mm]"
    StoreDoubleParameter "h_adhesive", 0.025
    SetParameterDescription "h_adhesive", "3M 467MP acrylic transfer adhesive thickness [mm]"

    StoreDoubleParameter "h_fr4", 1.51
    SetParameterDescription "h_fr4", "2-Layer FR-4 dielectric core thickness [mm] (finished stack = 1.60 mm)"
    StoreDoubleParameter "er_fr4", 4.40
    SetParameterDescription "er_fr4", "FR-4 relative permittivity @ 866.5 MHz (nominal 4.4 +/- 0.2)"
    StoreDoubleParameter "tand_fr4", 0.020
    SetParameterDescription "tand_fr4", "FR-4 dielectric loss tangent @ 866.5 MHz"

    StoreDoubleParameter "er_asa", 3.05
    SetParameterDescription "er_asa", "UV-stabilized ASA/PETG radome relative permittivity"
    StoreDoubleParameter "tand_asa", 0.012
    SetParameterDescription "tand_asa", "UV-stabilized ASA/PETG radome loss tangent"

    StoreDoubleParameter "t_cu", 0.035
    SetParameterDescription "t_cu", "1 oz outer copper thickness [mm]"
    StoreDoubleParameter "t_mask", 0.035
    SetParameterDescription "t_mask", "Green LPI solder mask thickness over laminate/copper [mm]"
    StoreDoubleParameter "use_enig_loss", 1
    SetParameterDescription "use_enig_loss", "1 = IPC-4552 ENIG Rs={rs_enig*1e3:.2f} mOhm/sq; 0 = pure ED copper"
    StoreDoubleParameter "fastener_metal_en", 0
    SetParameterDescription "fastener_metal_en", "0 = Committed M2.5 Nylon 66 screws; 1 = A4-316 stainless test"

    StoreDoubleParameter "c_m1_pf", 3.60
    SetParameterDescription "c_m1_pf", "Elliptic LPF shunt capacitor C_M1 [pF] (Murata GJM1555C1H3R6WB01D)"
    StoreDoubleParameter "l_m1_nh", 8.20
    SetParameterDescription "l_m1_nh", "Elliptic LPF series inductor L_M1 [nH] (Murata LQW15AN8N2G00D)"
    StoreDoubleParameter "c_mz_pf", 0.50
    SetParameterDescription "c_mz_pf", "Elliptic LPF parallel 2f0 zero capacitor C_MZ [pF] (GJM1555C1HR50WB01D)"
    StoreDoubleParameter "c_m2_pf", 4.30
    SetParameterDescription "c_m2_pf", "Elliptic LPF antenna-side shunt C_M2 [pF] (Murata GJM1555C1H4R3WB01D)"
    StoreDoubleParameter "r_ind_ohm", 0.106
    SetParameterDescription "r_ind_ohm", "Series ESR of L_M1 at 866.5 MHz for Q = 42 [Ohm]"

"""
    footer = """
    ' Rebuild 3D model from History List and fit camera to isometric view
    Rebuild
    Plot.ZoomToStructure
End Sub
"""
    return header + "\n".join(blocks) + footer


def generate_fem_crosscheck_macro() -> str:
    fem_body = vba_add_to_history(
        "configure Tetrahedral FEM cross-check solver",
        """
Mesh.MeshType "Tetrahedral"
With FDSolver
    .Reset
    .SetMethod "Tetrahedral", "General purpose"
    .OrderTet "Second"
    .OrderSrf "First"
    .Stimulation "1", "1"
    .ResetExcitationList
    .AutoNormImpedance "False"
    .NormingImpedance "50.0"
    .MeshAdaptionTet "True"
    .SetAdaptionStrategy "Energy"
    .AdaptionMinPasses "3"
    .AdaptionMaxPasses "8"
    .AdaptionAccuracy "0.005"
    .AddSingleFrequencyAdaption "0.8665", "True"
    .SweepErrorThreshold "True", "0.002"
    .MaxNumberOfSamples "1001"
End With
""",
    )
    return (
        "' =============================================================================\n"
        "' ISAC_868_Setup_FEM_CrossCheck.bas\n"
        "' Configures CST Studio Frequency-Domain (Tetrahedral FEM) Solver @ 730-940 MHz\n"
        "' with Curved Elements (Order 2) & Adaptive Mesh Refinement at 866.5 MHz\n"
        "' to independently cross-check the Time-Domain Hexahedral FIT results.\n"
        "' =============================================================================\n\n"
        "Option Explicit\n\n"
        "Sub Main()\n"
        "    Dim sCmd As String\n\n"
        '    StoreDoubleParameter "f_min", 0.73\n'
        '    StoreDoubleParameter "f_max", 0.94\n\n'
        + fem_body
        + "\n    Rebuild\n"
        "    ' Uncomment FDSolver.Start below to launch immediately upon macro import:\n"
        "    ' FDSolver.Start\n"
        "End Sub\n"
    )


def generate_sweep_all_macro() -> str:
    return """' =============================================================================
' ISAC_868_Sweep_All_Superstrates.bas
' Automated 10-Scenario CST Microwave Studio Batch Sweep & Touchstone Exporter
'
' Executes the exact 10 benchmark configurations matching `rf/ifa_enclosure_mom.py`
' and exports Touchstone v1.1 (.s1p) + 866.5 MHz Farfield ASCII summaries into
' `<project_dir>/../results/` (or `<project_dir>/Export_Results/`) for direct
' ingestion by `cst_studio/python/postprocess_cst_results.py`.
' =============================================================================

Option Explicit

Sub RunCase(ByVal caseTag As String, ByVal encl As Double, ByVal bat As Double, _
            ByVal erSub As Double, ByVal supId As Double, ByVal outDir As String)

    StoreDoubleParameter "enclosure_en", encl
    StoreDoubleParameter "battery_mode", bat
    StoreDoubleParameter "er_fr4", erSub
    StoreDoubleParameter "superstrate_id", supId
    StoreDoubleParameter "h_superstrate", 2.00

    Rebuild
    Solver.Start

    ' Export 1-port S-parameters as 50-Ohm Touchstone (.s1p)
    With TOUCHSTONE
        .Reset
        .FileName outDir & "/" & caseTag
        .Impedance "50"
        .FrequencyRange "Full"
        .Renormalize "True"
        .UseARResults "False"
        .Write
    End With

    ' Export 866.5 MHz 3D Farfield Realized Gain & Efficiency summary
    SelectTreeItem "Farfields\\farfield (f2_866p5MHz) [1]"
    With FarfieldPlot
        .Reset
        .Plottype "3D"
        .PlotMode "realized gain"
        .Plot
        .ASCIIExportAsSource outDir & "/farfield_866p5MHz_" & caseTag & ".txt"
    End With
End Sub

Sub Main()
    Dim outDir As String
    outDir = GetProjectPath("Project") & "\\cst_exports"
    On Error Resume Next
    MkDir outDir
    On Error GoTo 0

    ' Run all 10 benchmark cases (Mode 1 = Full Front-End with 3D Elliptic Pi-Filter)
    StoreDoubleParameter "excitation_mode", 1

    RunCase "01_bare_pcb",          0, 0, 4.40, 0, outDir
    RunCase "02_dry_air",           1, 0, 4.40, 0, outDir
    RunCase "03_enclosed_lipo",     1, 1, 4.40, 0, outDir
    RunCase "04_fr4_low_4p2",       1, 0, 4.20, 0, outDir
    RunCase "05_fr4_high_4p6",      1, 0, 4.60, 0, outDir
    RunCase "06_oil_ptfe",          1, 0, 4.40, 1, outDir
    RunCase "07_glaze_ice",         1, 0, 4.40, 2, outDir
    RunCase "08_alumina_al2o3",     1, 0, 4.40, 3, outDir
    RunCase "09_ipa_debye",         1, 0, 4.40, 4, outDir
    RunCase "10_water_debye",       1, 0, 4.40, 5, outDir

    MsgBox "Completed all 10 ISAC Rev E.5 CST antenna & superstrate sweeps -> " & outDir, vbInformation
End Sub
"""


def generate_ds_cosim_macro() -> str:
    return """' =============================================================================
' ISAC_868_FrontEnd_CoSim_DS.bas
' CST Design Studio (DS) Schematic Co-Simulation Macro for ISAC_868 Rev E.5
'
' Purpose:
'   When the 3D Microwave Studio model is solved in Mode 0 (`excitation_mode = 0`,
'   direct port at AE1 Pad 1 `/ANT_FEED`), this CST Design Studio schematic script
'   documents and sets up the full RF front-end co-simulation chain:
'     Port 1 (`SX1262 RFO_LP + C_RF=100pF`, 50 Ohm)
'       -> Asymmetric Return-Loss Bridge:
'            R1 = 8.2 Ohm (0.1% Yageo RT0402BRD078R2L)
'            R2 = 681 Ohm, R3 = 3.57 kOhm (/BR_S C_par = 0.1305 pF over 2.2x2.2 mm void)
'            C_S = C_S2 = 1.0 pF, L_Q = 27 nH, L_S = 30 nH, R_TERM = 56 Ohm
'       -> Coupled Detector Port 2 (`LT5538IDD#TRPBF` IN+ = 291.65 Ohm || 1.194 pF)
'       -> 4-Element Elliptic Harmonic Pi-Filter (`C_M1=3.6p, L_M1=8.2n||C_MZ=0.5p, C_M2=4.3p`
'            or drop-in Murata SimSurfing .s2p blocks)
'       -> 3D CST MWS Antenna Block (`AE1 + Enclosure + Debye Superstrate`).
'
' This enables instantaneous Monte-Carlo tolerance sweeps & Murata .s2p substitution
' in CST Design Studio without re-running the 3D field solver.
' =============================================================================

Option Explicit

Sub Main()
    ' Store RF Front-End schematic parameters in the Design Studio workspace
    StoreDoubleParameter "DS_R1_ohm", 8.20
    StoreDoubleParameter "DS_R2_ohm", 681.0
    StoreDoubleParameter "DS_R3_ohm", 3570.0
    StoreDoubleParameter "DS_RTERM_ohm", 56.0
    StoreDoubleParameter "DS_CS_pf", 1.00
    StoreDoubleParameter "DS_CS2_pf", 1.00
    StoreDoubleParameter "DS_CPAR_BRS_pf", 0.1305
    StoreDoubleParameter "DS_LQ_nh", 27.0
    StoreDoubleParameter "DS_LS_nh", 30.0
    StoreDoubleParameter "DS_RLT5538_ohm", 291.65
    StoreDoubleParameter "DS_CLT5538_pf", 1.194
    StoreDoubleParameter "DS_CM1_pf", 3.60
    StoreDoubleParameter "DS_LM1_nh", 8.20
    StoreDoubleParameter "DS_CMZ_pf", 0.50
    StoreDoubleParameter "DS_CM2_pf", 4.30

    MsgBox "CST Design Studio (DS) Rev E.5 Bridge + Elliptic Filter + LT5538 parameters registered." & vbCrLf & _
           "Connect Port 1 of the 3D MWS block (solved with excitation_mode=0) to C_M2/L_M1 on the DS canvas, " & _
           "or run python/postprocess_cst_results.py on exported .s1p files for automated 2,000-trial MC & 3-tone analysis.", _
           vbInformation
End Sub
"""


def render_cst_blueprint(geom: dict, out_png: Path) -> None:
    """Render a 4-panel senior RF engineering blueprint of the CST Studio model."""
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.2), dpi=180)
    fig.patch.set_facecolor("#FAFBFC")

    # ------------------------------------------------------------------
    # Panel A: Top-View CST 3D Geometry & Local Hexahedral Mesh Boxes
    # ------------------------------------------------------------------
    ax = axes[0, 0]
    ax.set_facecolor("#F3F5F8")
    # Enclosure outer shell
    ax.add_patch(Rectangle((-2.85, -2.85), 95.70, 45.70, fc="#DCE3EC", ec="#334155", lw=1.4, label="ASA/PETG Enclosure (95.7×45.7 mm)"))
    # PCB core
    bpoly = rounded_rect_poly(0.0, 0.0, 90.0, 40.0, 2.0)
    ax.add_patch(MplPolygon(list(bpoly.exterior.coords), closed=True, fc="#EFE2B2", ec="#856404", lw=1.2, label="FR-4 Core (90×40×1.51 mm)"))
    # Top GND counterpoise
    ax.add_patch(Rectangle((0.45, 0.45), 48.95, 39.10, fc="#D9A441", ec="#9A6B12", lw=0.8, alpha=0.75, label="50×40 mm ENIG Counterpoise"))
    # Bare-ENIG window
    ax.add_patch(Rectangle((73.40, 6.65), 14.40, 14.15, fc="#FFFBEB", ec="#16A34A", lw=1.2, ls="--", label="Bare-ENIG F.Mask Window"))
    # Open-East self-draining window
    ax.add_patch(Rectangle((74.60, 7.65), 18.25, 12.55, fc="#38BDF8", ec="#0284C7", lw=1.1, alpha=0.25, label="Open-East 0.80 mm Window + Superstrate"))
    # AE1 copper
    for g, col, lbl in (
        (geom["ae1_driven_poly"], "#C27803", "AE1 Driven IFA + 3 IDE Fingers"),
        (geom["ae1_return_poly"], "#92400E", "AE1 Grounded Return + 2 IDE Fingers"),
    ):
        ax.add_patch(MplPolygon(list(g.exterior.coords), closed=True, fc=col, ec="#451A03", lw=0.7, label=lbl))
    # Local Mesh boxes
    ax.add_patch(Rectangle((73.0, 6.5), 15.5, 14.5, fill=False, ec="#DC2626", lw=1.3, ls=":", label="Local Mesh Zone 1 (0.25×0.20×0.08 mm)"))
    ax.add_patch(Rectangle((41.0, 18.0), 9.6, 5.6, fill=False, ec="#7C3AED", lw=1.3, ls=":", label="Local Mesh Zone 2 (0.15×0.09×0.18 mm)"))
    for href in ("H1", "H2", "H3", "H4"):
        hp = geom["pads"][href][next(iter(geom["pads"][href]))]
        ax.add_patch(Circle((hp["x"], hp["y"]), 1.35, fc="#FFFFFF", ec="#475569", lw=0.9))
    ax.plot(41.20, 20.00, "o", color="#DC2626", ms=6)
    ax.annotate("Port 1 (/BR_Q)\nX=41.2 mm", (41.20, 20.00), xytext=(22.0, 26.5),
                arrowprops=dict(arrowstyle="->", color="#DC2626", lw=1.1), fontsize=8, fontweight="bold", color="#DC2626")
    ax.set_xlim(-6, 97)
    ax.set_ylim(-6, 46)
    ax.set_aspect("equal")
    ax.set_title("A. CST 3D Top View — Exact KiCad Copper, Enclosure & Local Mesh Zones", fontsize=10.5, fontweight="bold")
    ax.set_xlabel("X_gbr [mm] (AuxOrigin = Bottom-Left)")
    ax.set_ylabel("Y_gbr [mm]")
    ax.legend(loc="lower left", fontsize=7.0, ncol=2, framealpha=0.92)
    ax.grid(True, alpha=0.25)

    # ------------------------------------------------------------------
    # Panel B: Zoomed RF Launch, 0402 Elliptic Pi-Filter & AE1 Feed
    # ------------------------------------------------------------------
    ax = axes[0, 1]
    ax.set_facecolor("#F8FAFC")
    # Plot F.Cu ground pour in zoomed window
    zoom_box = box(40.5, 4.0, 88.0, 24.8)
    gnd_clip = geom["fcu_gnd_full"].intersection(zoom_box)
    for pts, is_hole in _poly_rings(gnd_clip):
        if not is_hole:
            ax.add_patch(MplPolygon(pts, closed=True, fc="#E5C07B", ec="#8C6218", lw=0.6, alpha=0.65))
    for g, col in (
        (geom["brq_poly"], "#D97706"),
        (geom["ant_feed_poly"], "#EA580C"),
        (geom["ae1_driven_poly"], "#B45309"),
        (geom["ae1_return_poly"], "#78350F"),
    ):
        for pts, is_hole in _poly_rings(g):
            if not is_hole:
                ax.add_patch(MplPolygon(pts, closed=True, fc=col, ec="#292524", lw=0.75))
    for vx, vy, od, _drl in geom["vias_gnd"]:
        if 40.5 <= vx <= 52.0 and 4.0 <= vy <= 24.8:
            ax.add_patch(Circle((vx, vy), 0.5 * od, fc="#FBBF24", ec="#1E293B", lw=0.7))
    # Annotate Lumped Elements
    for label, (lx, ly), (tx, ty) in (
        ("C_M1 (3.6 pF)", (42.60, 21.90), (40.8, 23.7)),
        ("L_M1 (8.2 nH)", (45.00, 20.00), (43.5, 16.5)),
        ("C_MZ (0.5 pF)", (45.00, 18.85), (44.0, 14.2)),
        ("C_M2 (4.3 pF)", (47.20, 21.90), (46.8, 23.7)),
        ("AE1 Pad 1", (50.00, 20.00), (52.5, 22.8)),
        ("5-Finger Bare-ENIG IDE\n(w=1.30, g=1.20 mm)", (80.60, 13.90), (63.5, 9.0)),
    ):
        ax.annotate(label, (lx, ly), xytext=(tx, ty),
                    arrowprops=dict(arrowstyle="->", color="#1E3A8A", lw=0.9),
                    fontsize=7.8, fontweight="bold", color="#1E3A8A")
    ax.plot([41.20, 41.20], [19.46, 20.54], color="#DC2626", lw=3.0, label="DiscreteFacePort 1 (/BR_Q)")
    ax.plot([49.40, 49.40], [19.46, 20.54], color="#059669", lw=2.5, ls="--", label="Mode 0 Port (/ANT_FEED)")
    ax.set_xlim(40.5, 88.0)
    ax.set_ylim(4.0, 25.0)
    ax.set_aspect("equal")
    ax.set_title("B. Zoomed CST Port, 0402 Elliptic Harmonic Pi-Filter & AE1 IDE Comb", fontsize=10.5, fontweight="bold")
    ax.set_xlabel("X_gbr [mm]")
    ax.set_ylabel("Y_gbr [mm]")
    ax.legend(loc="upper right", fontsize=7.5)
    ax.grid(True, alpha=0.25)

    # ------------------------------------------------------------------
    # Panel C: Z-Axis Stackup Cross-Section Through Sensing Window (Y = 14 mm)
    # ------------------------------------------------------------------
    ax = axes[1, 0]
    ax.set_facecolor("#F8FAFC")
    # Schematic Z cross-section along X = 46..93 mm
    ax.add_patch(Rectangle((46.0, -7.60), 46.85, 2.00, fc="#64748B", ec="#1E293B", lw=1.0, label="ASA/PETG Base Floor (-7.60..-5.60 mm)"))
    ax.add_patch(Rectangle((90.25, -5.60), 2.60, 4.00, fc="#64748B", ec="#1E293B", lw=1.0))
    ax.add_patch(Rectangle((46.0, -1.51), 44.00, 1.51, fc="#EFE2B2", ec="#856404", lw=1.1, label="FR-4 Core (-1.51..0.00 mm, εr=4.4)"))
    ax.add_patch(Rectangle((46.0, -1.58), 4.00, 0.07, fc="#D97706", ec="#78350F", lw=0.8, label="ENIG Cu (35 µm, Rs=23.74 mΩ/sq)"))
    for fx in (75.0, 77.5, 80.0, 82.5, 85.0):
        ax.add_patch(Rectangle((fx, 0.0), 1.30, 0.08, fc="#D97706", ec="#78350F", lw=0.8))
    ax.add_patch(Rectangle((73.60, 0.0), 14.00, 0.14, fc="#FDE047", ec="#CA8A04", lw=0.8, alpha=0.75, label="25 µm 3M 467MP Bondline (εr=2.80)"))
    ax.add_patch(Rectangle((46.0, 4.50), 28.60, 4.00, fc="#475569", ec="#1E293B", lw=1.0, label="ASA/PETG Flat Roof (+8.50 mm, εr=3.05)"))
    ax.add_patch(Rectangle((73.60, 0.14), 1.00, 8.36, fc="#475569", ec="#1E293B", lw=1.0))
    ax.add_patch(Rectangle((74.60, 0.14), 18.25, 0.80, fc="#64748B", ec="#0F172A", lw=1.1, label="0.80 mm Open-East Sensing Window"))
    ax.add_patch(Rectangle((74.60, 0.94), 14.00, 2.00, fc="#38BDF8", ec="#0284C7", lw=1.1, alpha=0.55, label="2.00 mm Debye Superstrate (Air/Ice/IPA/Water)"))
    ax.annotate("0.00 mm East Lip\n(Self-Draining Runoff ->)", (91.0, 0.94), xytext=(80.5, 5.2),
                arrowprops=dict(arrowstyle="->", color="#0284C7", lw=1.1), fontsize=8.2, fontweight="bold", color="#0369A1")
    ax.set_xlim(46.0, 94.5)
    ax.set_ylim(-8.5, 9.8)
    ax.set_title("C. CST Z-Cross-Section at Y = 14.0 mm — Zero-Air-Gap Bond & Open-East Window", fontsize=10.5, fontweight="bold")
    ax.set_xlabel("X_gbr [mm]")
    ax.set_ylabel("Z [mm] (Z = 0 on F.Cu)")
    ax.legend(loc="lower left", fontsize=7.1, ncol=2, framealpha=0.92)
    ax.grid(True, alpha=0.25)

    # ------------------------------------------------------------------
    # Panel D: CST 1st-Order Debye Complex Permittivity Across 0.70-3.00 GHz
    # ------------------------------------------------------------------
    ax = axes[1, 1]
    ax.set_facecolor("#F8FAFC")
    f_ghz = np.linspace(0.70, 3.00, 300)
    w = 2.0 * np.pi * f_ghz * 1e9
    eps_water = 4.90 + (80.10 - 4.90) / (1.0 + 1j * w * 9.30e-12)
    eps_ipa = 3.20 + (19.90 - 3.20) / (1.0 + 1j * w * 408.0e-12)

    ax.plot(f_ghz, eps_water.real, color="#0284C7", lw=2.0, label="Water ε'(f) [Debye1st, 79.9 @ 868 MHz]")
    ax.plot(f_ghz, -eps_water.imag, color="#0284C7", lw=1.6, ls="--", label="Water ε''(f) [3.81 @ 868 MHz]")
    ax.plot(f_ghz, eps_ipa.real, color="#9333EA", lw=2.0, label="IPA ε'(f) [Debye1st, 6.29 @ 868 MHz]")
    ax.plot(f_ghz, -eps_ipa.imag, color="#9333EA", lw=1.6, ls="--", label="IPA ε''(f) [6.09 @ 868 MHz]")
    ax.axhline(9.80, color="#475569", lw=1.3, ls="-.", label="Alumina Al2O3 ε' = 9.80")
    ax.axhline(3.20, color="#0EA5E9", lw=1.3, ls=":", label="Glaze Ice ε' = 3.20")
    for fh, lbl in ((0.8665, "f0"), (1.733, "2f0"), (2.5995, "3f0")):
        ax.axvline(fh, color="#DC2626", lw=0.9, alpha=0.55)
        ax.text(fh + 0.02, 72.0, lbl, color="#DC2626", fontsize=8, fontweight="bold")
    ax.set_yscale("log")
    ax.set_ylim(1.5, 110.0)
    ax.set_xlim(0.70, 3.00)
    ax.set_title("D. CST Dispersive Superstrate Models (0.70–3.00 GHz Fundamental + Harmonics)", fontsize=10.5, fontweight="bold")
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("Complex Permittivity Magnitude (log scale)")
    ax.legend(loc="center right", fontsize=7.3, framealpha=0.92)
    ax.grid(True, which="both", alpha=0.25)

    fig.suptitle(
        "ISAC_868 Rev E.5 — CST Studio Suite 3D Full-Wave Antenna, Radome & Superstrate Simulation Architecture",
        fontsize=12.5, fontweight="bold", y=0.985,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.965])
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def main() -> int:
    print("[CST-GEN] Extracting exact Rev E.5 RF copper, pad, via & zone geometry from KiCad...")
    geom = extract_kicad_rf_geometry()

    # 1. Write CST VBA Macros
    mws_bas = MACROS_DIR / "ISAC_868_Complete_Antenna_MWS.bas"
    fem_bas = MACROS_DIR / "ISAC_868_Setup_FEM_CrossCheck.bas"
    swp_bas = MACROS_DIR / "ISAC_868_Sweep_All_Superstrates.bas"
    ds_bas = MACROS_DIR / "ISAC_868_FrontEnd_CoSim_DS.bas"

    mws_bas.write_text(generate_main_mws_macro(geom), encoding="utf-8")
    fem_bas.write_text(generate_fem_crosscheck_macro(), encoding="utf-8")
    swp_bas.write_text(generate_sweep_all_macro(), encoding="utf-8")
    ds_bas.write_text(generate_ds_cosim_macro(), encoding="utf-8")

    # 2. Write 1:1 CAD DXF Exports + Geometry Manifest
    board_outline = rounded_rect_poly(0.0, 0.0, 90.0, 40.0, 2.0)
    for href in ("H1", "H2", "H3", "H4"):
        hp = geom["pads"][href][next(iter(geom["pads"][href]))]
        board_outline = board_outline.difference(Point(hp["x"], hp["y"]).buffer(0.5 * hp["w"], quad_segs=16))

    write_dxf_r12_lwpolylines(
        CAD_DIR / "AE1_and_Filter_F_Cu.dxf",
        {
            "F_CU_AE1_DRIVEN": geom["ae1_driven_poly"],
            "F_CU_AE1_RETURN": geom["ae1_return_poly"],
            "F_CU_ANT_FEED": geom["ant_feed_poly"],
            "F_CU_BR_Q_LAUNCH": geom["brq_poly"],
            "F_CU_GND_COUNTERPOISE": geom["fcu_gnd_full"],
        },
    )
    write_dxf_r12_lwpolylines(
        CAD_DIR / "Counterpoise_B_Cu.dxf",
        {"B_CU_GND_PLANE": geom["bcu_gnd_full"]},
    )
    write_dxf_r12_lwpolylines(
        CAD_DIR / "Bare_ENIG_Window_F_Mask.dxf",
        {"F_MASK_BARE_ENIG_WINDOW": box(73.40, 6.65, 87.80, 20.80)},
    )
    write_dxf_r12_lwpolylines(
        CAD_DIR / "PCB_Outline_EdgeCuts.dxf",
        {"EDGE_CUTS_90x40MM": board_outline},
    )

    manifest = {
        "hardware_revision": "E.5",
        "source_kicad_pcb": "ISAC_868_KiCad9.kicad_pcb",
        "source_kicad_pcb_sha256": geom["pcb_sha256"],
        "source_ae1_mod": "ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod",
        "source_ae1_mod_sha256": geom["mod_sha256"],
        "coordinate_origin_mm": {"AuxOrigin_sheet": [103.500, 120.000], "cst_origin": "Bottom-Left PCB F.Cu (0,0,0)"},
        "enig_sheet_resistance_866p5MHz_mOhm_per_sq": round(enig_sheet_resistance_ohm(866.5e6) * 1e3, 3),
        "ae1_driven_vertices": len(geom["ae1_driven_poly"].exterior.coords) - 1,
        "ae1_return_vertices": len(geom["ae1_return_poly"].exterior.coords) - 1,
        "extracted_pads_gbr_mm": geom["pads"],
        "extracted_rf_gnd_vias_gbr_mm": [
            {"x": vx, "y": vy, "od": od, "drill": drl} for (vx, vy, od, drl) in geom["vias_gnd"]
        ],
    }
    (CAD_DIR / "geometry_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # 3. Render 4-Panel CST Simulation Blueprint
    blueprint_png = PREVIEWS_DIR / "CST_Simulation_Model_Blueprint.png"
    render_cst_blueprint(geom, blueprint_png)

    print(f"[CST-GEN] Generated {mws_bas.name} ({mws_bas.stat().st_size:,} B)")
    print(f"[CST-GEN] Generated {fem_bas.name}, {swp_bas.name}, {ds_bas.name}")
    print(f"[CST-GEN] Generated 4 DXF layers + geometry_manifest.json in {CAD_DIR.relative_to(ROOT)}/")
    print(f"[CST-GEN] Rendered {blueprint_png.relative_to(ROOT)} ({blueprint_png.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
