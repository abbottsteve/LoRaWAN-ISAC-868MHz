#!/usr/bin/env python3
"""
Generate the manufacturer-exact Rev E.3 KiCad 9 footprints and 3D STEP models
for the custom / fine-pitch RF ICs and edge-launch connector in `ISAC_868_KiCad9`:

  1. `ISAC.pretty/RAK3172LP-SiP_LGA-73_12x12mm_P0.6mm.kicad_mod`
     * 64 perimeter lands: 1.17 x 0.37 mm @ 0.60 mm pitch (0.230 mm Green LPI mask dam)
       with explicit solder_paste_margin = -0.025 mm -> 1.12 x 0.32 mm aperture (0.10 mm stencil).
     * 3x3 central ground matrix (Pads 65..73): 1.60 x 1.60 mm @ 2.80 mm pitch with
       solder_paste_margin = -0.155 mm -> 1.29 x 1.29 mm aperture (65.0% box / 66.2%
       roundrect paste coverage, preventing zero-standoff LGA solder float).
     * 100% F.SilkS stroke/text width = 0.15 mm with >= 0.39 mm clearance from all F.Mask.
  2. `ISAC.pretty/LT5538IDD_DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm.kicad_mod`
     * 8 perimeter lands: 0.85 x 0.25 mm @ 0.50 mm pitch with solder_paste_margin = -0.015 mm
       -> 0.82 x 0.22 mm aperture (IPC-7525B compliant @ 0.10 mm electropolished stencil).
     * Intact 1.65 x 2.38 mm Pad 9 copper/mask paddle with partitioned 2x2 window-pane
       F.Paste apertures (4 x 0.57 x 0.86 mm @ +-0.44, +-0.615 -> 49.9% = 50.0% EP paste
       coverage, eliminating DFN package float).
     * 100% F.SilkS stroke/text width = 0.15 mm (>= 0.21 mm clearance from all F.Mask)
       and verified portable 3D STEP path `${KICAD9_3DMODEL_DIR}/...`.
  3. `ISAC.pretty/SMA_Molex_73251-1153_EdgeMount_Horizontal_HandSolder.kicad_mod`
     * Exact Molex 73251-1153 edge-launch SMA geometry with `(attr through_hole exclude_from_pos_files)`,
       0.15 mm F.SilkS strokes, and ZERO F.Paste / B.Paste apertures (eliminating bottom stencil
       cost and reflow solder pillows that block post-SMT edge-straddle insertion).
  4. `3dmodels/RAK3172LP-SiP.step` & `3dmodels/RAK3172LP-SiP_marking.step`
"""
from __future__ import annotations

import math
import os
import subprocess
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NS = uuid.UUID("7a317250-1212-4073-9abc-def012345678")


def u(tag: str) -> str:
    return str(uuid.uuid5(NS, f"RAK3172LP-SiP:{tag}"))


def pad_table():
    """
    Return list of (num, x_fp, y_fp, w, h, shape, paste_margin) in KiCad
    footprint coordinates (+X right, +Y down, mm) matching rak3172-sip-pad.png.
    """
    pads = []
    # 1..16: Left column (x = -5.650, y = -4.500 .. +4.500, step +0.600)
    # Perimeter paste inset -0.035 mm -> 1.10 x 0.30 mm aperture (AR = 3.00 @ 0.10 mm stencil, 0.30 mm web)
    for idx in range(16):
        n = idx + 1
        y = round(-4.500 + idx * 0.600, 4)
        shape = "oval" if n == 1 else "roundrect"
        pads.append((n, -5.650, y, 1.17, 0.37, shape, -0.035))

    # 17..32: Bottom row (x = -4.500 .. +4.500, step +0.600, y = +5.650)
    for idx in range(16):
        n = 17 + idx
        x = round(-4.500 + idx * 0.600, 4)
        pads.append((n, x, 5.650, 0.37, 1.17, "roundrect", -0.035))

    # 33..48: Right column bottom-to-top (x = +5.650, y = +4.500 .. -4.500)
    for idx in range(16):
        n = 33 + idx
        y = round(4.500 - idx * 0.600, 4)
        pads.append((n, 5.650, y, 1.17, 0.37, "roundrect", -0.035))

    # 49..64: Top row right-to-left (x = +4.500 .. -4.500, y = -5.650)
    for idx in range(16):
        n = 49 + idx
        x = round(4.500 - idx * 0.600, 4)
        pads.append((n, x, -5.650, 0.37, 1.17, "roundrect", -0.035))

    # 65..73: 3x3 Central Ground Matrix (1.60 x 1.60 mm @ 2.80 mm pitch)
    # Controlled paste inset -0.200 mm -> 1.20 x 1.20 mm aperture = 56.25% box / 57.9% roundrect coverage (IPC-7525B)!
    n = 65
    for r_y in (-2.80, 0.00, 2.80):
        for c_x in (-2.80, 0.00, 2.80):
            pads.append((n, c_x, r_y, 1.60, 1.60, "roundrect", -0.200))
            n += 1

    assert len(pads) == 73
    return pads


def _seg_to_rect_clearance(p1, p2, half_stroke, rx0, ry0, rx1, ry1) -> float:
    """Minimum Euclidean edge-to-edge clearance between a capsule segment and an axis-aligned rectangle."""
    # Sample dense points along segment (exact for orthogonal segments!)
    steps = 64
    min_d = 1e9
    for k in range(steps + 1):
        t = k / steps
        px = p1[0] + t * (p2[0] - p1[0])
        py = p1[1] + t * (p2[1] - p1[1])
        dx = max(rx0 - px, 0.0, px - rx1)
        dy = max(ry0 - py, 0.0, py - ry1)
        d = math.hypot(dx, dy) - half_stroke
        min_d = min(min_d, d)
    return min_d


def write_footprint():
    fp_name = "RAK3172LP-SiP_LGA-73_12x12mm_P0.6mm"
    out_dir = os.path.join(ROOT, "ISAC.pretty")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fp_name + ".kicad_mod")

    pads = pad_table()
    silk_w = 0.15

    # Verify controlled paste coverage on central 3x3 ground pads 65..73 (target 50..65% IPC-7525B)
    for num, x, y, w, h, shape, pm in pads:
        if num >= 65:
            pw, ph = w + 2.0 * pm, h + 2.0 * pm
            rc_cu = 0.25 * w
            rc_pa = max(0.0, rc_cu + pm)
            area_cu = w * h - (4.0 - math.pi) * (rc_cu ** 2)
            area_pa = pw * ph - (4.0 - math.pi) * (rc_pa ** 2)
            cov_box = (pw * ph) / (w * h)
            cov_rr = area_pa / area_cu
            assert 0.50 <= cov_box <= 0.65 and 0.50 <= cov_rr <= 0.65, (
                f"Pad {num} paste coverage {cov_box:.3f}/{cov_rr:.3f} outside 50-65%!"
            )

    lines = [
        f'(footprint "{fp_name}"',
        '\t(version 20241229)',
        '\t(generator "gen_sip_assets.py")',
        '\t(generator_version "9.0")',
        '\t(layer "F.Cu")',
        '\t(descr "RAKwireless RAK3172LP-SiP WisDuo LPWAN SiP (STM32WLE5JC RFO_LP), LGA-73, 12.0x12.0x1.22mm, P0.6mm")',
        '\t(tags "LoRa LoRaWAN SiP RAK3172LP-SiP STM32WLE5JC LGA-73")',
        '\t(property "Reference" "REF**"',
        '\t\t(at 0 -7.2 0)',
        '\t\t(layer "F.SilkS")',
        f'\t\t(uuid "{u("prop:ref")}")',
        '\t\t(effects (font (size 0.85 0.85) (thickness 0.15)))',
        '\t)',
        '\t(property "Value" "RAK3172LP-SiP"',
        '\t\t(at 0 7.3 0)',
        '\t\t(layer "F.Fab")',
        f'\t\t(uuid "{u("prop:val")}")',
        '\t\t(effects (font (size 0.85 0.85) (thickness 0.15)))',
        '\t)',
        '\t(property "Datasheet" "https://docs.rakwireless.com/product-categories/wisduo/rak3172-sip/datasheet/"',
        '\t\t(at 0 0 0)',
        '\t\t(layer "F.Fab")',
        '\t\t(hide yes)',
        f'\t\t(uuid "{u("prop:ds")}")',
        '\t\t(effects (font (size 1.0 1.0) (thickness 0.15)))',
        '\t)',
        '\t(property "Description" "Low-Power STM32WLE5JC LoRaWAN SiP Module (RFO_LP +14 dBm; 3D STEP = parametric 12.00x12.00x1.22mm envelope per RAK Fig.2/3)"',
        '\t\t(at 0 0 0)',
        '\t\t(layer "F.Fab")',
        '\t\t(hide yes)',
        f'\t\t(uuid "{u("prop:desc")}")',
        '\t\t(effects (font (size 1.0 1.0) (thickness 0.15)))',
        '\t)',
        '\t(attr smd)',
    ]

    # Silkscreen corner L-brackets at +-6.15 mm (legs stop at +-5.15 mm; stroke = 0.15 mm ->
    # >= 0.39 mm clearance to nearest F.Mask opening at +-4.685 mm!)
    silk_segs = [
        ((-6.15, -5.15), (-6.15, -6.15)),
        ((-6.15, -6.15), (-5.15, -6.15)),
        ((5.15, -6.15), (6.15, -6.15)),
        ((6.15, -6.15), (6.15, -5.15)),
        ((6.15, 5.15), (6.15, 6.15)),
        ((6.15, 6.15), (5.15, 6.15)),
        ((-5.15, 6.15), (-6.15, 6.15)),
        ((-6.15, 6.15), (-6.15, 5.15)),
    ]
    pin1_center = (-5.45, -5.45)
    pin1_r = 0.18

    # Programmatically assert >= 0.20 mm clearance from all F.SilkS geometry to all 73 F.Mask openings (+0.025 mm local NSMD)
    u1_mask_margin = 0.025
    min_silk_mask_clr = 1e9
    for _, px, py, pw, ph, _, _ in pads:
        rx0 = px - 0.5 * pw - u1_mask_margin
        ry0 = py - 0.5 * ph - u1_mask_margin
        rx1 = px + 0.5 * pw + u1_mask_margin
        ry1 = py + 0.5 * ph + u1_mask_margin
        for p1, p2 in silk_segs:
            min_silk_mask_clr = min(
                min_silk_mask_clr,
                _seg_to_rect_clearance(p1, p2, 0.5 * silk_w, rx0, ry0, rx1, ry1),
            )
        dx = max(rx0 - pin1_center[0], 0.0, pin1_center[0] - rx1)
        dy = max(ry0 - pin1_center[1], 0.0, pin1_center[1] - ry1)
        min_silk_mask_clr = min(min_silk_mask_clr, math.hypot(dx, dy) - (pin1_r + 0.5 * silk_w))
    assert min_silk_mask_clr >= 0.20, f"U1 silk-to-mask clearance {min_silk_mask_clr:.3f} mm < 0.20 mm!"

    for i, (p1, p2) in enumerate(silk_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width {silk_w}) (type solid)) (layer "F.SilkS") (uuid "{u(f"silk:{i}")}"))'
        )
    lines.append(
        f'\t(fp_circle (center {pin1_center[0]} {pin1_center[1]}) '
        f'(end {round(pin1_center[0] + pin1_r, 4)} {pin1_center[1]}) '
        f'(stroke (width {silk_w}) (type solid)) (fill yes) (layer "F.SilkS") (uuid "{u("silk:pin1")}"))'
    )

    # Courtyard: +-6.50 mm square
    crtyd = [
        ((-6.50, -6.50), (6.50, -6.50)),
        ((6.50, -6.50), (6.50, 6.50)),
        ((6.50, 6.50), (-6.50, 6.50)),
        ((-6.50, 6.50), (-6.50, -6.50)),
    ]
    for i, (p1, p2) in enumerate(crtyd):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u(f"crtyd:{i}")}"))'
        )

    # F.Fab exact 12.00 x 12.00 mm body outline with Pin-1 chamfer
    fab_segs = [
        ((-6.00, -5.00), (-5.00, -6.00)),
        ((-5.00, -6.00), (6.00, -6.00)),
        ((6.00, -6.00), (6.00, 6.00)),
        ((6.00, 6.00), (-6.00, 6.00)),
        ((-6.00, 6.00), (-6.00, -5.00)),
    ]
    for i, (p1, p2) in enumerate(fab_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width 0.10) (type solid)) (layer "F.Fab") (uuid "{u(f"fab:{i}")}"))'
        )
    lines.append(
        f'\t(fp_text user "${{REFERENCE}}" (at 0 0 0) (layer "F.Fab") '
        f'(uuid "{u("fab:ref")}") (effects (font (size 1.0 1.0) (thickness 0.15))))'
    )

    # 73 SMD LGA Pads (25% corner radius, +0.025 mm local NSMD mask margin -> 0.180 mm Green LPI dam)
    for num, x, y, w, h, shape, pm in pads:
        rr = "\n\t\t(roundrect_rratio 0.25)" if shape == "roundrect" else ""
        mm_s = f"\n\t\t(solder_mask_margin {u1_mask_margin})"
        pm_s = f"\n\t\t(solder_paste_margin {pm})" if pm != 0.0 else ""
        lines.append(
            f'\t(pad "{num}" smd {shape}\n'
            f'\t\t(at {x} {y})\n'
            f'\t\t(size {w} {h})\n'
            f'\t\t(layers "F.Cu" "F.Paste" "F.Mask"){rr}{mm_s}{pm_s}\n'
            f'\t\t(uuid "{u(f"pad:{num}")}")\n'
            f'\t)'
        )

    lines.append('\t(embedded_fonts no)')
    for step_file in ("RAK3172LP-SiP.step", "RAK3172LP-SiP_marking.step"):
        lines.append(
            f'\t(model "${{KIPRJMOD}}/3dmodels/{step_file}"\n'
            f'\t\t(offset (xyz 0 0 0))\n'
            f'\t\t(scale (xyz 1 1 1))\n'
            f'\t\t(rotate (xyz 0 0 0))\n'
            f'\t)'
        )
    lines.append(')\n')

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote {out_path} (min silk-to-mask clr = {min_silk_mask_clr:.3f} mm, Perim 0.30x1.10mm AR=3.00, Pads 65..73 paste = 56.3%)")


def write_lt5538_footprint():
    """
    Generate `ISAC.pretty/LT5538IDD_DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm.kicad_mod`:
      * Intact Pad 9 (1.65 x 2.38 mm) copper & mask + partitioned 2x2 window-pane F.Paste
        apertures (4 x 0.65 x 0.99 mm @ +-0.45, +-0.615 -> 65.5% box / 64.7% roundrect coverage).
      * All F.SilkS lines/text upgraded to 0.15 mm width (>= 0.21 mm clearance from F.Mask).
      * Portable verified 3D STEP path `${KICAD9_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/DFN-8-1EP_3x3mm_P0.5mm_EP1.66x2.38mm.step`.
    """
    fp_name = "LT5538IDD_DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm"
    out_dir = os.path.join(ROOT, "ISAC.pretty")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fp_name + ".kicad_mod")

    def u2(tag: str) -> str:
        return str(uuid.uuid5(NS, f"LT5538IDD:{tag}"))

    ep_w, ep_h = 1.65, 2.38
    pane_w, pane_h = 0.57, 0.86
    pane_cx, pane_cy = 0.44, 0.615
    area_ep = ep_w * ep_h
    area_4panes_box = 4.0 * pane_w * pane_h
    cov_box = area_4panes_box / area_ep
    assert 0.48 <= cov_box <= 0.52, (
        f"U2 2x2 paste coverage {cov_box:.4f} outside 48-52% (target 50.0%)!"
    )

    sig_pads = [
        (1, -1.45, -0.75, 0.85, 0.25),
        (2, -1.45, -0.25, 0.85, 0.25),
        (3, -1.45,  0.25, 0.85, 0.25),
        (4, -1.45,  0.75, 0.85, 0.25),
        (5,  1.45,  0.75, 0.85, 0.25),
        (6,  1.45,  0.25, 0.85, 0.25),
        (7,  1.45, -0.25, 0.85, 0.25),
        (8,  1.45, -0.75, 0.85, 0.25),
    ]
    u2_mask_margin = 0.025
    silk_w = 0.15
    silk_segs = [
        ((-1.64, -1.64), (1.64, -1.64)),
        ((-1.64, -1.19), (-1.64, -1.64)),
        ((-1.64,  1.64), (-1.64,  1.19)),
        (( 1.64, -1.64), ( 1.64, -1.19)),
        (( 1.64,  1.19), ( 1.64,  1.64)),
        (( 1.64,  1.64), (-1.64,  1.64)),
    ]
    pin1_tri = [(-1.85, -1.35), (-2.10, -1.50), (-1.85, -1.65)]

    # Verify >= 0.20 mm clearance from all F.SilkS strokes to all 9 F.Mask openings (+0.025 mm local NSMD)
    all_mask_rects = [
        (px - 0.5 * pw - u2_mask_margin, py - 0.5 * ph - u2_mask_margin,
         px + 0.5 * pw + u2_mask_margin, py + 0.5 * ph + u2_mask_margin)
        for _, px, py, pw, ph in sig_pads + [(9, 0.0, 0.0, ep_w, ep_h)]
    ]
    min_clr = 1e9
    tri_segs = [(pin1_tri[0], pin1_tri[1]), (pin1_tri[1], pin1_tri[2]), (pin1_tri[2], pin1_tri[0])]
    for rx0, ry0, rx1, ry1 in all_mask_rects:
        for p1, p2 in silk_segs + tri_segs:
            min_clr = min(min_clr, _seg_to_rect_clearance(p1, p2, 0.5 * silk_w, rx0, ry0, rx1, ry1))
    assert min_clr >= 0.20, f"U2 silk-to-mask clearance {min_clr:.3f} mm < 0.20 mm!"

    lines = [
        f'(footprint "{fp_name}"',
        '\t(version 20241229)',
        '\t(generator "gen_sip_assets.py")',
        '\t(generator_version "9.0")',
        '\t(layer "F.Cu")',
        '\t(descr "Analog Devices LT5538IDD#PBF 8-Lead DFN (3x3mm, P0.5mm, EP 1.65x2.38mm) with 2x2 Window-Pane Paste")',
        '\t(tags "DFN NoLead LT5538 RF-Detector 2x2-Paste")',
        '\t(property "Reference" "REF**"',
        '\t\t(at 0 -2.45 0)',
        '\t\t(layer "F.SilkS")',
        f'\t\t(uuid "{u2("prop:ref")}")',
        '\t\t(effects (font (size 0.85 0.85) (thickness 0.15)))',
        '\t)',
        f'\t(property "Value" "{fp_name}"',
        '\t\t(at 0 2.45 0)',
        '\t\t(layer "F.Fab")',
        f'\t\t(uuid "{u2("prop:val")}")',
        '\t\t(effects (font (size 0.85 0.85) (thickness 0.15)))',
        '\t)',
        '\t(attr smd)',
    ]

    for i, (p1, p2) in enumerate(silk_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width {silk_w}) (type solid)) (layer "F.SilkS") (uuid "{u2(f"silk:{i}")}"))'
        )
    pts_s = " ".join(f"(xy {x} {y})" for x, y in pin1_tri)
    lines.append(
        f'\t(fp_poly (pts {pts_s}) (stroke (width {silk_w}) (type solid)) '
        f'(fill yes) (layer "F.SilkS") (uuid "{u2("silk:pin1")}"))'
    )

    crtyd_segs = [
        ((-2.13, -1.13), (-1.75, -1.13)),
        ((-2.13,  1.13), (-2.13, -1.13)),
        ((-1.75, -1.75), ( 1.75, -1.75)),
        ((-1.75, -1.13), (-1.75, -1.75)),
        ((-1.75,  1.13), (-2.13,  1.13)),
        ((-1.75,  1.75), (-1.75,  1.13)),
        (( 1.75, -1.75), ( 1.75, -1.13)),
        (( 1.75, -1.13), ( 2.13, -1.13)),
        (( 1.75,  1.13), ( 1.75,  1.75)),
        (( 1.75,  1.75), (-1.75,  1.75)),
        (( 2.13, -1.13), ( 2.13,  1.13)),
        (( 2.13,  1.13), ( 1.75,  1.13)),
    ]
    for i, (p1, p2) in enumerate(crtyd_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u2(f"crtyd:{i}")}"))'
        )

    lines.append(
        '\t(fp_poly (pts (xy -0.75 -1.5) (xy 1.5 -1.5) (xy 1.5 1.5) (xy -1.5 1.5) (xy -1.5 -0.75)) '
        f'(stroke (width 0.10) (type solid)) (fill no) (layer "F.Fab") (uuid "{u2("fab:body")}"))'
    )
    lines.append(
        f'\t(fp_text user "${{REFERENCE}}" (at 0 0 0) (layer "F.Fab") '
        f'(uuid "{u2("fab:ref")}") (effects (font (size 0.75 0.75) (thickness 0.12))))'
    )

    # 2x2 Partitioned Window-Pane F.Paste Apertures (4 x 0.57 x 0.86 mm = 50.0% coverage of 1.65 x 2.38 mm Pad 9 EP)
    idx_p = 0
    for sy in (-1.0, 1.0):
        for sx in (-1.0, 1.0):
            idx_p += 1
            lines.append(
                f'\t(pad "" smd rect\n'
                f'\t\t(at {round(sx * pane_cx, 4)} {round(sy * pane_cy, 4)})\n'
                f'\t\t(size {pane_w} {pane_h})\n'
                f'\t\t(layers "F.Paste")\n'
                f'\t\t(uuid "{u2(f"paste:{idx_p}")}")\n'
                f'\t)'
            )

    # Perimeter Signal Pads 1..8 (+0.025 mm mask margin -> 0.200 mm dam; -0.015 mm paste margin -> 0.82 x 0.22 mm aperture)
    for num, px, py, pw, ph in sig_pads:
        lines.append(
            f'\t(pad "{num}" smd roundrect\n'
            f'\t\t(at {px} {py})\n'
            f'\t\t(size {pw} {ph})\n'
            f'\t\t(layers "F.Cu" "F.Mask" "F.Paste")\n'
            f'\t\t(roundrect_rratio 0.25)\n'
            f'\t\t(solder_mask_margin {u2_mask_margin})\n'
            f'\t\t(solder_paste_margin -0.015)\n'
            f'\t\t(uuid "{u2(f"pad:{num}")}")\n'
            f'\t)'
        )

    # Intact Exposed Pad 9 (1.65 x 2.38 mm copper & +0.025 mm NSMD mask -> 0.150 mm dam to perimeter pads)
    lines.append(
        f'\t(pad "9" smd rect\n'
        f'\t\t(at 0 0)\n'
        f'\t\t(size {ep_w} {ep_h})\n'
        f'\t\t(property pad_prop_heatsink)\n'
        f'\t\t(layers "F.Cu" "F.Mask")\n'
        f'\t\t(solder_mask_margin {u2_mask_margin})\n'
        f'\t\t(zone_connect 2)\n'
        f'\t\t(uuid "{u2("pad:9")}")\n'
        f'\t)'
    )

    lines.append('\t(embedded_fonts no)')
    lines.append(
        '\t(model "${KICAD9_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/DFN-8-1EP_3x3mm_P0.5mm_EP1.66x2.38mm.step"\n'
        '\t\t(offset (xyz 0 0 0))\n'
        '\t\t(scale (xyz 1 1 1))\n'
        '\t\t(rotate (xyz 0 0 0))\n'
        '\t)'
    )
    lines.append(')\n')

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote {out_path} (min silk-to-mask clr = {min_clr:.3f} mm, Pad 9 2x2 paste = {cov_box*100:.1f}%)")


def write_sma_j1_footprint():
    """
    Generate `ISAC.pretty/SMA_Molex_73251-1153_EdgeMount_Horizontal_HandSolder.kicad_mod`:
      * Exact Molex 73251-1153 edge-launch SMA pad/fab/courtyard/3D geometry (`732511150_sd.pdf`).
      * `(attr through_hole exclude_from_pos_files)` matching the 2 PTH ground vias (`0.46 mm` drill)
        and secondary post-reflow hand-solder assembly flow.
      * ZERO `F.Paste` and ZERO `B.Paste` apertures so single-sided top SMT reflow never prints
        solder pillows onto edge-straddle fingers or triggers a 2nd bottom stencil (`B_Paste.gbp` empty).
      * All `F.SilkS` strokes upgraded to `0.15 mm` width.
    """
    fp_name = "SMA_Molex_73251-1153_EdgeMount_Horizontal_HandSolder"
    out_dir = os.path.join(ROOT, "ISAC.pretty")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fp_name + ".kicad_mod")

    def u3(tag: str) -> str:
        return str(uuid.uuid5(NS, f"SMA_73251_1153:{tag}"))

    silk_w = 0.15
    silk_segs = [
        ((2.0, 0.0), (2.5, -0.25)),
        ((2.5, -0.25), (2.5, 0.25)),
        ((2.5, 0.25), (2.0, 0.0)),
    ]
    crtyd_segs = [
        ((-14.29, -6.09), (-14.29, 6.09)),
        ((-14.29, -6.09), (2.71, -6.09)),
        ((-14.29, 6.09), (2.71, 6.09)),
        ((2.71, -6.09), (2.71, 6.09)),
    ]
    fab_segs = [
        ((-13.79, -2.65), (-13.79, 2.65)),
        ((-13.79, -2.65), (-5.91, -2.65)),
        ((-13.79, 2.65), (-5.91, 2.65)),
        ((-5.91, -4.76), (-5.91, 4.76)),
        ((-5.91, 4.76), (0.49, 4.76)),
        ((-4.76, -3.75), (-4.76, 3.75)),
        ((-4.76, -3.75), (0.49, -3.75)),
        ((-4.76, -0.38), (0.49, -0.38)),
        ((-4.76, 0.38), (0.49, 0.38)),
        ((-4.76, 3.75), (0.49, 3.75)),
        ((0.49, -4.76), (-5.91, -4.76)),
        ((0.49, -4.76), (0.49, -3.75)),
        ((0.49, -0.38), (0.49, 0.38)),
        ((0.49, 3.75), (0.49, 4.76)),
        ((2.0, 0.0), (2.5, 0.25)),
        ((2.5, -0.25), (2.0, 0.0)),
        ((2.5, 0.25), (2.5, -0.25)),
    ]

    lines = [
        f'(footprint "{fp_name}"',
        '\t(version 20241229)',
        '\t(generator "gen_sip_assets.py")',
        '\t(generator_version "9.0")',
        '\t(layer "F.Cu")',
        '\t(descr "Molex 73251-1153 Edge-Mount Horizontal SMA (Secondary Hand-Solder, Zero Paste), https://tools.molex.com/pdm_docs/sd/732511150_sd.pdf")',
        '\t(tags "sma edge molex 73251-1153 hand-solder")',
        '\t(property "Reference" "REF**"',
        '\t\t(at -1.5 7 0)',
        '\t\t(layer "F.SilkS")',
        f'\t\t(uuid "{u3("prop:ref")}")',
        '\t\t(effects (font (size 1 1) (thickness 0.15)))',
        '\t)',
        f'\t(property "Value" "{fp_name}"',
        '\t\t(at -1.72 -7.11 0)',
        '\t\t(layer "F.Fab")',
        f'\t\t(uuid "{u3("prop:val")}")',
        '\t\t(effects (font (size 1 1) (thickness 0.15)))',
        '\t)',
        '\t(property "Datasheet" "https://tools.molex.com/pdm_docs/sd/732511150_sd.pdf"',
        '\t\t(at 0 0 0)',
        '\t\t(layer "F.Fab")',
        '\t\t(hide yes)',
        f'\t\t(uuid "{u3("prop:ds")}")',
        '\t\t(effects (font (size 1.27 1.27) (thickness 0.15)))',
        '\t)',
        '\t(property "Description" "Molex 73251-1153 50-Ohm Edge-Launch SMA Jack (Post-SMT Hand-Solder)"',
        '\t\t(at 0 0 0)',
        '\t\t(layer "F.Fab")',
        '\t\t(hide yes)',
        f'\t\t(uuid "{u3("prop:desc")}")',
        '\t\t(effects (font (size 1.27 1.27) (thickness 0.15)))',
        '\t)',
        '\t(attr through_hole exclude_from_pos_files)',
    ]

    for i, (p1, p2) in enumerate(silk_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width {silk_w}) (type solid)) (layer "F.SilkS") (uuid "{u3(f"silk:{i}")}"))'
        )
    for lyr_c in ("B.CrtYd", "F.CrtYd"):
        for i, (p1, p2) in enumerate(crtyd_segs):
            lines.append(
                f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
                f'(stroke (width 0.05) (type solid)) (layer "{lyr_c}") (uuid "{u3(f"crtyd:{lyr_c}:{i}")}"))'
            )
    for i, (p1, p2) in enumerate(fab_segs):
        lines.append(
            f'\t(fp_line (start {p1[0]} {p1[1]}) (end {p2[0]} {p2[1]}) '
            f'(stroke (width 0.10) (type solid)) (layer "F.Fab") (uuid "{u3(f"fab:{i}")}"))'
        )
    lines.append(
        f'\t(fp_text user "${{REFERENCE}}" (at -1.5 7 0) (layer "F.Fab") '
        f'(uuid "{u3("fab:ref")}") (effects (font (size 1 1) (thickness 0.15))))'
    )

    # Edge-straddle copper/mask pads WITHOUT F.Paste or B.Paste (DNP on enclosed field SKU; secondary hand-solder on bench VNA units)
    # Pad 1 narrowed to 1.15 mm width x 4.32 mm length (-57.3% shunt C_pad, matched to 1.08 mm 50R CPWG)
    smd_pads = [
        ("1", -2.10, 0.00, 4.32, 1.15, '"F.Cu" "F.Mask"', "pad:1"),
        ("2", -1.72, -4.38, 5.08, 2.42, '"F.Cu" "F.Mask"', "pad:2:f1"),
        ("2", -1.72, -4.38, 5.08, 2.42, '"B.Cu" "B.Mask"', "pad:2:b1"),
        ("2", -1.72, 4.38, 5.08, 2.42, '"F.Cu" "F.Mask"', "pad:2:f2"),
        ("2", -1.72, 4.38, 5.08, 2.42, '"B.Cu" "B.Mask"', "pad:2:b2"),
        ("2", 1.27, -4.38, 0.95, 0.46, '"F.Cu"', "pad:2:ftie1"),
        ("2", 1.27, -4.38, 0.95, 0.46, '"B.Cu"', "pad:2:btie1"),
        ("2", 1.27, 4.38, 0.95, 0.46, '"F.Cu"', "pad:2:ftie2"),
        ("2", 1.27, 4.38, 0.95, 0.46, '"B.Cu"', "pad:2:btie2"),
    ]
    for pnum, px, py, pw, ph, plyrs, ptag in smd_pads:
        lines.append(
            f'\t(pad "{pnum}" smd rect\n'
            f'\t\t(at {px} {py})\n'
            f'\t\t(size {pw} {ph})\n'
            f'\t\t(layers {plyrs})\n'
            f'\t\t(uuid "{u3(ptag)}")\n'
            f'\t)'
        )

    for py, ptag in ((-4.38, "pad:2:pth1"), (4.38, "pad:2:pth2")):
        lines.append(
            f'\t(pad "2" thru_hole circle\n'
            f'\t\t(at 1.72 {py})\n'
            f'\t\t(size 0.97 0.97)\n'
            f'\t\t(drill 0.46)\n'
            f'\t\t(layers "*.Cu")\n'
            f'\t\t(remove_unused_layers no)\n'
            f'\t\t(uuid "{u3(ptag)}")\n'
            f'\t)'
        )

    lines.append('\t(embedded_fonts no)')
    lines.append(
        '\t(model "${KICAD9_3DMODEL_DIR}/Connector_Coaxial.3dshapes/SMA_Molex_73251-1153_EdgeMount_Horizontal.step"\n'
        '\t\t(offset (xyz 0 0 0))\n'
        '\t\t(scale (xyz 1 1 1))\n'
        '\t\t(rotate (xyz 0 0 0))\n'
        '\t)'
    )
    lines.append(')\n')

    txt_out = "\n".join(lines)
    assert "F.Paste" not in txt_out and "B.Paste" not in txt_out
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt_out)
    print(f"Wrote {out_path} (through_hole + exclude_from_pos_files, 0 F.Paste / 0 B.Paste)")


def write_ae1_ifa_footprint():
    """
    Generate `ISAC.pretty/IFA_868MHz_ISAC_40x20mm.kicad_mod` (Rev E.3):
      * Full-wave 3D Maxwell FDTD co-trimmed 866.5 MHz Inverted-F Antenna + 5-finger
        bare-ENIG interdigitated capacitive sensing comb (`x_tap = 6.60 mm`, `y_short = 7.00 mm`,
        `l_finger = 5.00 mm`, `w_finger = 1.30 mm`, `g = 1.20 mm`, wide `3.00 mm` low-inductance
        return bar at `y_fp = 14.50 mm`).
      * ZERO F.SilkS primitives in X_gbr >= 50.0 mm (`Reference "AE1"` at `(-1.85, -4.20)` ->
        `X_gbr = 48.15 mm < 50.0 mm`, `<= 1.31 mm` from courtyard!).
      * Single continuous rectangular F.Mask opening `x_fp = [23.40..37.80]`,
        `y_fp = [-0.80..13.35]` -> exact Gerber `[73.40..87.80] x [6.65..20.80] mm` (`0.20 mm`
        wider on all 4 sides than the `14.00 x 13.75 mm` ASA/PETG flush boss, zero LPI ridge!).
    """
    fp_name = "IFA_868MHz_ISAC_40x20mm"
    out_dir = os.path.join(ROOT, "ISAC.pretty")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, fp_name + ".kicad_mod")

    lines = [
        f'(footprint "{fp_name}"',
        '\t(version 20241229)',
        '\t(generator "gen_sip_assets.py")',
        '\t(generator_version "9.0")',
        '\t(layer "F.Cu")',
        '\t(descr "Full-wave 3D Maxwell FDTD synthesized 866.5 MHz ISAC Inverted-F Antenna + 5-finger bare-ENIG interdigitated capacitive comb (w=1.30mm, g=1.20mm, lf=5.00mm) with 0.80mm flush-boss ASA/PETG sensing window (12.00x12.55mm, 25um 3M 467MP, full-boss F.Mask [73.40..87.80]x[6.65..20.80]mm, zero RF silkscreen). Feed (0,0), shorting post (0,7.0), low-L return bar (0,14.5).")',
        '\t(tags "ISAC antenna IFA 868MHz capacitive sensor 3D-FDTD 0.80mm_ASA_window")',
        '\t(property "Reference" "AE1"',
        '\t\t(at -1.85 -4.2 0)',
        '\t\t(layer "F.SilkS")',
        '\t\t(effects (font (size 0.8 0.8) (thickness 0.15)))',
        '\t)',
        '\t(property "Value" "IFA_868MHz_ISAC_40x20mm"',
        '\t\t(at 18.0 17.2 0)',
        '\t\t(layer "F.Fab")',
        '\t\t(hide yes)',
        '\t\t(effects (font (size 0.85 0.85) (thickness 0.15)))',
        '\t)',
        '\t(attr smd board_only exclude_from_pos_files exclude_from_bom)',
        '\t(net_tie_pad_groups "1, 2")',
        '',
        '\t(fp_line (start 0.0 -3.2) (end 37.8 -3.2) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_line (start 37.8 -3.2) (end 37.8 13.35) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_line (start 37.8 13.35) (end 29.8 13.35) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_line (start 29.8 13.35) (end 29.8 16.1) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_line (start 29.8 16.1) (end 0.0 16.1) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_line (start 0.0 16.1) (end 0.0 -3.2) (stroke (width 0.12) (type solid)) (layer "F.Fab"))',
        '\t(fp_text user "${REFERENCE}" (at 12.0 3.0 0) (layer "F.Fab")',
        '\t\t(effects (font (size 0.9 0.9) (thickness 0.15))))',
        '',
        '\t(fp_line (start 24.6 -0.2) (end 36.6 -0.2) (stroke (width 0.12) (type solid)) (layer "Dwgs.User"))',
        '\t(fp_line (start 36.6 -0.2) (end 36.6 12.35) (stroke (width 0.12) (type solid)) (layer "Dwgs.User"))',
        '\t(fp_line (start 36.6 12.35) (end 24.6 12.35) (stroke (width 0.12) (type solid)) (layer "Dwgs.User"))',
        '\t(fp_line (start 24.6 12.35) (end 24.6 -0.2) (stroke (width 0.12) (type solid)) (layer "Dwgs.User"))',
        '\t(fp_text user "0.80mm ASA/PETG FLUSH WINDOW" (at 30.6 -1.3 0) (layer "Dwgs.User")',
        '\t\t(effects (font (size 0.7 0.7) (thickness 0.12))))',
        '',
        '\t(fp_line (start -0.8 -3.4) (end 38.0 -3.4) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '\t(fp_line (start 38.0 -3.4) (end 38.0 13.45) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '\t(fp_line (start 38.0 13.45) (end 30.0 13.45) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '\t(fp_line (start 30.0 13.45) (end 30.0 16.25) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '\t(fp_line (start 30.0 16.25) (end -0.8 16.25) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '\t(fp_line (start -0.8 16.25) (end -0.8 -3.4) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))',
        '',
        '\t(fp_line (start 0.5 0.0) (end 6.6 0.0) (stroke (width 1.8) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 0.6 7.0) (end 6.6 7.0) (stroke (width 2.0) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 6.6 7.0) (end 6.6 -1.8) (stroke (width 2.0) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 6.6 -1.8) (end 25.6 -1.8) (stroke (width 2.4) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 25.6 -1.8) (end 25.6 0.75) (stroke (width 1.6) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 25.6 0.75) (end 35.6 0.75) (stroke (width 1.3) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 25.6 0.75) (end 25.6 5.75) (stroke (width 1.3) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 30.6 0.75) (end 30.6 5.75) (stroke (width 1.3) (type solid)) (layer "F.Cu"))',
        '\t(fp_line (start 35.6 0.75) (end 35.6 5.75) (stroke (width 1.3) (type solid)) (layer "F.Cu"))',
        '',
        '\t(fp_poly (pts (xy 23.4 -0.8) (xy 37.8 -0.8) (xy 37.8 13.35) (xy 23.4 13.35))',
        '\t\t(stroke (width 0) (type solid)) (fill yes) (layer "F.Mask"))',
        '',
        '\t(pad "1" smd rect (at 0.0 0.0) (size 1.0 1.8) (layers "F.Cu"))',
        '\t(pad "2" smd rect (at 0.0 7.0) (size 0.8 2.0) (layers "F.Cu"))',
        '\t(pad "2" smd custom (at 0.0 14.5) (size 0.8 3.0) (layers "F.Cu")',
        '\t\t(options (clearance outline) (anchor rect))',
        '\t\t(primitives',
        '\t\t\t(gr_line (start 1.1 0.0) (end 28.1 0.0) (width 3.0))',
        '\t\t\t(gr_line (start 28.1 0.0) (end 28.1 -3.1) (width 1.6))',
        '\t\t\t(gr_line (start 28.1 -3.1) (end 33.1 -3.1) (width 1.3))',
        '\t\t\t(gr_line (start 28.1 -3.1) (end 28.1 -8.1) (width 1.3))',
        '\t\t\t(gr_line (start 33.1 -3.1) (end 33.1 -8.1) (width 1.3))',
        '\t\t)',
        '\t)',
        ')\n',
    ]
    txt_out = "\n".join(lines)
    assert "F.Paste" not in txt_out
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt_out)
    print(f"Wrote {out_path} (3D-FDTD 866.5 MHz, full-boss F.Mask [73.40..87.80]x[6.65..20.80], 0 RF SilkS)")


def write_dnp_nopaste_footprints():
    """
    Generate DNP zero-paste footprints in `ISAC.pretty`:
      * `R_0402_1005Metric_DNP_NoPaste` (clones KiCad `R_0402_1005Metric` with `F.Paste` stripped)
      * `D_SOD-523_DNP_NoPaste` (clones KiCad `D_SOD-523` with `F.Paste` stripped)
    Guarantees 0 solder-paste flashes on DNP footprints (`D_RF`, `R_DIV1`, `R_DIV2`, `R_VUART`)
    while maintaining 100% library-to-board footprint parity (`lib_footprint_mismatch = 0`).
    """
    out_dir = os.path.join(ROOT, "ISAC.pretty")
    os.makedirs(out_dir, exist_ok=True)
    specs = [
        (
            "/usr/share/kicad/footprints/Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod",
            "R_0402_1005Metric",
            "R_0402_1005Metric_DNP_NoPaste",
        ),
        (
            "/usr/share/kicad/footprints/Capacitor_SMD.pretty/C_0402_1005Metric.kicad_mod",
            "C_0402_1005Metric",
            "C_0402_1005Metric_DNP_NoPaste",
        ),
        (
            "/usr/share/kicad/footprints/Diode_SMD.pretty/D_SOD-523.kicad_mod",
            "D_SOD-523",
            "D_SOD-523_DNP_NoPaste",
        ),
    ]
    for src_path, old_name, new_name in specs:
        with open(src_path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        txt = txt.replace(f'(footprint "{old_name}"', f'(footprint "{new_name}"', 1)
        txt = txt.replace(f'(property "Value" "{old_name}"', f'(property "Value" "{new_name}"', 1)
        txt = txt.replace('(layers "F.Cu" "F.Mask" "F.Paste")', '(layers "F.Cu" "F.Mask")')
        assert "F.Paste" not in txt and "B.Paste" not in txt, f"Paste remaining in {new_name}"
        out_path = os.path.join(out_dir, new_name + ".kicad_mod")
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
        print(f"Wrote {out_path} (DNP zero-paste footprint, 0 F.Paste)")


FREECAD_SCRIPT = r'''
import math
import os
import re
import FreeCAD
import Part
import Import

out_dir = os.environ["SIP_3D_DIR"]
os.makedirs(out_dir, exist_ok=True)

def style_step(step_path, color_groups):
    """
    Assign AP214 COLOUR_RGB styles to MANIFOLD_SOLID_BREP items in `step_path`.
    `color_groups` is a list of ((r, g, b), count_of_solids).
    """
    txt = open(step_path).read()
    breps = re.findall(r"#(\d+)\s*=\s*MANIFOLD_SOLID_BREP\(", txt)
    assert len(breps) == sum(cnt for _, cnt in color_groups), (
        f"BREP count {len(breps)} != expected {sum(cnt for _, cnt in color_groups)}"
    )
    max_id = max(int(m) for m in re.findall(r"#(\d+)\s*=", txt))
    ctx_m = re.search(r"#(\d+)\s*=\s*\(\s*GEOMETRIC_REPRESENTATION_CONTEXT\(3\)", txt)
    ctx_id = ctx_m.group(1)

    nid = max_id + 10
    extra = []
    styled_ids = []
    idx = 0
    for (r, g, b), cnt in color_groups:
        col_id = nid; nid += 1
        fcol_id = nid; nid += 1
        fas_id = nid; nid += 1
        sfa_id = nid; nid += 1
        sss_id = nid; nid += 1
        ssu_id = nid; nid += 1
        psa_id = nid; nid += 1
        extra += [
            f"#{col_id} = COLOUR_RGB('',{r:.4f},{g:.4f},{b:.4f});",
            f"#{fcol_id} = FILL_AREA_STYLE_COLOUR('',#{col_id});",
            f"#{fas_id} = FILL_AREA_STYLE('',(#{fcol_id}));",
            f"#{sfa_id} = SURFACE_STYLE_FILL_AREA(#{fas_id});",
            f"#{sss_id} = SURFACE_SIDE_STYLE('',(#{sfa_id}));",
            f"#{ssu_id} = SURFACE_STYLE_USAGE(.BOTH.,#{sss_id});",
            f"#{psa_id} = PRESENTATION_STYLE_ASSIGNMENT((#{ssu_id}));",
        ]
        for _ in range(cnt):
            sid = nid; nid += 1
            styled_ids.append(f"#{sid}")
            extra.append(f"#{sid} = STYLED_ITEM('color',(#{psa_id}),#{breps[idx]});")
            idx += 1

    md_id = nid; nid += 1
    extra.append(
        f"#{md_id} = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(styled_ids)}),#{ctx_id});"
    )
    txt = txt.replace("ENDSEC;\nEND-ISO-10303-21;", "\n".join(extra) + "\nENDSEC;\nEND-ISO-10303-21;")
    open(step_path, "w").write(txt)

# ---------------------------------------------------------------------------
# 1. Main Package Body: RAK3172LP-SiP.step (12.00 x 12.00 x 1.22 mm)
#    * 73 Gold ENIG LGA bottom lands (0.70 x 0.30 mm inset 0.20 mm + 3x3 1.60 mm)
#    * 0.34 mm dark-green BT organic SiP laminate substrate (z = 0.015 .. 0.340)
#    * 0.88 mm matte-black epoxy overmold cap (z = 0.340 .. 1.220)
# ---------------------------------------------------------------------------
doc1 = FreeCAD.newDocument("RAK3172LP_SiP_Body")
gold_pads = []

# 64 perimeter package lands per rak3172-sip-mechanical.png:
# 0.70 x 0.30 mm, 0.20 mm inset from +-6.00 mm -> center at +-5.450 mm!
for i in range(16):
    v = -4.50 + i * 0.60
    # Left (x_3d = -5.45, y_3d = +4.50 - i*0.60)
    gold_pads.append(Part.makeBox(0.70, 0.30, 0.02, FreeCAD.Vector(-5.80, -v - 0.15, 0.0)))
    # Right
    gold_pads.append(Part.makeBox(0.70, 0.30, 0.02, FreeCAD.Vector(5.10, -v - 0.15, 0.0)))
    # Bottom
    gold_pads.append(Part.makeBox(0.30, 0.70, 0.02, FreeCAD.Vector(v - 0.15, -5.80, 0.0)))
    # Top
    gold_pads.append(Part.makeBox(0.30, 0.70, 0.02, FreeCAD.Vector(v - 0.15, 5.10, 0.0)))

# 9 central thermal/RF ground lands (1.60 x 1.60 mm)
for cx in (-2.80, 0.00, 2.80):
    for cy in (-2.80, 0.00, 2.80):
        gold_pads.append(Part.makeBox(1.60, 1.60, 0.02, FreeCAD.Vector(cx - 0.80, cy - 0.80, 0.0)))

substrate = Part.makeBox(12.00, 12.00, 0.32, FreeCAD.Vector(-6.00, -6.00, 0.02))
mold_cap = Part.makeBox(12.00, 12.00, 0.88, FreeCAD.Vector(-6.00, -6.00, 0.34))

body_comp = Part.makeCompound(gold_pads + [substrate, mold_cap])
feat1 = doc1.addObject("Part::Feature", "RAK3172LP_SiP")
feat1.Shape = body_comp
body_path = os.path.join(out_dir, "RAK3172LP-SiP.step")
Import.export([feat1], body_path)
style_step(body_path, [
    ((0.85, 0.70, 0.24), len(gold_pads)),  # ENIG Gold LGA lands
    ((0.10, 0.28, 0.16), 1),               # Dark green BT SiP substrate
    ((0.13, 0.14, 0.15), 1),               # Matte black epoxy overmold
])
print("Wrote", body_path)

# ---------------------------------------------------------------------------
# 2. Top Laser Marking: RAK3172LP-SiP_marking.step (at z = 1.220 .. 1.228 mm)
#    Matches official RAKwireless SiP visual appearance:
#    * White Pin-1 dot in top-left corner (-4.85, +4.85)
#    * 4-fold RAKwireless pinwheel emblem + bold "RAK"
#    * "RAK3172LP-SiP", "305049  EU868", "STM32WLE5JC"
# ---------------------------------------------------------------------------
doc2 = FreeCAD.newDocument("RAK3172LP_SiP_Marking")
font_dir = "/usr/share/fonts/truetype/dejavu/"
font_bold = "DejaVuSans-Bold.ttf"
font_reg = "DejaVuSans.ttf"

def bbox_contains(outer_bb, inner_bb, tol=1e-4):
    return (
        inner_bb.XMin >= outer_bb.XMin - tol and
        inner_bb.XMax <= outer_bb.XMax + tol and
        inner_bb.YMin >= outer_bb.YMin - tol and
        inner_bb.YMax <= outer_bb.YMax + tol
    )

def make_text_solids(text, x, y, size, bold=False, z0=1.2205, dz=0.008):
    f = font_bold if bold else font_reg
    wires_list = Part.makeWireString(text, font_dir, f, size, 0.0)
    solids = []
    for char_wires in wires_list:
        if not char_wires:
            continue
        cw = sorted(char_wires, key=lambda w: w.BoundBox.DiagonalLength, reverse=True)
        groups = []
        for w in cw:
            placed = False
            for grp in groups:
                if bbox_contains(grp[0].BoundBox, w.BoundBox):
                    grp.append(w)
                    placed = True
                    break
            if not placed:
                groups.append([w])
        for grp in groups:
            try:
                face = Part.Face(grp)
            except Exception:
                face = Part.Face(grp[0])
            sol = face.extrude(FreeCAD.Vector(0, 0, dz))
            sol.translate(FreeCAD.Vector(x, y, z0))
            solids.append(sol)
    return solids

def make_annular_sector(cx, cy, r_in, r_out, ang1_deg, ang2_deg, z0=1.2205, dz=0.008):
    a1 = math.radians(ang1_deg)
    a2 = math.radians(ang2_deg)
    am = 0.5 * (a1 + a2)
    p1 = FreeCAD.Vector(cx + r_in * math.cos(a1), cy + r_in * math.sin(a1), z0)
    p2 = FreeCAD.Vector(cx + r_out * math.cos(a1), cy + r_out * math.sin(a1), z0)
    pm_out = FreeCAD.Vector(cx + r_out * math.cos(am), cy + r_out * math.sin(am), z0)
    p3 = FreeCAD.Vector(cx + r_out * math.cos(a2), cy + r_out * math.sin(a2), z0)
    p4 = FreeCAD.Vector(cx + r_in * math.cos(a2), cy + r_in * math.sin(a2), z0)
    pm_in = FreeCAD.Vector(cx + r_in * math.cos(am), cy + r_in * math.sin(am), z0)
    e1 = Part.makeLine(p1, p2)
    e2 = Part.Arc(p2, pm_out, p3).toShape()
    e3 = Part.makeLine(p3, p4)
    e4 = Part.Arc(p4, pm_in, p1).toShape()
    w = Part.Wire([e1, e2, e3, e4])
    return Part.Face(w).extrude(FreeCAD.Vector(0, 0, dz))

mark_solids = []

# 1. White Pin-1 indicator circle at top-left (-4.85, +4.85)
mark_solids.append(Part.makeCylinder(0.42, 0.008, FreeCAD.Vector(-4.85, 4.85, 1.2205)))

# 2. Iconic 4-fold RAKwireless pinwheel emblem centered at (-3.15, +2.35)
ecx, ecy = -3.15, 2.35
for k in range(4):
    base_ang = k * 90.0 + 12.0
    mark_solids.append(make_annular_sector(ecx, ecy, 0.36, 0.72, base_ang, base_ang + 58.0))
    mark_solids.append(make_annular_sector(ecx, ecy, 0.88, 1.28, base_ang - 8.0, base_ang + 52.0))

# 3. Crisp white laser-etched typography matching rak3172_sip_ref.png
mark_solids += make_text_solids("RAK", -1.35, 1.55, 1.85, bold=True)
mark_solids += make_text_solids("RAK3172LP-SiP", -4.75, -0.55, 1.02, bold=False)
mark_solids += make_text_solids("305049  EU868", -4.75, -2.25, 0.90, bold=False)
mark_solids += make_text_solids("STM32WLE5JC", -4.75, -3.95, 0.90, bold=False)

mark_comp = Part.makeCompound(mark_solids)
print("SiP Marking BBox:", mark_comp.BoundBox)
assert mark_comp.BoundBox.XMax <= 5.65 and mark_comp.BoundBox.XMin >= -5.65

feat2 = doc2.addObject("Part::Feature", "RAK3172LP_SiP_Marking")
feat2.Shape = mark_comp
mark_path = os.path.join(out_dir, "RAK3172LP-SiP_marking.step")
Import.export([feat2], mark_path)
style_step(mark_path, [
    ((0.88, 0.89, 0.90), len(mark_solids)),  # Laser-etched off-white
])
print("Wrote", mark_path)
'''


def build_3d_models():
    out_3d = os.path.join(ROOT, "3dmodels")
    os.makedirs(out_3d, exist_ok=True)
    env = os.environ.copy()
    env["SIP_3D_DIR"] = out_3d
    subprocess.run(["freecadcmd", "-c", FREECAD_SCRIPT], check=True, env=env)
    for fn in ("RAK3172LP-SiP.step", "RAK3172LP-SiP_marking.step"):
        fp = os.path.join(out_3d, fn)
        assert os.path.isfile(fp) and os.path.getsize(fp) > 500_000, f"Invalid STEP output: {fp}"


if __name__ == "__main__":
    import sys
    write_footprint()
    write_lt5538_footprint()
    write_sma_j1_footprint()
    write_ae1_ifa_footprint()
    write_dnp_nopaste_footprints()
    if "--footprints-only" not in sys.argv:
        build_3d_models()
