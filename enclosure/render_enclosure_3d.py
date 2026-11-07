#!/usr/bin/env python3
"""
ISAC_868 Rev E.5 — Studio-Grade 3D Enclosure & PCBA Assembly Renderer
=====================================================================
Renders multi-view 2x-supersampled Z-buffered 3D views directly from the
watertight Rev E.5 enclosure STLs (`ISAC_868_Lid_0p80mm_Window.stl`,
`ISAC_868_Base_Tray.stl`, `ISAC_868_Base_Tray_Battery.stl`) and live
`ISAC_868_KiCad9.kicad_pcb` geometry:

  A. Exploded 3D Isometric Assembly (Option A: Solid-Roof Lid + 3M 467MP + Rev E.5 PCBA + Parker O-Ring + 302535 LiPo + Base)
  B. Closed Exterior 3D Isometric View (95.7 x 45.7 x 16.1 mm Uniform Flat Waterproof Roof + Open-East 0.80 mm Deck)
  C. True 3D Longitudinal Cutaway at Y_gbr = 14.0 mm (IDE Comb Centerline — Open-East 0.80 mm Runoff Deck + Parker Face-Seal)
  D. True 3D Longitudinal Cutaway at Y_gbr = 19.2 mm (Option B Stepped 2/3 AA ER14335M Pod Under X < 50 mm GND)

Outputs:
  - `docs/ISAC_868_Enclosure_3D_Exploded.png`
  - `fab/documentation/ISAC_868_Enclosure_3D_Exploded.png` (when directory exists)
"""

from __future__ import annotations

import math
import os
import shutil
import numpy as np
import pcbnew
import trimesh
from PIL import Image, ImageDraw
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
FAB_DOCS = os.path.join(ROOT, "fab", "documentation")
PCB_PATH = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")

AUX_X_MM, AUX_Y_MM = 103.50, 120.00


# ---------------------------------------------------------------------------
# Procedural 3D Primitives for Accurate Multi-Material PCBA & Battery Solids
# ---------------------------------------------------------------------------
def _box_mesh(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> trimesh.Trimesh:
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5])
    return b


def _cyl_mesh(radius: float, length: float, axis: str, center: tuple[float, float, float], sections: int = 28) -> trimesh.Trimesh:
    c = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
    if axis == "x":
        rot = trimesh.transformations.rotation_matrix(math.pi * 0.5, [0, 1, 0])
        c.apply_transform(rot)
    elif axis == "y":
        rot = trimesh.transformations.rotation_matrix(-math.pi * 0.5, [1, 0, 0])
        c.apply_transform(rot)
    c.apply_translation(center)
    return c


def _extract_ae1_copper_boxes() -> list[trimesh.Trimesh]:
    """Extract exact AE1 F.Cu copper segments & 5 IDE fingers from .kicad_pcb + .kicad_mod."""
    import re as _re
    board = pcbnew.LoadBoard(PCB_PATH)
    ae1 = board.FindFootprintByReference("AE1")
    meshes: list[trimesh.Trimesh] = []
    if ae1 is None:
        return meshes

    fx = pcbnew.ToMM(ae1.GetPosition().x) - AUX_X_MM
    fy = AUX_Y_MM - pcbnew.ToMM(ae1.GetPosition().y)
    mod_path = os.path.join(ROOT, "ISAC.pretty", "IFA_868MHz_ISAC_40x20mm.kicad_mod")
    txt = open(mod_path, "r", encoding="utf-8").read()

    for m in _re.finditer(
        r'\(fp_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+'
        r'\(stroke\s+\(width\s+([-\d.]+)\)\s+\(type\s+\w+\)\)\s+\(layer\s+"F\.Cu"\)',
        txt,
    ):
        x1, y1, x2, y2, w = map(float, m.groups())
        x0, xa = fx + min(x1, x2) - w * 0.5, fx + max(x1, x2) + w * 0.5
        y0, ya = fy - max(y1, y2) - w * 0.5, fy - min(y1, y2) + w * 0.5
        meshes.append(_box_mesh(x0, xa, y0, ya, 0.00, 0.07))

    for pm in _re.finditer(
        r'\(pad\s+"\d+"\s+smd\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)\s+\(size\s+([-\d.]+)\s+([-\d.]+)\)(.*?)(?=\n\t\(pad|\n\)$)',
        txt,
        _re.S,
    ):
        px, py, pw, ph, body = float(pm.group(1)), float(pm.group(2)), float(pm.group(3)), float(pm.group(4)), pm.group(5)
        meshes.append(_box_mesh(fx + px - pw * 0.5, fx + px + pw * 0.5, fy - py - ph * 0.5, fy - py + ph * 0.5, 0.00, 0.07))
        for gm in _re.finditer(
            r'\(gr_line\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+\(end\s+([-\d.]+)\s+([-\d.]+)\)\s+\(width\s+([-\d.]+)\)\)',
            body,
        ):
            x1, y1, x2, y2, w = map(float, gm.groups())
            x0, xa = fx + px + min(x1, x2) - w * 0.5, fx + px + max(x1, x2) + w * 0.5
            y0, ya = fy - (py + max(y1, y2)) - w * 0.5, fy - (py + min(y1, y2)) + w * 0.5
            meshes.append(_box_mesh(x0, xa, y0, ya, 0.00, 0.07))

    return meshes


def build_pcba_parts(z_shift: float = 0.0) -> list[dict]:
    """
    Build multi-material 3D PCBA solids directly from live ISAC_868_KiCad9.kicad_pcb
    component placements (all populated parts; DNP parts excluded).
    """
    board = pcbnew.LoadBoard(PCB_PATH)
    parts: list[dict] = []

    def add_part(meshes_list, color, spec=0.22, shininess=24.0, cut_color=None, closed=True):
        if not meshes_list:
            return
        m = trimesh.util.concatenate(meshes_list) if len(meshes_list) > 1 else meshes_list[0].copy()
        if abs(z_shift) > 1e-6:
            m.apply_translation([0.0, 0.0, z_shift])
        parts.append({
            "mesh": m,
            "color": np.array(color, dtype=np.float32),
            "cut_color": np.array(cut_color if cut_color is not None else color, dtype=np.float32),
            "spec": spec,
            "shininess": shininess,
            "alpha": 1.0,
            "closed": closed,
        })

    # 1. 1.60 mm Green LPI FR-4 Substrate + Bare FR-4 Sensing Window [73.40..87.80] x [6.65..20.80]
    add_part([_box_mesh(0.0, 90.0, 0.0, 40.0, -1.60, 0.00)],
             color=(0.16, 0.36, 0.21), cut_color=(0.68, 0.76, 0.48), spec=0.18, shininess=18.0)
    # 50x40 mm Masked Copper Counterpoise tint on Top/Bottom (lighter LPI green over 1 oz Cu)
    add_part([_box_mesh(0.25, 49.70, 0.25, 39.75, -0.01, 0.02)],
             color=(0.21, 0.44, 0.26), cut_color=(0.68, 0.76, 0.48), spec=0.20, shininess=22.0)
    # Bare FR-4 amber laminate exposed inside continuous F.Mask opening [73.40..87.80] x [6.65..20.80]
    add_part([_box_mesh(73.40, 87.80, 6.65, 20.80, -0.01, 0.025)],
             color=(0.76, 0.63, 0.34), cut_color=(0.76, 0.63, 0.34), spec=0.12, shininess=12.0)

    # 2. Exact AE1 Bare-ENIG Gold Interdigital Comb + Masked IFA Trace
    ae1_gold = []
    ae1_masked = []
    for cm in _extract_ae1_copper_boxes():
        cx = float(cm.bounds[:, 0].mean())
        cy = float(cm.bounds[:, 1].mean())
        if 73.30 <= cx <= 87.90 and 6.55 <= cy <= 20.90:
            ae1_gold.append(cm)
        else:
            ae1_masked.append(cm)
    add_part(ae1_masked, color=(0.24, 0.47, 0.27), spec=0.20, shininess=20.0)
    add_part(ae1_gold, color=(0.91, 0.74, 0.22), cut_color=(0.95, 0.80, 0.28), spec=0.55, shininess=48.0)

    # 3. Live Populated Component Solids from .kicad_pcb
    ic_black = []
    passives_body = []
    gold_metals = []
    ivory_shrouds = []
    header_black = []
    silver_metals = []

    # Fiducials & Test Points (ENIG gold discs)
    for fp in board.GetFootprints():
        if fp.IsDNP():
            continue
        ref = fp.GetReference()
        pos = fp.GetPosition()
        xg = pcbnew.ToMM(pos.x) - AUX_X_MM
        yg = AUX_Y_MM - pcbnew.ToMM(pos.y)

        if ref == "AE1" or ref.startswith("H"):
            continue
        if ref.startswith(("FID", "TP")):
            r_mm = 0.50 if ref.startswith("FID") else 0.55
            gold_metals.append(_cyl_mesh(r_mm, 0.05, "z", (xg, yg, 0.025), sections=18))
            continue
        if ref == "U1":
            # RAK3172LP-SiP 12x12x1.22 mm LGA-73
            ic_black.append(_box_mesh(xg - 6.0, xg + 6.0, yg - 6.0, yg + 6.0, 0.02, 1.24))
            ivory_shrouds.append(_cyl_mesh(0.45, 0.04, "z", (xg - 4.6, yg + 4.6, 1.25), sections=16))
            continue
        if ref == "J1":
            # Molex 73251-1153 Edge-Launch Brass/Gold SMA
            gold_metals.append(_box_mesh(xg - 4.76, xg + 4.76, 38.40, 41.60, -2.80, 3.80))
            # Straddle legs on F.Cu & B.Cu
            for lx in (xg - 4.25, xg + 4.25):
                gold_metals.append(_box_mesh(lx - 0.50, lx + 0.50, 35.20, 38.50, 0.00, 0.65))
                gold_metals.append(_box_mesh(lx - 0.50, lx + 0.50, 35.20, 38.50, -2.25, -1.60))
            gold_metals.append(_box_mesh(xg - 0.38, xg + 0.38, 36.20, 38.50, 0.00, 0.45))
            # Threaded coaxial barrel extending North
            gold_metals.append(_cyl_mesh(3.15, 7.40, "y", (xg, 45.30, 0.90), sections=28))
            ivory_shrouds.append(_cyl_mesh(2.05, 7.45, "y", (xg, 45.32, 0.90), sections=20))
            gold_metals.append(_cyl_mesh(0.62, 7.55, "y", (xg, 45.35, 0.90), sections=14))
            continue
        if ref == "J2":
            # JST B2B-PH-K-S 2-pin ivory battery shroud (Pin 1 @ xg, Pin 2 @ xg - 2.00)
            cx_j2 = xg - 1.00
            ivory_shrouds.append(_box_mesh(cx_j2 - 2.95, cx_j2 + 2.95, yg - 2.25, yg + 2.25, 0.02, 6.00))
            for px in (xg - 2.00, xg):
                silver_metals.append(_cyl_mesh(0.32, 7.80, "z", (px, yg, 0.90), sections=12))
            continue
        if ref in ("J3", "J4", "J5"):
            pads = list(fp.Pads())
            xs = [pcbnew.ToMM(p.GetPosition().x) - AUX_X_MM for p in pads]
            ys = [AUX_Y_MM - pcbnew.ToMM(p.GetPosition().y) for p in pads]
            header_black.append(_box_mesh(min(xs) - 1.27, max(xs) + 1.27, min(ys) - 1.27, max(ys) + 1.27, 0.02, 2.56))
            for px, py in zip(xs, ys):
                gold_metals.append(_box_mesh(px - 0.32, px + 0.32, py - 0.32, py + 0.32, -2.80, 5.80))
            continue
        if ref == "SW1":
            silver_metals.append(_box_mesh(xg - 1.50, xg + 1.50, yg - 1.25, yg + 1.25, 0.02, 1.15))
            ic_black.append(_cyl_mesh(0.65, 0.45, "z", (xg, yg, 1.35), sections=16))
            continue

        # Generic SMD ICs, MOSFETs, inductors & passives sized from F.Cu / F.Fab bbox
        bb = fp.GetBoundingBox(False, False)
        bx0 = max(0.2, pcbnew.ToMM(bb.GetLeft()) - AUX_X_MM)
        bx1 = min(89.8, pcbnew.ToMM(bb.GetRight()) - AUX_X_MM)
        by0 = max(0.2, AUX_Y_MM - pcbnew.ToMM(bb.GetBottom()))
        by1 = min(39.8, AUX_Y_MM - pcbnew.ToMM(bb.GetTop()))
        dx = max(0.55, min(3.4, (bx1 - bx0) * 0.68))
        dy = max(0.55, min(3.4, (by1 - by0) * 0.68))
        cx, cy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
        if ref.startswith(("U", "Q", "D_")):
            h_z = 0.95 if ref != "U2" else 0.78
            ic_black.append(_box_mesh(cx - dx * 0.5, cx + dx * 0.5, cy - dy * 0.5, cy + dy * 0.5, 0.02, h_z))
        elif ref == "L_SMPS":
            ic_black.append(_box_mesh(xg - 1.0, xg + 1.0, yg - 0.62, yg + 0.62, 0.02, 0.95))
        elif ref in ("C_BULK1", "C_BULK2"):
            passives_body.append(_box_mesh(xg - 1.0, xg + 1.0, yg - 0.62, yg + 0.62, 0.02, 1.25))
        else:
            passives_body.append(_box_mesh(cx - dx * 0.42, cx + dx * 0.42, cy - dy * 0.42, cy + dy * 0.42, 0.02, 0.52))

    # Direct-soldered J2 bare-ENIG PTH pads + trimmed top solder cones + bottom-fed 26 AWG Red/Black silicone leads
    gold_metals.append(_box_mesh(10.90 - 0.68, 10.90 + 0.68, 36.15 - 0.88, 36.15 + 0.88, -1.62, 0.04))  # Pad 1 Square GND
    gold_metals.append(_cyl_mesh(0.72, 1.66, "z", (8.90, 36.15, -0.79), sections=18))                    # Pad 2 Round +VBAT
    for px_j2 in (8.90, 10.90):
        silver_metals.append(_cyl_mesh(0.46, 0.85, "z", (px_j2, 36.15, 0.45), sections=16))
    red_lead = [
        _cyl_mesh(0.52, 2.30, "z", (8.90, 36.15, -2.75), sections=14),
        _cyl_mesh(0.52, 4.60, "y", (8.90, 33.85, -3.85), sections=14),
    ]
    black_lead = [
        _cyl_mesh(0.52, 2.30, "z", (10.90, 36.15, -2.75), sections=14),
        _cyl_mesh(0.52, 4.60, "y", (10.90, 33.85, -3.85), sections=14),
    ]

    add_part(ic_black, color=(0.14, 0.15, 0.17), spec=0.28, shininess=28.0)
    add_part(header_black, color=(0.12, 0.12, 0.14), spec=0.22, shininess=20.0)
    add_part(passives_body, color=(0.56, 0.44, 0.30), spec=0.20, shininess=18.0)
    add_part(ivory_shrouds, color=(0.93, 0.91, 0.84), spec=0.24, shininess=22.0)
    add_part(silver_metals, color=(0.78, 0.80, 0.83), spec=0.48, shininess=40.0)
    add_part(gold_metals, color=(0.90, 0.73, 0.20), spec=0.60, shininess=52.0)
    add_part(red_lead, color=(0.86, 0.16, 0.14), spec=0.30, shininess=24.0)
    add_part(black_lead, color=(0.10, 0.11, 0.13), spec=0.26, shininess=22.0)

    return parts


# ---------------------------------------------------------------------------
# Vectorized 2x-SSAA Studio Z-Buffer + Shadow-Map + Section-Cap Renderer
# ---------------------------------------------------------------------------
def _look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = np.array([0.0, 0.0, 1.0])) -> np.ndarray:
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    right = right / np.linalg.norm(right)
    true_up = np.cross(right, fwd)
    R = np.stack([right, true_up, -fwd], axis=0)  # Camera looks along -Z_cam -> depth = -Z_cam
    return R


def _clip_triangles_y_ge(verts_tri: np.ndarray, y_cut: float) -> np.ndarray:
    """
    Exact Sutherland-Hodgman 3D triangle clipping against half-space Y >= y_cut.
    Input: (N, 3, 3) triangle vertices in world coordinates.
    Output: (M, 3, 3) clipped triangles.
    """
    d = verts_tri[:, :, 1] - y_cut  # >= 0 means inside
    inside_cnt = np.sum(d >= 0.0, axis=1)

    full_in = verts_tri[inside_cnt == 3]
    partial_idx = np.where((inside_cnt == 1) | (inside_cnt == 2))[0]
    if len(partial_idx) == 0:
        return full_in

    out_tris = [full_in] if len(full_in) > 0 else []
    for idx in partial_idx:
        tri = verts_tri[idx]
        poly = []
        for i in range(3):
            p1 = tri[i]
            p2 = tri[(i + 1) % 3]
            d1 = p1[1] - y_cut
            d2 = p2[1] - y_cut
            if d1 >= 0.0:
                poly.append(p1)
            if (d1 >= 0.0) != (d2 >= 0.0):
                t = d1 / (d1 - d2)
                poly.append(p1 + t * (p2 - p1))
        if len(poly) == 3:
            out_tris.append(np.array([poly], dtype=np.float64))
        elif len(poly) == 4:
            out_tris.append(np.array([[poly[0], poly[1], poly[2]], [poly[0], poly[2], poly[3]]], dtype=np.float64))

    return np.concatenate(out_tris, axis=0) if out_tris else np.zeros((0, 3, 3), dtype=np.float64)


def _extract_crease_edges(mesh: trimesh.Trimesh, angle_deg: float = 24.0) -> np.ndarray:
    """Return (E, 2, 3) world-space crease edges where adjacent face normals differ by > angle_deg."""
    try:
        adj_edges = mesh.face_adjacency_edges
        adj_angles = mesh.face_adjacency_angles
        mask = adj_angles > math.radians(angle_deg)
        sel = adj_edges[mask]
        if len(sel) == 0:
            return np.zeros((0, 2, 3), dtype=np.float64)
        return mesh.vertices[sel]
    except Exception:
        return np.zeros((0, 2, 3), dtype=np.float64)


def _rasterize_depth_only(tris_px: np.ndarray, tris_z: np.ndarray, zbuf: np.ndarray):
    """Fast scanline/bbox Z-buffer fill for directional shadow map."""
    H, W = zbuf.shape
    x0 = tris_px[:, 0, 0]
    y0 = tris_px[:, 0, 1]
    x1 = tris_px[:, 1, 0]
    y1 = tris_px[:, 1, 1]
    x2 = tris_px[:, 2, 0]
    y2 = tris_px[:, 2, 1]

    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    valid = np.abs(denom) > 1e-6
    idxs = np.where(valid)[0]

    min_xs = np.maximum(0, np.floor(np.minimum(np.minimum(x0, x1), x2)).astype(np.int32))
    max_xs = np.minimum(W - 1, np.ceil(np.maximum(np.maximum(x0, x1), x2)).astype(np.int32))
    min_ys = np.maximum(0, np.floor(np.minimum(np.minimum(y0, y1), y2)).astype(np.int32))
    max_ys = np.minimum(H - 1, np.ceil(np.maximum(np.maximum(y0, y1), y2)).astype(np.int32))

    for i in idxs:
        ix0, ix1 = min_xs[i], max_xs[i]
        iy0, iy1 = min_ys[i], max_ys[i]
        if ix0 > ix1 or iy0 > iy1:
            continue
        inv_d = 1.0 / denom[i]
        px = np.arange(ix0, ix1 + 1, dtype=np.float32) + 0.5
        py = np.arange(iy0, iy1 + 1, dtype=np.float32) + 0.5
        gx, gy = np.meshgrid(px, py)
        w0 = ((y1[i] - y2[i]) * (gx - x2[i]) + (x2[i] - x1[i]) * (gy - y2[i])) * inv_d
        w1 = ((y2[i] - y0[i]) * (gx - x2[i]) + (x0[i] - x2[i]) * (gy - y2[i])) * inv_d
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
        if not np.any(inside):
            continue
        z_interp = w0 * tris_z[i, 0] + w1 * tris_z[i, 1] + w2 * tris_z[i, 2]
        sub_z = zbuf[iy0:iy1 + 1, ix0:ix1 + 1]
        upd = inside & (z_interp < sub_z)
        sub_z[upd] = z_interp[upd]


def render_scene(
    objects: list[dict],
    eye_dir: tuple[float, float, float],
    target: tuple[float, float, float],
    half_width_mm: float,
    img_size: tuple[int, int] = (1100, 760),
    y_cut: float | None = None,
    bg_top: tuple[float, float, float] = (0.955, 0.968, 0.985),
    bg_bot: tuple[float, float, float] = (0.875, 0.902, 0.938),
) -> Image.Image:
    """
    2x-SSAA Orthographic CAD Studio Renderer with:
      - Directional 1024x1024 PCF shadow map
      - 3-Point Studio Blinn-Phong + Hemisphere Sky/Ground Irradiance
      - Exact Rossignac-Borrel 3D Watertight Section-Plane Capping (when y_cut is set)
      - Alpha-Translucent pass (for inspecting window / cavity internals)
      - Anti-aliased CAD Crease Edges
    """
    out_w, out_h = img_size
    W, H = out_w * 2, out_h * 2  # 2x SSAA

    target_v = np.array(target, dtype=np.float64)
    dir_v = np.array(eye_dir, dtype=np.float64)
    dir_v = dir_v / np.linalg.norm(dir_v)
    eye_v = target_v + dir_v * 260.0
    R_cam = _look_at(eye_v, target_v)
    view_dir = dir_v  # vector from surface toward camera

    aspect = W / float(H)
    half_h_mm = half_width_mm / aspect

    def world_to_screen(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rel = (pts - eye_v) @ R_cam.T
        sx = (rel[..., 0] / half_width_mm * 0.5 + 0.5) * W
        sy = (0.5 - rel[..., 1] / half_h_mm * 0.5) * H
        depth = -rel[..., 2]  # positive distance from camera plane
        return np.stack([sx, sy], axis=-1), depth

    # Studio 3-point lighting directions (normalized vectors pointing TOWARD light)
    key_dir = np.array([-0.42, -0.52, 0.74], dtype=np.float64)
    key_dir /= np.linalg.norm(key_dir)
    fill_dir = np.array([0.65, -0.25, 0.72], dtype=np.float64)
    fill_dir /= np.linalg.norm(fill_dir)
    rim_dir = np.array([0.20, 0.82, 0.54], dtype=np.float64)
    rim_dir /= np.linalg.norm(rim_dir)

    # Pre-clip all object triangles
    prepared = []
    all_opaque_tris = []
    for obj in objects:
        raw_tris = obj["mesh"].triangles.copy()
        if y_cut is not None:
            raw_tris = _clip_triangles_y_ge(raw_tris, y_cut)
        if len(raw_tris) == 0:
            continue
        e1 = raw_tris[:, 1] - raw_tris[:, 0]
        e2 = raw_tris[:, 2] - raw_tris[:, 0]
        nrm = np.cross(e1, e2)
        nlen = np.linalg.norm(nrm, axis=1, keepdims=True)
        valid_n = nlen[:, 0] > 1e-10
        raw_tris = raw_tris[valid_n]
        nrm = nrm[valid_n] / nlen[valid_n]
        creases = _extract_crease_edges(obj["mesh"], angle_deg=24.0)
        if y_cut is not None and len(creases) > 0:
            keep_e = (creases[:, 0, 1] >= y_cut - 1e-4) & (creases[:, 1, 1] >= y_cut - 1e-4)
            creases = creases[keep_e]
        rec = dict(obj)
        rec["tris"] = raw_tris
        rec["normals"] = nrm
        rec["creases"] = creases
        prepared.append(rec)
        if obj.get("alpha", 1.0) >= 0.99:
            all_opaque_tris.append(raw_tris)

    # Build 1024x1024 directional shadow map for key light
    SW = 1024
    shadow_z = np.full((SW, SW), 1e9, dtype=np.float32)
    light_eye = target_v + key_dir * 260.0
    R_light = _look_at(light_eye, target_v)
    sh_half = max(half_width_mm * 1.25, 72.0)

    def world_to_light(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rel = (pts - light_eye) @ R_light.T
        lx = (rel[..., 0] / sh_half * 0.5 + 0.5) * SW
        ly = (0.5 - rel[..., 1] / sh_half * 0.5) * SW
        lz = -rel[..., 2]
        return np.stack([lx, ly], axis=-1), lz

    if all_opaque_tris:
        cat_tris = np.concatenate(all_opaque_tris, axis=0)
        l_px, l_z = world_to_light(cat_tris)
        _rasterize_depth_only(l_px.astype(np.float32), l_z.astype(np.float32), shadow_z)

    # Background vertical studio gradient
    t_grad = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    c_top = np.array(bg_top, dtype=np.float32)[None, None, :]
    c_bot = np.array(bg_bot, dtype=np.float32)[None, None, :]
    color_buf = (1.0 - t_grad) * c_top + t_grad * c_bot
    color_buf = np.broadcast_to(color_buf, (H, W, 3)).copy()
    z_buf = np.full((H, W), 1e9, dtype=np.float32)

    def shade_triangles(normals: np.ndarray, base_rgb: np.ndarray, spec_k: float, shininess: float) -> np.ndarray:
        ndotl_key = np.clip(normals @ key_dir, 0.0, 1.0)
        ndotl_fill = np.clip(normals @ fill_dir, 0.0, 1.0)
        ndotl_rim = np.clip(normals @ rim_dir, 0.0, 1.0)
        hemi = 0.5 + 0.5 * normals[:, 2]  # Sky vs ground ambient

        h_vec = key_dir + view_dir
        h_vec /= np.linalg.norm(h_vec)
        spec = (np.clip(normals @ h_vec, 0.0, 1.0) ** shininess) * spec_k

        amb = (0.24 + 0.16 * hemi)[:, None] * base_rgb[None, :]
        diff = (0.58 * ndotl_key + 0.24 * ndotl_fill + 0.14 * ndotl_rim)[:, None] * base_rgb[None, :]
        return amb + diff + spec[:, None], ndotl_key

    def rasterize_part(rec: dict, blend_alpha: float = 1.0):
        tris = rec["tris"]
        normals = rec["normals"]
        px, tz = world_to_screen(tris)
        px = px.astype(np.float32)
        tz = tz.astype(np.float32)

        facing = normals @ view_dir
        lit_rgb, ndotl_k = shade_triangles(normals, rec["color"], rec["spec"], rec["shininess"])

        # Front-face pass
        front_idx = np.where(facing >= -0.02)[0]
        x0, y0 = px[:, 0, 0], px[:, 0, 1]
        x1, y1 = px[:, 1, 0], px[:, 1, 1]
        x2, y2 = px[:, 2, 0], px[:, 2, 1]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

        min_xs = np.maximum(0, np.floor(np.minimum(np.minimum(x0, x1), x2)).astype(np.int32))
        max_xs = np.minimum(W - 1, np.ceil(np.maximum(np.maximum(x0, x1), x2)).astype(np.int32))
        min_ys = np.maximum(0, np.floor(np.minimum(np.minimum(y0, y1), y2)).astype(np.int32))
        max_ys = np.minimum(H - 1, np.ceil(np.maximum(np.maximum(y0, y1), y2)).astype(np.int32))

        z_front_part = np.full((H, W), 1e9, dtype=np.float32) if (y_cut is not None and rec.get("closed", True)) else None

        for i in front_idx:
            if abs(denom[i]) < 1e-6:
                continue
            ix0, ix1 = min_xs[i], max_xs[i]
            iy0, iy1 = min_ys[i], max_ys[i]
            if ix0 > ix1 or iy0 > iy1:
                continue
            inv_d = 1.0 / denom[i]
            xs_g = np.arange(ix0, ix1 + 1, dtype=np.float32) + 0.5
            ys_g = np.arange(iy0, iy1 + 1, dtype=np.float32) + 0.5
            gx, gy = np.meshgrid(xs_g, ys_g)
            w0 = ((y1[i] - y2[i]) * (gx - x2[i]) + (x2[i] - x1[i]) * (gy - y2[i])) * inv_d
            w1 = ((y2[i] - y0[i]) * (gx - x2[i]) + (x0[i] - x2[i]) * (gy - y2[i])) * inv_d
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
            if not np.any(inside):
                continue

            z_int = w0 * tz[i, 0] + w1 * tz[i, 1] + w2 * tz[i, 2]
            if z_front_part is not None:
                sf = z_front_part[iy0:iy1 + 1, ix0:ix1 + 1]
                uf = inside & (z_int < sf)
                sf[uf] = z_int[uf]

            sub_z = z_buf[iy0:iy1 + 1, ix0:ix1 + 1]
            vis = inside & (z_int < sub_z)
            if not np.any(vis):
                continue

            # World coordinates of visible pixels for shadow lookup
            wp = (
                w0[..., None] * tris[i, 0]
                + w1[..., None] * tris[i, 1]
                + w2[..., None] * tris[i, 2]
            )
            l_uv, l_d = world_to_light(wp)
            lu = np.clip(l_uv[..., 0].astype(np.int32), 1, SW - 2)
            lv = np.clip(l_uv[..., 1].astype(np.int32), 1, SW - 2)
            # 3x3 PCF soft shadow filter
            in_lit = np.zeros_like(l_d, dtype=np.float32)
            for du in (-1, 0, 1):
                for dv_o in (-1, 0, 1):
                    in_lit += (l_d - 0.65 <= shadow_z[lv + dv_o, lu + du]).astype(np.float32)
            in_lit /= 9.0
            sh_factor = 1.0 - (1.0 - in_lit) * (0.34 * float(ndotl_k[i] > 0.05))

            shaded = np.clip(lit_rgb[i][None, None, :] * sh_factor[..., None], 0.0, 1.0)
            sub_c = color_buf[iy0:iy1 + 1, ix0:ix1 + 1]
            if blend_alpha >= 0.99:
                sub_z[vis] = z_int[vis]
                sub_c[vis] = shaded[vis]
            else:
                sub_c[vis] = blend_alpha * shaded[vis] + (1.0 - blend_alpha) * sub_c[vis]

        # Rossignac-Borrel exact watertight 3D section cap on plane Y = y_cut
        if y_cut is not None and z_front_part is not None and blend_alpha >= 0.99 and abs(view_dir[1]) > 1e-4:
            z_back_part = np.full((H, W), 1e9, dtype=np.float32)
            back_idx = np.where(facing < 0.02)[0]
            for i in back_idx:
                if abs(denom[i]) < 1e-6:
                    continue
                ix0, ix1 = min_xs[i], max_xs[i]
                iy0, iy1 = min_ys[i], max_ys[i]
                if ix0 > ix1 or iy0 > iy1:
                    continue
                inv_d = 1.0 / denom[i]
                xs_g = np.arange(ix0, ix1 + 1, dtype=np.float32) + 0.5
                ys_g = np.arange(iy0, iy1 + 1, dtype=np.float32) + 0.5
                gx, gy = np.meshgrid(xs_g, ys_g)
                w0 = ((y1[i] - y2[i]) * (gx - x2[i]) + (x2[i] - x1[i]) * (gy - y2[i])) * inv_d
                w1 = ((y2[i] - y0[i]) * (gx - x2[i]) + (x0[i] - x2[i]) * (gy - y2[i])) * inv_d
                w2 = 1.0 - w0 - w1
                inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
                if not np.any(inside):
                    continue
                z_int = w0 * tz[i, 0] + w1 * tz[i, 1] + w2 * tz[i, 2]
                sb = z_back_part[iy0:iy1 + 1, ix0:ix1 + 1]
                ub = inside & (z_int < sb)
                sb[ub] = z_int[ub]

            cap_mask = (z_back_part < 1e8) & (z_back_part < z_front_part - 1e-3)
            cy_idx, cx_idx = np.where(cap_mask)
            if len(cy_idx) > 0:
                ndc_x = ((cx_idx.astype(np.float64) + 0.5) / W - 0.5) * 2.0 * half_width_mm
                ndc_y = (0.5 - (cy_idx.astype(np.float64) + 0.5) / H) * 2.0 * half_h_mm
                # Ray origin in world space at camera plane (depth = 0): eye_v + ndc_x * right + ndc_y * up
                ray_o = eye_v[None, :] + ndc_x[:, None] * R_cam[0][None, :] + ndc_y[:, None] * R_cam[1][None, :]
                ray_d = -R_cam[2]  # unit forward vector
                z_plane = ((y_cut - ray_o[:, 1]) / ray_d[1]).astype(np.float32)
                valid_cap = (z_plane > 0.0) & (z_plane <= z_back_part[cy_idx, cx_idx] + 0.05) & (z_plane < z_buf[cy_idx, cx_idx])
                if np.any(valid_cap):
                    vy = cy_idx[valid_cap]
                    vx = cx_idx[valid_cap]
                    vz = z_plane[valid_cap]
                    z_buf[vy, vx] = vz
                    # Subtle 45-degree engineering hatch modulation on cut face
                    hatch = (((vx + vy) // 9) % 2 == 0).astype(np.float32)
                    c_base = rec["cut_color"][None, :] * (0.90 + 0.10 * hatch[:, None])
                    color_buf[vy, vx] = np.clip(c_base, 0.0, 1.0)

    # 1. Render all opaque parts
    for rec in prepared:
        if rec.get("alpha", 1.0) >= 0.99:
            rasterize_part(rec, blend_alpha=1.0)

    # 2. Draw crisp anti-aliased CAD crease edges on opaque parts
    img_hi = Image.fromarray((np.clip(color_buf, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(img_hi)
    for rec in prepared:
        if rec.get("alpha", 1.0) < 0.99 or len(rec["creases"]) == 0:
            continue
        c_pts, c_z = world_to_screen(rec["creases"])
        edge_rgb = tuple(int(max(0, min(255, c * 0.42 * 255))) for c in rec["color"])
        for seg_uv, seg_d in zip(c_pts, c_z):
            mx = int(0.5 * (seg_uv[0, 0] + seg_uv[1, 0]))
            my = int(0.5 * (seg_uv[0, 1] + seg_uv[1, 1]))
            md = 0.5 * (seg_d[0] + seg_d[1])
            if 0 <= mx < W and 0 <= my < H and md <= z_buf[my, mx] + 0.65:
                draw.line(
                    [(float(seg_uv[0, 0]), float(seg_uv[0, 1])), (float(seg_uv[1, 0]), float(seg_uv[1, 1]))],
                    fill=edge_rgb,
                    width=2,
                )
    color_buf = np.asarray(img_hi, dtype=np.float32) / 255.0

    # 3. Render translucent parts (e.g. closed exterior lid window preview)
    for rec in prepared:
        alpha = float(rec.get("alpha", 1.0))
        if alpha < 0.99:
            rasterize_part(rec, blend_alpha=alpha)

    img_final_hi = Image.fromarray((np.clip(color_buf, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB")
    return img_final_hi.resize((out_w, out_h), resample=Image.Resampling.LANCZOS)


def _build_oring_loop_mesh(z_center: float = -1.90) -> trimesh.Trimesh:
    """Build symmetric 360-degree Dia 1.20 mm Silicone/EPDM Parker O-ring loop in exact AuxOrigin frame."""
    # Symmetric groove centerline: X in [-1.55 .. 91.55], Y in [-1.55 .. 41.55]
    x0, x1 = -1.55, 91.55
    y0, y1 = -1.55, 41.55
    r = 0.46
    segs = [
        _cyl_mesh(r, x1 - x0, "x", (0.5 * (x0 + x1), y0, z_center), sections=18),
        _cyl_mesh(r, x1 - x0, "x", (0.5 * (x0 + x1), y1, z_center), sections=18),
        _cyl_mesh(r, y1 - y0, "y", (x0, 0.5 * (y0 + y1), z_center), sections=18),
        _cyl_mesh(r, y1 - y0, "y", (x1, 0.5 * (y0 + y1), z_center), sections=18),
    ]
    return trimesh.util.concatenate(segs)


def generate_enclosure_3d_sheet():
    lid_mesh = trimesh.load_mesh(os.path.join(HERE, "ISAC_868_Lid_0p80mm_Window.stl"), process=True)
    base_mesh = trimesh.load_mesh(os.path.join(HERE, "ISAC_868_Base_Tray.stl"), process=True)
    base_bat_mesh = trimesh.load_mesh(os.path.join(HERE, "ISAC_868_Base_Tray_Battery.stl"), process=True)
    oring_mesh = _build_oring_loop_mesh(z_center=-1.90)

    # Colors matching engineering blueprints
    COL_LID = (0.33, 0.63, 0.89)
    COL_LID_CUT = (0.14, 0.44, 0.78)
    COL_BASE = (0.74, 0.79, 0.83)
    COL_BASE_CUT = (0.48, 0.56, 0.62)
    COL_ORING = (0.86, 0.24, 0.22)
    COL_LIPO = (0.68, 0.44, 0.78)
    COL_ER14 = (0.95, 0.58, 0.18)
    COL_ADH = (0.55, 0.88, 0.96)

    # --- Panel A: Exploded 3D Isometric Assembly (Option A Slim LiPo) ---
    lid_exp = lid_mesh.copy()
    lid_exp.apply_translation([0.0, 0.0, 22.5])
    adh_exp = _box_mesh(73.60, 87.60, 6.85, 20.60, 11.50, 11.68)  # 3M 467MP window transfer bond
    pcba_exp = build_pcba_parts(z_shift=4.0)
    oring_exp = oring_mesh.copy()
    oring_exp.apply_translation([0.0, 0.0, -3.2])
    lipo_exp = _box_mesh(9.10, 44.10, 7.10, 32.10, -10.50, -7.50)
    base_exp = base_mesh.copy()
    base_exp.apply_translation([0.0, 0.0, -16.5])

    scene_a = (
        [
            {"mesh": base_exp, "color": np.array(COL_BASE), "cut_color": np.array(COL_BASE_CUT), "spec": 0.22, "shininess": 22.0, "alpha": 1.0, "closed": True},
            {"mesh": lipo_exp, "color": np.array(COL_LIPO), "cut_color": np.array(COL_LIPO), "spec": 0.35, "shininess": 32.0, "alpha": 1.0, "closed": True},
            {"mesh": oring_exp, "color": np.array(COL_ORING), "cut_color": np.array(COL_ORING), "spec": 0.25, "shininess": 18.0, "alpha": 1.0, "closed": True},
            {"mesh": adh_exp, "color": np.array(COL_ADH), "cut_color": np.array(COL_ADH), "spec": 0.40, "shininess": 36.0, "alpha": 0.68, "closed": True},
            {"mesh": lid_exp, "color": np.array(COL_LID), "cut_color": np.array(COL_LID_CUT), "spec": 0.28, "shininess": 28.0, "alpha": 1.0, "closed": True},
        ]
        + pcba_exp
    )
    img_a = render_scene(scene_a, eye_dir=(-0.62, -0.82, 0.56), target=(45.0, 20.5, 6.5), half_width_mm=65.0)

    # --- Panel B: Closed Weatherproof Assembled 3D View (95.7 x 45.7 x 16.1 mm Uniform Flat Roof) ---
    pcba_closed = build_pcba_parts(z_shift=0.0)
    scene_b = (
        pcba_closed
        + [
            {"mesh": base_mesh, "color": np.array(COL_BASE), "cut_color": np.array(COL_BASE_CUT), "spec": 0.22, "shininess": 22.0, "alpha": 1.0, "closed": True},
            {"mesh": oring_mesh, "color": np.array(COL_ORING), "cut_color": np.array(COL_ORING), "spec": 0.22, "shininess": 18.0, "alpha": 1.0, "closed": True},
            {"mesh": lid_mesh, "color": np.array(COL_LID), "cut_color": np.array(COL_LID_CUT), "spec": 0.30, "shininess": 30.0, "alpha": 0.86, "closed": True},
        ]
    )
    img_b = render_scene(scene_b, eye_dir=(0.56, -0.84, 0.58), target=(46.0, 20.5, 1.5), half_width_mm=56.0)

    # --- Panel C: True 3D Longitudinal Cutaway @ Y_gbr = 14.0 mm (IDE Comb Centerline) ---
    lipo_in_tray = _box_mesh(9.10, 44.10, 7.10, 32.10, -5.66, -2.66)
    scene_c = (
        pcba_closed
        + [
            {"mesh": lipo_in_tray, "color": np.array(COL_LIPO), "cut_color": np.array((0.78, 0.52, 0.88)), "spec": 0.30, "shininess": 28.0, "alpha": 1.0, "closed": True},
            {"mesh": base_mesh, "color": np.array(COL_BASE), "cut_color": np.array(COL_BASE_CUT), "spec": 0.22, "shininess": 22.0, "alpha": 1.0, "closed": True},
            {"mesh": oring_mesh, "color": np.array(COL_ORING), "cut_color": np.array(COL_ORING), "spec": 0.22, "shininess": 18.0, "alpha": 1.0, "closed": True},
            {"mesh": lid_mesh, "color": np.array(COL_LID), "cut_color": np.array(COL_LID_CUT), "spec": 0.28, "shininess": 28.0, "alpha": 1.0, "closed": True},
        ]
    )
    img_c = render_scene(scene_c, eye_dir=(-0.18, -0.96, 0.34), target=(45.0, 21.0, 0.5), half_width_mm=54.0, y_cut=14.0)

    # --- Panel D: Option B Dual-Fit Stepped 2/3 AA (ER14335M) 3D Cutaway @ Y_gbr = 19.2 mm ---
    er14_cell = _cyl_mesh(7.25, 33.50, "x", (28.75, 19.20, -9.35), sections=36)
    pos_cap = _cyl_mesh(2.40, 1.20, "x", (45.80, 19.20, -9.35), sections=20)
    scene_d = (
        pcba_closed
        + [
            {"mesh": er14_cell, "color": np.array(COL_ER14), "cut_color": np.array((0.98, 0.68, 0.28)), "spec": 0.34, "shininess": 30.0, "alpha": 1.0, "closed": True},
            {"mesh": pos_cap, "color": np.array((0.82, 0.84, 0.86)), "cut_color": np.array((0.82, 0.84, 0.86)), "spec": 0.45, "shininess": 40.0, "alpha": 1.0, "closed": True},
            {"mesh": base_bat_mesh, "color": np.array(COL_BASE), "cut_color": np.array(COL_BASE_CUT), "spec": 0.22, "shininess": 22.0, "alpha": 1.0, "closed": True},
            {"mesh": oring_mesh, "color": np.array(COL_ORING), "cut_color": np.array(COL_ORING), "spec": 0.22, "shininess": 18.0, "alpha": 1.0, "closed": True},
            {"mesh": lid_mesh, "color": np.array(COL_LID), "cut_color": np.array(COL_LID_CUT), "spec": 0.28, "shininess": 28.0, "alpha": 1.0, "closed": True},
        ]
    )
    img_d = render_scene(scene_d, eye_dir=(-0.20, -0.95, 0.34), target=(45.0, 22.0, -4.2), half_width_mm=54.0, y_cut=19.2)

    # Compose publication-grade 2x2 figure with engineering callouts
    fig, axes = plt.subplots(2, 2, figsize=(15.2, 10.6), dpi=180)
    panels = [
        (
            axes[0, 0],
            img_a,
            "A. Exploded Assembly (Flat Lid + 3M 467MP + Pure-SMD PCBA + Parker O-Ring)",
            [
                ("100% Uniform Flat Waterproof Roof (+8.50 mm)", (0.35, 0.25), (0.04, 0.06)),
                ("J2 DNP Direct-Solder Batt Pads (1=GND, 2=+VBAT)", (0.27, 0.44), (0.03, 0.18)),
                ("Open-East 0.80 mm Deck + 3M 467MP", (0.78, 0.36), (0.53, 0.11)),
                ("Bare-ENIG 5-Finger AE1 Comb", (0.73, 0.45), (0.60, 0.88)),
                ("360-Deg Parker ORD 5700 O-Ring + Base", (0.32, 0.72), (0.04, 0.91)),
            ],
        ),
        (
            axes[0, 1],
            img_b,
            "B. Sealed Exterior View (95.7 x 45.7 x 16.1 mm Uniform Flat Roof & Open-East Deck)",
            [
                ("Symmetric 2.6 mm 4-Wall O-Ring Seal", (0.56, 0.28), (0.32, 0.08)),
                ("Uniform Flat Top Cover (Zero Domes/Roof Slots!)", (0.28, 0.25), (0.03, 0.17)),
                ("Open-East Self-Draining 0.80 mm Deck\n(0.00 mm Dam Lip -> 0.00 mL Pool!)", (0.80, 0.54), (0.48, 0.18)),
                ("Bottom-Fed J2 Soldered Leads Inside Seal", (0.26, 0.42), (0.04, 0.88)),
            ],
        ),
        (
            axes[1, 0],
            img_c,
            "C. Longitudinal Cutaway @ Y_gbr = 14.0 mm (Open-East Runoff Deck + Parker Seal)",
            [
                ("302535 LiPo + 1.80x0.76 mm\nParker Groove (23.3% Squeeze)", (0.31, 0.63), (0.03, 0.86)),
                ("4.5 mm / 4.0 mm Unloaded Air Cavities", (0.63, 0.53), (0.43, 0.15)),
                ("Open-East 0.80 mm Deck + 25 um 3M 467MP\n(0.000 mm Air Gap & Free East Runoff!)", (0.83, 0.49), (0.49, 0.87)),
            ],
        ),
        (
            axes[1, 1],
            img_d,
            "D. Option B Stepped 2/3 AA (ER14335M) Cutaway @ Y_gbr = 19.2 mm (X < 50 mm Bay)",
            [
                ("ER14335M 2/3 AA 3.6V 1300mAh\n(-19.1 mm Stepped Anti-Roll Cradle)", (0.34, 0.62), (0.04, 0.87)),
                ("100% Battery-Free Unloaded Air\nUnder 868 MHz IFA & AE1!", (0.68, 0.45), (0.52, 0.87)),
            ],
        ),
    ]

    for ax, pil_im, title, callouts in panels:
        ax.imshow(np.asarray(pil_im))
        ax.set_title(title, fontsize=9.1, fontweight="bold", pad=6)
        ax.axis("off")
        w_px, h_px = pil_im.size
        for txt, xy_rel, tx_rel in callouts:
            ax.annotate(
                txt,
                xy=(xy_rel[0] * w_px, xy_rel[1] * h_px),
                xytext=(tx_rel[0] * w_px, tx_rel[1] * h_px),
                fontsize=7.6,
                fontweight="bold",
                color="#0d2b4e",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#1565c0", alpha=0.90, lw=0.9),
                arrowprops=dict(arrowstyle="->", color="#0d47a1", lw=1.25),
            )

    fig.suptitle(
        "ISAC_868 Rev E.5 — Self-Draining UV-Stabilized ASA/PETG Enclosure & PCBA 3D Renders (Exact AuxOrigin STL Solids)",
        fontsize=12.2,
        fontweight="bold",
        y=0.992,
    )
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.972])

    os.makedirs(DOCS, exist_ok=True)
    out_docs = os.path.join(DOCS, "ISAC_868_Enclosure_3D_Exploded.png")
    fig.savefig(out_docs, dpi=180, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)

    if os.path.isdir(FAB_DOCS):
        shutil.copy2(out_docs, os.path.join(FAB_DOCS, "ISAC_868_Enclosure_3D_Exploded.png"))

    print(f"Exported 3D Enclosure Render     : {out_docs}")
    return out_docs


if __name__ == "__main__":
    generate_enclosure_3d_sheet()
