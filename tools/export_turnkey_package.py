#!/usr/bin/env python3
"""
Unified Deterministic PCBWay Turnkey Release Packager (`Rev E.5`)
=================================================================
Rebuilds all generated CAD/mechanical sources from scratch, enforces locked DRC
rules, removes any stale legacy exports in `fab/`, exports all manufacturing
artefacts using a **single consistent Auxiliary / Drill-File Origin (`AuxOrigin`)**,
and seals `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip` with `SHA256SUMS.txt`.

Pipeline Stages:
  1. Regenerate SiP symbol/footprint/3D STEP (`tools/gen_sip_assets.py`)
  2. Regenerate Schematic + Turnkey BOM (`tools/gen_sch.py`)
  3. Regenerate PCB layout + locked DRC stackup (`tools/gen_pcb.py`)
  4. Verify cryptographic rule-deck lock (`tools/rules_isac.py --verify`)
  5. Regenerate watertight 0.80 mm window enclosure STLs (`enclosure/gen_enclosure.py`)
  6. Purge stale legacy files in `fab/` so CAM sees zero ambiguity
  7. Export RS-274X/X2 Gerbers + `.gbrjob` + Excellon PTH/NPTH drills + PDF/Gerber
     drill maps (`--use-drill-file-origin` / `--drill-origin plot`)
  8. Export IPC-D-356 bare-board test netlist + KiCad schematic netlist (`netlist/`)
  9. Export normalized Pick-and-Place CPL (`cpl/ISAC_868_Turnkey_CPL_Top.csv`) with
     `[0.0, 360.0)` rotations, zero DNP/BOARD_ONLY/hand-solder parts, and exact `F.Cu`
     pad-bbox centroids in `AuxOrigin` coordinates
 10. Export 3D PCBA STEP (`--drill-origin --subst-models`) + enclosure STLs (`mechanical/`)
 11. Export Schematic & Assembly/Layer PDFs + Turnkey/CPL specs (`documentation/` & `docs/`)
 12. Generate `SHA256SUMS.txt` and build `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`
"""

import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pcbnew

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT = "ISAC_868_KiCad9"

SCH_PATH = os.path.join(ROOT, f"{PROJECT}.kicad_sch")
PCB_PATH = os.path.join(ROOT, f"{PROJECT}.kicad_pcb")

FAB_DIR = os.path.join(ROOT, "fab")
DOCS_DIR = os.path.join(ROOT, "docs")
ENC_DIR = os.path.join(ROOT, "enclosure")

BOM_DIR = os.path.join(FAB_DIR, "bom")
CPL_DIR = os.path.join(FAB_DIR, "cpl")
GBR_DIR = os.path.join(FAB_DIR, "gerbers")
NET_DIR = os.path.join(FAB_DIR, "netlist")
MECH_DIR = os.path.join(FAB_DIR, "mechanical")
DOC_FAB_DIR = os.path.join(FAB_DIR, "documentation")

ZIP_NAME = "ISAC_868_RevE5_PCBWay_Turnkey.zip"
ZIP_PATH = os.path.join(FAB_DIR, ZIP_NAME)
SHA_PATH = os.path.join(FAB_DIR, "SHA256SUMS.txt")

STALE_LEGACY_PATHS = [
    os.path.join(FAB_DIR, "ISAC_868_BOM.csv"),
    os.path.join(FAB_DIR, "ISAC_868_CPL_Top.csv"),
    os.path.join(FAB_DIR, "ISAC_868_Gerbers.zip"),
    os.path.join(FAB_DIR, "ISAC_868_PCBWay_Turnkey.zip"),
    os.path.join(FAB_DIR, "ISAC_868_RevE0_PCBWay_Turnkey.zip"),
    os.path.join(FAB_DIR, "ISAC_868_RevE1_PCBWay_Turnkey.zip"),
    os.path.join(FAB_DIR, "ISAC_868_RevE2_PCBWay_Turnkey.zip"),
    os.path.join(FAB_DIR, "ISAC_868_RevE3_PCBWay_Turnkey.zip"),
    os.path.join(FAB_DIR, "ISAC_868_RevE4_PCBWay_Turnkey.zip"),
    os.path.join(CPL_DIR, "ISAC_868_Turnkey_THT.csv"),
    os.path.join(ENC_DIR, "ISAC_868_Debug_Slot_Plugs.stl"),
    os.path.join(ENC_DIR, "ISAC_868_Debug_Slot_Plugs.scad"),
]

# Option 2A: Single-sided top SMT stencil only — intentionally omit B.Paste so CAM never cuts a bottom stencil
GERBER_LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,F.SilkS,B.SilkS,Edge.Cuts"


def run_cmd(cmd, cwd=ROOT, desc=None):
    if desc:
        print(f"[PACKAGER] {desc}...")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(f"\n[PACKAGER FAIL] Command failed (exit {proc.returncode}): {' '.join(cmd)}\n")
        if proc.stdout:
            sys.stderr.write(f"--- STDOUT ---\n{proc.stdout}\n")
        if proc.stderr:
            sys.stderr.write(f"--- STDERR ---\n{proc.stderr}\n")
        sys.exit(proc.returncode)
    return proc.stdout


def clean_dir_files(directory, keep_basenames=()):
    os.makedirs(directory, exist_ok=True)
    keep = set(keep_basenames)
    for entry in os.listdir(directory):
        if entry in keep:
            continue
        p = os.path.join(directory, entry)
        if os.path.isfile(p) or os.path.islink(p):
            os.remove(p)
        elif os.path.isdir(p):
            shutil.rmtree(p)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_fcu_pad_centroids_aux(pcb_path):
    """
    Compute exact F.Cu copper pad-array bounding-box centroids in AuxOrigin (Gerber/Drill)
    coordinates `(X_gbr, Y_gbr)` [mm] for populated SMD components (`smd_centroids`) and
    populated THT components (`tht_info`, `HIGH-01` split).
    """
    board = pcbnew.LoadBoard(pcb_path)
    aux = board.GetDesignSettings().GetAuxOrigin()
    ax_mm = pcbnew.ToMM(aux.x)
    ay_mm = pcbnew.ToMM(aux.y)

    smd_centroids = {}
    tht_rows = []
    excluded_refs = set()
    exclude_mask = (
        pcbnew.FP_BOARD_ONLY
        | pcbnew.FP_EXCLUDE_FROM_POS_FILES
        | pcbnew.FP_EXCLUDE_FROM_BOM
    )

    for fp in board.GetFootprints():
        ref = fp.GetReference().strip()
        attrs = fp.GetAttributes()
        is_pop_tht = (
            not fp.IsDNP()
            and not (attrs & (pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM))
            and bool(attrs & pcbnew.FP_THROUGH_HOLE)
        )
        if not is_pop_tht and (fp.IsDNP() or (attrs & exclude_mask)):
            excluded_refs.add(ref)
            continue

        xs = []
        ys = []
        for pad in fp.Pads():
            if not pad.IsOnLayer(pcbnew.F_Cu):
                continue
            poly = pad.GetEffectivePolygon(pcbnew.F_Cu, 0)
            if poly.IsEmpty():
                bb = pad.GetBoundingBox()
            else:
                bb = poly.BBox()
            x1 = pcbnew.ToMM(bb.GetLeft()) - ax_mm
            x2 = pcbnew.ToMM(bb.GetRight()) - ax_mm
            # KiCad sheet Y increases downward; Gerber/Drill AuxOrigin +Y increases upward
            y1 = ay_mm - pcbnew.ToMM(bb.GetBottom())
            y2 = ay_mm - pcbnew.ToMM(bb.GetTop())
            xs.extend([x1, x2])
            ys.extend([y1, y2])

        if not xs:
            raise RuntimeError(f"Populated footprint {ref} has zero F.Cu copper pads!")

        cx = 0.5 * (min(xs) + max(xs))
        cy = 0.5 * (min(ys) + max(ys))
        if is_pop_tht:
            excluded_refs.add(ref)
            rot_deg = round(fp.GetOrientationDegrees() % 360.0, 4)
            if rot_deg >= 360.0 or rot_deg == 0.0:
                rot_deg = 0.0
            fpid = fp.GetFPID()
            pkg_str = f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}" if str(fpid.GetLibNickname()) else str(fpid.GetLibItemName())
            tht_rows.append({
                "Ref": ref,
                "Val": fp.GetValue().strip(),
                "Package": pkg_str,
                "PosX": f"{cx:.4f}",
                "PosY": f"{cy:.4f}",
                "Rot": f"{rot_deg:.4f}",
                "Side": "top",
            })
        else:
            smd_centroids[ref] = (cx, cy)

    tht_rows.sort(key=lambda r: r["Ref"])
    return smd_centroids, tht_rows, excluded_refs


def export_normalized_cpl(pcb_path, out_csv_path):
    """
    Export 100% pure-SMD Pick-and-Place CPL using `--use-drill-file-origin --exclude-dnp`
    (`67` populated SMD rows, `0` THT parts; `J1..J5` are all `DNP = Yes` on the field SKU).
    """
    centroids, tht_rows, excluded_refs = compute_fcu_pad_centroids_aux(pcb_path)
    if tht_rows:
        raise RuntimeError(
            f"Expected 0 populated THT parts on 100% pure-SMD Rev E.5 PCBA, got: {tht_rows}"
        )

    with tempfile.NamedTemporaryFile(prefix="isac_raw_pos_", suffix=".csv", delete=False) as tf:
        raw_csv = tf.name

    try:
        run_cmd(
            [
                "kicad-cli", "pcb", "export", "pos",
                "--side", "front",
                "--format", "csv",
                "--units", "mm",
                "--use-drill-file-origin",
                "--exclude-dnp",
                "--output", raw_csv,
                pcb_path,
            ],
            desc="Exporting raw front SMD CPL (--use-drill-file-origin --exclude-dnp)",
        )

        rows_out = []
        seen_refs = set()
        with open(raw_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref = row["Ref"].strip()
                if ref in excluded_refs or ref not in centroids:
                    continue
                if ref in seen_refs:
                    raise RuntimeError(f"Duplicate reference {ref} in raw position export!")
                seen_refs.add(ref)

                cx, cy = centroids[ref]
                raw_rot = float(row["Rot"])
                rot_norm = round(raw_rot % 360.0, 4)
                if rot_norm >= 360.0 or rot_norm == 0.0:
                    rot_norm = 0.0

                side = row["Side"].strip().lower()
                if side != "top":
                    raise RuntimeError(f"Unexpected bottom-side component {ref} ({side})!")

                rows_out.append({
                    "Ref": ref,
                    "Val": row["Val"].strip(),
                    "Package": row["Package"].strip(),
                    "PosX": f"{cx:.4f}",
                    "PosY": f"{cy:.4f}",
                    "Rot": f"{rot_norm:.4f}",
                    "Side": "top",
                })

        missing = set(centroids.keys()) - seen_refs
        if missing:
            raise RuntimeError(f"Populated SMD footprints missing from CPL export: {sorted(missing)}")

        rows_out.sort(key=lambda r: r["Ref"])

        os.makedirs(os.path.dirname(out_csv_path), exist_ok=True)
        with open(out_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows_out)

        return len(rows_out)
    finally:
        if os.path.exists(raw_csv):
            os.remove(raw_csv)


def _export_bench_tht_handsolder_csv(pcb_path, out_csv_path):
    """
    Write companion `fab/cpl/ISAC_868_Bench_THT_HandSolder.csv` on disk documenting
    exact `AuxOrigin` pad-bbox midpoint + Pad-1 coordinates for THT headers `J2..J5`
    and optional bench VNA edge-straddle SMA `J1` (`DNP = Yes` on enclosed field SKU).
    Kept outside `ISAC_868_RevE5_PCBWay_Turnkey.zip` so CAM sees strictly 1 CPL CSV.
    """
    board = pcbnew.LoadBoard(pcb_path)
    aux = board.GetDesignSettings().GetAuxOrigin()
    ax_mm = pcbnew.ToMM(aux.x)
    ay_mm = pcbnew.ToMM(aux.y)

    rows = []
    for ref in ("J1", "J2", "J3", "J4", "J5"):
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise RuntimeError(f"Missing connector {ref} on board!")
        xs, ys = [], []
        for pad in fp.Pads():
            if not pad.IsOnLayer(pcbnew.F_Cu):
                continue
            bb = pad.GetBoundingBox()
            xs.extend([pcbnew.ToMM(bb.GetLeft()) - ax_mm, pcbnew.ToMM(bb.GetRight()) - ax_mm])
            ys.extend([ay_mm - pcbnew.ToMM(bb.GetBottom()), ay_mm - pcbnew.ToMM(bb.GetTop())])
        cx = 0.5 * (min(xs) + max(xs))
        cy = 0.5 * (min(ys) + max(ys))
        p1 = fp.FindPadByNumber("1")
        p1x = pcbnew.ToMM(p1.GetPosition().x) - ax_mm
        p1y = ay_mm - pcbnew.ToMM(p1.GetPosition().y)
        rot_deg = round(fp.GetOrientationDegrees() % 360.0, 4)
        if rot_deg >= 360.0 or rot_deg == 0.0:
            rot_deg = 0.0
        rows.append({
            "Ref": ref,
            "Val": fp.GetValue().strip(),
            "Package": str(fp.GetFPID().GetLibItemName()),
            "FieldSKU_DNP": "Yes" if fp.IsDNP() else "No",
            "BodyCenter_X_mm": f"{cx:.4f}",
            "BodyCenter_Y_mm": f"{cy:.4f}",
            "Pad1_X_mm": f"{p1x:.4f}",
            "Pad1_Y_mm": f"{p1y:.4f}",
            "Rot_deg": f"{rot_deg:.4f}",
            "AssemblyProcess": (
                "DNP_FieldSKU_HandSolder_BenchVNA_PostReflow"
                if ref == "J1"
                else (
                    "DNP_FieldSKU_DirectSolder_BattLeads_From_B_Cu"
                    if ref == "J2"
                    else (
                        "DNP_FieldSKU_BareENIG_PogoPads_PreLid"
                        if fp.IsDNP()
                        else "Top_Vertical_THT_SelectiveOrWave"
                    )
                )
            ),
        })

    os.makedirs(os.path.dirname(out_csv_path), exist_ok=True)
    with open(out_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_turnkey_package(skip_regen=False):
    py = sys.executable or "/usr/bin/python3"

    # 1. Regenerate CAD, DRC lock, watertight flat-lid STLs & 3D enclosure render
    if not skip_regen:
        run_cmd([py, "tools/gen_sip_assets.py"], desc="1/6 Regenerating RAK3172LP-SiP symbol/footprint/3D STEP")
        run_cmd([py, "tools/gen_sch.py"], desc="2/6 Regenerating Schematic & Turnkey BOM")
        run_cmd([py, "tools/gen_pcb.py"], desc="3/6 Regenerating PCB Layout & Locked Stackup")
        run_cmd([py, "tools/rules_isac.py", "--verify"], desc="4/6 Verifying Cryptographic Rule-Deck Lock")
        run_cmd([py, "enclosure/gen_enclosure.py"], desc="5/6 Regenerating Watertight Flat-Lid 0.80 mm Window STLs")
        run_cmd([py, "enclosure/render_enclosure_3d.py"], desc="6/6 Rendering 3D Exploded & Cutaway Enclosure Sheet")

    # 2. Purge stale legacy files in fab/ so CAM sees zero ambiguity
    print("[PACKAGER] Purging stale legacy duplicates in fab/...")
    for stale in STALE_LEGACY_PATHS:
        if os.path.exists(stale):
            os.remove(stale)
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    if os.path.exists(SHA_PATH):
        os.remove(SHA_PATH)

    clean_dir_files(GBR_DIR)
    clean_dir_files(NET_DIR)
    clean_dir_files(CPL_DIR, keep_basenames=("CPL_README.md",))
    clean_dir_files(MECH_DIR)
    clean_dir_files(DOC_FAB_DIR, keep_basenames=("PCBWAY_TURNKEY_FABRICATION_SPECIFICATION.md",))
    os.makedirs(BOM_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    bom_csv = os.path.join(BOM_DIR, "ISAC_868_Turnkey_BOM.csv")
    if not os.path.isfile(bom_csv):
        raise RuntimeError(f"Missing Turnkey BOM CSV: {bom_csv}")

    # 3. Export RS-274X/Gerber X2 layers + .gbrjob using --use-drill-file-origin
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "gerbers",
            "--output", GBR_DIR + "/",
            "--layers", GERBER_LAYERS,
            "--use-drill-file-origin",
            PCB_PATH,
        ],
        desc="Exporting Gerbers + .gbrjob (--use-drill-file-origin)",
    )

    # 4. Export Excellon PTH/NPTH drills + PDF & GerberX2 drill maps (--drill-origin plot)
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "drill",
            "--output", GBR_DIR + "/",
            "--format", "excellon",
            "--drill-origin", "plot",
            "--excellon-units", "mm",
            "--excellon-separate-th",
            "--generate-map",
            "--map-format", "pdf",
            PCB_PATH,
        ],
        desc="Exporting Excellon PTH/NPTH drills + PDF drill maps (--drill-origin plot)",
    )
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "drill",
            "--output", GBR_DIR + "/",
            "--format", "excellon",
            "--drill-origin", "plot",
            "--excellon-units", "mm",
            "--excellon-separate-th",
            "--generate-map",
            "--map-format", "gerberx2",
            PCB_PATH,
        ],
        desc="Exporting GerberX2 PTH/NPTH drill maps (--drill-origin plot)",
    )

    # 5. Export IPC-D-356 bare-board test netlist & schematic netlist
    d356_path = os.path.join(NET_DIR, f"{PROJECT}.d356")
    net_path = os.path.join(NET_DIR, f"{PROJECT}.net")
    run_cmd(
        ["kicad-cli", "pcb", "export", "ipcd356", "--output", d356_path, PCB_PATH],
        desc="Exporting IPC-D-356 bare-board test netlist",
    )
    run_cmd(
        ["kicad-cli", "sch", "export", "netlist", "--output", net_path, SCH_PATH],
        desc="Exporting KiCad schematic netlist",
    )

    # 6. Export normalized 100% pure-SMD Pick-and-Place CPL CSV + Bench Hand-Solder Reference CSV
    cpl_csv = os.path.join(CPL_DIR, "ISAC_868_Turnkey_CPL_Top.csv")
    n_cpl = export_normalized_cpl(PCB_PATH, cpl_csv)
    print(f"[PACKAGER] Wrote {cpl_csv} ({n_cpl} pure-SMD placements, 0 THT parts).")

    bench_csv = os.path.join(CPL_DIR, "ISAC_868_Bench_THT_HandSolder.csv")
    _export_bench_tht_handsolder_csv(PCB_PATH, bench_csv)
    print(f"[PACKAGER] Wrote companion {bench_csv} (J1 bench SMA + J2 direct-solder batt + J3..J5 pogo reference).")

    # Sync enclosure System Box-Build BOM CSV into docs/
    enc_bb = os.path.join(ENC_DIR, "ISAC_868_System_BoxBuild_BOM.csv")
    if os.path.isfile(enc_bb):
        shutil.copy2(enc_bb, os.path.join(DOCS_DIR, "ISAC_868_System_BoxBuild_BOM.csv"))

    # 7. Export 3D PCBA STEP (--drill-origin --subst-models --no-dnp) + copy enclosure STLs
    step_path = os.path.join(MECH_DIR, "ISAC_868_PCBA.step")
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "step",
            "--drill-origin",
            "--subst-models",
            "--no-dnp",
            "--force",
            "--output", step_path,
            PCB_PATH,
        ],
        desc="Exporting 3D PCBA STEP assembly (--drill-origin --subst-models --no-dnp)",
    )
    for stl_name in (
        "ISAC_868_Lid_0p80mm_Window.stl",
        "ISAC_868_Base_Tray.stl",
        "ISAC_868_Base_Tray_Battery.stl",
    ):
        src_stl = os.path.join(ENC_DIR, stl_name)
        if not os.path.isfile(src_stl):
            raise RuntimeError(f"Missing enclosure STL: {src_stl}")
        shutil.copy2(src_stl, os.path.join(MECH_DIR, stl_name))

    # 8. Export Schematic, Assembly & Layer PDFs + copy Turnkey/CPL specs into documentation/
    sch_pdf = os.path.join(DOC_FAB_DIR, "ISAC_868_Schematic.pdf")
    asm_pdf = os.path.join(DOC_FAB_DIR, "ISAC_868_Assembly_Top.pdf")
    top_pdf = os.path.join(DOC_FAB_DIR, "ISAC_868_PCB_Top_Sheet.pdf")
    bot_pdf = os.path.join(DOC_FAB_DIR, "ISAC_868_PCB_Bottom_Sheet.pdf")

    run_cmd(
        ["kicad-cli", "sch", "export", "pdf", "--output", sch_pdf, SCH_PATH],
        desc="Exporting Schematic PDF",
    )
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "pdf",
            "--layers", "F.Fab,F.SilkS,F.CrtYd,Edge.Cuts",
            "--include-border-title",
            "--crossout-DNP-footprints-on-fab-layers",
            "--sketch-pads-on-fab-layers",
            "--mode-single",
            "--output", asm_pdf,
            PCB_PATH,
        ],
        desc="Exporting Top Assembly Drawing PDF (DNP crossed out)",
    )
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "pdf",
            "--layers", "F.Cu,F.Mask,F.SilkS,Edge.Cuts,User.Drawings,User.Comments",
            "--include-border-title",
            "--mode-single",
            "--output", top_pdf,
            PCB_PATH,
        ],
        desc="Exporting PCB Top Sheet PDF",
    )
    top_pdf_txt = run_cmd(["pdftotext", top_pdf, "-"], desc="Auditing PCB Top Sheet PDF text hygiene (LOW-02)")
    if "\u00fe\u00ff" in top_pdf_txt or "51.1R" in top_pdf_txt:
        raise RuntimeError("ISAC_868_PCB_Top_Sheet.pdf contains UTF-16 mojibake ('þÿ') or stale '51.1R' text!")
    run_cmd(
        [
            "kicad-cli", "pcb", "export", "pdf",
            "--layers", "B.Cu,B.Mask,B.SilkS,Edge.Cuts",
            "--mirror",
            "--include-border-title",
            "--mode-single",
            "--output", bot_pdf,
            PCB_PATH,
        ],
        desc="Exporting PCB Bottom Sheet PDF",
    )

    cpl_readme_src = os.path.join(CPL_DIR, "CPL_README.md")
    if not os.path.isfile(cpl_readme_src):
        raise RuntimeError(f"Missing CPL README: {cpl_readme_src}")
    shutil.copy2(cpl_readme_src, os.path.join(DOC_FAB_DIR, "CPL_README.md"))

    for bp_name in (
        "ISAC_868_Enclosure_0p80mm_Blueprint.png",
        "ISAC_868_Enclosure_Battery_Blueprint.png",
        "ISAC_868_Enclosure_3D_Exploded.png",
    ):
        enc_bp = os.path.join(DOCS_DIR, bp_name)
        if os.path.isfile(enc_bp):
            shutil.copy2(enc_bp, os.path.join(DOC_FAB_DIR, bp_name))

    # Sync PDFs, 3D ray-traced renders, summary PDF & fresh ERC/DRC reports to docs/ and fab/documentation/
    for pdf_file in (sch_pdf, asm_pdf, top_pdf, bot_pdf):
        shutil.copy2(pdf_file, os.path.join(DOCS_DIR, os.path.basename(pdf_file)))

    pcba_renders = [
        (
            "ISAC_868_3D_Top.png",
            ["kicad-cli", "pcb", "render", "--side", "top", "--zoom", "1.42", "--quality", "high",
             "--width", "2200", "--height", "1150", "--background", "opaque"],
            "Rendering 3D Top PCBA inspection PNG (ray-traced)",
        ),
        (
            "ISAC_868_3D_Bottom.png",
            ["kicad-cli", "pcb", "render", "--side", "bottom", "--zoom", "1.42", "--quality", "high",
             "--width", "2200", "--height", "1150", "--background", "opaque"],
            "Rendering 3D Bottom PCBA inspection PNG (ray-traced)",
        ),
        (
            "ISAC_868_3D_Iso.png",
            ["kicad-cli", "pcb", "render", "--perspective", "--rotate", "-45,0,35", "--zoom", "1.12",
             "--floor", "--quality", "high", "--width", "2200", "--height", "1350", "--background", "opaque"],
            "Rendering 3D Front-Left Isometric PCBA inspection PNG (ray-traced)",
        ),
        (
            "ISAC_868_3D_Iso_Rear.png",
            ["kicad-cli", "pcb", "render", "--perspective", "--rotate", "-42,0,-145", "--zoom", "1.12",
             "--floor", "--quality", "high", "--width", "2200", "--height", "1350", "--background", "opaque"],
            "Rendering 3D Rear-Right Antenna/Bridge Isometric PCBA inspection PNG (ray-traced)",
        ),
    ]
    for r_fname, r_cmd, r_desc in pcba_renders:
        out_doc_png = os.path.join(DOCS_DIR, r_fname)
        run_cmd(r_cmd + ["--output", out_doc_png, PCB_PATH], desc=r_desc)
        shutil.copy2(out_doc_png, os.path.join(DOC_FAB_DIR, r_fname))
    run_cmd(
        [py, "tools/render_summary_pdf.py"],
        desc="Rendering System Design & Operation Summary PDF (WeasyPrint)",
    )
    run_cmd(
        [
            "kicad-cli", "sch", "erc",
            "--severity-all", "--exit-code-violations",
            "--output", os.path.join(DOCS_DIR, "ISAC_868_ERC.rpt"),
            SCH_PATH,
        ],
        desc="Generating clean ERC report (0 violations)",
    )
    run_cmd(
        [
            "kicad-cli", "pcb", "drc",
            "--severity-all", "--all-track-errors", "--schematic-parity", "--exit-code-violations",
            "--output", os.path.join(DOCS_DIR, "ISAC_868_DRC.rpt"),
            PCB_PATH,
        ],
        desc="Generating clean DRC + all-track-errors + schematic-parity report (0 violations)",
    )

    # 9. Collect exact Turnkey archive manifest, write SHA256SUMS.txt, and zip
    archive_map = {}

    # Single BOM CSV + 100% pure-SMD CPL CSV (0 THT parts on field SKU!)
    archive_map["bom/ISAC_868_Turnkey_BOM.csv"] = bom_csv
    archive_map["cpl/ISAC_868_Turnkey_CPL_Top.csv"] = cpl_csv

    for sub_name, sub_dir in (
        ("gerbers", GBR_DIR),
        ("netlist", NET_DIR),
        ("mechanical", MECH_DIR),
        ("documentation", DOC_FAB_DIR),
    ):
        for fname in sorted(os.listdir(sub_dir)):
            if fname == "__pycache__" or fname.endswith((".pyc", ".pyo", ".bak", "-bak", "~")):
                continue
            fpath = os.path.join(sub_dir, fname)
            if os.path.isfile(fpath):
                archive_map[f"{sub_name}/{fname}"] = fpath

    sha_lines = []
    for rel_arc in sorted(archive_map.keys()):
        digest = sha256_file(archive_map[rel_arc])
        sha_lines.append(f"{digest}  {rel_arc}")

    with open(SHA_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sha_lines) + "\n")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel_arc in sorted(archive_map.keys()):
            zf.write(archive_map[rel_arc], arcname=rel_arc)
        zf.write(SHA_PATH, arcname="SHA256SUMS.txt")

    zip_kb = os.path.getsize(ZIP_PATH) / 1024.0
    print(
        f"[PACKAGER PASS] Sealed {ZIP_PATH} ({len(archive_map) + 1} files, {zip_kb:.1f} KiB) "
        f"with verified SHA256SUMS.txt."
    )


if __name__ == "__main__":
    skip = "--skip-regen" in sys.argv
    build_turnkey_package(skip_regen=skip)
