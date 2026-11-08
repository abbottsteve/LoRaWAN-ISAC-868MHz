#!/usr/bin/env python3
"""
Documentation-to-Hardware, Link & MathML Parity Verifier (`Rev E.5`)
====================================================================
Prevents silent documentation, link, MathML, or simulation drift across the
two-tier open-hardware documentation graph by cross-checking:
  - `README.md` (executive scientific landing page, <= 280 lines)
  - `docs/ISAC_868MHz_System_Design_and_Operation_Summary.md` & `.pdf`
  - `docs/rf_design_and_simulation.md`
  - `docs/firmware_and_pinmap.md` (`U1` LGA-73 pinout & `FPort = 10` payload)
  - `docs/bom_and_enclosure.md` (46-line Turnkey BOM & `TP1..TP5`)
  - `docs/power_budget.md` & `docs/rf_link_budget.md`
  - `docs/bringup_report.md` (`5–10` board pilot bring-up & sign-off checklist)
  - `cst_studio/README.md` & `CITATION.cff`
  - `fab/documentation/PCBWAY_TURNKEY_FABRICATION_SPECIFICATION.md` & `fab/cpl/CPL_README.md`
  - `docs/*` visual inspection PDFs/PNGs
against live ground truth extracted from:
  - `rf/results/ifa_fullwave_3d.json` & `rf/results/bridge_3tone_curves.json` (<= 0.01 dB / 0.00 MHz)
  - `firmware/test/data/design_values.json`
  - `ISAC_868_KiCad9.kicad_pcb`
  - `firmware/include/isac_board_pins.h` & `firmware/include/isac_sensing.h`
  - `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip`
"""

import csv
import io
import json
import os
import re
import subprocess
import sys
import zipfile

import pcbnew

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(ROOT, "docs")

SUMMARY_MD = os.path.join(DOCS_DIR, "ISAC_868MHz_System_Design_and_Operation_Summary.md")
SUMMARY_PDF = os.path.join(DOCS_DIR, "ISAC_868MHz_System_Design_and_Operation_Summary.pdf")
README_MD = os.path.join(ROOT, "README.md")
RF_SIM_MD = os.path.join(DOCS_DIR, "rf_design_and_simulation.md")
FW_PIN_MD = os.path.join(DOCS_DIR, "firmware_and_pinmap.md")
BOM_ENC_MD = os.path.join(DOCS_DIR, "bom_and_enclosure.md")
POWER_MD = os.path.join(DOCS_DIR, "power_budget.md")
LINK_BUDGET_MD = os.path.join(DOCS_DIR, "rf_link_budget.md")
BRINGUP_MD = os.path.join(DOCS_DIR, "bringup_report.md")
OPEN_ITEMS_MD = os.path.join(DOCS_DIR, "OPEN_ITEMS.md")
CST_MD = os.path.join(ROOT, "cst_studio", "README.md")
CITATION_CFF = os.path.join(ROOT, "CITATION.cff")
TURNKEY_SPEC_MD = os.path.join(ROOT, "fab", "documentation", "PCBWAY_TURNKEY_FABRICATION_SPECIFICATION.md")
CPL_README_MD = os.path.join(ROOT, "fab", "cpl", "CPL_README.md")

DESIGN_JSON = os.path.join(ROOT, "firmware", "test", "data", "design_values.json")
IFA_JSON = os.path.join(ROOT, "rf", "results", "ifa_fullwave_3d.json")
BR_JSON = os.path.join(ROOT, "rf", "results", "bridge_3tone_curves.json")
PCB_PATH = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")
ZIP_PATH = os.path.join(ROOT, "fab", "ISAC_868_RevE5_PCBWay_Turnkey.zip")
FW_PINS_H = os.path.join(ROOT, "firmware", "include", "isac_board_pins.h")
FW_SENSING_H = os.path.join(ROOT, "firmware", "include", "isac_sensing.h")

BANNED_LEGACY_TOKENS = (
    "Rev C.0",
    "Revision C.0",
    "Rev D.0",
    "Revision D.0",
    "Rev E.0",
    "Revision E.0",
    "Rev E.1",
    "Revision E.1",
    "Rev E.2",
    "Revision E.2",
    "Rev E.3",
    "Revision E.3",
    "Rev E.4",
    "Revision E.4",
    "RevE0_Frame",
    "ISAC_868_RevE0_PCBWay_Turnkey.zip",
    "ISAC_868_RevE1_PCBWay_Turnkey.zip",
    "ISAC_868_RevE2_PCBWay_Turnkey.zip",
    "ISAC_868_RevE3_PCBWay_Turnkey.zip",
    "ISAC_868_RevE4_PCBWay_Turnkey.zip",
    "MLZ2012M150WT000",
    "RG1005P-8R2-B-T5",
    "TNPW04028R20BEED",
    "ERA-2AEB8R2X",
    "C2906778",
    "C80043",
    "C86104",
    "C135303",
    "C496550",
    "51.1R",
    "\u00fe\u00ff",
    "../analysis",
    "B5819W",
    "RAK3172-E",
    "STM32WLE5CC",
    "AP2112K",
    "v_f2_mv",
    "vbat_20mv",
)

REQUIRED_DOCS_VISUALS = (
    "ISAC_868_Schematic.pdf",
    "ISAC_868_PCB_Top_Sheet.pdf",
    "ISAC_868_PCB_Bottom_Sheet.pdf",
    "ISAC_868_Assembly_Top.pdf",
    "ISAC_868_3D_Top.png",
    "ISAC_868_3D_Bottom.png",
    "ISAC_868_3D_Iso.png",
    "ISAC_868_3D_Iso_Rear.png",
    "ISAC_868_Enclosure_0p80mm_Blueprint.png",
    "ISAC_868_Enclosure_Battery_Blueprint.png",
    "ISAC_868_Enclosure_3D_Exploded.png",
)


def _split_refs(s):
    return sorted(tok.strip(" `*") for tok in re.split(r"[,;\s]+", s.strip(" `*")) if tok.strip(" `*"))


def _parse_markdown_bom_rows(md_text):
    rows = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) == 9 and re.match(r"^\d+$", cells[0]):
            rows.append({
                "Item": int(cells[0]),
                "Designators": _split_refs(cells[1]),
                "Qty": int(cells[2]),
                "Value": cells[3].strip("` "),
                "Footprint": cells[4].strip("` "),
                "MPN": cells[5].strip("` "),
                "Manufacturer": cells[6].strip("` "),
                "LCSC": cells[7].strip("` "),
                "DNP": re.sub(r"[*`]", "", cells[8]).strip(),
            })
    return rows


def _audit_markdown_links_and_math(md_path, md_text, errors):
    rel_label = os.path.relpath(md_path, ROOT)
    base_dir = os.path.dirname(md_path)
    in_code = False
    in_math_block = False

    for idx, line in enumerate(md_text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.strip() == "$$":
            in_math_block = not in_math_block
            continue

        if in_math_block:
            for bad in (r"\!", r"\,", r"\%", r"\_", r"\|"):
                if bad in line:
                    errors.append(f"[MATHML ESCAPE] {rel_label}:{idx} contains CommonMark-stripped '{bad}'")
            if re.search(r"[^A-Za-z0-9\\]_", line):
                errors.append(f"[MATHML SUBSCRIPT] {rel_label}:{idx} has non-alnum before '_' inside display math")
            continue

        line_nocode = re.sub(r"`[^`]*`", "CODE", line)

        # Check relative file/directory links [text](target)
        for m_lnk in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", line_nocode):
            target = m_lnk.group(1).strip().split()[0]
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            resolved = os.path.normpath(os.path.join(base_dir, file_part))
            if not os.path.exists(resolved):
                errors.append(f"[BROKEN LINK] {rel_label}:{idx} -> {target!r} (missing {resolved})")

        # Check inline math CommonMark hazards
        for m_math in re.finditer(r"\$\$?([^$]+)\$\$?", line_nocode):
            expr = m_math.group(1)
            for bad in (r"\!", r"\,", r"\%", r"\_", r"\|"):
                if bad in expr:
                    errors.append(f"[MATHML ESCAPE] {rel_label}:{idx} contains CommonMark-stripped '{bad}'")
            if re.search(r"[^A-Za-z0-9\\]_", expr):
                errors.append(f"[MATHML SUBSCRIPT] {rel_label}:{idx} has non-alnum before '_' in {m_math.group(0)!r}")
            if (m_math.start() > 0 and line_nocode[m_math.start() - 1].isalnum()) or (
                m_math.end() < len(line_nocode) and line_nocode[m_math.end()].isalnum()
            ):
                errors.append(f"[MATHML DELIM] {rel_label}:{idx} has alphanumeric touching '$' in {m_math.group(0)!r}")

        if re.search(r"\)\$\)", line_nocode):
            errors.append(f"[MATHML DELIM] {rel_label}:{idx} contains ')$)' delimiter hazard")


def run_doc_parity_audit():
    errors = []

    req_files = (
        SUMMARY_MD, SUMMARY_PDF, README_MD, RF_SIM_MD, FW_PIN_MD, BOM_ENC_MD,
        POWER_MD, LINK_BUDGET_MD, BRINGUP_MD, OPEN_ITEMS_MD, CST_MD, CITATION_CFF,
        TURNKEY_SPEC_MD, CPL_README_MD, DESIGN_JSON, IFA_JSON, BR_JSON,
        PCB_PATH, ZIP_PATH, FW_PINS_H, FW_SENSING_H,
    )
    for req_path in req_files:
        if not os.path.isfile(req_path):
            errors.append(f"[DOC MISSING] Required file not found: {req_path}")
    if errors:
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1

    sum_md = open(SUMMARY_MD, "r", encoding="utf-8").read()
    readme_md = open(README_MD, "r", encoding="utf-8").read()
    rf_sim_md = open(RF_SIM_MD, "r", encoding="utf-8").read()
    fw_pin_md = open(FW_PIN_MD, "r", encoding="utf-8").read()
    bom_enc_md = open(BOM_ENC_MD, "r", encoding="utf-8").read()
    power_md = open(POWER_MD, "r", encoding="utf-8").read()
    link_md = open(LINK_BUDGET_MD, "r", encoding="utf-8").read()
    bringup_md = open(BRINGUP_MD, "r", encoding="utf-8").read()
    open_items_md = open(OPEN_ITEMS_MD, "r", encoding="utf-8").read()
    cst_md = open(CST_MD, "r", encoding="utf-8").read()
    citation_cff = open(CITATION_CFF, "r", encoding="utf-8").read()
    spec_md = open(TURNKEY_SPEC_MD, "r", encoding="utf-8").read()
    cpl_md = open(CPL_README_MD, "r", encoding="utf-8").read()

    dv = json.load(open(DESIGN_JSON, "r", encoding="utf-8"))
    ifa_j = json.load(open(IFA_JSON, "r", encoding="utf-8"))
    br_j = json.load(open(BR_JSON, "r", encoding="utf-8"))
    fw_pins = open(FW_PINS_H, "r", encoding="utf-8").read()

    # Executive README conciseness check (open-hardware layered pattern: <= 280 lines)
    readme_lines = len(readme_md.splitlines())
    if readme_lines > 280 or readme_lines < 160:
        errors.append(f"[README LENGTH] Expected concise 160..280-line executive README.md, found {readme_lines} lines!")

    # CITATION.cff metadata check
    for cff_tok in ("cff-version: 1.2.0", "Boachie", "Stephen K.", "Apache-2.0", "E.5"):
        if cff_tok not in citation_cff:
            errors.append(f"[CITATION.CFF] Missing expected metadata token {cff_tok!r}!")

    # Gate 4 RF & EM Single-Source-of-Truth Verification (0.00 MHz / <= 0.01 dB)
    if br_j["c_par_brs_pf"] >= 0.15 or abs(dv["C_PAR_BRS_PF"] - br_j["c_par_brs_pf"]) > 1e-4:
        errors.append(f"[GATE 4] /BR_S C_par {br_j['c_par_brs_pf']} pF >= 0.15 pF or out of sync!")
    if br_j["nominal_866p5_metrics"]["directivity_wc_dB"] < 22.0 or abs(
        dv["directivity_dB"] - br_j["nominal_866p5_metrics"]["directivity_wc_dB"]
    ) > 0.01:
        errors.append("[GATE 4] 50-Ohm directivity < 22.0 dB or out of sync (> 0.01 dB)!")
    if dv["mc_air_to_ice_contrast_p01_dB"] < 8.0 or abs(
        dv["mc_air_to_ice_contrast_p01_dB"] - br_j["mc_summary"][0]["air_to_ice_contrast_p01_dB"]
    ) > 0.01:
        errors.append("[GATE 4] Calibrated P01 Air-to-Ice contrast < 8.0 dB or out of sync (> 0.01 dB)!")

    media_map = {r["medium"]: r for r in dv["table"]}
    expected_sens = round(
        (ifa_j["media"]["dry air"]["f0_MHz"] - ifa_j["media"]["glaze ice"]["f0_MHz"]) / (3.2**0.5 - 1.0), 2
    )
    if abs(dv.get("air_to_ice_sensitivity_MHz_per_RIU", 0.0) - expected_sens) > 1e-6:
        errors.append(
            f"[GATE 4] Sensitivity discrepancy: dv={dv.get('air_to_ice_sensitivity_MHz_per_RIU')} vs FDTD={expected_sens}"
        )
    for med_name, m_dv in media_map.items():
        if med_name not in ifa_j["media"]:
            errors.append(f"[GATE 4] Medium {med_name!r} missing from ifa_fullwave_3d.json!")
            continue
        m_ifa = ifa_j["media"][med_name]
        if abs(m_dv["f_res_MHz"] - m_ifa["f0_MHz"]) > 1e-6:
            errors.append(
                f"[GATE 4] {med_name} f_res discrepancy: dv={m_dv['f_res_MHz']} vs FDTD={m_ifa['f0_MHz']}"
            )

    # Extract text from Summary PDF & Top Sheet PDF via pdftotext
    proc = subprocess.run(["pdftotext", SUMMARY_PDF, "-"], capture_output=True, text=True)
    sum_pdf_txt = proc.stdout if proc.returncode == 0 else ""
    if proc.returncode != 0:
        errors.append(f"[PDF] pdftotext failed on {SUMMARY_PDF}: {proc.stderr}")
    if os.path.getsize(SUMMARY_PDF) < 15_000:
        errors.append(f"[PDF] {SUMMARY_PDF} suspiciously small ({os.path.getsize(SUMMARY_PDF)} bytes)")
    if os.path.getmtime(SUMMARY_PDF) + 2.0 < os.path.getmtime(SUMMARY_MD):
        errors.append("[PDF] ISAC_868MHz_System_Design_and_Operation_Summary.pdf is older than its .md source!")
    if "Hardware Revision E.5" not in sum_pdf_txt:
        errors.append("[PDF] Summary PDF missing 'Hardware Revision E.5' header/body text!")

    top_pdf_path = os.path.join(DOCS_DIR, "ISAC_868_PCB_Top_Sheet.pdf")
    if os.path.isfile(top_pdf_path):
        tp_proc = subprocess.run(["pdftotext", top_pdf_path, "-"], capture_output=True, text=True)
        if "\u00fe\u00ff" in tp_proc.stdout or "51.1R" in tp_proc.stdout:
            errors.append("[PDF HYGIENE] ISAC_868_PCB_Top_Sheet.pdf contains UTF-16 mojibake or stale 51.1R text!")

    # Zero banned stale legacy tokens across all primary & modular docs
    for doc_label, content in (
        ("README.md", readme_md),
        ("docs/ISAC_868MHz_System_Design_and_Operation_Summary.md", sum_md),
        ("docs/ISAC_868MHz_System_Design_and_Operation_Summary.pdf", sum_pdf_txt),
        ("docs/rf_design_and_simulation.md", rf_sim_md),
        ("docs/firmware_and_pinmap.md", fw_pin_md),
        ("docs/bom_and_enclosure.md", bom_enc_md),
        ("docs/power_budget.md", power_md),
        ("docs/rf_link_budget.md", link_md),
        ("docs/bringup_report.md", bringup_md),
        ("docs/OPEN_ITEMS.md", open_items_md),
        ("cst_studio/README.md", cst_md),
        ("CITATION.cff", citation_cff),
        ("PCBWAY_TURNKEY_FABRICATION_SPECIFICATION.md", spec_md),
        ("CPL_README.md", cpl_md),
    ):
        for bad in BANNED_LEGACY_TOKENS:
            if bad in content:
                errors.append(f"[LEGACY DRIFT] Stale token {bad!r} present in {doc_label}!")

    # Link & GitHub MathML hygiene audit across active Markdown files
    for md_path, md_txt in (
        (README_MD, readme_md),
        (SUMMARY_MD, sum_md),
        (RF_SIM_MD, rf_sim_md),
        (FW_PIN_MD, fw_pin_md),
        (BOM_ENC_MD, bom_enc_md),
        (POWER_MD, power_md),
        (LINK_BUDGET_MD, link_md),
        (BRINGUP_MD, bringup_md),
        (OPEN_ITEMS_MD, open_items_md),
        (CST_MD, cst_md),
    ):
        _audit_markdown_links_and_math(md_path, md_txt, errors)

    # Pilot bring-up checklist verification in bringup_report.md
    for pilot_tok in ("5–10", "Pilot", "B-07", "B-06", "B-04", "TP1", "TP2", "TP3", "TP4", "TP5"):
        if pilot_tok not in bringup_md:
            errors.append(f"[BRINGUP] Token {pilot_tok!r} missing from docs/bringup_report.md!")

    # Live PCB & Turnkey ZIP counts and BOM table
    board = pcbnew.LoadBoard(PCB_PATH)
    n_footprints = len(board.GetFootprints())
    n_vias = sum(1 for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA))
    n_board_only = sum(1 for fp in board.GetFootprints() if (fp.GetAttributes() & pcbnew.FP_BOARD_ONLY))

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        bom_csv_txt = zf.read("bom/ISAC_868_Turnkey_BOM.csv").decode("utf-8")
        cpl_csv_txt = zf.read("cpl/ISAC_868_Turnkey_CPL_Top.csv").decode("utf-8")
        gbrjob = json.loads(zf.read("gerbers/ISAC_868_KiCad9-job.gbrjob").decode("utf-8"))

    bom_rows = list(csv.DictReader(io.StringIO(bom_csv_txt)))
    cpl_rows = list(csv.DictReader(io.StringIO(cpl_csv_txt)))
    pop_bom_rows = [r for r in bom_rows if r["DNP"].strip() == "No"]
    dnp_bom_rows = [r for r in bom_rows if r["DNP"].strip() == "Yes"]
    n_pop_parts = sum(int(r["Qty"]) for r in pop_bom_rows)
    n_dnp_parts = sum(int(r["Qty"]) for r in dnp_bom_rows)

    if len(cpl_rows) != n_pop_parts or len(cpl_rows) != 67:
        errors.append(
            f"[CPL COUNT] Expected {n_pop_parts} populated pure-SMD parts (67 SMD, 0 THT), "
            f"found SMD={len(cpl_rows)}!"
        )

    # 1. Executive tokens required in BOTH README.md and Summary MD
    exec_tokens = [
        f"Rev {dv['revision']}",
        gbrjob["GeneralSpecs"]["Finish"],
        "RAK3172LP-SIP-8-SM-NI",
        "RT0402BRD078R2L",
        "LT5538IDD#TRPBF",
        "AO3401A",
        "ASA/PETG",
        "467MP",
        f"{dv['air_to_ice_sensitivity_MHz_per_RIU']:.2f} MHz/RIU",
        f"{dv['mc_air_to_ice_contrast_p01_dB']:.2f} dB",
    ]
    for row_m in dv["table"]:
        exec_tokens.extend([
            f"{row_m['f_res_MHz']:.1f}",
            f"{row_m['tilt_dB']:+.2f}",
            f"{row_m['level_dBm']:.2f}",
        ])
    for tok in exec_tokens:
        if tok not in readme_md:
            errors.append(f"[README PARITY] Token {tok!r} missing from README.md!")
        if tok not in sum_md:
            errors.append(f"[SUMMARY PARITY] Token {tok!r} missing from Summary MD!")

    for count_tok in (f"`{n_footprints}`", f"`{n_pop_parts}`", f"`{n_dnp_parts}`", f"`{n_board_only}`", f"`{n_vias}`"):
        if count_tok not in readme_md:
            errors.append(f"[README COUNT] Footprint/via token {count_tok!r} missing from README.md!")

    # 2. Subsystem component MPNs verified in Summary MD and modular docs/bom_and_enclosure.md
    for mpn_tok in (
        "LQH2MCN150K02L",
        "TPS7A0233DBVR",
        "TPS22919DCKR",
        "NX3008CBKS,115",
        "GJM1555C1H3R6WB01D",
        "LQW15AN8N2G00D",
        "GJM1555C1HR50WB01D",
        "GJM1555C1H4R3WB01D",
    ):
        if mpn_tok not in sum_md:
            errors.append(f"[SUMMARY MPN] Token {mpn_tok!r} missing from Summary MD!")
        if mpn_tok not in bom_enc_md:
            errors.append(f"[BOM DOC MPN] Token {mpn_tok!r} missing from docs/bom_and_enclosure.md!")

    # 3. FPort = 10 wire contract & U1 pin-number parity inside docs/firmware_and_pinmap.md
    for fport_tok in ("state_flags", "tilt_db_x100", "level_dbm_x100", "eps_est_x100", "vbat_mv", "notch_db_x10"):
        if fport_tok not in fw_pin_md:
            errors.append(f"[FW DOC PAYLOAD] Field {fport_tok!r} missing from docs/firmware_and_pinmap.md!")

    for m_pin in re.finditer(r"^\s*#define\s+ISAC_SIP_PIN_([A-Z0-9_]+)\s+(\d+)U?\b", fw_pins, re.M):
        sig, pnum = m_pin.group(1), m_pin.group(2)
        if sig in ("SWDIO", "SWCLK", "DET_ADC", "BAT_SENSE", "RF_OUT", "BOOT0", "NRST", "DET_EN", "BAT_MON_EN"):
            if f"**`{pnum}`**" not in fw_pin_md:
                errors.append(f"[FW PIN PARITY] U1 Pin {pnum} ({sig}) missing from docs/firmware_and_pinmap.md!")

    # 4. 1:1 46-row BOM table parity between docs/bom_and_enclosure.md and Turnkey BOM CSV
    md_bom = _parse_markdown_bom_rows(bom_enc_md)
    if len(md_bom) != len(bom_rows):
        errors.append(f"[BOM DOC] Expected {len(bom_rows)} BOM rows in docs/bom_and_enclosure.md, found {len(md_bom)}")
    else:
        for csv_r, md_r in zip(bom_rows, md_bom):
            item_no = int(csv_r["Item"])
            csv_refs = _split_refs(csv_r["Designators"])
            if (
                md_r["Item"] != item_no
                or md_r["Designators"] != csv_refs
                or md_r["Qty"] != int(csv_r["Qty"])
                or md_r["MPN"] != csv_r["MPN"].strip()
                or md_r["LCSC"] != csv_r["LCSC"].strip()
                or md_r["DNP"] != csv_r["DNP"].strip()
            ):
                errors.append(f"[BOM DOC] Item {item_no} mismatch: MD={md_r} vs CSV={csv_r}")

    # 5. Verify all 11 visual inspection sheets in docs/ exist, are non-empty, and up-to-date
    pcb_mtime = os.path.getmtime(PCB_PATH)
    for vname in REQUIRED_DOCS_VISUALS:
        vpath = os.path.join(DOCS_DIR, vname)
        if not os.path.isfile(vpath):
            errors.append(f"[DOCS VISUAL] Missing visual inspection sheet: {vpath}")
            continue
        sz = os.path.getsize(vpath)
        if sz < 10_000:
            errors.append(f"[DOCS VISUAL] Visual sheet {vname} suspiciously small ({sz} bytes)")
        if vname.endswith((".pdf", ".png")) and os.path.getmtime(vpath) + 30.0 < pcb_mtime:
            errors.append(f"[DOCS STALE] {vname} is stale relative to .kicad_pcb!")

    print(
        f"[DOC PARITY] Verified Rev E.5 Summary MD+PDF, executive README.md ({readme_lines} lines), "
        f"3 modular docs/ manuals ({len(md_bom)}/{len(bom_rows)} BOM rows), CITATION.cff, "
        f"RF/EM JSONs (0.00 MHz / <=0.01 dB), links/MathML, 0 legacy tokens, "
        f"{len(REQUIRED_DOCS_VISUALS)}/11 visual sheets, CPL={len(cpl_rows)} pure-SMD parts."
    )

    if errors:
        sys.stderr.write(f"\n[DOC PARITY FAILED] {len(errors)} violation(s) detected:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    print("[DOC PARITY PASS] 100% Rev E.5 layered documentation, link, MathML & hardware parity confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_doc_parity_audit())
