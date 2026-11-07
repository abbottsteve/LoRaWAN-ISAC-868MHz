#!/usr/bin/env python3
"""
Negative Mutation Verification Suite — 8 Seeded Manufacturing & Firmware Defects
================================================================================
Copies clean `Rev E.1` artefacts into isolated temporary `/tmp` sandboxes, injects
each of the **8 critical manufacturing / CAD / firmware regressions** one at a time,
executes the production verification gates (`check_dfm.py` / `check_bom_cpl.py`),
and asserts that **8/8 seeded defects are deterministically caught (`exit != 0`
with exact root-cause diagnostic match)** without touching workspace files:

  1. Open via-in-pad inside `U1` Pad 69 (`LGA-73` central ground pad)
  2. Untented via on `F.Mask` + `0.05 mm` solder-mask dam sliver (`< 0.10 mm`)
  3. `.gbrjob` `"Finish": "None"` (missing mandatory ENIG specification)
  4. `0.15 mm` narrow `F_Paste.gtp` stencil aperture (`AR = 0.531 < 0.66`)
  5. `B.Cu` clearance slot carved directly beneath `/DET_IN` (`AUD20-01` regression)
  6. `DNP` calibration diverter `R_DIV1` leaked into Turnkey `CPL` CSV
  7. `CPL` `PosY` shifted by `+80.0 mm` sheet offset (Gerber-vs-CPL origin mismatch)
  8. Firmware `isac_board_pins.h` `DET_ADC` pin mutated from `PA15` to `PA10`
"""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pcbnew

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = "/usr/bin/python3"
CHECK_DFM = os.path.join(ROOT, "tools", "check_dfm.py")
CHECK_BOM_CPL = os.path.join(ROOT, "tools", "check_bom_cpl.py")

PCB_SRC = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")
PRO_SRC = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pro")
DRU_SRC = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_dru")
GBR_SRC = os.path.join(ROOT, "fab", "gerbers")
ZIP_SRC = os.path.join(ROOT, "fab", "ISAC_868_RevE5_PCBWay_Turnkey.zip")
FW_PINS_SRC = os.path.join(ROOT, "firmware", "include", "isac_board_pins.h")


def _stage_pcb_sandbox(tmpdir):
    """Stage isolated PCB + project + Gerbers + symlinks to 3dmodels & libraries in tmpdir."""
    pcb_dst = os.path.join(tmpdir, "ISAC_868_KiCad9.kicad_pcb")
    pro_dst = os.path.join(tmpdir, "ISAC_868_KiCad9.kicad_pro")
    dru_dst = os.path.join(tmpdir, "ISAC_868_KiCad9.kicad_dru")
    gbr_dst = os.path.join(tmpdir, "gerbers")

    shutil.copy2(PCB_SRC, pcb_dst)
    shutil.copy2(PRO_SRC, pro_dst)
    shutil.copy2(DRU_SRC, dru_dst)
    shutil.copytree(GBR_SRC, gbr_dst)

    for sym_item in ("ISAC.pretty", "3dmodels", "fp-lib-table", "sym-lib-table", "ISAC.kicad_sym"):
        src = os.path.join(ROOT, sym_item)
        dst = os.path.join(tmpdir, sym_item)
        if os.path.exists(src) and not os.path.exists(dst):
            os.symlink(src, dst)

    return pcb_dst, pro_dst, gbr_dst


def _rebuild_zip_with_mutation(src_zip, dst_zip, mutator_fn):
    """
    Copy `src_zip` to `dst_zip`, applying `mutator_fn(name, bytes) -> bytes`, and
    recomputing `SHA256SUMS.txt` so the archive checksum passes and the downstream
    semantic gate itself must catch the seeded defect.
    """
    entries = {}
    with zipfile.ZipFile(src_zip, "r") as zin:
        for name in zin.namelist():
            if name.endswith("/") or name == "SHA256SUMS.txt":
                continue
            entries[name] = mutator_fn(name, zin.read(name))

    sha_lines = []
    for name in sorted(entries.keys()):
        digest = hashlib.sha256(entries[name]).hexdigest()
        sha_lines.append(f"{digest}  {name}")
    sha_bytes = ("\n".join(sha_lines) + "\n").encode("utf-8")

    with zipfile.ZipFile(dst_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name in sorted(entries.keys()):
            zout.writestr(name, entries[name])
        zout.writestr("SHA256SUMS.txt", sha_bytes)


def _run_gate(cmd):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, combined


# ==============================================================================
# 8 Seeded Defect Scenarios
# ==============================================================================
def defect_1_via_in_pad_u1_pad69(tmpdir):
    pcb_dst, pro_dst, gbr_dst = _stage_pcb_sandbox(tmpdir)
    board = pcbnew.LoadBoard(pcb_dst)
    u1 = board.FindFootprintByReference("U1")
    pad69 = u1.FindPadByNumber("69")

    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pad69.GetPosition())
    v.SetWidth(pcbnew.FromMM(0.60))
    v.SetDrill(pcbnew.FromMM(0.30))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(pad69.GetNet())
    v.SetFrontTentingMode(pcbnew.TENTING_MODE_NOT_TENTED)
    v.SetBackTentingMode(pcbnew.TENTING_MODE_NOT_TENTED)
    board.Add(v)
    pcbnew.SaveBoard(pcb_dst, board)

    rc, out = _run_gate([
        PY, CHECK_DFM, "--pcb", pcb_dst, "--gerber-dir", gbr_dst, "--pro", pro_dst,
    ])
    return rc, out, ["[GATE a]", "U1.Pad69"]


def defect_2_untented_via_and_0p05mm_mask_sliver(tmpdir):
    pcb_dst, pro_dst, gbr_dst = _stage_pcb_sandbox(tmpdir)
    board = pcbnew.LoadBoard(pcb_dst)
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    v0 = vias[0]
    v0.SetFrontTentingMode(pcbnew.TENTING_MODE_NOT_TENTED)
    pcbnew.SaveBoard(pcb_dst, board)

    # Re-plot F_Mask.gts so the untented via opening appears in RS-274X Gerber,
    # then inject a 0.05 mm mask dam sliver adjacent to U1 Pad 1 (12.600, 26.600).
    subprocess.run(
        [
            "kicad-cli", "pcb", "export", "gerbers",
            "--output", gbr_dst + "/",
            "--layers", "F.Mask",
            "--use-drill-file-origin",
            pcb_dst,
        ],
        check=True, capture_output=True, text=True,
    )
    fmask_file = os.path.join(gbr_dst, "ISAC_868_KiCad9-F_Mask.gts")
    with open(fmask_file, "r", encoding="utf-8") as f:
        gts = f.read()

    # U1 Pad 1 spans Y = 26.600 +/- 0.210 (0.025 mm local mask margin) -> top edge at Y = 26.810 mm.
    # Add a G36..G37 opening with bottom edge at Y = 26.860 mm -> 0.050 mm mask dam sliver!
    sliver_region = (
        "G36*\n"
        "X12100000Y26860000D02*\n"
        "X13100000Y26860000D01*\n"
        "X13100000Y27200000D01*\n"
        "X12100000Y27200000D01*\n"
        "X12100000Y26860000D01*\n"
        "G37*\n"
        "M02*\n"
    )
    gts = gts.replace("M02*", sliver_region)
    with open(fmask_file, "w", encoding="utf-8") as f:
        f.write(gts)

    rc, out = _run_gate([
        PY, CHECK_DFM, "--pcb", pcb_dst, "--gerber-dir", gbr_dst, "--pro", pro_dst,
    ])
    return rc, out, ["Untented via barrel exposed in F_Mask.gts", "sliver"]


def defect_3_gbrjob_finish_none(tmpdir):
    pcb_dst, pro_dst, gbr_dst = _stage_pcb_sandbox(tmpdir)
    job_file = os.path.join(gbr_dst, "ISAC_868_KiCad9-job.gbrjob")
    with open(job_file, "r", encoding="utf-8") as f:
        job_data = json.load(f)
    job_data["GeneralSpecs"]["Finish"] = "None"
    with open(job_file, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2)

    rc, out = _run_gate([
        PY, CHECK_DFM, "--pcb", pcb_dst, "--gerber-dir", gbr_dst, "--pro", pro_dst,
    ])
    return rc, out, ["[GATE b]", "GeneralSpecs.Finish", "ENIG"]


def defect_4_narrow_0p15mm_paste_aperture(tmpdir):
    pcb_dst, pro_dst, gbr_dst = _stage_pcb_sandbox(tmpdir)
    gtp_file = os.path.join(gbr_dst, "ISAC_868_KiCad9-F_Paste.gtp")
    with open(gtp_file, "r", encoding="utf-8") as f:
        gtp = f.read()

    # Inject 0.85 x 0.15 mm stencil aperture (AR@0.12 = 0.531 < 0.66, AR@0.10 = 0.638 < 0.90)
    gtp = gtp.replace(
        "G04 APERTURE END LIST*",
        "%ADD99R,0.850000X0.150000*%\nG04 APERTURE END LIST*",
    )
    gtp = gtp.replace(
        "M02*",
        "D99*\nX41950000Y14700000D03*\nM02*",
    )
    with open(gtp_file, "w", encoding="utf-8") as f:
        f.write(gtp)

    rc, out = _run_gate([
        PY, CHECK_DFM, "--pcb", pcb_dst, "--gerber-dir", gbr_dst, "--pro", pro_dst,
    ])
    return rc, out, ["[GATE c]", "D99", "Area Ratio"]


def defect_5_bcu_slot_under_det_in(tmpdir):
    pcb_dst, pro_dst, gbr_dst = _stage_pcb_sandbox(tmpdir)
    board = pcbnew.LoadBoard(pcb_dst)

    # Locate midpoint of an F.Cu /DET_IN track and carve a perpendicular B.Cu signal trace
    # across it, then refill zones so B.Cu GND plane splits right beneath /DET_IN (AUD20-01!).
    det_tracks = [
        t for t in board.GetTracks()
        if not isinstance(t, pcbnew.PCB_VIA)
        and t.GetLayer() == pcbnew.F_Cu
        and t.GetNetname() == "/DET_IN"
    ]
    t_ref = max(
        det_tracks,
        key=lambda t: (t.GetEnd().x - t.GetStart().x) ** 2 + (t.GetEnd().y - t.GetStart().y) ** 2,
    )
    mx = (t_ref.GetStart().x + t_ref.GetEnd().x) // 2
    my = (t_ref.GetStart().y + t_ref.GetEnd().y) // 2

    non_gnd_net = next(
        n for n in board.GetNetInfo().NetsByNetcode().values()
        if n.GetNetname() in ("3V3_DET", "/3V3_DET", "/DET_EN")
    )
    slot_trk = pcbnew.PCB_TRACK(board)
    slot_trk.SetStart(pcbnew.VECTOR2I(mx - pcbnew.FromMM(1.2), my - pcbnew.FromMM(1.2)))
    slot_trk.SetEnd(pcbnew.VECTOR2I(mx + pcbnew.FromMM(1.2), my + pcbnew.FromMM(1.2)))
    slot_trk.SetWidth(pcbnew.FromMM(0.25))
    slot_trk.SetLayer(pcbnew.B_Cu)
    slot_trk.SetNet(non_gnd_net)
    board.Add(slot_trk)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(pcb_dst, board)

    rc, out = _run_gate([
        PY, CHECK_DFM, "--pcb", pcb_dst, "--gerber-dir", gbr_dst, "--pro", pro_dst,
    ])
    return rc, out, ["[GATE e]", "/DET_IN"]


def defect_6_dnp_r_div1_leaked_into_cpl(tmpdir):
    mut_zip = os.path.join(tmpdir, "ISAC_868_RevE2_PCBWay_Turnkey.zip")

    def _mutate(name, data):
        if name == "cpl/ISAC_868_Turnkey_CPL_Top.csv":
            txt = data.decode("utf-8").rstrip("\n")
            txt += "\nR_DIV1,0R,Resistor_SMD:R_0402_1005Metric,29.8000,16.5000,90.0000,top\n"
            return txt.encode("utf-8")
        return data

    _rebuild_zip_with_mutation(ZIP_SRC, mut_zip, _mutate)
    rc, out = _run_gate([PY, CHECK_BOM_CPL, "--no-check-fab-dir", "--zip", mut_zip])
    return rc, out, ["DNP component 'R_DIV1'", "Populated BOM != CPL"]


def defect_7_cpl_posy_shifted_plus_80mm(tmpdir):
    mut_zip = os.path.join(tmpdir, "ISAC_868_RevE2_PCBWay_Turnkey.zip")

    def _mutate(name, data):
        if name == "cpl/ISAC_868_Turnkey_CPL_Top.csv":
            reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=reader.fieldnames, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                row["PosY"] = f"{float(row['PosY']) + 80.0:.4f}"
                writer.writerow(row)
            return buf.getvalue().encode("utf-8")
        return data

    _rebuild_zip_with_mutation(ZIP_SRC, mut_zip, _mutate)
    rc, out = _run_gate([PY, CHECK_BOM_CPL, "--no-check-fab-dir", "--zip", mut_zip])
    return rc, out, ["[CPL ORIGIN]", "centroid mismatch vs F_Cu.gtl"]


def defect_8_fw_det_adc_changed_pa15_to_pa10(tmpdir):
    mut_fw = os.path.join(tmpdir, "isac_board_pins.h")
    with open(FW_PINS_SRC, "r", encoding="utf-8") as f:
        fw_txt = f.read()

    # Mutate DET_ADC GPIO macro from PA15 (15U) to PA10 (10U)
    mut_txt, n_sub = re.subn(
        r"(#define\s+ISAC_GPIOA_PIN_DET_ADC\s+)15U",
        r"\g<1>10U",
        fw_txt,
    )
    assert n_sub == 1, "Expected exact ISAC_GPIOA_PIN_DET_ADC macro in isac_board_pins.h"
    with open(mut_fw, "w", encoding="utf-8") as f:
        f.write(mut_txt)

    rc, out = _run_gate([PY, CHECK_BOM_CPL, "--fw-pins", mut_fw])
    return rc, out, ["[FW PARITY]", "DET_ADC", "PA10", "PA15"]


def main():
    scenarios = [
        ("1. Open Via-in-Pad inside U1 Pad 69 (LGA-73)", defect_1_via_in_pad_u1_pad69),
        ("2. Untented Via + 0.05 mm Solder-Mask Dam Sliver", defect_2_untented_via_and_0p05mm_mask_sliver),
        ("3. .gbrjob Surface Finish Mutated to 'None'", defect_3_gbrjob_finish_none),
        ("4. 0.15 mm Narrow F_Paste.gtp Aperture (AR < 0.66)", defect_4_narrow_0p15mm_paste_aperture),
        ("5. B.Cu Clearance Slot Under /DET_IN (AUD20-01)", defect_5_bcu_slot_under_det_in),
        ("6. DNP Part R_DIV1 Leaked into Turnkey CPL CSV", defect_6_dnp_r_div1_leaked_into_cpl),
        ("7. CPL PosY Shifted by +80.0 mm Sheet Offset", defect_7_cpl_posy_shifted_plus_80mm),
        ("8. Firmware isac_board_pins.h DET_ADC PA15 -> PA10", defect_8_fw_det_adc_changed_pa15_to_pa10),
    ]

    caught = 0
    failures = []

    print("=" * 80)
    print("ISAC_868 Rev E.5 — Negative Mutation Verification Suite (8 Seeded Defects)")
    print("=" * 80)

    for label, fn in scenarios:
        with tempfile.TemporaryDirectory(prefix="isac_seeded_defect_") as tmpdir:
            rc, out, expected_tokens = fn(tmpdir)
            missing_tokens = [tok for tok in expected_tokens if tok not in out]
            if rc != 0 and not missing_tokens:
                caught += 1
                # Extract first concise diagnostic bullet
                diag = next(
                    (ln.strip() for ln in out.splitlines() if ln.strip().startswith("- [")),
                    "gate exited non-zero as expected",
                )
                print(f"  [CAUGHT] {label}\n           {diag}")
            else:
                failures.append((label, rc, missing_tokens, out))
                print(
                    f"  [MISSED] {label} (exit_code={rc}, missing_diagnostics={missing_tokens})"
                )

    print("-" * 80)
    print(f"SEEDED DEFECT SUMMARY: {caught}/{len(scenarios)} seeded defects deterministically caught.")
    print("=" * 80)

    if caught != len(scenarios) or failures:
        for label, rc, missing_tokens, out in failures:
            sys.stderr.write(
                f"\n[MUTATION ESCAPE] {label}: exit={rc}, missing={missing_tokens}\n{out}\n"
            )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
