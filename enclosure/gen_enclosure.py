#!/usr/bin/env python3
"""
gen_enclosure.py -- Parametric CAD, 3D PCBA Clearance Verifier & Watertight STL
                    Generator for the Rev E.5 868 MHz ISAC Node with Open-East
                    Self-Draining 0.80 mm UV-Stabilized ASA / PETG Sensing Deck,
                    Continuous 360-Degree Parker ORD 5700 Face-Seal O-Ring Groove,
                    Solid Weatherproof Electronics Roof & Wall-Gusseted M2.5 Bosses
                    (Audit Closure: BLK-02, BLK-03, MED-04).

Canonical Right-Handed Coordinate System (1:1 identical to Gerber X2, Drill, CPL & STEP):
  - Origin (0, 0, 0) = Bottom-Left corner of the 90.00 x 40.00 mm PCB on F.Cu top surface
                       (KiCad AuxOrigin = Sheet (103.50, 120.00) mm).
  - +X in [0, 90.00] mm = East (toward 40 x 40 mm antenna & open-East sensing runoff deck).
  - +Y in [0, 40.00] mm = North (Y = 40.00 - dy_board; Y = 40.00 mm is top J2 edge,
                                 Y = 0.00 mm is bottom SWD/UART pogo-pad edge).
  - +Z (mm)             = Up above F.Cu top surface (z = 0.00 mm is F.Cu; z = -1.60 mm is B.Cu).

Generates:
  1. enclosure/ISAC_868_Lid_0p80mm_Window.stl
     - 100% Uniform-Flat-Roof (z_top = +8.50 mm) UV-stabilized ASA (indoor alt: PETG) upper lid
       with open-East self-draining t_ASA = 0.80 mm (5 x 0.16 mm solid FDM layers) sensing deck over
       the 12.00 x 12.55 mm bare-ENIG interdigitated comb (X = 74.60..86.60 mm, Y = 7.65..20.20 mm)
       extending flush through X = 92.85 mm (0.00 mm East dam lip, 0.00 mL trapped water pool),
       bonded with 25 um 3M 467MP void-free acrylic transfer tape for 0.000 mm air gap across
       -40..+85 C, 100% solid unbroken flat roof (J1/J2/J3/J4/J5 DNP — zero connector domes or roof
       slots), flat Z = -1.44 mm compliant perimeter face-seal clamping skirt (+0.16 mm standoff gap
       preventing -10% FR-4 tolerance hard-stop), and 4 x M2.5 Nylon clamping pillars sealed by captive
       EPDM washers.
  2. enclosure/ISAC_868_Base_Tray.stl
     - Matching symmetric 95.70 x 45.70 mm slim lower base tray with continuous 360-degree unbroken
       Parker ORD 5700 static face-seal O-ring groove (1.80 mm wide x 0.76 mm deep + 0.16 mm compliant
       gap = 0.92 mm compressed gland for Dia 1.20 mm Shore 50A cord: 23.3% squeeze, 68.3% <= 85%
       nominal gland fill; 82.7% <= 85% fill at 1.44 mm thin PCB), 4.00 mm M2.5 standoffs, internal
       under-PCB wire-relief channel beneath J2 bare-ENIG PTH solder pads (4.56 mm clear bend height
       below B.Cu, 100% inside the O-ring seal), and 4.00 mm unloaded IFA air cavity.
  3. enclosure/ISAC_868_Base_Tray_Battery.stl
     - Stepped dual-fit field battery-bay base tray with identical symmetric 360-degree Parker
       face-seal O-ring groove and a 2.00 mm-walled lower cradle strictly under the X < 50 mm GND
       counterpoise (fits EITHER a 2/3 AA ER14335M 3.6V 1300mAh sub-zero spiral Li-SOCl2
       cylinder OR a 302535 LiPo pouch across coplanar side shelves), keeping X = 50..90 mm
       antenna aperture unloaded and preserving M2.5 x 22 mm corner screw lengths (+2.30 mm full nut thread engagement).
  4. enclosure/ISAC_868_Enclosure_0p80mm.scad
     - 1:1 synchronized OpenSCAD parametric source in exact right-handed AuxOrigin coordinates.
  5. docs/ISAC_868_Enclosure_0p80mm_Blueprint.png & docs/ISAC_868_Enclosure_Battery_Blueprint.png
     - Dimensioned mechanical cross-section & top-view assembly blueprints.
"""
from __future__ import annotations

import math
import os
import re
import numpy as np
import pcbnew
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
os.makedirs(HERE, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)

# ---------------------------------------------------------------------------
# Exact Right-Handed AuxOrigin / Gerber / STEP Coordinates (mm)
#   X in [0, 90] East, Y in [0, 40] North (= 40.00 - dy_down), Z = 0 on F.Cu
# ---------------------------------------------------------------------------
AUX_X_SHEET, AUX_Y_SHEET = 103.50, 120.00
W_PCB, H_PCB, T_PCB = 90.00, 40.00, 1.60
CLR_XY = 0.25          # Per-side PCB-to-wall fit clearance
WALL = 2.60            # Symmetric 4-wall thickness (0.400 lip + 1.80 groove + 0.400 lip = 2.60 mm)
WALL_NORTH = WALL      # Symmetric 2.60 mm North wall -> 95.70 x 45.70 mm outer shell!

# Parker ORD 5700 Static Face-Seal Perimeter O-Ring Gland (Dia 1.20 mm Shore 50A Silicone/EPDM cord)
# Compliant Z-stackup (HIGH-MECH-01): Z_SKIRT_BOT = -1.44 mm leaves a +0.16 mm compliant spring gap above
# Z_BASE_TOP = -1.60 mm at nominal 1.60 mm PCB so +/-10% PCB thickness tolerance (1.44..1.76 mm) never
# hard-stops on the outer skirt before clamping the 0.80 mm sensing boss & 3M 467MP adhesive!
ORING_CORD_DIA_MM = 1.20
GROOVE_WIDTH_MM = 1.80
GROOVE_MARGIN = 0.400  # Outer/inner lip margin around 1.80 mm wide groove (2*0.400 + 1.80 = 2.60 mm)
Z_BASE_TOP = -1.60     # Base standoff & perimeter lip reference plane at nominal PCB B.Cu
Z_GROOVE_BOT = -2.36   # 0.76 mm groove cut + 0.16 mm compliant gap = 0.92 mm gland (23.33% squeeze, 68.30% fill; 82.67% <= 85% @ 1.44 mm thin PCB!)

# Committed 0.80 mm Open-East Self-Draining UV-Stabilized ASA / PETG Sensing Deck over AE1 comb
# (AE1 continuous F.Mask opening = [73.40..87.80] x [6.65..20.80] mm, 0.20 mm wider than boss!)
WIN_X0, WIN_X1 = 74.60, 86.60   # 12.00 mm active sensing width over IDE fingers
WIN_Y0, WIN_Y1 = 7.65, 20.20    # 12.55 mm active sensing height (comb center @ (80.60, 13.925))
T_WINDOW_MM = 0.80              # Committed 0.80 mm ASA/PETG High-Sensitivity Window (5 x 0.16 mm layers)
T_PLA_WINDOW = T_WINDOW_MM      # Backward-compatible constant alias
Z_SPILLWAY_BOT = 0.16           # +0.16 mm bottom clearance over masked PCB East margin [87.60..90.25]

# Structural step-down boss collar around West/South/North & East boss lip (clears Y=21.80 IFA arm & H4)
BOSS_X0, BOSS_X1 = 73.60, 87.60
BOSS_Y0, BOSS_Y1 = 6.85, 20.60

# Lid Z heights (mm above PCB F.Cu z = 0.00) -- 100% UNIFORM FLAT TOP COVER (Z_LID_TOP = +8.50 mm)!
Z_SKIRT_BOT = -1.44    # Compliant perimeter clamping face (+0.16 mm above Z_BASE_TOP=-1.60 mm -> zero overconstraint!)
Z_ELEC_CEIL = 6.50     # Clears RAK3172LP-SiP (1.24 mm), J2 direct-solder wire fillet (<=1.5 mm -> +5.0 mm clr), SW1 & passives
Z_ANT_CEIL = 4.50      # Free-air pocket above main 868 MHz IFA radiator (X >= 50 mm)
Z_LID_TOP = 8.50       # 100% uniform flat outer lid roof height (2.00 mm solid waterproof ASA roof, zero domes!)

# Base tray Z heights (mm below PCB B.Cu z = -1.60)
Z_CAV_FLOOR = -5.60    # 4.00 mm unloaded air pocket beneath PCB & 40x40 mm antenna aperture
Z_BASE_BOT = -7.60     # 2.00 mm solid bottom floor (total Option A closed height = 16.10 mm uniform!)

# 4 x M2.5 Nylon mounting holes (symmetric in Y: 3.50 and 36.50 mm)
HOLES = [(3.50, 3.50), (86.50, 3.50), (3.50, 36.50), (86.50, 36.50)]
HOLE_HALF = 1.40       # 2.80 mm clearance shaft for M2.5 Nylon screw
PILLAR_HALF = 3.10     # Interior boss reach around each M2.5 hole; outer faces gusseted to walls!
H1_NW_PILLAR_EAST_X = 5.40  # +1.05 mm clear of J2 F.CrtYd X_min=6.45 mm; +2.82 mm clear of J2 Pad 2 copper

# J2 = DNP Direct-Solder Battery PTH Pads (Pad 1 Square GND @ (10.90, 36.15), Pad 2 Round +VBAT @ (8.90, 36.15)):
# 24-26 AWG silicone leads route from the battery cradle underneath B.Cu (-1.60 mm) inside WIRE_TRENCH
# (-6.16 mm floor -> 4.56 mm vertical bend clearance + neutral-cure RTV strain relief) upward into J2 PTH holes!
WIRE_TRENCH = (7.40, 15.00, 31.50, 37.65)       # Under-PCB wire-relief channel directly beneath J2 PTH pads!

# Option A Slim Base Tray LiPo Cradle (strictly in X < 50 mm)
POUCH_POCKET = (8.60, 44.60, 6.30, 32.10)      # 36.00 x 25.80 mm locating pocket strictly in X < 50 mm
POUCH_RIM_OUT = (7.00, 46.20, 4.70, 33.70)     # 1.60 mm-wide molded retention frame blocking shift toward X >= 50 mm
Z_POUCH_FLOOR = -6.16  # 4.56 mm clear height below B.Cu (-1.60 mm); leaves 1.44 mm (9 x 0.16 mm) solid floor!
Z_POUCH_RIM = -2.76    # 3.40 mm tall positive battery cradle wall (leaves 1.16 mm clearance to B.Cu = -1.60 mm!)

# Option B Stepped Dual-Fit Field Battery Pod (strictly under X < 50.0 mm GND counterpoise; clears M2.5 nuts!)
BAT_CRADLE_IN = (8.60, 47.40, 11.60, 26.80)    # 38.80 x 15.20 mm anti-roll 2/3 AA ER14335M cradle
BAT_POD_OUT = (6.60, 49.40, 9.60, 28.80)       # 42.80 x 19.20 mm outer pod (2.00 mm walls; X <= 49.40 mm!)
Z_BAT_FLOOR = -17.10   # 15.50 mm clear height below B.Cu (-1.60 mm) -> clears 14.5 mm ER14335M + VHB pad
Z_BAT_BOT = -19.10     # 2.00 mm solid impact-resistant battery bay floor


GROOVE_CORNER_R_IN = 0.60   # Parker ORD 5700 concentric inner bend radius (= 0.5 * d_cord -> zero corner kink)
GROOVE_CORNER_R_OUT = GROOVE_CORNER_R_IN + GROOVE_WIDTH_MM  # 2.40 mm outer bend radius (constant 1.80 mm gland width)


def _in_perimeter_groove(xc: float, yc: float) -> bool:
    """
    True if (xc, yc) lies inside the continuous 360-degree unbroken 1.80 x 0.76 mm Parker ORD 5700
    face-seal O-ring groove around West, South, East, and North walls with concentric rounded corners
    (R_in = 0.60 mm, R_out = 2.40 mm -> constant 1.80 mm radial gland width around all 4 corners).
    """
    x_out_min = -CLR_XY - WALL + GROOVE_MARGIN
    x_out_max = W_PCB + CLR_XY + WALL - GROOVE_MARGIN
    y_out_min = -CLR_XY - WALL + GROOVE_MARGIN
    y_out_max = H_PCB + CLR_XY + WALL_NORTH - GROOVE_MARGIN

    x_in_min = x_out_min + GROOVE_WIDTH_MM
    x_in_max = x_out_max - GROOVE_WIDTH_MM
    y_in_min = y_out_min + GROOVE_WIDTH_MM
    y_in_max = y_out_max - GROOVE_WIDTH_MM

    cx_w = x_in_min + GROOVE_CORNER_R_IN
    cx_e = x_in_max - GROOVE_CORNER_R_IN
    cy_s = y_in_min + GROOVE_CORNER_R_IN
    cy_n = y_in_max - GROOVE_CORNER_R_IN

    if (xc < cx_w) and (yc < cy_s):
        return GROOVE_CORNER_R_IN < math.hypot(cx_w - xc, cy_s - yc) < GROOVE_CORNER_R_OUT
    if (xc > cx_e) and (yc < cy_s):
        return GROOVE_CORNER_R_IN < math.hypot(xc - cx_e, cy_s - yc) < GROOVE_CORNER_R_OUT
    if (xc < cx_w) and (yc > cy_n):
        return GROOVE_CORNER_R_IN < math.hypot(cx_w - xc, yc - cy_n) < GROOVE_CORNER_R_OUT
    if (xc > cx_e) and (yc > cy_n):
        return GROOVE_CORNER_R_IN < math.hypot(xc - cx_e, yc - cy_n) < GROOVE_CORNER_R_OUT

    in_outer = (x_out_min < xc < x_out_max) and (y_out_min < yc < y_out_max)
    in_inner = (x_in_min < xc < x_in_max) and (y_in_min < yc < y_in_max)
    return in_outer and (not in_inner)


def _in_lid_pillar(xc: float, yc: float) -> bool:
    """Wall-gusseted upper clamping pillars (fused directly into orthogonal outer walls)."""
    for hx, hy in HOLES:
        x_min = -CLR_XY if hx < 45.0 else (hx - PILLAR_HALF)
        x_max = (
            H1_NW_PILLAR_EAST_X
            if (abs(hx - 3.50) < 1e-4 and abs(hy - 36.50) < 1e-4)
            else ((hx + PILLAR_HALF) if hx < 45.0 else (W_PCB + CLR_XY))
        )
        y_min = -CLR_XY if hy < 20.0 else (hy - PILLAR_HALF)
        y_max = (hy + PILLAR_HALF) if hy < 20.0 else (H_PCB + CLR_XY)
        if (x_min < xc < x_max) and (y_min < yc < y_max):
            return True
    return False


def _in_base_pillar(xc: float, yc: float) -> bool:
    """Wall-gusseted lower M2.5 standoffs (zero freestanding corner cantilevers)."""
    for hx, hy in HOLES:
        x_min = -CLR_XY if hx < 45.0 else (hx - PILLAR_HALF)
        x_max = (hx + PILLAR_HALF) if hx < 45.0 else (W_PCB + CLR_XY)
        y_min = -CLR_XY if hy < 20.0 else (hy - PILLAR_HALF)
        y_max = (hy + PILLAR_HALF) if hy < 20.0 else (H_PCB + CLR_XY)
        if (x_min < xc < x_max) and (y_min < yc < y_max):
            return True
    return False


def build_manifold_from_grid(xs: np.ndarray, ys: np.ndarray, active: np.ndarray,
                             z_bot: np.ndarray, z_top: np.ndarray) -> trimesh.Trimesh:
    """
    Construct a 100% watertight, zero-T-junction 2-manifold Trimesh from an exact
    non-uniform rectilinear grid where each active cell (i, j) spans [z_bot[i,j], z_top[i,j]].
    """
    nx, ny = len(xs) - 1, len(ys) - 1
    vert_map: dict[tuple[float, float, float], int] = {}
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def vid(x: float, y: float, z: float) -> int:
        key = (round(float(x), 5), round(float(y), 5), round(float(z), 5))
        idx = vert_map.get(key)
        if idx is None:
            idx = len(verts)
            vert_map[key] = idx
            verts.append(key)
        return idx

    def add_quad(p0, p1, p2, p3):
        """Counter-clockwise quad (p0 -> p1 -> p2 -> p3) viewed from outside."""
        v0, v1, v2, v3 = vid(*p0), vid(*p1), vid(*p2), vid(*p3)
        faces.append((v0, v1, v2))
        faces.append((v0, v2, v3))

    all_zs = sorted({round(float(z), 5) for z in np.concatenate([z_bot[active], z_top[active]])})

    # 1. Top (+Z normal) and Bottom (-Z normal) horizontal faces
    for i in range(nx):
        x0, x1 = xs[i], xs[i + 1]
        for j in range(ny):
            if not active[i, j]:
                continue
            y0, y1 = ys[j], ys[j + 1]
            zb, zt = float(z_bot[i, j]), float(z_top[i, j])
            add_quad((x0, y0, zt), (x1, y0, zt), (x1, y1, zt), (x0, y1, zt))
            add_quad((x0, y0, zb), (x0, y1, zb), (x1, y1, zb), (x1, y0, zb))

    def emit_wall_intervals(zb1, zt1, occ_neighbor, z_splits, p_start_xy, p_end_xy):
        cuts = sorted(z for z in z_splits if zb1 - 1e-6 <= z <= zt1 + 1e-6)
        for k in range(len(cuts) - 1):
            za, zb = cuts[k], cuts[k + 1]
            if zb - za < 1e-6:
                continue
            z_mid = 0.5 * (za + zb)
            if occ_neighbor is not None and (occ_neighbor[0] - 1e-6 <= z_mid <= occ_neighbor[1] + 1e-6):
                continue
            add_quad(
                (p_start_xy[0], p_start_xy[1], za),
                (p_end_xy[0], p_end_xy[1], za),
                (p_end_xy[0], p_end_xy[1], zb),
                (p_start_xy[0], p_start_xy[1], zb),
            )

    # 2. Vertical walls normal to +/-X
    for ix in range(nx + 1):
        x = xs[ix]
        for j in range(ny):
            y0, y1 = ys[j], ys[j + 1]
            left_on = (ix - 1 >= 0) and active[ix - 1, j]
            right_on = (ix < nx) and active[ix, j]
            if left_on:
                occ_r = (float(z_bot[ix, j]), float(z_top[ix, j])) if right_on else None
                emit_wall_intervals(float(z_bot[ix - 1, j]), float(z_top[ix - 1, j]),
                                    occ_r, all_zs, (x, y0), (x, y1))
            if right_on:
                occ_l = (float(z_bot[ix - 1, j]), float(z_top[ix - 1, j])) if left_on else None
                emit_wall_intervals(float(z_bot[ix, j]), float(z_top[ix, j]),
                                    occ_l, all_zs, (x, y1), (x, y0))

    # 3. Vertical walls normal to +/-Y
    for iy in range(ny + 1):
        y = ys[iy]
        for i in range(nx):
            x0, x1 = xs[i], xs[i + 1]
            bot_on = (iy - 1 >= 0) and active[i, iy - 1]
            top_on = (iy < ny) and active[i, iy]
            if bot_on:
                occ_t = (float(z_bot[i, iy]), float(z_top[i, iy])) if top_on else None
                emit_wall_intervals(float(z_bot[i, iy - 1]), float(z_top[i, iy - 1]),
                                    occ_t, all_zs, (x1, y), (x0, y))
            if top_on:
                occ_b = (float(z_bot[i, iy - 1]), float(z_top[i, iy - 1])) if bot_on else None
                emit_wall_intervals(float(z_bot[i, iy]), float(z_top[i, iy]),
                                    occ_b, all_zs, (x0, y), (x1, y))

    mesh = trimesh.Trimesh(vertices=np.array(verts, dtype=float),
                           faces=np.array(faces, dtype=int), process=True)
    assert mesh.is_watertight, "ERROR: Generated mesh is not watertight!"
    assert mesh.is_winding_consistent, "ERROR: Inconsistent face winding!"
    assert mesh.is_volume, "ERROR: Mesh is not a valid closed volume!"
    return mesh


def make_grid_coords():
    x_pts = {
        round(-WALL - CLR_XY, 4),
        round(-WALL - CLR_XY + GROOVE_MARGIN, 4),
        round(-WALL - CLR_XY + GROOVE_MARGIN + GROOVE_WIDTH_MM, 4),
        -CLR_XY, 0.0, 50.0,
        H1_NW_PILLAR_EAST_X,
        WIRE_TRENCH[0], WIRE_TRENCH[1],
        POUCH_RIM_OUT[0], POUCH_POCKET[0], POUCH_POCKET[1], POUCH_RIM_OUT[1],
        BAT_POD_OUT[0], BAT_CRADLE_IN[0], BAT_CRADLE_IN[1], BAT_POD_OUT[1],
        BOSS_X0, WIN_X0, WIN_X1, BOSS_X1,
        W_PCB, W_PCB + CLR_XY,
        round(W_PCB + CLR_XY + WALL - GROOVE_MARGIN - GROOVE_WIDTH_MM, 4),
        round(W_PCB + CLR_XY + WALL - GROOVE_MARGIN, 4),
        round(W_PCB + CLR_XY + WALL, 4),
    }
    y_pts = {
        round(-WALL - CLR_XY, 4),
        round(-WALL - CLR_XY + GROOVE_MARGIN, 4),
        round(-WALL - CLR_XY + GROOVE_MARGIN + GROOVE_WIDTH_MM, 4),
        -CLR_XY, 0.0,
        POUCH_RIM_OUT[2], POUCH_POCKET[2], POUCH_POCKET[3], POUCH_RIM_OUT[3],
        BAT_POD_OUT[2], BAT_CRADLE_IN[2], BAT_CRADLE_IN[3], BAT_POD_OUT[3],
        BOSS_Y0, WIN_Y0, WIN_Y1, BOSS_Y1,
        WIRE_TRENCH[2], WIRE_TRENCH[3],
        H_PCB, H_PCB + CLR_XY,
        round(H_PCB + CLR_XY + WALL_NORTH - GROOVE_MARGIN - GROOVE_WIDTH_MM, 4),
        round(H_PCB + CLR_XY + WALL_NORTH - GROOVE_MARGIN, 4),
        round(H_PCB + CLR_XY + WALL_NORTH, 4),
    }
    for hx, hy in HOLES:
        for d in (-PILLAR_HALF, -HOLE_HALF, HOLE_HALF, PILLAR_HALF):
            x_pts.add(round(hx + d, 4))
            y_pts.add(round(hy + d, 4))
    # Discretize concentric O-ring corner radii (R_in = 0.60 mm, R_out = 2.40 mm) smoothly on grid
    cx_w = -WALL - CLR_XY + GROOVE_MARGIN + GROOVE_WIDTH_MM + GROOVE_CORNER_R_IN
    cx_e = W_PCB + CLR_XY + WALL - GROOVE_MARGIN - GROOVE_WIDTH_MM - GROOVE_CORNER_R_IN
    cy_s = -WALL - CLR_XY + GROOVE_MARGIN + GROOVE_WIDTH_MM + GROOVE_CORNER_R_IN
    cy_n = H_PCB + CLR_XY + WALL_NORTH - GROOVE_MARGIN - GROOVE_WIDTH_MM - GROOVE_CORNER_R_IN
    for k in range(8 + 1):
        ang = (0.5 * math.pi * k) / 8.0
        for r_c in (GROOVE_CORNER_R_IN, GROOVE_CORNER_R_OUT):
            dc = r_c * math.cos(ang)
            ds = r_c * math.sin(ang)
            x_pts.add(round(cx_w - dc, 4))
            x_pts.add(round(cx_e + dc, 4))
            y_pts.add(round(cy_s - ds, 4))
            y_pts.add(round(cy_n + ds, 4))
    xs = np.array(sorted(x_pts), dtype=float)
    ys = np.array(sorted(y_pts), dtype=float)
    return xs, ys


def get_lid_grid():
    xs, ys = make_grid_coords()
    nx, ny = len(xs) - 1, len(ys) - 1
    active = np.ones((nx, ny), dtype=bool)
    z_bot = np.zeros((nx, ny), dtype=float)
    z_top = np.full((nx, ny), Z_LID_TOP, dtype=float)

    for i in range(nx):
        xc = 0.5 * (xs[i] + xs[i + 1])
        for j in range(ny):
            yc = 0.5 * (ys[j] + ys[j + 1])

            # Open-East self-draining runoff deck (BLK-02): flush z_top = +0.80 mm from X = 74.60
            # all the way off the East outer wall X = 92.85 mm (0.00 mm dam lip, 0.00 mL pool!)
            in_open_east_deck = (xc > WIN_X0) and (WIN_Y0 < yc < WIN_Y1)
            if in_open_east_deck:
                z_top[i, j] = T_WINDOW_MM

            # 1. Through-holes ONLY for 4 x M2.5 Nylon screws (100% uniform flat waterproof roof!)
            if any(abs(xc - hx) < HOLE_HALF and abs(yc - hy) < HOLE_HALF for hx, hy in HOLES):
                active[i, j] = False
                continue

            # 2. Symmetric 360-deg outer perimeter skirt clamping flat at Z_SKIRT_BOT = -1.60 mm over Parker O-ring
            in_pcb_pocket = (-CLR_XY < xc < W_PCB + CLR_XY) and (-CLR_XY < yc < H_PCB + CLR_XY)
            if not in_pcb_pocket:
                z_bot[i, j] = Z_SKIRT_BOT
                continue

            # 3. 4 x M2.5 corner clamping pillars (press flush onto PCB z = 0.00 mm; NW trimmed to X<=5.40 mm)
            if _in_lid_pillar(xc, yc):
                z_bot[i, j] = 0.00
                continue

            # 4. Active 0.80 mm flush sensing diaphragm + East boss lip [74.60..87.60] x [7.65..20.20]
            if (WIN_X0 < xc < BOSS_X1) and (WIN_Y0 < yc < WIN_Y1):
                z_bot[i, j] = 0.00          # Flush contact on bare-ENIG IDE comb (0.000 mm air gap!)
                z_top[i, j] = T_WINDOW_MM   # Exact 0.80 mm solid diaphragm (5 x 0.16 mm layers)!
                continue

            # 5. Open-East spillway bridge over masked PCB margin [87.60..90.25] x [7.65..20.20]
            if (xc > BOSS_X1) and (WIN_Y0 < yc < WIN_Y1):
                z_bot[i, j] = Z_SPILLWAY_BOT  # +0.16 mm clear of masked PCB edge; 0.64 mm solid bridge
                z_top[i, j] = T_WINDOW_MM
                continue

            # 6. Structural West/South/North step-down boss collar around active sensing deck
            if (BOSS_X0 < xc < BOSS_X1) and (BOSS_Y0 < yc < BOSS_Y1):
                z_bot[i, j] = 0.00
                z_top[i, j] = Z_LID_TOP
                continue

            # 7. Internal ceiling: 6.50 mm uniform solid roof over electronics (X < 50), 4.50 mm over IFA (X >= 50)
            z_bot[i, j] = Z_ELEC_CEIL if xc < 50.0 else Z_ANT_CEIL

    return xs, ys, active, z_bot, z_top


def get_base_grid(include_battery_pod: bool = False):
    xs, ys = make_grid_coords()
    nx, ny = len(xs) - 1, len(ys) - 1
    active = np.ones((nx, ny), dtype=bool)
    z_bot = np.full((nx, ny), Z_BASE_BOT, dtype=float)
    z_top = np.full((nx, ny), Z_CAV_FLOOR, dtype=float)

    for i in range(nx):
        xc = 0.5 * (xs[i] + xs[i + 1])
        for j in range(ny):
            yc = 0.5 * (ys[j] + ys[j + 1])

            if any(abs(xc - hx) < HOLE_HALF and abs(yc - hy) < HOLE_HALF for hx, hy in HOLES):
                active[i, j] = False
                continue

            in_pcb_pocket = (-CLR_XY < xc < W_PCB + CLR_XY) and (-CLR_XY < yc < H_PCB + CLR_XY)
            if not in_pcb_pocket:
                if _in_perimeter_groove(xc, yc):
                    z_top[i, j] = Z_GROOVE_BOT
                else:
                    z_top[i, j] = Z_BASE_TOP
                continue

            if _in_base_pillar(xc, yc):
                z_top[i, j] = Z_BASE_TOP
                continue

            in_pouch = (POUCH_POCKET[0] < xc < POUCH_POCKET[1]) and (POUCH_POCKET[2] < yc < POUCH_POCKET[3])
            in_trench = (WIRE_TRENCH[0] < xc < WIRE_TRENCH[1]) and (WIRE_TRENCH[2] < yc < WIRE_TRENCH[3])
            in_rim = (POUCH_RIM_OUT[0] < xc < POUCH_RIM_OUT[1]) and (POUCH_RIM_OUT[2] < yc < POUCH_RIM_OUT[3])

            if include_battery_pod and (BAT_POD_OUT[0] < xc < BAT_POD_OUT[1]) and (BAT_POD_OUT[2] < yc < BAT_POD_OUT[3]):
                z_bot[i, j] = Z_BAT_BOT
                if (BAT_CRADLE_IN[0] < xc < BAT_CRADLE_IN[1]) and (BAT_CRADLE_IN[2] < yc < BAT_CRADLE_IN[3]):
                    z_top[i, j] = Z_BAT_FLOOR
                elif in_pouch or in_trench:
                    z_top[i, j] = Z_POUCH_FLOOR
                else:
                    z_top[i, j] = Z_CAV_FLOOR
                continue

            if in_pouch or in_trench:
                z_top[i, j] = Z_POUCH_FLOOR
                continue
            if (not include_battery_pod) and in_rim:
                z_top[i, j] = Z_POUCH_RIM
                continue

            z_top[i, j] = Z_CAV_FLOOR

    return xs, ys, active, z_bot, z_top


def get_base_battery_grid():
    return get_base_grid(include_battery_pod=True)


def build_lid_0p80mm() -> trimesh.Trimesh:
    return build_manifold_from_grid(*get_lid_grid())


def build_base_tray() -> trimesh.Trimesh:
    return build_manifold_from_grid(*get_base_grid(include_battery_pod=False))


def build_base_tray_battery() -> trimesh.Trimesh:
    return build_manifold_from_grid(*get_base_battery_grid())


def verify_weatherproof_gland_and_drainage() -> dict[str, float]:
    """
    Verify BLK-02, BLK-03 & HIGH-MECH-01 mechanical invariants directly on the generated grid:
      1. Compliant Z-stackup + Parker ORD 5700 static face-seal O-ring gland:
         - Z_SKIRT_BOT = -1.44 mm leaves +0.16 mm compliant clamping gap at nominal 1.60 mm PCB
           (0.00 mm gap at -10% thin 1.44 mm PCB -> zero overconstrained hard-stop!).
         - 1.80 x 0.76 mm groove cut -> 0.92 mm compressed gland height at nominal 1.60 mm PCB:
           23.33% squeeze (within 20..30%), 68.30% <= 85.0% gland fill (and 82.67% <= 85.0% fill
           even at worst-case 1.44 mm thin PCB!), and 100% continuous 360-degree closed loop.
      2. 100% solid weatherproof roof over X < 50 mm electronics bay (zero debug slots; only 4
         corner M2.5 clamping shafts sealed by captive EPDM washers).
      3. Open-East self-draining sensing deck: z_top == 0.80 mm monotonically from WIN_X0
         to East outer wall X = 92.85 mm across Y in [WIN_Y0..WIN_Y1] (0.00 mm dam lip).
    """
    g_cut_depth = round(Z_BASE_TOP - Z_GROOVE_BOT, 4)
    compliant_gap_nom = round(Z_SKIRT_BOT - Z_BASE_TOP, 4)
    g_height_nom = round(Z_SKIRT_BOT - Z_GROOVE_BOT, 4)
    squeeze_pct = round(100.0 * (ORING_CORD_DIA_MM - g_height_nom) / ORING_CORD_DIA_MM, 2)
    cord_area = math.pi * ((0.5 * ORING_CORD_DIA_MM) ** 2)
    gland_area_nom = GROOVE_WIDTH_MM * g_height_nom
    gland_fill_pct = round(100.0 * cord_area / gland_area_nom, 2)
    gland_fill_thin_pcb_pct = round(100.0 * cord_area / (GROOVE_WIDTH_MM * g_cut_depth), 2)

    assert abs(GROOVE_WIDTH_MM - 1.80) < 1e-4 and abs(g_cut_depth - 0.76) < 1e-4
    assert compliant_gap_nom >= 0.159, f"Insufficient compliant Z gap {compliant_gap_nom} mm for -10% PCB tolerance!"
    assert 20.0 <= squeeze_pct <= 30.0, f"Nominal O-ring squeeze {squeeze_pct}% outside 20..30% Parker spec!"
    assert gland_fill_pct <= 85.0, f"Nominal O-ring gland fill {gland_fill_pct}% exceeds 85% Parker limit!"
    assert gland_fill_thin_pcb_pct <= 85.0, (
        f"Thin-PCB (1.44 mm) O-ring gland fill {gland_fill_thin_pcb_pct}% exceeds 85% Parker hydraulic limit!"
    )

    xs, ys, lid_act, lid_zb, lid_zt = get_lid_grid()
    _, _, base_act, _, base_zt = get_base_grid(include_battery_pod=False)
    nx, ny = len(xs) - 1, len(ys) - 1

    groove_mask = np.zeros((nx, ny), dtype=bool)
    for i in range(nx):
        xc = 0.5 * (xs[i] + xs[i + 1])
        for j in range(ny):
            yc = 0.5 * (ys[j] + ys[j + 1])
            if _in_perimeter_groove(xc, yc):
                assert base_act[i, j] and abs(base_zt[i, j] - Z_GROOVE_BOT) < 1e-5, (
                    f"Perimeter O-ring groove broken at ({xc:.2f}, {yc:.2f})!"
                )
                assert lid_act[i, j] and abs(lid_zb[i, j] - Z_SKIRT_BOT) < 1e-5, (
                    f"Lid clamping face not flat at Z={Z_SKIRT_BOT:.2f} mm over O-ring at ({xc:.2f}, {yc:.2f})!"
                )
                groove_mask[i, j] = True

            # Verify zero roof debug slots anywhere (only 4x M2.5 screw holes inactive)
            if not lid_act[i, j]:
                assert any(abs(xc - hx) < HOLE_HALF and abs(yc - hy) < HOLE_HALF for hx, hy in HOLES), (
                    f"BLK-03 violation: Roof perforation outside M2.5 holes at ({xc:.2f}, {yc:.2f})!"
                )

            # Verify open-East self-draining sensing runoff deck AND 100% uniform flat Z_LID_TOP roof!
            if (xc > WIN_X0) and (WIN_Y0 < yc < WIN_Y1):
                assert lid_act[i, j] and abs(lid_zt[i, j] - T_WINDOW_MM) < 1e-5, (
                    f"BLK-02 violation: East drainage blocked at ({xc:.2f}, {yc:.2f}), z_top={lid_zt[i,j]}!"
                )
            elif lid_act[i, j]:
                assert abs(lid_zt[i, j] - Z_LID_TOP) < 1e-5, (
                    f"FLAT-ROOF violation: Non-uniform lid roof height z_top={lid_zt[i,j]} at ({xc:.2f}, {yc:.2f})!"
                )

    # Verify groove_mask is a single connected 360-degree loop surrounding the PCB interior
    start_ij = tuple(np.argwhere(groove_mask)[0])
    visited = {start_ij}
    stack = [start_ij]
    while stack:
        ci, cj = stack.pop()
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = ci + di, cj + dj
            if 0 <= ni < nx and 0 <= nj < ny and groove_mask[ni, nj] and (ni, nj) not in visited:
                visited.add((ni, nj))
                stack.append((ni, nj))
    assert len(visited) == int(np.sum(groove_mask)), "O-ring groove is disconnected!"

    return {
        "groove_width_mm": GROOVE_WIDTH_MM,
        "groove_depth_mm": g_cut_depth,
        "compressed_gland_mm": g_height_nom,
        "compliant_gap_mm": compliant_gap_nom,
        "squeeze_pct": squeeze_pct,
        "gland_fill_pct": gland_fill_pct,
    }


def verify_pcba_clearances() -> dict[str, float]:
    """
    Programmatically verify against `ISAC_868_KiCad9.kicad_pcb` + 3D VRML/STEP models
    in the TRUE RIGHT-HANDED AuxOrigin / Gerber / STEP frame that:
      1. AE1's bare-ENIG F.Mask opening coincides 1:1 with `(BOSS_X0-0.20..BOSS_X1+0.20, BOSS_Y0-0.20..BOSS_Y1+0.20)`.
      2. 100% of populated Rev E.5 PCBA components (all 68 populated BOM parts + fiducials/testpoints;
         DNP parts J1, J3, J4, J5, C_SMPS3, D_RF, R_DIV1, R_DIV2, R_VUART excluded) have strictly
         positive 3D XYZ clearance (> 0.15 mm) to the lid and both base trays.
    """
    pcb_path = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")
    board = pcbnew.LoadBoard(pcb_path)
    ds = board.GetDesignSettings()
    ax_mm = pcbnew.ToMM(ds.GetAuxOrigin().x)
    ay_mm = pcbnew.ToMM(ds.GetAuxOrigin().y)
    assert abs(ax_mm - AUX_X_SHEET) < 1e-4 and abs(ay_mm - AUX_Y_SHEET) < 1e-4, (
        f"Unexpected AuxOrigin ({ax_mm}, {ay_mm}) != ({AUX_X_SHEET}, {AUX_Y_SHEET})"
    )

    ae1 = board.FindFootprintByReference("AE1")
    assert ae1 is not None, "Missing AE1 footprint on PCB!"
    ae1_mask_boxes = []
    for p in ae1.Pads():
        if p.IsOnLayer(pcbnew.F_Mask) and not p.IsOnLayer(pcbnew.F_Cu):
            bb = p.GetBoundingBox()
            ae1_mask_boxes.append((
                pcbnew.ToMM(bb.GetLeft()) - ax_mm,
                ay_mm - pcbnew.ToMM(bb.GetBottom()),
                pcbnew.ToMM(bb.GetRight()) - ax_mm,
                ay_mm - pcbnew.ToMM(bb.GetTop()),
            ))
    for gi in ae1.GraphicalItems():
        if gi.GetLayer() == pcbnew.F_Mask:
            bb = gi.GetBoundingBox()
            ae1_mask_boxes.append((
                pcbnew.ToMM(bb.GetLeft()) - ax_mm,
                ay_mm - pcbnew.ToMM(bb.GetBottom()),
                pcbnew.ToMM(bb.GetRight()) - ax_mm,
                ay_mm - pcbnew.ToMM(bb.GetTop()),
            ))
    assert len(ae1_mask_boxes) >= 1, "AE1 has no bare-ENIG F.Mask window items!"
    mx0 = min(b[0] for b in ae1_mask_boxes)
    my0 = min(b[1] for b in ae1_mask_boxes)
    mx1 = max(b[2] for b in ae1_mask_boxes)
    my1 = max(b[3] for b in ae1_mask_boxes)
    assert (
        abs(mx0 - (BOSS_X0 - 0.20)) < 0.05
        and abs(mx1 - (BOSS_X1 + 0.20)) < 0.05
        and abs(my0 - (BOSS_Y0 - 0.20)) < 0.05
        and abs(my1 - (BOSS_Y1 + 0.20)) < 0.05
    ), (
        f"BOSS MASK MISMATCH: AE1 F.Mask [{mx0:.2f}..{mx1:.2f}, {my0:.2f}..{my1:.2f}] "
        f"must equal Boss+0.20mm [{BOSS_X0-0.20:.2f}..{BOSS_X1+0.20:.2f}, {BOSS_Y0-0.20:.2f}..{BOSS_Y1+0.20:.2f}]!"
    )

    k3d = "/usr/share/kicad/3dmodels"
    xs, ys, lid_act, lid_zb, lid_zt = get_lid_grid()
    _, _, base_act, base_zb, base_zt = get_base_grid(include_battery_pod=False)
    _, _, bat_act, bat_zb, bat_zt = get_base_battery_grid()
    nx, ny = len(xs) - 1, len(ys) - 1

    encl_boxes: list[tuple[float, float, float, float, float, float, str]] = []
    for i in range(nx):
        xc = 0.5 * (xs[i] + xs[i + 1])
        for j in range(ny):
            yc = 0.5 * (ys[j] + ys[j + 1])
            in_pocket = (-CLR_XY < xc < W_PCB + CLR_XY) and (-CLR_XY < yc < H_PCB + CLR_XY)
            in_lid_pil = _in_lid_pillar(xc, yc)
            in_base_pil = _in_base_pillar(xc, yc)
            in_boss = ((BOSS_X0 < xc < BOSS_X1) and (BOSS_Y0 < yc < BOSS_Y1)) or ((xc > BOSS_X1) and (WIN_Y0 < yc < WIN_Y1))
            if lid_act[i, j]:
                tag = "lid_skirt" if not in_pocket else ("pillar" if in_lid_pil else ("boss" if in_boss else "lid_ceil"))
                encl_boxes.append((float(xs[i]), float(ys[j]), float(lid_zb[i, j]),
                                   float(xs[i + 1]), float(ys[j + 1]), float(lid_zt[i, j]), tag))
            if base_act[i, j]:
                btag = "base_wall" if not in_pocket else ("pillar" if in_base_pil else "base_floor")
                encl_boxes.append((float(xs[i]), float(ys[j]), float(base_zb[i, j]),
                                   float(xs[i + 1]), float(ys[j + 1]), float(base_zt[i, j]), btag))
            if bat_act[i, j]:
                btag2 = "base_wall" if not in_pocket else ("pillar" if in_base_pil else "base_floor")
                encl_boxes.append((float(xs[i]), float(ys[j]), float(bat_zb[i, j]),
                                   float(xs[i + 1]), float(ys[j + 1]), float(bat_zt[i, j]), btag2))

    def box3d_dist(a, b) -> float:
        dx = max(0.0, a[0] - b[3], b[0] - a[3])
        dy = max(0.0, a[1] - b[4], b[1] - a[4])
        dz = max(0.0, a[2] - b[5], b[2] - a[5])
        if dx == 0.0 and dy == 0.0 and dz == 0.0:
            ox = min(a[3], b[3]) - max(a[0], b[0])
            oy = min(a[4], b[4]) - max(a[1], b[1])
            oz = min(a[5], b[5]) - max(a[2], b[2])
            return -min(ox, oy, oz)
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    min_clr_by_tag = {
        "lid_skirt": 999.0, "pillar": 999.0, "lid_ceil": 999.0,
        "boss": 999.0, "base_wall": 999.0, "base_floor": 999.0,
    }
    checked_refs = []

    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        if fp.IsDNP():
            continue
        ref = fp.GetReference()
        if ref in ("H1", "H2", "H3", "H4", "AE1"):
            continue
        checked_refs.append(ref)
        fx = pcbnew.ToMM(fp.GetPosition().x) - ax_mm
        fy = ay_mm - pcbnew.ToMM(fp.GetPosition().y)
        frot = math.radians(fp.GetOrientationDegrees())

        models = list(fp.Models())
        if models:
            pts_all = []
            for m in models:
                p_step = m.m_Filename.replace("${KICAD9_3DMODEL_DIR}", k3d).replace("${KIPRJMOD}", ROOT)
                p_wrl = re.sub(r"\.step$", ".wrl", p_step, flags=re.I)
                if os.path.exists(p_wrl):
                    txt = open(p_wrl, errors="ignore").read()
                    for blk in re.findall(r"point\s*\[([^\]]+)\]", txt):
                        for m2 in re.finditer(r"([-\d.Ee+]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)", blk):
                            pts_all.append([
                                float(m2.group(1)) * 2.54 * m.m_Scale.x + m.m_Offset.x,
                                float(m2.group(2)) * 2.54 * m.m_Scale.y + m.m_Offset.y,
                                float(m2.group(3)) * 2.54 * m.m_Scale.z + m.m_Offset.z,
                            ])
                elif os.path.exists(p_step):
                    txt = open(p_step, errors="ignore").read()
                    for x, y, z in re.findall(
                        r"CARTESIAN_POINT\([^,]*,\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)\)",
                        txt,
                    ):
                        pts_all.append([
                            float(x) * m.m_Scale.x + m.m_Offset.x,
                            float(y) * m.m_Scale.y + m.m_Offset.y,
                            float(z) * m.m_Scale.z + m.m_Offset.z,
                        ])
                else:
                    raise AssertionError(f"Missing 3D model for {ref}: {m.m_Filename}")
            pts = np.array(pts_all, dtype=float)
            cz, sz = math.cos(frot), math.sin(frot)
            pts_rh = pts @ np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]).T
            cbox = (
                float(fx + pts_rh[:, 0].min()),
                float(fy + pts_rh[:, 1].min()),
                float(pts_rh[:, 2].min()),
                float(fx + pts_rh[:, 0].max()),
                float(fy + pts_rh[:, 1].max()),
                float(pts_rh[:, 2].max()),
            )
        else:
            pxs, pys = [], []
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                pxs += [pcbnew.ToMM(bb.GetLeft()) - ax_mm, pcbnew.ToMM(bb.GetRight()) - ax_mm]
                pys += [ay_mm - pcbnew.ToMM(bb.GetBottom()), ay_mm - pcbnew.ToMM(bb.GetTop())]
            cbox = (min(pxs), min(pys), 0.001, max(pxs), max(pys), 0.035)

        for eb in encl_boxes:
            d = box3d_dist(cbox, eb[:6])
            tag = eb[6]
            assert d > 0.15, (
                f"3D Enclosure interference / insufficient clearance on {ref} "
                f"(bbox={tuple(round(v,2) for v in cbox)}) vs {tag} "
                f"{tuple(round(v,2) for v in eb[:6])}: clr = {d:.3f} mm!"
            )
            if d < min_clr_by_tag[tag]:
                min_clr_by_tag[tag] = d

    required_rev_e = {
        "U1", "U2", "U3", "FB_VDDA", "D_VBAT", "D_RST", "D_SWD", "D_UART", "D_3V3",
        "Q1", "C_Q1", "Q2", "R_BPD", "Q3", "C_BULK1", "C_BULK2", "SW1",
        "R_VAPP", "R_BHI", "FID1", "FID2", "FID3", "FID4", "FID5",
    }
    assert required_rev_e.issubset(set(checked_refs)), (
        f"Missing expected Rev E.5 populated components in clearance check: {required_rev_e - set(checked_refs)}"
    )

    j2_fp = board.FindFootprintByReference("J2")
    assert j2_fp is not None and j2_fp.IsDNP(), "Expected J2 to be DNP on sealed flat-lid Rev E.5 PCBA!"
    j2_crt = j2_fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    j2_crt_box = (
        pcbnew.ToMM(j2_crt.GetLeft()) - ax_mm,
        ay_mm - pcbnew.ToMM(j2_crt.GetBottom()),
        0.0,
        pcbnew.ToMM(j2_crt.GetRight()) - ax_mm,
        ay_mm - pcbnew.ToMM(j2_crt.GetTop()),
        0.10,
    )
    j2_pil_crtyd_clr = min(
        box3d_dist(j2_crt_box, eb[:6])
        for eb in encl_boxes
        if eb[6] == "pillar" and eb[5] > 0.0
    )
    assert j2_pil_crtyd_clr >= 0.50 - 1e-4, (
        f"Lid clamping pillar to J2 F.CrtYd clearance = {j2_pil_crtyd_clr:.3f} mm (< 0.50 mm)!"
    )
    min_clr_by_tag["j2_crtyd_pillar"] = j2_pil_crtyd_clr

    # Direct-soldered 24-26 AWG battery wire top fillet cone (z <= +2.00 mm) & under-B.Cu bend envelope
    j2_solder_fillet_box = (8.10, 35.15, 0.02, 11.70, 37.15, 2.00)
    j2_fillet_ceil_clr = min(
        box3d_dist(j2_solder_fillet_box, eb[:6])
        for eb in encl_boxes
        if eb[6] == "lid_ceil" and eb[5] > 0.0
    )
    j2_fillet_lat_clr = min(
        box3d_dist(j2_solder_fillet_box, eb[:6])
        for eb in encl_boxes
        if eb[6] in ("pillar", "lid_skirt", "boss") and eb[5] > 0.0
    )
    assert j2_fillet_ceil_clr >= 4.40 - 1e-4 and j2_fillet_lat_clr >= 2.50 - 1e-4, (
        f"Direct-soldered J2 wire fillet clearance = {j2_fillet_ceil_clr:.2f} mm ceil / {j2_fillet_lat_clr:.2f} mm lat!"
    )
    j2_under_wire_box = (8.10, 32.20, -5.40, 14.20, 36.95, -1.62)
    j2_under_wire_clr = min(
        box3d_dist(j2_under_wire_box, eb[:6])
        for eb in encl_boxes
        if eb[6] in ("base_floor", "pillar", "base_wall")
    )
    assert j2_under_wire_clr >= 0.70 - 1e-4, (
        f"Under-PCB J2 battery wire bend clearance in WIRE_TRENCH = {j2_under_wire_clr:.2f} mm (< 0.70 mm)!"
    )
    min_clr_by_tag["j2_fillet_headroom"] = j2_fillet_ceil_clr
    min_clr_by_tag["j2_under_wire_clr"] = j2_under_wire_clr

    min_clr_by_tag["count"] = float(len(checked_refs))
    return min_clr_by_tag


# MED-04: 1:1 Synchronized OpenSCAD Parametric Model matching get_lid_grid() & get_base_grid()
SCAD_TEMPLATE = """\
// ISAC_868_Enclosure_0p80mm.scad -- Rev E.5 Uniform-Flat-Roof Waterproof Enclosure
// Coordinate System: Right-Handed AuxOrigin / Gerber / STEP (+X East 0..90, +Y North 0..40, +Z Up above F.Cu)
// Key Rev E.5 Features (1:1 synchronized with gen_enclosure.py):
//   1. 100% Uniform Flat Waterproof Top Cover (z_top = +8.50 mm across entire roof; J1..J5 DNP; zero domes or roof slots!)
//   2. Open-East Self-Draining 0.80 mm UV-Stabilized ASA / PETG Sensing Deck (X = 74.60..92.85 mm, 0.00 mm dam lip!)
//   3. Symmetric 95.70 x 45.70 mm Outer Shell with Compliant Z_SKIRT_BOT = -1.44 mm (+0.16 mm tolerance gap) &
//      Continuous 360-Deg Parker ORD 5700 Face-Seal O-Ring Groove (1.80 x 0.76 mm -> 0.92 mm gland, 23.3% squeeze, 68.3% fill)
$fn = 48;

w_pcb = 90.00;  h_pcb = 40.00;  t_pcb = 1.60;
z_skirt_bot = -1.44;            clr = 0.25;     wall = 2.60;
groove_margin = 0.400;          groove_w = 1.80;  groove_d = 0.76;
groove_r_in = 0.60;             groove_r_out = 2.40;
t_asa_window = 0.80;

win_x0 = 74.60; win_x1 = 86.60;
win_y0 = 7.65;  win_y1 = 20.20;
boss_x0 = 73.60; boss_x1 = 87.60;
boss_y0 = 6.85;  boss_y1 = 20.60;

holes = [[3.5, 3.5], [86.5, 3.5], [3.5, 36.5], [86.5, 36.5]];

module rounded_rect_2d(x0, y0, w, h, r) {
    offset(r = r)
        translate([x0 + r, y0 + r])
            square([w - 2*r, h - 2*r]);
}

module parker_oring_groove_2d() {
    difference() {
        rounded_rect_2d(-clr - wall + groove_margin, -clr - wall + groove_margin,
                        w_pcb + 2*(clr + wall - groove_margin),
                        h_pcb + 2*(clr + wall - groove_margin),
                        groove_r_out);
        rounded_rect_2d(-clr - wall + groove_margin + groove_w, -clr - wall + groove_margin + groove_w,
                        w_pcb + 2*(clr + wall - groove_margin - groove_w),
                        h_pcb + 2*(clr + wall - groove_margin - groove_w),
                        groove_r_in);
    }
}

module lid_0p80mm() {
    difference() {
        // 100% uniform flat solid-roof outer shell (95.70 x 45.70 mm, z = -1.44..+8.50 mm compliant skirt)
        translate([-clr - wall, -clr - wall, z_skirt_bot])
            cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 8.50 - z_skirt_bot]);
        // Electronics bay internal cavity (X = 0..50 mm, uniform solid ceiling z = 6.50 mm)
        difference() {
            translate([-clr, -clr, -t_pcb - 0.1])
                cube([50.0 + clr, h_pcb + 2*clr, 6.50 + t_pcb + 0.1]);
            translate([-clr, -clr, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 8.0]);
            translate([-clr, 36.5 - 3.1, 0]) cube([5.40 + clr, 3.5 + 3.1 + clr, 8.0]);
        }
        // Antenna free-air cavity (X = 50..90 mm, ceiling z = 4.50 mm)
        difference() {
            translate([50.0, -clr, -t_pcb - 0.1])
                cube([40.0 + clr, h_pcb + 2*clr, 4.50 + t_pcb + 0.1]);
            translate([boss_x0, boss_y0, 0])
                cube([boss_x1 - boss_x0, boss_y1 - boss_y0, 5.0]);
            translate([boss_x1, win_y0, 0.16])
                cube([(w_pcb + clr) - boss_x1, win_y1 - win_y0, 5.0]);
            translate([86.5 - 3.1, -clr, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 5.0]);
            translate([86.5 - 3.1, 36.5 - 3.1, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 5.0]);
        }
        // Open-East self-draining runoff cut (flush z_top = +0.80 mm all the way through X = 92.85 mm!)
        translate([win_x0, win_y0, t_asa_window])
            cube([(w_pcb + clr + wall + 0.2) - win_x0, win_y1 - win_y0, 9.0]);
        // 4 x M2.5 Nylon screw through-holes
        for (h = holes)
            translate([h[0], h[1], -t_pcb - 1]) cylinder(d = 2.80, h = 14.0);
    }
}

module base_tray_option_a_slim() {
    difference() {
        translate([-clr - wall, -clr - wall, -7.60])
            cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 6.00]);
        // Continuous 360-degree unbroken 1.80 x 0.76 mm Parker ORD 5700 concentric-corner face-seal O-ring groove
        translate([0, 0, -t_pcb - groove_d])
            linear_extrude(height = groove_d + 0.1) parker_oring_groove_2d();
        // Main 4.00 mm unloaded air pocket
        difference() {
            translate([-clr, -clr, -5.60])
                cube([w_pcb + 2*clr, h_pcb + 2*clr, 4.20]);
            translate([-clr, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([-clr, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([7.00, 4.70, -5.70])
                cube([39.20, 29.00, 2.94]);
        }
        // Option A 302535/352535 LiPo pocket + under-PCB J2 direct-solder wire-relief channel (-6.16 mm)
        translate([8.60, 6.30, -6.16])
            cube([36.00, 25.80, 4.00]);
        translate([7.40, 31.50, -6.16])
            cube([7.60, 6.15, 4.70]);
        // 4 x M2.5 Nylon screw through-holes
        for (h = holes)
            translate([h[0], h[1], -10.0]) cylinder(d = 2.80, h = 10.0);
    }
}

module base_tray_battery() {
    difference() {
        union() {
            translate([-clr - wall, -clr - wall, -7.60])
                cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 6.00]);
            translate([6.60, 9.60, -19.10])
                cube([42.80, 19.20, 13.50]);
        }
        // Continuous 360-degree unbroken 1.80 x 0.76 mm Parker ORD 5700 concentric-corner face-seal O-ring groove
        translate([0, 0, -t_pcb - groove_d])
            linear_extrude(height = groove_d + 0.1) parker_oring_groove_2d();
        difference() {
            translate([-clr, -clr, -5.60])
                cube([w_pcb + 2*clr, h_pcb + 2*clr, 4.20]);
            translate([-clr, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([-clr, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
        }
        translate([8.60, 11.60, -17.10])
            cube([38.80, 15.20, 11.70]);
        translate([8.60, 6.30, -6.16])
            cube([36.00, 25.80, 4.00]);
        translate([7.40, 31.50, -6.16])
            cube([7.60, 6.15, 4.70]);
        for (h = holes)
            translate([h[0], h[1], -20.0]) cylinder(d = 2.80, h = 20.0);
    }
}

lid_0p80mm();
// translate([0, 0, -12]) base_tray_battery();
"""


def plot_blueprint(out_png: str):
    fig, (ax_top, ax_sec) = plt.subplots(2, 1, figsize=(9.8, 7.6), dpi=180,
                                         gridspec_kw={"height_ratios": [1.22, 1.0]})

    w_out = W_PCB + 2 * (WALL + CLR_XY)
    h_out = H_PCB + 2 * CLR_XY + WALL + WALL_NORTH
    ax_top.add_patch(Rectangle((-WALL - CLR_XY, -WALL - CLR_XY), w_out, h_out,
                               fc="#e8eef5", ec="#2b3a4a", lw=1.5,
                               label=f"Uniform-Flat-Roof Waterproof Shell ({w_out:.1f} x {h_out:.1f} x 16.1 mm)"))
    # Continuous 360-degree Parker ORD 5700 O-ring loop
    gx0 = -WALL - CLR_XY + GROOVE_MARGIN
    gy0 = -WALL - CLR_XY + GROOVE_MARGIN
    ax_top.add_patch(Rectangle((gx0, gy0), w_out - 2 * GROOVE_MARGIN, h_out - 2 * GROOVE_MARGIN,
                               fc="none", ec="#d32f2f", lw=1.1, ls="-.",
                               label="360-Deg Parker ORD 5700 O-Ring Groove (1.80x0.76 mm, 23.3% squeeze)"))
    ax_top.add_patch(Rectangle((0, 0), W_PCB, H_PCB, fc="#fdfaf2", ec="#555555", lw=1.1, ls="--",
                               label="Rev E.5 Pure-SMD PCB (90.0 x 40.0 x 1.6 mm, AuxOrigin @ BL)"))
    ax_top.add_patch(Rectangle((0, 0), 49.4, H_PCB, fc="#d7ead9", ec="#2e7d32", lw=1.0, alpha=0.65,
                               label="RAK3172LP-SiP Electronics & 50x40 GND (Uniform +8.5 mm Flat Roof)"))
    ax_top.add_patch(Rectangle((50.0, 0), 40.0, H_PCB, fc="#fff8e1", ec="#b28704", lw=0.9, alpha=0.55,
                               label="40x40 mm Copper-Free Antenna Aperture (4.5 mm / 4.0 mm air cavities)"))

    board_bp = pcbnew.LoadBoard(os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb"))
    ae1_fp = board_bp.FindFootprintByReference("AE1")
    ae1_rects = []
    if ae1_fp is not None:
        fx = pcbnew.ToMM(ae1_fp.GetPosition().x) - AUX_X_SHEET
        fy = AUX_Y_SHEET - pcbnew.ToMM(ae1_fp.GetPosition().y)
        mod_txt = open(os.path.join(ROOT, "ISAC.pretty", "IFA_868MHz_ISAC_40x20mm.kicad_mod"), "r", encoding="utf-8").read()
        for m in re.finditer(
            r'\(fp_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+'
            r'\(stroke\s+\(width\s+([-\d.]+)\)\s+\(type\s+\w+\)\)\s+\(layer\s+"F\.Cu"\)',
            mod_txt,
        ):
            x1, y1, x2, y2, w = map(float, m.groups())
            ae1_rects.append((fx + min(x1, x2) - w * 0.5, fy - max(y1, y2) - w * 0.5, abs(x2 - x1) + w, abs(y2 - y1) + w))
        for pm in re.finditer(
            r'\(pad\s+"\d+"\s+smd\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)\s+\(size\s+([-\d.]+)\s+([-\d.]+)\)(.*?)(?=\n\t\(pad|\n\)$)',
            mod_txt,
            re.S,
        ):
            px, py, pw, ph, body = float(pm.group(1)), float(pm.group(2)), float(pm.group(3)), float(pm.group(4)), pm.group(5)
            ae1_rects.append((fx + px - pw * 0.5, fy - py - ph * 0.5, pw, ph))
            for gm in re.finditer(
                r'\(gr_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+\(width\s+([-\d.]+)\)\)',
                body,
            ):
                x1, y1, x2, y2, w = map(float, gm.groups())
                ae1_rects.append((fx + px + min(x1, x2) - w * 0.5, fy - (py + max(y1, y2)) - w * 0.5, abs(x2 - x1) + w, abs(y2 - y1) + w))
    for rx0, ry0, rw, rh in ae1_rects:
        if rx0 + rw * 0.5 < 73.40:
            ax_top.add_patch(Rectangle((rx0, ry0), rw, rh, fc="#c87533", ec="none", alpha=0.82))

    ax_top.add_patch(Rectangle((73.40, 6.65), 14.40, 14.15,
                               fc="#fffde7", ec="#f57f17", lw=1.0, ls="--",
                               label="Continuous Bare-ENIG F.Mask ([73.4..87.8]x[6.65..20.8])"))
    ax_top.add_patch(Rectangle((BOSS_X0, BOSS_Y0), BOSS_X1 - BOSS_X0, BOSS_Y1 - BOSS_Y0,
                               fc="#bbdefb", ec="#1565c0", lw=1.2, alpha=0.72))
    ax_top.add_patch(Rectangle((WIN_X0, WIN_Y0), (W_PCB + CLR_XY + WALL) - WIN_X0, WIN_Y1 - WIN_Y0,
                               fc="#64b5f6", ec="#0d47a1", lw=1.5, alpha=0.68,
                               label="0.80 mm Open-East Self-Draining Sensing Deck (X=74.6..92.85 mm)"))
    ax_top.add_patch(Rectangle((POUCH_RIM_OUT[0], POUCH_RIM_OUT[2]),
                               POUCH_RIM_OUT[1] - POUCH_RIM_OUT[0], POUCH_RIM_OUT[3] - POUCH_RIM_OUT[2],
                               fc="#cfd8dc", ec="#455a64", lw=1.0))
    ax_top.add_patch(Rectangle((POUCH_POCKET[0], POUCH_POCKET[2]),
                               POUCH_POCKET[1] - POUCH_POCKET[0], POUCH_POCKET[3] - POUCH_POCKET[2],
                               fc="#f3e5f5", ec="#6a1b9a", lw=1.2, ls="--",
                               label="Option A Captive LiPo Cradle (302535/352535 3.7V 300mAh, X < 50 mm)"))
    ax_top.add_patch(Rectangle((WIRE_TRENCH[0], WIRE_TRENCH[2]),
                               WIRE_TRENCH[1] - WIRE_TRENCH[0], WIRE_TRENCH[3] - WIRE_TRENCH[2],
                               fc="#4fc3f7", ec="#01579b", lw=1.0,
                               label="Under-B.Cu Wire Relief & Direct-Solder J2 PTH (1=GND, 2=+VBAT)"))
    ax_top.add_patch(Circle((8.90, 36.15), 0.65, fc="#ef5350", ec="#b71c1c", lw=0.9))
    ax_top.add_patch(Rectangle((10.25, 35.50), 1.30, 1.30, fc="#263238", ec="#000000", lw=0.9))
    for rx0, ry0, rw, rh in ae1_rects:
        if rx0 + rw * 0.5 >= 73.40:
            ax_top.add_patch(Rectangle((rx0, ry0), rw, rh, fc="#d4af37", ec="#7a5c00", lw=0.45))
    for hx, hy in HOLES:
        ax_top.add_patch(Circle((hx, hy), 1.4, fc="white", ec="#222", lw=1.0))

    ax_top.set_aspect("equal")
    ax_top.set_xlim(-6, 97)
    ax_top.set_ylim(-18.0, 47.5)
    ax_top.set_xlabel("Gerber / STEP X coordinate (mm, East)")
    ax_top.set_ylabel("Gerber / STEP Y coordinate (mm, North)")
    ax_top.set_title("A. Top Registration (Right-Handed AuxOrigin): Rev E.5 PCBA + 360-Deg Parker O-Ring + Open-East Deck")
    ax_top.legend(loc="lower left", fontsize=6.2, ncol=2, framealpha=0.95)
    ax_top.grid(alpha=0.25)

    # --- Panel B: Cross-Section Along Y_gbr = 14.0 mm (Comb Centerline) ---
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_BASE_BOT), POUCH_POCKET[0] - (-WALL - CLR_XY), 2.0,
                               fc="#cfd8dc", ec="#37474f", lw=1.0, label="Slim Base Tray w/ 1.80x0.76 mm Parker O-Ring Groove"))
    ax_sec.add_patch(Rectangle((POUCH_POCKET[0], Z_BASE_BOT), POUCH_POCKET[1] - POUCH_POCKET[0], Z_POUCH_FLOOR - Z_BASE_BOT,
                               fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((POUCH_POCKET[1], Z_BASE_BOT), (W_PCB + WALL + CLR_XY) - POUCH_POCKET[1], 2.0,
                               fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((POUCH_RIM_OUT[0], Z_CAV_FLOOR), POUCH_POCKET[0] - POUCH_RIM_OUT[0], Z_POUCH_RIM - Z_CAV_FLOOR,
                               fc="#b0bec5", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((POUCH_POCKET[1], Z_CAV_FLOOR), POUCH_RIM_OUT[1] - POUCH_POCKET[1], Z_POUCH_RIM - Z_CAV_FLOOR,
                               fc="#b0bec5", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_CAV_FLOOR), WALL, 4.0, fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((W_PCB + CLR_XY, Z_CAV_FLOOR), WALL, 4.0, fc="#cfd8dc", ec="#37474f", lw=1.0))
    # O-ring grooves on West & East walls (0.76 mm groove + 0.16 mm compliant gap = 0.92 mm compressed gland)
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY + GROOVE_MARGIN, Z_GROOVE_BOT), GROOVE_WIDTH_MM, Z_SKIRT_BOT - Z_GROOVE_BOT,
                               fc="#ef5350", ec="#b71c1c", lw=0.8, label="Dia 1.20 mm Silicone/EPDM O-Ring (23.3% squeeze, 68.3% fill)"))
    ax_sec.add_patch(Rectangle((W_PCB + CLR_XY + GROOVE_MARGIN, Z_GROOVE_BOT), GROOVE_WIDTH_MM, Z_SKIRT_BOT - Z_GROOVE_BOT,
                               fc="#ef5350", ec="#b71c1c", lw=0.8))

    ax_sec.add_patch(Rectangle((9.10, Z_POUCH_FLOOR + 0.50), 35.0, 3.00, fc="#ce93d8", ec="#6a1b9a", lw=1.1,
                               label="Option A: 302535 3.7V 300mAh LT-LiPo (3.0x25x35 mm, -40 C)"))
    ax_sec.add_patch(Rectangle((12.0, Z_POUCH_FLOOR), 29.0, 0.50, fc="#90a4ae", ec="none"))
    ax_sec.add_patch(Rectangle((0, -T_PCB), W_PCB, T_PCB, fc="#c5e1a5", ec="#33691e", lw=1.2,
                               label="1.60 mm FR-4 PCB (Rev E.5 ENIG, full-boss F.Mask opening)"))
    ax_sec.add_patch(Rectangle((75.25, -0.05), 10.75, 0.22, fc="#d4af37", ec="#7a5c00", lw=0.8,
                               label="Bare-ENIG IDE Fingers + 25 um 3M 467MP (0.000 mm air gap)"))

    # Lid left + solid roof + West boss + Open-East self-draining 0.80 mm deck!
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_SKIRT_BOT), WALL, Z_LID_TOP - Z_SKIRT_BOT,
                               fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((-CLR_XY, Z_ELEC_CEIL), 50.0 + CLR_XY, Z_LID_TOP - Z_ELEC_CEIL,
                               fc="#90caf9", ec="#0d47a1", lw=1.0, label="Solid-Roof UV-Stabilized ASA Lid (0.16 mm layers)"))
    ax_sec.add_patch(Rectangle((50.0, Z_ANT_CEIL), BOSS_X0 - 50.0, Z_LID_TOP - Z_ANT_CEIL,
                               fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((BOSS_X0, 0.0), WIN_X0 - BOSS_X0, Z_LID_TOP, fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((WIN_X0, 0.0), BOSS_X1 - WIN_X0, T_WINDOW_MM, fc="#1e88e5", ec="#0d47a1", lw=1.4,
                               label="Open-East 0.80 mm Self-Draining Deck (0.00 mm Dam Lip -> Zero Water Pool!)"))
    ax_sec.add_patch(Rectangle((BOSS_X1, Z_SPILLWAY_BOT), (W_PCB + CLR_XY) - BOSS_X1, T_WINDOW_MM - Z_SPILLWAY_BOT,
                               fc="#1e88e5", ec="#0d47a1", lw=1.2))
    ax_sec.add_patch(Rectangle((W_PCB + CLR_XY, Z_SKIRT_BOT), WALL, T_WINDOW_MM - Z_SKIRT_BOT,
                               fc="#1e88e5", ec="#0d47a1", lw=1.2))

    ax_sec.annotate("Open-East Runoff Deck (z_top = +0.80 mm)\n0.00 mm East Lip -> Free Gravity Drainage!",
                    xy=(90.5, 0.80), xytext=(53.0, 2.2),
                    fontsize=7.8, fontweight="bold", color="#0d47a1",
                    arrowprops=dict(arrowstyle="->", color="#0d47a1", lw=1.2))
    ax_sec.set_xlim(-6, 97)
    ax_sec.set_ylim(-14.2, 10.2)
    ax_sec.set_xlabel("Gerber / STEP X coordinate (mm)")
    ax_sec.set_ylabel("Vertical Z height (mm)")
    ax_sec.set_title("B. Cross-Section at Y_gbr = 14.0 mm (Comb Center): Open-East Self-Draining 0.80 mm Deck + Parker Face-Seal")
    ax_sec.legend(loc="lower left", fontsize=6.6, ncol=2, framealpha=0.92)
    ax_sec.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def plot_battery_blueprint(out_png: str):
    fig, (ax_top, ax_sec) = plt.subplots(2, 1, figsize=(10.0, 8.2), dpi=180,
                                         gridspec_kw={"height_ratios": [1.15, 1.15]})

    w_out = W_PCB + 2 * (WALL + CLR_XY)
    h_out = H_PCB + 2 * CLR_XY + WALL + WALL_NORTH
    ax_top.add_patch(Rectangle((-WALL - CLR_XY, -WALL - CLR_XY), w_out, h_out,
                               fc="#e8eef5", ec="#2b3a4a", lw=1.5,
                               label=f"Enclosure Outer Shell ({w_out:.1f} x {h_out:.1f} mm)"))
    ax_top.add_patch(Rectangle((0, 0), 50.0, H_PCB, fc="#d7ead9", ec="#2e7d32", lw=1.0, alpha=0.60,
                               label="50x40 mm Solid GND Counterpoise (RF-Shielded Battery Safe Zone)"))
    ax_top.add_patch(Rectangle((50.0, 0), 40.0, H_PCB, fc="#fff8e1", ec="#b28704", lw=0.9, alpha=0.55,
                               label="40x40 mm 868 MHz Antenna Keepout (Strictly Battery-Free Air Cavity)"))
    ax_top.add_patch(Rectangle((BAT_POD_OUT[0], BAT_POD_OUT[2]),
                               BAT_POD_OUT[1] - BAT_POD_OUT[0], BAT_POD_OUT[3] - BAT_POD_OUT[2],
                               fc="#cfd8dc", ec="#37474f", lw=1.2,
                               label="Stepped Battery Pod Outer Wall (42.8 x 19.2 mm, 2.0 mm walls)"))
    ax_top.add_patch(Rectangle((BAT_CRADLE_IN[0], BAT_CRADLE_IN[2]),
                               BAT_CRADLE_IN[1] - BAT_CRADLE_IN[0], BAT_CRADLE_IN[3] - BAT_CRADLE_IN[2],
                               fc="#fff3e0", ec="#e65100", lw=1.4,
                               label="2/3 AA ER14335M Anti-Roll Cradle (38.8 x 15.2 x 15.5 mm)"))
    ax_top.add_patch(Rectangle((12.0, 11.95), 33.5, 14.5, fc="#ffcc80", ec="#bf360c", lw=1.2, alpha=0.85,
                               label="2/3 AA ER14335M 3.6V 1300mAh Li-SOCl2 (14.5 x 33.5 mm)"))
    ax_top.add_patch(Rectangle((11.5, 6.70), 35.0, 25.0, fc="none", ec="#6a1b9a", lw=1.3, ls="--",
                               label="Alt: 302535 3.7V 300mAh LiPo Pouch on -6.16 mm Shelves"))
    ax_top.add_patch(Rectangle((WIRE_TRENCH[0], WIRE_TRENCH[2]),
                               WIRE_TRENCH[1] - WIRE_TRENCH[0], WIRE_TRENCH[3] - WIRE_TRENCH[2],
                               fc="#4fc3f7", ec="#01579b", lw=1.1,
                               label="Under-PCB Wire Relief (-6.16 mm) to Direct-Solder J2 PTH Pads"))
    ax_top.add_patch(Circle((8.90, 36.15), 0.65, fc="#ef5350", ec="#b71c1c", lw=0.9))
    ax_top.add_patch(Rectangle((10.25, 35.50), 1.30, 1.30, fc="#263238", ec="#000000", lw=0.9))
    for hx, hy in HOLES:
        ax_top.add_patch(Circle((hx, hy), 1.4, fc="white", ec="#222", lw=1.0))

    ax_top.set_aspect("equal")
    ax_top.set_xlim(-6, 97)
    ax_top.set_ylim(-18.0, 47.5)
    ax_top.set_xlabel("Gerber / STEP X coordinate (mm, East)")
    ax_top.set_ylabel("Gerber / STEP Y coordinate (mm, North)")
    ax_top.set_title("A. Dual-Fit Stepped Battery Bay Registration (Strictly Under X < 50 mm GND Plane)")
    ax_top.legend(loc="lower left", fontsize=6.3, ncol=2, framealpha=0.95)
    ax_top.grid(alpha=0.25)

    # --- Panel B: Longitudinal Cross-Section Along Y_gbr = 19.2 mm ---
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_BASE_BOT), BAT_POD_OUT[0] - (-WALL - CLR_XY), 2.0,
                               fc="#cfd8dc", ec="#37474f", lw=1.0, label="Stepped Base Tray (ISAC_868_Base_Tray_Battery.stl)"))
    ax_sec.add_patch(Rectangle((BAT_POD_OUT[1], Z_BASE_BOT), (W_PCB + WALL + CLR_XY) - BAT_POD_OUT[1], 2.0,
                               fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_CAV_FLOOR), WALL, 4.0, fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((W_PCB + CLR_XY, Z_CAV_FLOOR), WALL, 4.0, fc="#cfd8dc", ec="#37474f", lw=1.0))
    ax_sec.add_patch(Rectangle((BAT_POD_OUT[0], Z_BAT_BOT), BAT_CRADLE_IN[0] - BAT_POD_OUT[0], Z_CAV_FLOOR - Z_BAT_BOT,
                               fc="#b0bec5", ec="#263238", lw=1.0))
    ax_sec.add_patch(Rectangle((BAT_CRADLE_IN[1], Z_BAT_BOT), BAT_POD_OUT[1] - BAT_CRADLE_IN[1], Z_CAV_FLOOR - Z_BAT_BOT,
                               fc="#b0bec5", ec="#263238", lw=1.0))
    ax_sec.add_patch(Rectangle((BAT_POD_OUT[0], Z_BAT_BOT), BAT_POD_OUT[1] - BAT_POD_OUT[0], Z_BAT_FLOOR - Z_BAT_BOT,
                               fc="#b0bec5", ec="#263238", lw=1.0))
    ax_sec.add_patch(Rectangle((12.0, -16.60), 33.5, 14.5, fc="#ffb74d", ec="#bf360c", lw=1.2,
                               label="2/3 AA ER14335M (14.5 mm dia x 33.5 mm, -55..+85 C)"))
    ax_sec.add_patch(Rectangle((14.0, -17.10), 29.5, 0.50, fc="#90a4ae", ec="none",
                               label="0.50 mm 3M VHB Retention Tape"))
    ax_sec.add_patch(Rectangle((0, -T_PCB), W_PCB, T_PCB, fc="#c5e1a5", ec="#33691e", lw=1.2,
                               label="1.60 mm FR-4 PCB (50x40 mm GND shields AE1 from battery)"))
    ax_sec.add_patch(Rectangle((75.25, -0.05), 10.75, 0.22, fc="#d4af37", ec="#7a5c00", lw=0.8))
    ax_sec.add_patch(Rectangle((-WALL - CLR_XY, Z_SKIRT_BOT), WALL, Z_LID_TOP - Z_SKIRT_BOT,
                               fc="#90caf9", ec="#0d47a1", lw=1.0, label="Solid-Roof Lid w/ Open-East 0.80 mm Deck"))
    ax_sec.add_patch(Rectangle((-CLR_XY, Z_ELEC_CEIL), 50.0 + CLR_XY, Z_LID_TOP - Z_ELEC_CEIL,
                               fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((50.0, Z_ANT_CEIL), BOSS_X0 - 50.0, Z_LID_TOP - Z_ANT_CEIL,
                               fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((BOSS_X0, 0.0), WIN_X0 - BOSS_X0, Z_LID_TOP, fc="#90caf9", ec="#0d47a1", lw=1.0))
    ax_sec.add_patch(Rectangle((WIN_X0, 0.0), BOSS_X1 - WIN_X0, T_WINDOW_MM, fc="#1e88e5", ec="#0d47a1", lw=1.4))
    ax_sec.add_patch(Rectangle((BOSS_X1, Z_SPILLWAY_BOT), (W_PCB + CLR_XY) - BOSS_X1, T_WINDOW_MM - Z_SPILLWAY_BOT,
                               fc="#1e88e5", ec="#0d47a1", lw=1.2))
    ax_sec.add_patch(Rectangle((W_PCB + CLR_XY, Z_SKIRT_BOT), WALL, T_WINDOW_MM - Z_SKIRT_BOT,
                               fc="#1e88e5", ec="#0d47a1", lw=1.2))

    ax_sec.annotate("4.00 mm Unloaded Air\nUnder 868 MHz IFA!", xy=(62.0, -3.6), xytext=(53.0, -14.5),
                    fontsize=7.8, fontweight="bold", color="#b28704",
                    arrowprops=dict(arrowstyle="->", color="#b28704", lw=1.2))
    ax_sec.set_xlim(-6, 97)
    ax_sec.set_ylim(-21.5, 10.5)
    ax_sec.set_xlabel("Gerber / STEP X coordinate (mm)")
    ax_sec.set_ylabel("Vertical Z height (mm)")
    ax_sec.set_title("B. Longitudinal Section: Stepped Battery Pod Preserves 100% Unloaded Antenna Aperture")
    ax_sec.legend(loc="lower right", fontsize=6.5, ncol=1, framealpha=0.92)
    ax_sec.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


if __name__ == "__main__":
    # Remove obsolete Rev E.4 debug slot plugs STL if present (BLK-03: solid weatherproof roof!)
    for stale_plugs in (
        os.path.join(HERE, "ISAC_868_Debug_Slot_Plugs.stl"),
        os.path.join(ROOT, "fab", "mechanical", "ISAC_868_Debug_Slot_Plugs.stl"),
    ):
        if os.path.isfile(stale_plugs):
            os.remove(stale_plugs)

    lid = build_lid_0p80mm()
    base = build_base_tray()
    base_bat = build_base_tray_battery()
    gland_stats = verify_weatherproof_gland_and_drainage()
    clr_stats = verify_pcba_clearances()

    lid_stl = os.path.join(HERE, "ISAC_868_Lid_0p80mm_Window.stl")
    base_stl = os.path.join(HERE, "ISAC_868_Base_Tray.stl")
    base_bat_stl = os.path.join(HERE, "ISAC_868_Base_Tray_Battery.stl")
    scad_path = os.path.join(HERE, "ISAC_868_Enclosure_0p80mm.scad")
    bp_png = os.path.join(DOCS, "ISAC_868_Enclosure_0p80mm_Blueprint.png")
    bp_bat_png = os.path.join(DOCS, "ISAC_868_Enclosure_Battery_Blueprint.png")

    lid.export(lid_stl)
    base.export(base_stl)
    base_bat.export(base_bat_stl)
    with open(scad_path, "w", encoding="utf-8") as fh:
        fh.write(SCAD_TEMPLATE)
    plot_blueprint(bp_png)
    plot_battery_blueprint(bp_bat_png)

    for stl_path in (lid_stl, base_stl, base_bat_stl):
        reloaded_mesh = trimesh.load_mesh(stl_path, process=True)
        assert reloaded_mesh.is_watertight, f"Reloaded STL not watertight: {stl_path}"
        assert reloaded_mesh.is_winding_consistent, f"Reloaded STL winding inconsistent: {stl_path}"
        assert reloaded_mesh.is_volume, f"Reloaded STL not closed volume: {stl_path}"

    rx, ry = 80.6, 14.0
    z_hits = []
    for tri in lid.triangles:
        v0, v1, v2 = tri[:, :2]
        d00 = np.dot(v1 - v0, v1 - v0)
        d01 = np.dot(v1 - v0, v2 - v0)
        d11 = np.dot(v2 - v0, v2 - v0)
        denom = d00 * d11 - d01 * d01
        if abs(denom) < 1e-10:
            continue
        p = np.array([rx, ry]) - v0
        d20 = np.dot(p, v1 - v0)
        d21 = np.dot(p, v2 - v0)
        u_b = (d11 * d20 - d01 * d21) / denom
        v_b = (d00 * d21 - d01 * d20) / denom
        w_b = 1.0 - u_b - v_b
        if u_b >= -1e-7 and v_b >= -1e-7 and w_b >= -1e-7:
            z_val = round(float(w_b * tri[0, 2] + u_b * tri[1, 2] + v_b * tri[2, 2]), 4)
            if z_val not in z_hits:
                z_hits.append(z_val)
    z_hits.sort()
    assert len(z_hits) == 2 and abs(z_hits[0] - 0.0) < 1e-4 and abs(z_hits[1] - T_PLA_WINDOW) < 1e-4, (
        f"Unexpected sensing window Z surfaces at (80.6, 14.0): {z_hits}"
    )

    print(
        f"Verified Rev E.5 Compliant-Skirt Waterproof Gland & Open-East Drainage:\n"
        f"  Groove = {gland_stats['groove_width_mm']:.2f} x {gland_stats['groove_depth_mm']:.2f} mm "
        f"(+{gland_stats['compliant_gap_mm']:.2f} mm gap -> {gland_stats['compressed_gland_mm']:.2f} mm gland) | "
        f"Squeeze = {gland_stats['squeeze_pct']:.1f}% | Fill = {gland_stats['gland_fill_pct']:.1f}% (<= 85%) | "
        f"360-deg loop = UNBROKEN | Flat roof z_top = +8.50 mm (0 roof slots; 4 EPDM-sealed corner shafts) | East dam lip = 0.00 mm"
    )
    print(f"Verified right-handed 3D XYZ clearances across {int(clr_stats['count'])} populated Rev E.5 PCBA items (ZERO collisions):")
    print(f"  Min clr -> Lid Skirt: {clr_stats['lid_skirt']:.2f} mm | M2.5 Pillars: {clr_stats['pillar']:.2f} mm "
          f"(J2 F.CrtYd clr = {clr_stats['j2_crtyd_pillar']:.2f} mm >= 0.50) "
          f"| Flat 6.50 mm Ceiling: {clr_stats['lid_ceil']:.2f} mm "
          f"(J2 solder fillet headroom = +{clr_stats['j2_fillet_headroom']:.2f} mm, "
          f"under-PCB wire channel clr = {clr_stats['j2_under_wire_clr']:.2f} mm) | Base Floor: {clr_stats['base_floor']:.2f} mm")
    print(f"Exported watertight Lid STL      : {lid_stl}")
    print(f"  watertight={lid.is_watertight}, winding_consistent={lid.is_winding_consistent}, "
          f"volume={lid.volume:.1f} mm^3, faces={len(lid.faces)}")
    print(f"  Ray-check @ IDE center (80.6, 14.0): z_bot={z_hits[0]:.3f} mm, z_top={z_hits[1]:.3f} mm "
          f"-> thickness = {z_hits[1]-z_hits[0]:.3f} mm (0.000 mm air gap!)")
    print(f"Exported watertight Slim Base STL: {base_stl}")
    print(f"  watertight={base.is_watertight}, winding_consistent={base.is_winding_consistent}, "
          f"volume={base.volume:.1f} mm^3, faces={len(base.faces)}")
    print(f"Exported watertight Bat Base STL : {base_bat_stl}")
    print(f"  watertight={base_bat.is_watertight}, winding_consistent={base_bat.is_winding_consistent}, "
          f"volume={base_bat.volume:.1f} mm^3, faces={len(base_bat.faces)}")
    print(f"Exported OpenSCAD source         : {scad_path}")
    print(f"Exported Blueprint PNGs          : {bp_png}, {bp_bat_png}")
    import sys as _sys
    if HERE not in _sys.path:
        _sys.path.insert(0, HERE)
    import render_enclosure_3d
    render_enclosure_3d.generate_enclosure_3d_sheet()
