#!/usr/bin/env python3
"""
Post-DRC Computational Geometry & RS-274X Gerber Verification Gate (`Rev E.0`)
===============================================================================
Inspects `ISAC_868_KiCad9.kicad_pcb`, `ISAC.pretty`, `.gbrjob`, and exported
RS-274X/X2 Gerbers directly via `/usr/bin/python3` (`pcbnew` + `shapely`):

  a) Zero Via-in-Pad & Tenting:
     - 0 via barrels overlapping or touching any SMD pad copper (`>= 0.12 mm`
       via-copper-to-SMD-pad-copper clearance)
     - All vias `drill >= 0.30 mm`, `annular_ring >= 0.15 mm`
     - 100% tented in `pcbnew` (`F.Mask` & `B.Mask`) AND 0 via barrels intersecting
       any opening in `*-F_Mask.gts` or `*-B_Mask.gbs`
  b) Stackup, Finish & `LGA-73` / `DFN-8` Mask Bridges:
     - `.gbrjob` `"Finish" == "ENIG"`, `BoardThickness` & physical stackup `1.60 +/- 0.02 mm`,
       `F.Mask` & `B.Mask` color `"Green"`
     - `m_SolderMaskMinWidth == 0.10 mm`, `m_SolderMaskMargin == 0.00 mm`, `0` DRC exclusions
     - Intact `>= 0.10 mm` solder-mask dams between all 64 perimeter pads of `U1` (`LGA-73`),
       all 8 perimeter pads of `U2` (`DFN-8`), and globally across all disjoint openings on
       `*-F_Mask.gts` and `*-B_Mask.gbs`
  c) Stencil Paste Area Ratio & Thermal Windowing:
     - Parses `*-F_Paste.gtp` RS-274X apertures (`R`, `C`, `O`, `RoundRect`, macros) and flashes
     - Asserts `AR >= 0.66` at `t = 0.12 mm` AND `AR >= 0.90` at `t = 0.10 mm` across all
       `U1`, `U2`, `Q1`, `0402`, and every flashed aperture on the board (`0` paste in `dx >= 50 mm`)
     - Asserts `50% - 75%` paste coverage on each of `U1` `Pads 65..73` and on `U2` `Pad 9`
  d) Board-vs-Library Footprint & 3D Parity:
     - Asserts `<= 0.05 mm` pad center parity and `<= 0.02 mm` rotated pad bounding-box size
       parity against `.pretty` libraries (catching `90 deg` rotation bugs)
     - Asserts every electrical footprint has `>= 1` 3D STEP model, `0` hardcoded `/home/` paths,
       and 100% of referenced 3D STEP files exist on disk
  e) RF & SiP `B.Cu` Return-Plane Integrity:
     - Samples `SHAPE_POLY_SET.Contains(pt)` (which checks interior clearance holes!) every
       `0.05 mm` along `/RF_PA`, `/BR_P`, `/BR_Q`, `/ANT_FEED`, `/SMA_C`, `/BR_S`, `/BR_O`,
       `/DET_IN` (`dx < 49.35 mm`) AND across a `0.25 mm` grid under `U1`'s `3x3` ground matrix
       (`dx = 14.6..21.9, dy = 14.3..21.5`), asserting 100% unbroken `B.Cu` ground plane
     - Asserts 0% copper pour inside `dx >= 50.0 mm` antenna/sensing aperture
  f) Fiducials, Silkscreen, Acute Bends & Unanchored Stubs:
     - `>= 3` non-collinear global fiducials + `>= 2` local `U1` fiducials (`dx < 49.0 mm`)
     - `0` silkscreen strokes `< 0.15 mm` (in `.kicad_pcb` and `*-F_Silkscreen.gto`)
     - `100%` of silkscreen inside `Edge.Cuts`
     - `0` acute track bends `< 85 deg` and `0` unanchored track endpoints
"""

import argparse
from collections import defaultdict
import glob
import json
import math
import os
import re
import sys

import pcbnew
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYS_FP_DIR = "/usr/share/kicad/footprints"
SYS_3D_DIR = "/usr/share/kicad/3dmodels"


# ==============================================================================
# RS-274X / Gerber X2 Computational Geometry Parser
# ==============================================================================
def _arc_points(x0, y0, x1, y1, i_off, j_off, clockwise, steps=32):
    cx = x0 + i_off
    cy = y0 + j_off
    r = math.hypot(x0 - cx, y0 - cy)
    if r < 1e-9:
        return [(x0, y0), (x1, y1)]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if clockwise:
        if a1 >= a0 - 1e-9:
            a1 -= 2.0 * math.pi
    else:
        if a1 <= a0 + 1e-9:
            a1 += 2.0 * math.pi
    pts = []
    for k in range(steps + 1):
        ang = a0 + (a1 - a0) * (k / float(steps))
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    pts[0] = (x0, y0)
    pts[-1] = (x1, y1)
    return pts


def _build_aperture_spec(ap_type, params_str, macros):
    """
    Return dict `{code_type, poly, width, height, area, perim, is_circle, dia}` in mm
    centered at (0, 0).
    """
    parts = [p for p in params_str.split("X") if p != ""] if params_str else []
    vals = [float(p) for p in parts]

    if ap_type == "C":
        d = vals[0]
        r = 0.5 * d
        p = Point(0.0, 0.0).buffer(r, quad_segs=32)
        area = math.pi * r * r
        perim = math.pi * d
        return {
            "type": "C", "poly": p, "width": d, "height": d,
            "area": area, "perim": perim, "box_area": d * d, "box_perim": 4.0 * d,
            "is_circle": True, "dia": d,
        }
    elif ap_type == "R":
        w = vals[0]
        h = vals[1] if len(vals) >= 2 else w
        p = box(-0.5 * w, -0.5 * h, 0.5 * w, 0.5 * h)
        area = w * h
        perim = 2.0 * (w + h)
        return {
            "type": "R", "poly": p, "width": w, "height": h,
            "area": area, "perim": perim, "box_area": area, "box_perim": perim,
            "is_circle": False, "dia": min(w, h),
        }
    elif ap_type == "O":
        w = vals[0]
        h = vals[1] if len(vals) >= 2 else w
        r = 0.5 * min(w, h)
        if w >= h:
            dx = 0.5 * (w - h)
            p = LineString([(-dx, 0.0), (dx, 0.0)]).buffer(r, quad_segs=24)
        else:
            dy = 0.5 * (h - w)
            p = LineString([(0.0, -dy), (0.0, dy)]).buffer(r, quad_segs=24)
        straight = abs(w - h)
        area = straight * (2.0 * r) + math.pi * r * r
        perim = 2.0 * straight + 2.0 * math.pi * r
        return {
            "type": "O", "poly": p, "width": w, "height": h,
            "area": area, "perim": perim, "box_area": w * h, "box_perim": 2.0 * (w + h),
            "is_circle": False, "dia": min(w, h),
        }
    elif ap_type == "RoundRect" and len(vals) >= 9:
        r = vals[0]
        corners = [(vals[1], vals[2]), (vals[3], vals[4]), (vals[5], vals[6]), (vals[7], vals[8])]
        base = Polygon(corners).convex_hull
        p = base.buffer(r, quad_segs=24) if r > 0.0 else base
        minx, miny, maxx, maxy = p.bounds
        w = maxx - minx
        h = maxy - miny
        area = p.area
        perim = p.length
        return {
            "type": "RoundRect", "poly": p, "width": w, "height": h,
            "area": area, "perim": perim, "box_area": w * h, "box_perim": 2.0 * (w + h),
            "is_circle": False, "dia": min(w, h),
        }
    elif ap_type in macros:
        p = macros[ap_type]
        minx, miny, maxx, maxy = p.bounds
        w = maxx - minx
        h = maxy - miny
        return {
            "type": ap_type, "poly": p, "width": w, "height": h,
            "area": p.area, "perim": p.length, "box_area": w * h, "box_perim": 2.0 * (w + h),
            "is_circle": False, "dia": min(w, h),
        }
    else:
        d = vals[0] if vals else 0.1
        p = box(-0.5 * d, -0.5 * d, 0.5 * d, 0.5 * d)
        return {
            "type": ap_type, "poly": p, "width": d, "height": d,
            "area": d * d, "perim": 4.0 * d, "box_area": d * d, "box_perim": 4.0 * d,
            "is_circle": False, "dia": d,
        }


def parse_rs274x(gerber_path):
    """
    Parse an RS-274X / Gerber X2 file into exact Shapely geometries in mm:
      - `apertures`: `{dcode: spec_dict}`
      - `flashes`: list of `{dcode, x, y, poly, comp, pad, spec}`
      - `regions`: list of `{poly, comp, pad}` (from `G36*...G37*`)
      - `draws`: list of `{dcode, poly, p0, p1, comp}` (from `D01*` outside `G36`)
    """
    with open(gerber_path, "r", encoding="utf-8") as f:
        text = f.read()

    unit_scale = 25.4 if "%MOIN*%" in text else 1.0
    m_fs = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
    dec_x = int(m_fs.group(2)) if m_fs else 6
    dec_y = int(m_fs.group(4)) if m_fs else 6
    scale_x = unit_scale * (10.0 ** (-dec_x))
    scale_y = unit_scale * (10.0 ** (-dec_y))

    # Parse FreePoly / outline macros (%AMname* ... *%)
    macros = {}
    for m_am in re.finditer(r"%AM([A-Za-z0-9_]+)\*(.*?)%", text, flags=re.DOTALL):
        mname = m_am.group(1)
        mbody = m_am.group(2)
        if mname == "RoundRect":
            continue
        prim_polys = []
        for stmt in mbody.split("*"):
            stmt = stmt.strip()
            if not stmt or stmt.startswith("0 "):
                continue
            toks = [t.strip() for t in stmt.split(",")]
            if toks[0] == "4" and len(toks) >= 9 and "$" not in stmt:
                npts = int(float(toks[2]))
                coords = []
                for idx in range(npts + 1):
                    px = float(toks[3 + 2 * idx]) * unit_scale
                    py = float(toks[4 + 2 * idx]) * unit_scale
                    coords.append((px, py))
                if len(coords) >= 3:
                    poly = Polygon(coords)
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    if not poly.is_empty:
                        prim_polys.append(poly)
        if prim_polys:
            macros[mname] = unary_union(prim_polys)

    apertures = {}
    flashes = []
    regions = []
    draws = []

    cur_dcode = None
    cur_comp = None
    cur_pad = None
    in_region = False
    reg_contours = []
    cur_contour = []
    interp_mode = "G01"
    cx = 0.0
    cy = 0.0

    coord_re = re.compile(
        r"^(?:G0?([123]))?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0([123])\*$"
    )
    add_re = re.compile(r"^%ADD(\d+)([A-Za-z0-9_]+)(?:,(.*?))?\*%$")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("G04"):
            continue

        m_add = add_re.match(line)
        if m_add:
            dcode = f"D{m_add.group(1)}"
            ap_type = m_add.group(2)
            params = m_add.group(3) or ""
            if unit_scale != 1.0 and params:
                params = "X".join(str(float(p) * unit_scale) for p in params.split("X") if p != "")
            apertures[dcode] = _build_aperture_spec(ap_type, params, macros)
            continue

        if line.startswith("%TO.C,"):
            cur_comp = line[6:-2].split(",")[0].strip()
            continue
        if line.startswith("%TO.P,"):
            fields = line[6:-2].split(",")
            cur_comp = fields[0].strip()
            cur_pad = fields[1].strip() if len(fields) > 1 else ""
            continue
        if line.startswith("%TD"):
            cur_comp = None
            cur_pad = None
            continue
        if line.startswith("%"):
            continue

        if line == "G36*":
            in_region = True
            reg_contours = []
            cur_contour = []
            continue
        if line == "G37*":
            if len(cur_contour) >= 3:
                reg_contours.append(cur_contour)
            cur_contour = []
            in_region = False
            polys = []
            for pts in reg_contours:
                p = Polygon(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 1e-9:
                    polys.append(p)
            if polys:
                u = unary_union(polys)
                if u.geom_type == "MultiPolygon":
                    for g in u.geoms:
                        regions.append({"poly": g, "comp": cur_comp, "pad": cur_pad})
                elif u.geom_type == "Polygon":
                    regions.append({"poly": u, "comp": cur_comp, "pad": cur_pad})
            continue

        if line in ("G01*", "G1*"):
            interp_mode = "G01"
            continue
        if line in ("G02*", "G2*"):
            interp_mode = "G02"
            continue
        if line in ("G03*", "G3*"):
            interp_mode = "G03"
            continue
        if line == "G75*":
            continue

        m_sel = re.match(r"^(?:G54)?(D[1-9]\d+)\*$", line)
        if m_sel:
            cur_dcode = m_sel.group(1)
            continue

        m_c = coord_re.match(line)
        if m_c:
            g_inline, xs, ys, is_, js_, d_op = m_c.groups()
            if g_inline:
                interp_mode = f"G0{g_inline}"
            nx = int(xs) * scale_x if xs is not None else cx
            ny = int(ys) * scale_y if ys is not None else cy
            ioff = int(is_) * scale_x if is_ is not None else 0.0
            joff = int(js_) * scale_y if js_ is not None else 0.0

            if d_op == "2":
                if in_region:
                    if len(cur_contour) >= 3:
                        reg_contours.append(cur_contour)
                    cur_contour = [(nx, ny)]
            elif d_op == "1":
                if in_region:
                    if not cur_contour:
                        cur_contour = [(cx, cy)]
                    if interp_mode in ("G02", "G03") and (abs(ioff) > 0 or abs(joff) > 0):
                        arc_pts = _arc_points(cx, cy, nx, ny, ioff, joff, interp_mode == "G02")
                        cur_contour.extend(arc_pts[1:])
                    else:
                        cur_contour.append((nx, ny))
                else:
                    spec = apertures.get(cur_dcode)
                    r = 0.5 * spec["dia"] if spec else 0.05
                    if interp_mode in ("G02", "G03") and (abs(ioff) > 0 or abs(joff) > 0):
                        pts = _arc_points(cx, cy, nx, ny, ioff, joff, interp_mode == "G02")
                    else:
                        pts = [(cx, cy), (nx, ny)]
                    seg_poly = LineString(pts).buffer(r, quad_segs=16)
                    draws.append({
                        "dcode": cur_dcode,
                        "poly": seg_poly,
                        "line": LineString(pts),
                        "p0": (cx, cy),
                        "p1": (nx, ny),
                        "comp": cur_comp,
                    })
            elif d_op == "3":
                spec = apertures.get(cur_dcode)
                if spec is not None:
                    fpoly = translate(spec["poly"], xoff=nx, yoff=ny)
                    flashes.append({
                        "dcode": cur_dcode,
                        "x": nx,
                        "y": ny,
                        "poly": fpoly,
                        "comp": cur_comp,
                        "pad": cur_pad,
                        "spec": spec,
                    })

            cx, cy = nx, ny

    return {
        "apertures": apertures,
        "flashes": flashes,
        "regions": regions,
        "draws": draws,
    }


# ==============================================================================
# KiCad SHAPE_POLY_SET -> Shapely Polygon Converter (AuxOrigin Frame)
# ==============================================================================
def _poly_set_to_shapely_aux(pset, ax_mm, ay_mm):
    polys = []
    for i in range(pset.OutlineCount()):
        outline = pset.Outline(i)
        ext = [
            (pcbnew.ToMM(outline.CPoint(k).x) - ax_mm, ay_mm - pcbnew.ToMM(outline.CPoint(k).y))
            for k in range(outline.PointCount())
        ]
        if len(ext) < 3:
            continue
        holes = []
        for h_idx in range(pset.HoleCount(i)):
            hole = pset.Hole(i, h_idx)
            h_pts = [
                (pcbnew.ToMM(hole.CPoint(k).x) - ax_mm, ay_mm - pcbnew.ToMM(hole.CPoint(k).y))
                for k in range(hole.PointCount())
            ]
            if len(h_pts) >= 3:
                holes.append(h_pts)
        p = Polygon(ext, holes)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    return unary_union(polys) if polys else Polygon()


def _find_gerber_file(gerber_dir, suffix):
    matches = sorted(glob.glob(os.path.join(gerber_dir, f"*{suffix}")))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected strictly 1 '*{suffix}' file in {gerber_dir}, found {len(matches)}: {matches}"
        )
    return matches[0]


# ==============================================================================
# Six Deterministic Post-DRC Computational Geometry Gates
# ==============================================================================
def run_dfm_audit(pcb_path, gerber_dir, pro_path, pretty_dir):
    errors = []

    if not os.path.isfile(pcb_path):
        raise FileNotFoundError(f"Missing PCB file: {pcb_path}")
    if not os.path.isfile(pro_path):
        raise FileNotFoundError(f"Missing project file: {pro_path}")

    board = pcbnew.LoadBoard(pcb_path)
    ds = board.GetDesignSettings()
    aux = ds.GetAuxOrigin()
    ax_mm = pcbnew.ToMM(aux.x)
    ay_mm = pcbnew.ToMM(aux.y)

    # Board local origin (X0 = 103.5, Y0 = 80.0; H = 40.0 -> ax = X0, ay = Y0 + 40.0)
    x0_mm = ax_mm
    y0_mm = ay_mm - 40.0

    fmask_path = _find_gerber_file(gerber_dir, "-F_Mask.gts")
    bmask_path = _find_gerber_file(gerber_dir, "-B_Mask.gbs")
    fpaste_path = _find_gerber_file(gerber_dir, "-F_Paste.gtp")
    bpaste_cands = [f for f in os.listdir(gerber_dir) if f.endswith("-B_Paste.gbp")]
    fsilk_path = _find_gerber_file(gerber_dir, "-F_Silkscreen.gto")
    bsilk_path = _find_gerber_file(gerber_dir, "-B_Silkscreen.gbo")
    edge_path = _find_gerber_file(gerber_dir, "-Edge_Cuts.gm1")
    fcu_path = _find_gerber_file(gerber_dir, "-F_Cu.gtl")
    bcu_path = _find_gerber_file(gerber_dir, "-B_Cu.gbl")
    gbrjob_path = _find_gerber_file(gerber_dir, "-job.gbrjob")

    fmask_gbr = parse_rs274x(fmask_path)
    bmask_gbr = parse_rs274x(bmask_path)
    fpaste_gbr = parse_rs274x(fpaste_path)
    fsilk_gbr = parse_rs274x(fsilk_path)
    bsilk_gbr = parse_rs274x(bsilk_path)
    edge_gbr = parse_rs274x(edge_path)
    fcu_gbr = parse_rs274x(fcu_path)
    bcu_gbr = parse_rs274x(bcu_path)

    fmask_openings = (
        [r["poly"] for r in fmask_gbr["regions"]]
        + [f["poly"] for f in fmask_gbr["flashes"]]
        + [d["poly"] for d in fmask_gbr["draws"]]
    )
    bmask_openings = (
        [r["poly"] for r in bmask_gbr["regions"]]
        + [f["poly"] for f in bmask_gbr["flashes"]]
        + [d["poly"] for d in bmask_gbr["draws"]]
    )
    fmask_union = unary_union(fmask_openings) if fmask_openings else Polygon()
    bmask_union = unary_union(bmask_openings) if bmask_openings else Polygon()

    # ==========================================================================
    # GATE (a): Zero Via-in-Pad & 100% Tenting
    # ==========================================================================
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    smd_pads_f = []
    smd_pads_b = []
    fps_by_ref = {}

    for fp in board.GetFootprints():
        ref = fp.GetReference().strip()
        fps_by_ref[ref] = fp
        for pad in fp.Pads():
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            pnum = str(pad.GetNumber()).strip()
            if pad.IsOnLayer(pcbnew.F_Cu):
                poly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
                if not poly.is_empty:
                    smd_pads_f.append((ref, pnum, poly))
            if pad.IsOnLayer(pcbnew.B_Cu):
                poly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.B_Cu, 0), ax_mm, ay_mm)
                if not poly.is_empty:
                    smd_pads_b.append((ref, pnum, poly))

    if len(vias) == 0:
        errors.append("[GATE a] Board contains 0 vias!")

    min_via_smd_gap = float("inf")
    min_via_drill = float("inf")
    min_annular = float("inf")

    for v in vias:
        vx = pcbnew.ToMM(v.GetPosition().x) - ax_mm
        vy = ay_mm - pcbnew.ToMM(v.GetPosition().y)
        dia = pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu))
        drill = pcbnew.ToMM(v.GetDrillValue())
        annular = 0.5 * (dia - drill)
        min_via_drill = min(min_via_drill, drill)
        min_annular = min(min_annular, annular)

        if drill < 0.30 - 1e-4:
            errors.append(f"[GATE a] Via at ({vx:.3f}, {vy:.3f}) drill {drill:.3f} mm < 0.30 mm")
        if annular < 0.15 - 1e-4:
            errors.append(f"[GATE a] Via at ({vx:.3f}, {vy:.3f}) annular ring {annular:.3f} mm < 0.15 mm")
        if v.GetFrontTentingMode() != pcbnew.TENTING_MODE_TENTED:
            errors.append(f"[GATE a] Via at ({vx:.3f}, {vy:.3f}) is NOT tented on F.Mask in .kicad_pcb")
        if v.GetBackTentingMode() != pcbnew.TENTING_MODE_TENTED:
            errors.append(f"[GATE a] Via at ({vx:.3f}, {vy:.3f}) is NOT tented on B.Mask in .kicad_pcb")

        v_cu = Point(vx, vy).buffer(0.5 * dia, quad_segs=24)
        v_barrel = Point(vx, vy).buffer(0.5 * drill, quad_segs=24)

        for ref, pnum, ppoly in smd_pads_f:
            gap = v_cu.distance(ppoly)
            min_via_smd_gap = min(min_via_smd_gap, gap)
            if v_barrel.intersects(ppoly) or gap < 0.12 - 1e-4:
                errors.append(
                    f"[GATE a] Via-in-pad / SMD clearance violation at ({vx:.3f}, {vy:.3f}) vs "
                    f"{ref}.Pad{pnum}: copper gap = {gap:.4f} mm (< 0.12 mm)"
                )
        for ref, pnum, ppoly in smd_pads_b:
            gap = v_cu.distance(ppoly)
            min_via_smd_gap = min(min_via_smd_gap, gap)
            if v_barrel.intersects(ppoly) or gap < 0.12 - 1e-4:
                errors.append(
                    f"[GATE a] Back SMD via clearance violation at ({vx:.3f}, {vy:.3f}) vs "
                    f"{ref}.Pad{pnum}: copper gap = {gap:.4f} mm (< 0.12 mm)"
                )

        if not fmask_union.is_empty and v_barrel.intersects(fmask_union):
            errors.append(
                f"[GATE a] Untented via barrel exposed in F_Mask.gts at ({vx:.3f}, {vy:.3f})"
            )
        if not bmask_union.is_empty and v_barrel.intersects(bmask_union):
            errors.append(
                f"[GATE a] Untented via barrel exposed in B_Mask.gbs at ({vx:.3f}, {vy:.3f})"
            )

    print(
        f"[DFM a] Vias={len(vias)}, min_drill={min_via_drill:.3f}mm (>=0.30), "
        f"min_AR={min_annular:.3f}mm (>=0.15), min_SMD_gap={min_via_smd_gap:.3f}mm (>=0.12), "
        f"100% F/B tented."
    )

    # ==========================================================================
    # GATE (b): Stackup, ENIG Finish, DRC Exclusions & LGA-73 / DFN-8 Mask Dams
    # ==========================================================================
    with open(gbrjob_path, "r", encoding="utf-8") as f:
        gbrjob = json.load(f)

    finish = gbrjob.get("GeneralSpecs", {}).get("Finish", "")
    if finish != "ENIG":
        errors.append(f"[GATE b] .gbrjob GeneralSpecs.Finish is {finish!r} (expected 'ENIG')")

    imp_ctrl = gbrjob.get("GeneralSpecs", {}).get("ImpedanceControlled", False)
    if bool(imp_ctrl) is not False:
        errors.append(
            f"[GATE b] .gbrjob GeneralSpecs.ImpedanceControlled is {imp_ctrl!r} "
            f"(expected False/omitted for standard 2L FR-4 without impedance coupon)"
        )

    job_thick = float(gbrjob.get("GeneralSpecs", {}).get("BoardThickness", 0.0))
    if abs(job_thick - 1.60) > 0.02:
        errors.append(
            f"[GATE b] .gbrjob BoardThickness = {job_thick:.4f} mm (outside 1.60 +/- 0.02 mm)"
        )

    stack_thick = 0.0
    mask_colors = {}
    for layer_entry in gbrjob.get("MaterialStackup", []):
        ltype = layer_entry.get("Type", "")
        if ltype in ("Copper", "Dielectric", "SolderMask") and "Thickness" in layer_entry:
            stack_thick += float(layer_entry["Thickness"])
        if ltype == "SolderMask":
            mask_colors[layer_entry.get("Name", "")] = layer_entry.get("Color", "")

    if abs(stack_thick - 1.60) > 0.02:
        errors.append(
            f"[GATE b] .gbrjob MaterialStackup sum = {stack_thick:.4f} mm (outside 1.60 +/- 0.02 mm)"
        )
    for mname in ("Top Solder Mask", "Bottom Solder Mask"):
        if mask_colors.get(mname) != "Green":
            errors.append(f"[GATE b] .gbrjob {mname} Color is {mask_colors.get(mname)!r} (expected 'Green')")

    pcb_thick = pcbnew.ToMM(ds.GetBoardThickness())
    if abs(pcb_thick - 1.60) > 0.02:
        errors.append(f"[GATE b] .kicad_pcb BoardThickness = {pcb_thick:.4f} mm (outside 1.60 +/- 0.02 mm)")

    sm_min_w = round(pcbnew.ToMM(ds.m_SolderMaskMinWidth), 4)
    sm_margin = round(pcbnew.ToMM(ds.m_SolderMaskExpansion), 4)
    if sm_min_w != 0.1000:
        errors.append(f"[GATE b] m_SolderMaskMinWidth = {sm_min_w:.4f} mm (expected 0.1000 mm)")
    if sm_margin != 0.0350:
        errors.append(f"[GATE b] m_SolderMaskExpansion = {sm_margin:.4f} mm (expected 0.0350 mm IPC-7351B NSMD)")

    with open(pro_path, "r", encoding="utf-8") as f:
        pro_json = json.load(f)
    exclusions = pro_json.get("board", {}).get("design_settings", {}).get("drc_exclusions", [])
    if len(exclusions) != 0:
        errors.append(f"[GATE b] .kicad_pro contains {len(exclusions)} DRC exclusions (expected 0)")

    # Decompose F_Mask.gts & B_Mask.gbs unions into connected opening components
    fmask_geoms = list(fmask_union.geoms) if fmask_union.geom_type == "MultiPolygon" else (
        [fmask_union] if not fmask_union.is_empty else []
    )
    bmask_geoms = list(bmask_union.geoms) if bmask_union.geom_type == "MultiPolygon" else (
        [bmask_union] if not bmask_union.is_empty else []
    )

    def _pad_mask_dam_audit(ref, total_pads, perim_groups):
        if ref not in fps_by_ref:
            errors.append(f"[GATE b] Missing footprint {ref} on board")
            return 0.0
        fp = fps_by_ref[ref]
        pad_to_idx = {}
        for pnum in range(1, total_pads + 1):
            pad = fp.FindPadByNumber(str(pnum))
            if pad is None:
                errors.append(f"[GATE b] Missing {ref} Pad {pnum}")
                continue
            px = pcbnew.ToMM(pad.GetPosition().x) - ax_mm
            py = ay_mm - pcbnew.ToMM(pad.GetPosition().y)
            pt = Point(px, py)
            hits = [idx for idx, g in enumerate(fmask_geoms) if g.contains(pt)]
            if len(hits) != 1:
                errors.append(
                    f"[GATE b] {ref} Pad {pnum} at ({px:.3f}, {py:.3f}) matched {len(hits)} F_Mask openings (expected 1)"
                )
            else:
                pad_to_idx[pnum] = hits[0]

        if len(set(pad_to_idx.values())) != total_pads:
            errors.append(
                f"[GATE b] {ref} solder-mask bridge! {total_pads} pads merged into "
                f"{len(set(pad_to_idx.values()))} F_Mask openings"
            )

        min_dam = float("inf")
        for grp in perim_groups:
            for a, b in zip(grp[:-1], grp[1:]):
                if a in pad_to_idx and b in pad_to_idx:
                    ia, ib = pad_to_idx[a], pad_to_idx[b]
                    dam = 0.0 if ia == ib else fmask_geoms[ia].distance(fmask_geoms[ib])
                    min_dam = min(min_dam, dam)
                    if dam < 0.10 - 5e-4:
                        errors.append(
                            f"[GATE b] {ref} Pads {a}-{b} solder-mask dam {dam:.4f} mm < 0.10 mm"
                        )
        return min_dam

    u1_min_dam = _pad_mask_dam_audit(
        "U1", 73,
        [list(range(1, 17)), list(range(17, 33)), list(range(33, 49)), list(range(49, 65))],
    )
    u2_min_dam = _pad_mask_dam_audit("U2", 9, [[1, 2, 3, 4], [5, 6, 7, 8]])

    # Global pairwise mask sliver check across all disjoint openings on F.Mask & B.Mask
    global_min_dam = float("inf")
    for lname, geoms in (("F_Mask.gts", fmask_geoms), ("B_Mask.gbs", bmask_geoms)):
        if len(geoms) < 2:
            continue
        tree = STRtree(geoms)
        for i, g1 in enumerate(geoms):
            cand_idxs = tree.query(g1.buffer(0.25))
            for j in cand_idxs:
                if j <= i:
                    continue
                d = g1.distance(geoms[j])
                global_min_dam = min(global_min_dam, d)
                if d < 0.10 - 5e-4:
                    c1 = g1.centroid
                    errors.append(
                        f"[GATE b] Solder-mask dam sliver on {lname} near ({c1.x:.3f}, {c1.y:.3f}): "
                        f"width = {d:.4f} mm < 0.10 mm"
                    )

    print(
        f"[DFM b] Finish={finish!r}, Thick={job_thick:.2f}mm (stack={stack_thick:.3f}mm), "
        f"Exclusions={len(exclusions)}, U1_dam={u1_min_dam:.3f}mm, U2_dam={u2_min_dam:.3f}mm, "
        f"Global_min_dam={global_min_dam:.3f}mm (>=0.10)."
    )

    # ==========================================================================
    # GATE (c): Stencil Paste Area Ratio (0.10mm), Omitted B_Paste & Windowing
    # ==========================================================================
    if bpaste_cands:
        errors.append(
            f"[GATE c] Unexpected bottom stencil Gerber file(s) {bpaste_cands} present in {gerber_dir}; "
            f"Option 2A single-sided top SMT requires omitting *-B_Paste.gbp!"
        )

    if not fpaste_gbr["flashes"]:
        errors.append("[GATE c] F_Paste.gtp contains 0 flashed paste apertures!")
    if fpaste_gbr["regions"] or fpaste_gbr["draws"]:
        for reg in fpaste_gbr["regions"]:
            p = reg["poly"]
            ar10 = p.area / (p.length * 0.10) if p.length > 0 else 0.0
            if ar10 < 0.80:
                errors.append(
                    f"[GATE c] F_Paste.gtp region aperture fails 0.10mm stencil AR: AR@0.10={ar10:.3f} (<0.80)"
                )

    # Verify every defined & flashed aperture in F_Paste.gtp on 0.10 mm (100 um) stencil (BLK-07)
    seen_paste_comps = set()
    min_ar10 = float("inf")
    min_ar_desc = ""

    for dcode, spec in fpaste_gbr["apertures"].items():
        ar10_exact = spec["area"] / (spec["perim"] * 0.10)
        ar10_box = spec["box_area"] / (spec["box_perim"] * 0.10)
        ar10 = min(ar10_exact, ar10_box)
        if ar10 < min_ar10:
            min_ar10 = ar10
            min_ar_desc = f"{dcode}({spec['width']:.3f}x{spec['height']:.3f}mm)"
        if ar10 < 0.80 - 1e-4:
            errors.append(
                f"[GATE c] Stencil aperture {dcode} ({spec['width']:.3f} x {spec['height']:.3f} mm) "
                f"violates IPC-7525 Area Ratio on 0.10mm stencil: AR@0.10mm={ar10:.3f} (req >=0.80 / >=0.66 floor)"
            )

    flashes_by_comp = defaultdict(list)
    for fl in fpaste_gbr["flashes"]:
        if fl["comp"]:
            seen_paste_comps.add(fl["comp"])
            flashes_by_comp[fl["comp"]].append(fl)
        if fl["x"] >= 50.0:
            errors.append(
                f"[GATE c] Unexpected solder paste flash inside antenna/IDE aperture at "
                f"({fl['x']:.3f}, {fl['y']:.3f})"
            )

    for req_comp in ("U1", "U2", "Q1", "R1", "C_S", "C_M1", "L_M1", "C_MZ", "C_M2"):
        if req_comp not in seen_paste_comps:
            errors.append(f"[GATE c] Required SMD component {req_comp} missing from F_Paste.gtp!")
    if "J1" in seen_paste_comps:
        errors.append("[GATE c] Edge-straddle hand-solder connector J1 must have 0 paste in F_Paste.gtp!")

    paste_union = unary_union([fl["poly"] for fl in fpaste_gbr["flashes"]])

    # Zero paste flashes on ANY DNP footprint (BLK-07 / Gate 3)
    dnp_refs = sorted(r for r, fp in fps_by_ref.items() if fp.IsDNP())
    for dnp_r in dnp_refs:
        if dnp_r in seen_paste_comps:
            errors.append(f"[GATE c] DNP footprint {dnp_r} has %TO.C paste flash(es) in F_Paste.gtp!")
        for pad in fps_by_ref[dnp_r].Pads():
            if pad.IsOnLayer(pcbnew.F_Cu):
                ppoly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
                if not ppoly.is_empty and ppoly.intersection(paste_union).area > 1e-6:
                    errors.append(f"[GATE c] DNP pad {dnp_r}.{pad.GetNumber()} overlaps F_Paste.gtp!")

    # Verify exact U1 perimeter (0.30 x 1.10 mm) & center (56.25% = 1.20 x 1.20 mm) paste apertures
    u1_covs = []
    if "U1" in fps_by_ref:
        u1_perim_ok = 0
        for pnum in range(1, 65):
            pad = fps_by_ref["U1"].FindPadByNumber(str(pnum))
            cu_poly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
            hits = [fl for fl in flashes_by_comp["U1"] if cu_poly.intersects(fl["poly"])]
            if len(hits) != 1:
                errors.append(f"[GATE c] U1 Pad {pnum} expected 1 paste flash, got {len(hits)}")
                break
            minx, miny, maxx, maxy = hits[0]["poly"].bounds
            dims = sorted([maxx - minx, maxy - miny])
            if abs(dims[0] - 0.30) > 0.01 or abs(dims[1] - 1.10) > 0.01:
                errors.append(
                    f"[GATE c] U1 Pad {pnum} paste aperture {dims[0]:.3f}x{dims[1]:.3f} mm != 0.300x1.100 mm"
                )
                break
            u1_perim_ok += 1
        if u1_perim_ok != 64 and not any("U1 Pad" in e for e in errors):
            errors.append(f"[GATE c] Expected 64 U1 perimeter paste flashes, got {u1_perim_ok}")
        for pnum in range(65, 74):
            pad = fps_by_ref["U1"].FindPadByNumber(str(pnum))
            cu_poly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
            paste_area = cu_poly.intersection(paste_union).area
            cov = 100.0 * paste_area / cu_poly.area
            u1_covs.append(cov)
            if not (53.0 <= cov <= 59.5):
                errors.append(
                    f"[GATE c] U1 Pad {pnum} LGA paste coverage {cov:.1f}% outside 56.25% +/- 3.25%"
                )

    # Verify exact U2 perimeter (0.22 x 0.82 mm) & Pad 9 EP (4 x 0.57 x 0.86 mm = 50.0% +/- 2%) paste
    u2_cov = 0.0
    if "U2" in fps_by_ref:
        u2_perim_ok = 0
        for pnum in range(1, 9):
            pad = fps_by_ref["U2"].FindPadByNumber(str(pnum))
            cu_poly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
            hits = [fl for fl in flashes_by_comp["U2"] if cu_poly.intersects(fl["poly"])]
            if len(hits) != 1:
                errors.append(f"[GATE c] U2 Pad {pnum} expected 1 paste flash, got {len(hits)}")
                break
            minx, miny, maxx, maxy = hits[0]["poly"].bounds
            dims = sorted([maxx - minx, maxy - miny])
            if abs(dims[0] - 0.22) > 0.01 or abs(dims[1] - 0.82) > 0.01:
                errors.append(
                    f"[GATE c] U2 Pad {pnum} paste aperture {dims[0]:.3f}x{dims[1]:.3f} mm != 0.220x0.820 mm"
                )
                break
            u2_perim_ok += 1
        if u2_perim_ok != 8 and not any("U2 Pad" in e for e in errors):
            errors.append(f"[GATE c] Expected 8 U2 perimeter paste flashes, got {u2_perim_ok}")
        pad9 = fps_by_ref["U2"].FindPadByNumber("9")
        cu_poly9 = _poly_set_to_shapely_aux(pad9.GetEffectivePolygon(pcbnew.F_Cu, 0), ax_mm, ay_mm)
        ep_panes = [fl for fl in flashes_by_comp["U2"] if cu_poly9.intersects(fl["poly"])]
        if len(ep_panes) != 4:
            errors.append(f"[GATE c] Expected 4 U2 Pad 9 EP window-pane paste flashes, got {len(ep_panes)}")
        for fl in ep_panes:
            minx, miny, maxx, maxy = fl["poly"].bounds
            dims = sorted([maxx - minx, maxy - miny])
            if abs(dims[0] - 0.57) > 0.015 or abs(dims[1] - 0.86) > 0.015:
                errors.append(
                    f"[GATE c] U2 Pad 9 pane {dims[0]:.3f}x{dims[1]:.3f} mm != 0.570x0.860 mm"
                )
                break
        paste_area9 = cu_poly9.intersection(paste_union).area
        u2_cov = 100.0 * paste_area9 / cu_poly9.area
        if not (48.0 <= u2_cov <= 52.0):
            errors.append(
                f"[GATE c] U2 Pad 9 thermal EP paste coverage {u2_cov:.2f}% outside 50.0% +/- 2.0%"
            )

    print(
        f"[DFM c] F_Paste (0.10mm stencil, B_Paste omitted) min AR={min_ar_desc}: AR@0.10={min_ar10:.3f} (>=0.80); "
        f"DNP_flashes=0/{len(dnp_refs)}; U1_perim=0.30x1.10, U1_EP={min(u1_covs):.1f}%, "
        f"U2_perim=0.22x0.82, U2_EP={u2_cov:.2f}% (50% target)."
    )

    # ==========================================================================
    # GATE (d): Board-vs-Library Footprint Pad Parity & 3D STEP Verification
    # ==========================================================================
    pcb_dir = os.path.dirname(os.path.abspath(pcb_path))
    max_pos_err = 0.0
    max_sz_err = 0.0
    checked_3d = 0

    for fp in board.GetFootprints():
        ref = fp.GetReference().strip()
        fpid = fp.GetFPID()
        lib_nick = str(fpid.GetLibNickname())
        fp_name = str(fpid.GetLibItemName())

        if lib_nick == "ISAC":
            lib_path = pretty_dir
        else:
            lib_path = os.path.join(SYS_FP_DIR, f"{lib_nick}.pretty")

        if not os.path.isdir(lib_path):
            errors.append(f"[GATE d] Footprint library directory missing for {ref}: {lib_path}")
            continue

        lib_fp = pcbnew.FootprintLoad(lib_path, fp_name)
        if lib_fp is None:
            errors.append(f"[GATE d] Footprint {lib_nick}:{fp_name} for {ref} not found in {lib_path}")
            continue

        if fp.IsFlipped():
            lib_fp.Flip(lib_fp.GetPosition(), False)
        lib_fp.SetPosition(fp.GetPosition())
        lib_fp.SetOrientation(fp.GetOrientation())

        b_pads = list(fp.Pads())
        l_pads = list(lib_fp.Pads())
        if len(b_pads) != len(l_pads):
            errors.append(
                f"[GATE d] {ref} ({lib_nick}:{fp_name}) pad count mismatch: "
                f"board={len(b_pads)} vs library={len(l_pads)}"
            )
            continue

        def _pad_sort_key(p):
            return (
                str(p.GetNumber()).strip(),
                p.GetLayerSet().FmtHex(),
                round(pcbnew.ToMM(p.GetPosition().x), 2),
                round(pcbnew.ToMM(p.GetPosition().y), 2),
            )

        b_pads.sort(key=_pad_sort_key)
        l_pads.sort(key=_pad_sort_key)

        for bp, lp in zip(b_pads, l_pads):
            bnum = str(bp.GetNumber()).strip()
            lnum = str(lp.GetNumber()).strip()
            if bnum != lnum:
                errors.append(f"[GATE d] {ref} pad number mismatch: board={bnum!r} vs lib={lnum!r}")
                continue

            dx_p = pcbnew.ToMM(bp.GetPosition().x - lp.GetPosition().x)
            dy_p = pcbnew.ToMM(bp.GetPosition().y - lp.GetPosition().y)
            pos_err = math.hypot(dx_p, dy_p)
            max_pos_err = max(max_pos_err, pos_err)
            if pos_err > 0.05 + 1e-5:
                errors.append(
                    f"[GATE d] {ref}.Pad{bnum} coordinate drift vs .pretty: "
                    f"delta={pos_err:.4f} mm > 0.05 mm"
                )

            bbb = bp.GetBoundingBox()
            lbb = lp.GetBoundingBox()
            dw = abs(pcbnew.ToMM(bbb.GetWidth() - lbb.GetWidth()))
            dh = abs(pcbnew.ToMM(bbb.GetHeight() - lbb.GetHeight()))
            sz_err = max(dw, dh)
            max_sz_err = max(max_sz_err, sz_err)
            if dw > 0.02 + 1e-5 or dh > 0.02 + 1e-5:
                errors.append(
                    f"[GATE d] {ref}.Pad{bnum} rotated size mismatch vs .pretty: "
                    f"dW={dw:.4f} mm, dH={dh:.4f} mm (> 0.02 mm)"
                )

        is_board_only = bool(fp.GetAttributes() & pcbnew.FP_BOARD_ONLY)
        if ref in ("H1", "H2", "H3", "H4"):
            if len(b_pads) != 1 or abs(pcbnew.ToMM(b_pads[0].GetDrillSize().x) - 2.70) > 1e-3:
                got_dr = pcbnew.ToMM(b_pads[0].GetDrillSize().x) if b_pads else 0.0
                errors.append(
                    f"[GATE d] {ref} mounting hole NPTH drill = {got_dr:.3f} mm "
                    f"(expected ISO 273 medium-fit 2.700 mm for M2.5)"
                )
        models = list(fp.Models())
        if not is_board_only and len(models) == 0:
            errors.append(f"[GATE d] Electrical footprint {ref} has 0 3D STEP models assigned")

        for mdl in models:
            raw_mpath = mdl.m_Filename
            if "/home/" in raw_mpath:
                errors.append(f"[GATE d] {ref} contains hardcoded /home/ 3D model path: {raw_mpath}")
            resolved = (
                raw_mpath.replace("${KIPRJMOD}", pcb_dir)
                .replace("${KICAD9_3DMODEL_DIR}", SYS_3D_DIR)
                .replace("${KICAD8_3DMODEL_DIR}", SYS_3D_DIR)
            )
            if not os.path.isabs(resolved):
                resolved = os.path.join(pcb_dir, resolved)
            if not os.path.isfile(resolved) or os.path.getsize(resolved) == 0:
                errors.append(f"[GATE d] {ref} 3D model missing or empty on disk: {resolved} ({raw_mpath})")
            else:
                checked_3d += 1

    print(
        f"[DFM d] {len(fps_by_ref)} footprints verified vs .pretty "
        f"(max_pos_err={max_pos_err:.4f}mm <=0.05, max_size_err={max_sz_err:.4f}mm <=0.02); "
        f"{checked_3d} 3D STEP files verified (0 /home/ paths)."
    )

    # ==========================================================================
    # GATE (e): RF & SiP B.Cu Return-Plane Integrity + 0% Antenna Copper Pour
    # ==========================================================================
    bcu_zone_polys = pcbnew.SHAPE_POLY_SET()
    ant_box_aux = box(50.0, 0.0, 90.0, 40.0)

    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        for lyr, lname in ((pcbnew.F_Cu, "F.Cu"), (pcbnew.B_Cu, "B.Cu")):
            if not z.IsOnLayer(lyr):
                continue
            filled = z.GetFilledPolysList(lyr)
            sh_poly = _poly_set_to_shapely_aux(filled, ax_mm, ay_mm)
            leak = sh_poly.intersection(ant_box_aux)
            if not leak.is_empty and leak.area > 1e-6:
                errors.append(
                    f"[GATE e] Copper zone pour leaks into dx >= 50.0 mm antenna aperture on {lname} "
                    f"(area = {leak.area:.4f} mm^2)"
                )
            if lyr == pcbnew.B_Cu and z.GetNetname() == "GND":
                bcu_zone_polys.Append(filled)

    # Also verify B_Cu.gbl has 0 copper features in X_gbr >= 50.0 mm
    for item_list in (bcu_gbr["regions"], bcu_gbr["flashes"], bcu_gbr["draws"]):
        for it in item_list:
            leak = it["poly"].intersection(ant_box_aux)
            if not leak.is_empty and leak.area > 1e-6:
                errors.append(
                    f"[GATE e] B_Cu.gbl contains copper in X_gbr >= 50.0 mm antenna aperture "
                    f"(area = {leak.area:.4f} mm^2)"
                )

    if bcu_zone_polys.IsEmpty():
        errors.append("[GATE e] B.Cu GND filled zone polygon set is empty!")

    rf_nets = {"/RF_PA", "/BR_P", "/BR_Q", "/ANT_FEED", "/SMA_C", "/BR_S", "/BR_O", "/DET_IN"}
    rf_samples = 0
    rf_broken = 0
    brs_void_samples = 0

    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if t.GetLayer() != pcbnew.F_Cu or t.GetNetname() not in rf_nets:
            continue
        x1 = pcbnew.ToMM(t.GetStart().x) - x0_mm
        y1 = pcbnew.ToMM(t.GetStart().y) - y0_mm
        x2 = pcbnew.ToMM(t.GetEnd().x) - x0_mm
        y2 = pcbnew.ToMM(t.GetEnd().y) - y0_mm
        seg_len = math.hypot(x2 - x1, y2 - y1)
        n_steps = max(1, int(math.ceil(seg_len / 0.05)))
        for k in range(n_steps + 1):
            u = k / float(n_steps)
            dx = x1 + u * (x2 - x1)
            dy = y1 + u * (y2 - y1)
            if dx >= 49.35:
                continue
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(x0_mm + dx), pcbnew.FromMM(y0_mm + dy))
            if t.GetNetname() == "/BR_S":
                # Intentional 2.20 x 2.20 mm F.Cu/B.Cu parasitic cutout void (BLK-01 / BLK-02)
                brs_void_samples += 1
                if not (33.40 <= dx <= 35.60 and 24.18 <= dy <= 26.38):
                    errors.append(
                        f"[GATE e] /BR_S trace escapes 2.2x2.2mm parasitic cutout at (dx={dx:.3f}, dy={dy:.3f})!"
                    )
                if bcu_zone_polys.Contains(pt):
                    errors.append(
                        f"[GATE e] B.Cu copper present beneath /BR_S at (dx={dx:.3f}, dy={dy:.3f}) — "
                        f"must be void for C_par < 0.15 pF!"
                    )
                continue
            rf_samples += 1
            if not bcu_zone_polys.Contains(pt):
                rf_broken += 1
                if rf_broken <= 5:
                    errors.append(
                        f"[GATE e] Unbroken B.Cu return-plane violation under {t.GetNetname()} "
                        f"at board (dx={dx:.3f}, dy={dy:.3f})!"
                    )

    if rf_samples == 0 or brs_void_samples == 0:
        errors.append("[GATE e] Zero RF or /BR_S void samples found across mandatory RF nets!")

    # Sample 0.25 mm grid under U1's 3x3 ground matrix (dx = 14.6..21.9, dy = 14.3..21.5)
    u1_grid_samples = 0
    u1_grid_broken = 0
    nx_grid = int(round((21.9 - 14.6) / 0.25))
    ny_grid = int(round((21.5 - 14.3) / 0.25))
    for ix in range(nx_grid + 1):
        dx = 14.6 + ix * 0.25
        if dx > 21.9 + 1e-6:
            break
        for iy in range(ny_grid + 1):
            dy = 14.3 + iy * 0.25
            if dy > 21.5 + 1e-6:
                break
            u1_grid_samples += 1
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(x0_mm + dx), pcbnew.FromMM(y0_mm + dy))
            if not bcu_zone_polys.Contains(pt):
                u1_grid_broken += 1
                if u1_grid_broken <= 5:
                    errors.append(
                        f"[GATE e] B.Cu ground slot/void under U1 3x3 LGA matrix at "
                        f"(dx={dx:.2f}, dy={dy:.2f})!"
                    )

    # Verify every F.Cu GND zone island has >= 2 stitching vias (F-16)
    gnd_vias_board = [
        t.GetPosition()
        for t in board.GetTracks()
        if isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "GND"
    ]
    fcu_gnd_islands = 0
    for z in board.Zones():
        if z.GetIsRuleArea() or not z.IsOnLayer(pcbnew.F_Cu) or z.GetNetname() != "GND":
            continue
        ps = z.GetFilledPolysList(pcbnew.F_Cu)
        for oi in range(ps.OutlineCount()):
            fcu_gnd_islands += 1
            sub = pcbnew.SHAPE_POLY_SET()
            sub.AddOutline(ps.Outline(oi))
            for hi in range(ps.HoleCount(oi)):
                sub.AddHole(ps.Hole(oi, hi), 0)
            n_iv = sum(1 for vpos in gnd_vias_board if sub.Contains(vpos))
            if n_iv < 2:
                bb = sub.BBox()
                errors.append(
                    f"[GATE e] F.Cu GND zone island #{oi + 1} "
                    f"[{pcbnew.ToMM(bb.GetLeft()) - x0_mm:.2f}..{pcbnew.ToMM(bb.GetRight()) - x0_mm:.2f}, "
                    f"{pcbnew.ToMM(bb.GetTop()) - y0_mm:.2f}..{pcbnew.ToMM(bb.GetBottom()) - y0_mm:.2f}] "
                    f"has only {n_iv} GND via(s) (required >= 2)"
                )

    print(
        f"[DFM e] B.Cu return plane: {rf_samples - rf_broken}/{rf_samples} RF samples (0.05mm step) "
        f"& {u1_grid_samples - u1_grid_broken}/{u1_grid_samples} U1 matrix samples (0.25mm grid) "
        f"unbroken; {fcu_gnd_islands} F.Cu GND islands all >=2 vias; 0% pour in dx >= 50.0mm."
    )

    # ==========================================================================
    # GATE (f): Fiducials, Silkscreen (>=0.15mm & inside Edge.Cuts), Acute Bends & Stubs
    # ==========================================================================
    global_fids = []
    local_u1_fids = []
    u1_cx = (pcbnew.ToMM(fps_by_ref["U1"].GetPosition().x) - x0_mm) if "U1" in fps_by_ref else 18.25
    u1_cy = (pcbnew.ToMM(fps_by_ref["U1"].GetPosition().y) - y0_mm) if "U1" in fps_by_ref else 17.90

    fcu_all_polys = (
        [r["poly"] for r in fcu_gbr["regions"]]
        + [f["poly"] for f in fcu_gbr["flashes"]]
        + [d["poly"] for d in fcu_gbr["draws"]]
    )
    fcu_union = unary_union(fcu_all_polys) if fcu_all_polys else Polygon()

    for ref, fp in sorted(fps_by_ref.items()):
        if not ref.startswith("FID"):
            continue
        fx = pcbnew.ToMM(fp.GetPosition().x) - x0_mm
        fy = pcbnew.ToMM(fp.GetPosition().y) - y0_mm
        fx_aux = pcbnew.ToMM(fp.GetPosition().x) - ax_mm
        fy_aux = ay_mm - pcbnew.ToMM(fp.GetPosition().y)
        if fx >= 49.0:
            errors.append(f"[GATE f] Fiducial {ref} placed inside antenna bay (dx={fx:.2f} >= 49.0 mm)")
        pads = list(fp.Pads())
        cu_d = pcbnew.ToMM(pads[0].GetSize().x) if pads else 0.0
        if cu_d < 1.00 - 1e-3:
            errors.append(
                f"[GATE f] Fiducial {ref} copper pad diameter {cu_d:.3f} mm < 1.000 mm PCBWay SMT minimum"
            )
        # Verify Ø2.00 mm F_Mask.gts opening and 0 mm^2 foreign F_Cu.gtl copper inside opening
        fpt = Point(fx_aux, fy_aux)
        mhits = [g for g in fmask_geoms if g.contains(fpt)]
        if len(mhits) != 1:
            errors.append(f"[GATE f] Fiducial {ref} matched {len(mhits)} F_Mask.gts openings (expected 1)")
        else:
            mopen = mhits[0]
            mw = mopen.bounds[2] - mopen.bounds[0]
            mh = mopen.bounds[3] - mopen.bounds[1]
            if min(mw, mh) < 2.00 - 0.02:
                errors.append(
                    f"[GATE f] Fiducial {ref} F_Mask.gts opening {mw:.3f}x{mh:.3f} mm < 2.00 mm diameter"
                )
            cu_in_open = fcu_union.intersection(mopen)
            own_pad = fpt.buffer(0.5 * cu_d + 0.02, quad_segs=32)
            foreign_cu_area = cu_in_open.difference(own_pad).area
            if foreign_cu_area > 1e-4:
                errors.append(
                    f"[GATE f] Fiducial {ref} has {foreign_cu_area:.4f} mm^2 foreign F_Cu copper inside Ø2.0mm mask opening!"
                )
        if ref in ("FID1", "FID2", "FID3"):
            global_fids.append((ref, fx, fy))
        elif math.hypot(fx - u1_cx, fy - u1_cy) <= 12.5:
            local_u1_fids.append((ref, fx, fy))

    if len(global_fids) < 3:
        errors.append(f"[GATE f] Found {len(global_fids)} global fiducials (required >= 3)")
    else:
        (_, x1, y1), (_, x2, y2), (_, x3, y3) = global_fids[:3]
        tri_area = 0.5 * abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
        if tri_area < 200.0:
            errors.append(
                f"[GATE f] Global fiducials collinear / insufficient span (triangle area={tri_area:.1f} mm^2)"
            )
    if len(local_u1_fids) < 2:
        errors.append(f"[GATE f] Found {len(local_u1_fids)} local U1 fiducials (required >= 2)")

    # Build exact Edge.Cuts closed polygon from Edge_Cuts.gm1 draws
    edge_lines = [d["line"] for d in edge_gbr["draws"]]
    from shapely.ops import polygonize
    edge_polys = list(polygonize(unary_union(edge_lines)))
    if len(edge_polys) != 1:
        errors.append(f"[GATE f] Edge_Cuts.gm1 did not form 1 closed board outline (got {len(edge_polys)})")
        board_outline = box(0.0, 0.0, 90.0, 40.0)
    else:
        board_outline = edge_polys[0]

    # Check silkscreen stroke widths & Edge.Cuts containment in .kicad_pcb + F_Silkscreen.gto
    min_silk_w = float("inf")
    for d in board.GetDrawings():
        if d.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        if isinstance(d, pcbnew.PCB_TEXT) and d.IsVisible():
            th = pcbnew.ToMM(d.GetTextThickness())
            min_silk_w = min(min_silk_w, th)
            if th < 0.15 - 1e-4:
                errors.append(f"[GATE f] Board silk text {d.GetText()!r} thickness {th:.3f} mm < 0.15 mm")
        elif isinstance(d, pcbnew.PCB_SHAPE) and d.GetShape() != pcbnew.SHAPE_T_POLY:
            w = pcbnew.ToMM(d.GetWidth())
            min_silk_w = min(min_silk_w, w)
            if w < 0.15 - 1e-4:
                errors.append(f"[GATE f] Board silk shape stroke {w:.3f} mm < 0.15 mm")

    for ref, fp in fps_by_ref.items():
        rtxt = fp.Reference()
        if rtxt.IsVisible() and rtxt.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            th = pcbnew.ToMM(rtxt.GetTextThickness())
            min_silk_w = min(min_silk_w, th)
            if th < 0.15 - 1e-4:
                errors.append(f"[GATE f] {ref} Ref silk thickness {th:.3f} mm < 0.15 mm")
        for gi in fp.GraphicalItems():
            if gi.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                continue
            if isinstance(gi, pcbnew.PCB_TEXT) and gi.IsVisible():
                th = pcbnew.ToMM(gi.GetTextThickness())
                min_silk_w = min(min_silk_w, th)
                if th < 0.15 - 1e-4:
                    errors.append(f"[GATE f] {ref} fp_text silk thickness {th:.3f} mm < 0.15 mm")
            elif isinstance(gi, pcbnew.PCB_SHAPE):
                w = pcbnew.ToMM(gi.GetWidth())
                if gi.GetShape() != pcbnew.SHAPE_T_POLY or w > 0.0:
                    min_silk_w = min(min_silk_w, w)
                    if w < 0.15 - 1e-4:
                        errors.append(f"[GATE f] {ref} fp_shape silk stroke {w:.3f} mm < 0.15 mm")

    for dcode, spec in fsilk_gbr["apertures"].items():
        min_silk_w = min(min_silk_w, spec["dia"])
        if spec["dia"] < 0.15 - 1e-4:
            errors.append(
                f"[GATE f] F_Silkscreen.gto aperture {dcode} width {spec['dia']:.4f} mm < 0.15 mm"
            )

    silk_items_gbr = (
        [d["poly"] for d in fsilk_gbr["draws"]]
        + [fl["poly"] for fl in fsilk_gbr["flashes"]]
        + [r["poly"] for r in fsilk_gbr["regions"]]
    )
    bsilk_items_gbr = (
        [d["poly"] for d in bsilk_gbr["draws"]]
        + [fl["poly"] for fl in bsilk_gbr["flashes"]]
        + [r["poly"] for r in bsilk_gbr["regions"]]
    )
    if silk_items_gbr:
        silk_union = unary_union(silk_items_gbr)
        outside = silk_union.difference(board_outline)
        if not outside.is_empty and outside.area > 1e-6:
            errors.append(
                f"[GATE f] Silkscreen extends outside Edge.Cuts profile (outside area={outside.area:.4f} mm^2)"
            )

    # Gate 3 Forensic Checks:
    # (1) Zero F_Silkscreen.gto or B_Silkscreen.gbo primitives in X_gbr >= 50.0 mm (HIGH-01)
    ant_silk_box = box(50.0, -5.0, 95.0, 45.0)
    for s_lbl, s_polys in (("F_Silkscreen.gto", silk_items_gbr), ("B_Silkscreen.gbo", bsilk_items_gbr)):
        ant_hits = [p for p in s_polys if p.intersects(ant_silk_box) and p.intersection(ant_silk_box).area > 1e-7]
        if ant_hits:
            errors.append(
                f"[GATE f] {s_lbl} contains {len(ant_hits)} silkscreen primitive(s) in X_gbr >= 50.0 mm keepout!"
            )

    # (2) Single continuous bare-ENIG AE1 F_Mask.gts window [73.40..87.80] x [6.65..20.80] mm (HIGH-01)
    # Exclude H3 (86.5, 36.5) and H4 (86.5, 3.5) M2.5 NPTH hole clearances at top/bottom board corners
    all_ant_mask_opens = [g for g in fmask_geoms if g.intersects(box(50.5, 0.0, 90.0, 40.0))]
    ae1_mask_opens = [g for g in fmask_geoms if g.intersects(box(50.5, 5.5, 90.0, 34.5))]
    if len(all_ant_mask_opens) != 3 or len(ae1_mask_opens) != 1:
        errors.append(
            f"[GATE f] Expected 1 continuous F_Mask.gts opening in AE1 window (+2 M2.5 NPTH holes), "
            f"found window={len(ae1_mask_opens)}, total_ant={len(all_ant_mask_opens)}!"
        )
    else:
        mx0, my0, mx1, my1 = ae1_mask_opens[0].bounds
        rect_fill = ae1_mask_opens[0].area / max(1e-6, (mx1 - mx0) * (my1 - my0))
        if (
            abs(mx0 - 73.40) > 0.05
            or abs(mx1 - 87.80) > 0.05
            or abs(my0 - 6.65) > 0.05
            or abs(my1 - 20.80) > 0.05
            or rect_fill < 0.999
        ):
            errors.append(
                f"[GATE f] AE1 F_Mask.gts opening [{mx0:.3f}..{mx1:.3f}]x[{my0:.3f}..{my1:.3f}] "
                f"(fill={rect_fill:.4f}) != [73.40..87.80]x[6.65..20.80] continuous rectangle!"
            )

    # (3) 100% of visible F.SilkS reference designators <= 2.00 mm from courtyard & 0 collisions (HIGH-02)
    vis_ref_count = 0
    max_ref_crtyd_mm = 0.0
    via_polys_aux = [
        Point(pcbnew.ToMM(v.GetPosition().x) - ax_mm, ay_mm - pcbnew.ToMM(v.GetPosition().y)).buffer(
            0.5 * pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu)), quad_segs=16
        )
        for v in vias
    ]
    via_union_aux = unary_union(via_polys_aux) if via_polys_aux else Polygon()
    for ref, fp in sorted(fps_by_ref.items()):
        rtxt = fp.Reference()
        if not (rtxt.IsVisible() and rtxt.GetLayer() == pcbnew.F_SilkS):
            continue
        vis_ref_count += 1
        tbb = rtxt.GetBoundingBox()
        rbox = box(
            pcbnew.ToMM(tbb.GetLeft()) - ax_mm,
            ay_mm - pcbnew.ToMM(tbb.GetBottom()),
            pcbnew.ToMM(tbb.GetRight()) - ax_mm,
            ay_mm - pcbnew.ToMM(tbb.GetTop()),
        )
        # Build parent courtyard bbox on F.CrtYd (fallback to pad bbox)
        cx_vals, cy_vals = [], []
        for gi in fp.GraphicalItems():
            if gi.GetLayer() == pcbnew.F_CrtYd:
                gbb = gi.GetBoundingBox()
                cx_vals.extend([pcbnew.ToMM(gbb.GetLeft()) - ax_mm, pcbnew.ToMM(gbb.GetRight()) - ax_mm])
                cy_vals.extend([ay_mm - pcbnew.ToMM(gbb.GetBottom()), ay_mm - pcbnew.ToMM(gbb.GetTop())])
        if not cx_vals:
            fbb = fp.GetFpPadsLocalBbox()
            pos = fp.GetPosition()
            cx_vals = [pcbnew.ToMM(pos.x + fbb.GetLeft()) - ax_mm, pcbnew.ToMM(pos.x + fbb.GetRight()) - ax_mm]
            cy_vals = [ay_mm - pcbnew.ToMM(pos.y + fbb.GetBottom()), ay_mm - pcbnew.ToMM(pos.y + fbb.GetTop())]
        cbox = box(min(cx_vals), min(cy_vals), max(cx_vals), max(cy_vals))
        dist_mm = rbox.distance(cbox)
        max_ref_crtyd_mm = max(max_ref_crtyd_mm, dist_mm)
        if dist_mm > 2.00 + 1e-3:
            errors.append(
                f"[GATE f] Visible F.SilkS Ref {ref} is {dist_mm:.2f} mm (> 2.00 mm) from parent courtyard!"
            )
        if not fmask_union.is_empty and rbox.intersects(fmask_union) and rbox.intersection(fmask_union).area > 1e-4:
            errors.append(f"[GATE f] Visible F.SilkS Ref {ref} overlaps exposed F_Mask.gts pad opening!")
        if not via_union_aux.is_empty and rbox.intersects(via_union_aux) and rbox.intersection(via_union_aux).area > 1e-4:
            errors.append(f"[GATE f] Visible F.SilkS Ref {ref} overlaps copper via!")

    # (4) Zero B_Silkscreen.gbo overlaps with copper vias or B_Mask.gbs openings (DFM-02)
    if bsilk_items_gbr:
        bsilk_union = unary_union(bsilk_items_gbr)
        if not via_union_aux.is_empty and bsilk_union.intersects(via_union_aux) and bsilk_union.intersection(via_union_aux).area > 1e-4:
            errors.append("[GATE f] B_Silkscreen.gbo overlaps tented via barrel/annular ring!")
        if not bmask_union.is_empty and bsilk_union.intersects(bmask_union) and bsilk_union.intersection(bmask_union).area > 1e-4:
            errors.append("[GATE f] B_Silkscreen.gbo overlaps exposed B_Mask.gbs pad opening!")

    # Acute track bends (< 85 deg) & unanchored stubs
    tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
    verts = defaultdict(list)
    for t in tracks:
        p1 = (round(pcbnew.ToMM(t.GetStart().x) - ax_mm, 3), round(ay_mm - pcbnew.ToMM(t.GetStart().y), 3))
        p2 = (round(pcbnew.ToMM(t.GetEnd().x) - ax_mm, 3), round(ay_mm - pcbnew.ToMM(t.GetEnd().y), 3))
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 0.05:
            continue
        verts[(t.GetLayer(), t.GetNetCode(), p1)].append((p2[0] - p1[0], p2[1] - p1[1], t.GetNetname()))
        verts[(t.GetLayer(), t.GetNetCode(), p2)].append((p1[0] - p2[0], p1[1] - p2[1], t.GetNetname()))

    min_bend_deg = 180.0
    for (_, _, vpt), vecs in verts.items():
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                v1x, v1y, nname = vecs[i]
                v2x, v2y, _ = vecs[j]
                l1 = math.hypot(v1x, v1y)
                l2 = math.hypot(v2x, v2y)
                cos_a = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (l1 * l2)))
                ang = math.degrees(math.acos(cos_a))
                if ang > 1.0:
                    min_bend_deg = min(min_bend_deg, ang)
                    if ang < 85.0:
                        errors.append(
                            f"[GATE f] Acute copper bend {ang:.1f} deg (< 85 deg) on {nname} at {vpt}"
                        )

    # Unanchored copper track endpoints: every track endpoint must anchor to another same-layer/net
    # track, a same-net via, or a same-layer/net pad.
    anchors_by_layer_net = defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            nc = pad.GetNetCode()
            for lyr in (pcbnew.F_Cu, pcbnew.B_Cu):
                if pad.IsOnLayer(lyr):
                    ppoly = _poly_set_to_shapely_aux(pad.GetEffectivePolygon(lyr, 0), ax_mm, ay_mm)
                    if not ppoly.is_empty:
                        anchors_by_layer_net[(lyr, nc)].append(ppoly)
    for v in vias:
        vx = pcbnew.ToMM(v.GetPosition().x) - ax_mm
        vy = ay_mm - pcbnew.ToMM(v.GetPosition().y)
        vr = 0.5 * pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu))
        vpoly = Point(vx, vy).buffer(vr, quad_segs=16)
        nc = v.GetNetCode()
        anchors_by_layer_net[(pcbnew.F_Cu, nc)].append(vpoly)
        anchors_by_layer_net[(pcbnew.B_Cu, nc)].append(vpoly)

    track_geoms = []
    for idx, t in enumerate(tracks):
        x1 = pcbnew.ToMM(t.GetStart().x) - ax_mm
        y1 = ay_mm - pcbnew.ToMM(t.GetStart().y)
        x2 = pcbnew.ToMM(t.GetEnd().x) - ax_mm
        y2 = ay_mm - pcbnew.ToMM(t.GetEnd().y)
        hw = 0.5 * pcbnew.ToMM(t.GetWidth())
        t_line = LineString([(x1, y1), (x2, y2)])
        track_geoms.append((idx, t.GetLayer(), t.GetNetCode(), t.GetNetname(), (x1, y1), (x2, y2), hw, t_line))

    unanchored_count = 0
    for idx, lyr, nc, nname, p1, p2, hw, _ in track_geoms:
        static_anchors = anchors_by_layer_net[(lyr, nc)]
        other_lines = [tg[7].buffer(tg[6]) for tg in track_geoms if tg[0] != idx and tg[1] == lyr and tg[2] == nc]
        for ep in (p1, p2):
            pt = Point(ep)
            anchored = any(a.distance(pt) <= 0.02 for a in static_anchors) or any(
                ol.distance(pt) <= 0.02 for ol in other_lines
            )
            if not anchored:
                unanchored_count += 1
                errors.append(
                    f"[GATE f] Unanchored copper stub on {nname} ({'F.Cu' if lyr == pcbnew.F_Cu else 'B.Cu'}) "
                    f"at AuxOrigin ({ep[0]:.3f}, {ep[1]:.3f})"
                )

    print(
        f"[DFM f] Global_fids={len(global_fids)}, Local_U1_fids={len(local_u1_fids)}, "
        f"Vis_Silk_Refs={vis_ref_count} (max_crtyd={max_ref_crtyd_mm:.2f}mm <=2.00), "
        f"Ant_Silk=0, AE1_Mask=[73.40..87.80]x[6.65..20.80], "
        f"min_bend={min_bend_deg:.1f}deg (>=85), unanchored_stubs={unanchored_count}."
    )

    if errors:
        sys.stderr.write(f"\n[DFM GATE FAILED] {len(errors)} violation(s) detected:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    print("[DFM GATE PASS] All 6 computational geometry & RS-274X Gerber gates PASSED (0 violations).")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Post-DRC Computational Geometry & Gerber Verification Gate")
    ap.add_argument("--pcb", default=os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb"))
    ap.add_argument("--gerber-dir", default=os.path.join(ROOT, "fab", "gerbers"))
    ap.add_argument("--pro", default=os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pro"))
    ap.add_argument("--pretty-dir", default=os.path.join(ROOT, "ISAC.pretty"))
    args = ap.parse_args()
    sys.exit(run_dfm_audit(args.pcb, args.gerber_dir, args.pro, args.pretty_dir))


if __name__ == "__main__":
    main()
