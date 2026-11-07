#!/usr/bin/env python3
"""
Multi-Domain Design Consistency Verifier (`Rev E.5`)
====================================================
Cross-checks exported manufacturing, CAD, Gerber, Drill, BOM, CPL, and firmware
artefacts independently of the schematic/PCB generator scripts:

  1. Schematic Netlist (`.net`) <-> PCB (`.kicad_pcb`) <-> Turnkey BOM (`.csv`)
     <-> Turnkey CPL (`.csv`, F.Cu pad-array IPC-7351 centroids)
  2. Gerber `.gbrjob` (`ENIG`), `B_Paste.gbp` (`0` apertures), `F/B_Silkscreen`
     (`0` non-`AE1` ink in `X > 50.0 mm` antenna keepout), Excellon `-PTH.drl` /
     `-NPTH.drl`, `SHA256SUMS.txt`, and working-tree cache hygiene
  3. Firmware source & compiled `.elf` / `.bin` scan confirming no hardcoded
     test `AppKey` bytes and presence of NVM + boot self-test symbols
"""

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile

import pcbnew

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCH_PATH = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_sch")
PCB_PATH = os.path.join(ROOT, "ISAC_868_KiCad9.kicad_pcb")
ZIP_PATH = os.path.join(ROOT, "fab", "ISAC_868_RevE5_PCBWay_Turnkey.zip")
ELF_PATH = os.path.join(ROOT, "firmware", "build", "isac_rak3172lp_sip.elf")
BIN_PATH = os.path.join(ROOT, "firmware", "build", "isac_rak3172lp_sip.bin")

AUX_X_MM = 103.5
AUX_Y_MM = 120.0

TEST_KEY_ASCII = "2b7e151628aed2a6abf7158809cf4f3c"
TEST_KEY_BYTES = bytes.fromhex(TEST_KEY_ASCII)


def _split_refs(s):
    return [r.strip() for r in s.split(",") if r.strip()]


def _parse_excellon_hits(drl_text):
    tools = {}
    cur_tool = None
    hits = []
    for raw in drl_text.splitlines():
        line = raw.strip()
        m_def = re.match(r"^(T\d+)C([0-9.]+)", line)
        if m_def:
            tools[m_def.group(1)] = float(m_def.group(2))
            continue
        if line in tools:
            cur_tool = line
            continue
        m_xy = re.match(r"^X(-?[0-9.]+)Y(-?[0-9.]+)$", line)
        if m_xy and cur_tool is not None:
            hits.append((tools[cur_tool], float(m_xy.group(1)), float(m_xy.group(2))))
    return hits


def _max_silkscreen_x_mm(gbr_text):
    fmt_m = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", gbr_text)
    dec_x = int(fmt_m.group(2)) if fmt_m else 6
    scale = 10.0 ** (-dec_x)
    max_x = 0.0
    coord_re = re.compile(r"X(-?\d+)Y(-?\d+).*?D0([13])\*")
    for raw in gbr_text.splitlines():
        s = raw.strip()
        m = coord_re.search(s)
        if m:
            x_mm = int(m.group(1)) * scale
            if x_mm > max_x:
                max_x = x_mm
    return max_x


def _parse_netlist_components(net_text):
    comps = {}
    pos = 0
    marker = "(comp (ref "
    while True:
        idx = net_text.find(marker, pos)
        if idx < 0:
            break
        depth = 0
        end = idx
        in_str = False
        while end < len(net_text):
            ch = net_text[end]
            if ch == '"' and (end == 0 or net_text[end - 1] != "\\"):
                in_str = not in_str
            elif not in_str:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end += 1
                        break
            end += 1
        blk = net_text[idx:end]
        pos = end
        m_ref = re.search(r'\(comp\s+\(ref\s+"([^"]+)"\)', blk)
        if not m_ref:
            continue
        ref = m_ref.group(1)
        m_val = re.search(r'\(value\s+"([^"]*)"\)', blk)
        m_mpn = re.search(r'\(property\s+\(name\s+"MPN"\)\s+\(value\s+"([^"]*)"\)\)', blk)
        is_dnp = bool(re.search(r"\(dnp\)", blk)) or bool(
            re.search(r'\(property\s+\(name\s+"dnp"\)\s+\(value\s+"1"\)\)', blk, re.I)
        )
        comps[ref] = {
            "value": m_val.group(1) if m_val else "",
            "mpn": m_mpn.group(1) if m_mpn else "",
            "dnp": is_dnp,
        }
    return comps


def _fp_pad_centroid_aux(fp):
    xmins, xmaxs, ymins, ymaxs = [], [], [], []
    for pad in fp.Pads():
        bb = pad.GetBoundingBox()
        xmins.append(pcbnew.ToMM(bb.GetLeft()) - AUX_X_MM)
        xmaxs.append(pcbnew.ToMM(bb.GetRight()) - AUX_X_MM)
        ymins.append(AUX_Y_MM - pcbnew.ToMM(bb.GetBottom()))
        ymaxs.append(AUX_Y_MM - pcbnew.ToMM(bb.GetTop()))
    if not xmins:
        pos = fp.GetPosition()
        return pcbnew.ToMM(pos.x) - AUX_X_MM, AUX_Y_MM - pcbnew.ToMM(pos.y)
    return 0.5 * (min(xmins) + max(xmaxs)), 0.5 * (min(ymins) + max(ymaxs))


def main():
    errors = []

    for req in (SCH_PATH, PCB_PATH, ZIP_PATH, ELF_PATH, BIN_PATH):
        if not os.path.isfile(req):
            errors.append(f"[MISSING] Required file not found: {req}")
    if errors:
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1

    # 1. Working-tree & Turnkey ZIP hygiene check (zero .pyc / __pycache__ / .bak anywhere in repo)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if "/.git" in dirpath or dirpath.endswith("/.git"):
            continue
        if "__pycache__" in dirnames:
            rel_d = os.path.relpath(os.path.join(dirpath, "__pycache__"), ROOT)
            errors.append(f"[HYGIENE] Forbidden __pycache__ directory in repository: {rel_d}")
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo", ".bak", "~")) or fn == ".DS_Store":
                rel_f = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                errors.append(f"[HYGIENE] Forbidden artifact file in repository: {rel_f}")

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        znames = zf.namelist()
        for zn in znames:
            if zn.endswith((".pyc", ".pyo", ".bak", "~")) or "__pycache__" in zn or ".DS_Store" in zn:
                errors.append(f"[ZIP HYGIENE] Forbidden file packaged inside Turnkey ZIP: {zn}")

        if "SHA256SUMS.txt" not in znames:
            errors.append("[ZIP] Missing SHA256SUMS.txt inside Turnkey ZIP")
        else:
            sha_txt = zf.read("SHA256SUMS.txt").decode("utf-8")
            sha_map = {}
            for ln in sha_txt.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                digest, relp = ln.split(None, 1)
                relp = relp.lstrip("*./")
                sha_map[relp] = digest
                if relp not in znames:
                    errors.append(f"[SHA256] Listed file missing from ZIP: {relp}")
                else:
                    actual = hashlib.sha256(zf.read(relp)).hexdigest()
                    if actual != digest:
                        errors.append(f"[SHA256] Digest mismatch for {relp}: {actual} != {digest}")
            for zn in znames:
                if zn != "SHA256SUMS.txt" and zn not in sha_map:
                    errors.append(f"[SHA256] Unlisted file inside Turnkey ZIP: {zn}")

        bom_rows = list(csv.DictReader(io.StringIO(zf.read("bom/ISAC_868_Turnkey_BOM.csv").decode("utf-8"))))
        cpl_rows = list(csv.DictReader(io.StringIO(zf.read("cpl/ISAC_868_Turnkey_CPL_Top.csv").decode("utf-8"))))
        if "cpl/ISAC_868_Turnkey_THT.csv" in znames:
            errors.append("[ZIP CPL] Unexpected cpl/ISAC_868_Turnkey_THT.csv inside 100% pure-SMD Turnkey ZIP!")
        net_txt = zf.read("netlist/ISAC_868_KiCad9.net").decode("utf-8")
        gbrjob = json.loads(zf.read("gerbers/ISAC_868_KiCad9-job.gbrjob").decode("utf-8"))
        if any(zn.endswith("-B_Paste.gbp") for zn in znames):
            errors.append("[B_PASTE] Unexpected *-B_Paste.gbp inside Turnkey ZIP (Option 2A omits B.Paste)!")
        fsilk = zf.read("gerbers/ISAC_868_KiCad9-F_Silkscreen.gto").decode("utf-8")
        bsilk = zf.read("gerbers/ISAC_868_KiCad9-B_Silkscreen.gbo").decode("utf-8")
        pth_drl = zf.read("gerbers/ISAC_868_KiCad9-PTH.drl").decode("utf-8")
        npth_drl = zf.read("gerbers/ISAC_868_KiCad9-NPTH.drl").decode("utf-8")

    # 2. Schematic Netlist <-> PCB <-> BOM <-> CPL Parity
    net_comps = _parse_netlist_components(net_txt)
    board = pcbnew.LoadBoard(PCB_PATH)

    pcb_pop = {}
    pcb_dnp = {}
    pcb_board_only = set()
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        attr = fp.GetAttributes()
        cx, cy = _fp_pad_centroid_aux(fp)
        if attr & pcbnew.FP_BOARD_ONLY:
            pcb_board_only.add(ref)
        elif attr & pcbnew.FP_DNP:
            pcb_dnp[ref] = (cx, cy, fp.GetValue())
        else:
            pcb_pop[ref] = (cx, cy, fp.GetValue())

    if len(pcb_pop) != 67 or len(pcb_dnp) != 10 or len(pcb_board_only) != 15:
        errors.append(
            f"[PCB COUNTS] Expected 67 pop + 10 DNP + 15 board_only = 92, "
            f"got {len(pcb_pop)} + {len(pcb_dnp)} + {len(pcb_board_only)} = {len(board.GetFootprints())}"
        )

    expected_dnp = {"C_SMPS3", "D_RF", "J1", "J2", "J3", "J4", "J5", "R_DIV1", "R_DIV2", "R_VUART"}
    if set(pcb_dnp.keys()) != expected_dnp:
        errors.append(f"[PCB DNP] Expected DNP={sorted(expected_dnp)}, got {sorted(pcb_dnp.keys())}")

    all_pcb_refs = set(pcb_pop.keys()) | set(pcb_dnp.keys()) | pcb_board_only
    if set(net_comps.keys()) != all_pcb_refs:
        errors.append(
            f"[SCH<->PCB] 92-symbol parity mismatch: only_in_sch={sorted(set(net_comps.keys()) - all_pcb_refs)}, "
            f"only_in_pcb={sorted(all_pcb_refs - set(net_comps.keys()))}"
        )

    # Cross-check BOM CSV vs PCB
    bom_pop_refs = set()
    bom_dnp_refs = set()
    for r in bom_rows:
        refs = _split_refs(r["Designators"])
        if len(refs) != int(r["Qty"]):
            errors.append(f"[BOM QTY] Item {r['Item']} Qty={r['Qty']} != len(refs)={len(refs)}")
        if r["DNP"].strip() == "Yes":
            bom_dnp_refs.update(refs)
        else:
            bom_pop_refs.update(refs)

    if bom_pop_refs != set(pcb_pop.keys()):
        errors.append(f"[BOM<->PCB POP] Mismatch: {sorted(bom_pop_refs ^ set(pcb_pop.keys()))}")
    if bom_dnp_refs != set(pcb_dnp.keys()):
        errors.append(f"[BOM<->PCB DNP] Mismatch: {sorted(bom_dnp_refs ^ set(pcb_dnp.keys()))}")

    # Cross-check 100% pure-SMD CPL CSV (67, 0 THT parts) vs PCB populated parts (67)
    cpl_map = {r["Ref"].strip(): r for r in cpl_rows}
    if "J2" in cpl_map:
        errors.append("[CPL J2 DNP] DNP battery header J2 leaked into pure-SMD CPL CSV!")
    expected_cpl_refs = set(pcb_pop.keys())
    if set(cpl_map.keys()) != expected_cpl_refs or len(cpl_map) != 67:
        errors.append(
            f"[CPL<->PCB] Expected 67 pure-SMD populated refs, diff={sorted(set(cpl_map.keys()) ^ expected_cpl_refs)}"
        )
    for dnp_r in pcb_dnp:
        if dnp_r in cpl_map:
            errors.append(f"[CPL DNP LEAK] DNP part {dnp_r} present in CPL!")

    bench_csv_path = os.path.join(ROOT, "fab", "cpl", "ISAC_868_Bench_THT_HandSolder.csv")
    if not os.path.isfile(bench_csv_path):
        errors.append(f"[BENCH CSV] Missing companion {bench_csv_path}")
    else:
        bench_rows = list(csv.DictReader(open(bench_csv_path, "r", encoding="utf-8")))
        if {r["Ref"] for r in bench_rows} != {"J1", "J2", "J3", "J4", "J5"}:
            errors.append(f"[BENCH CSV] Expected J1..J5 in {bench_csv_path}, got {[r['Ref'] for r in bench_rows]}")

    max_cpl_err = 0.0
    for ref, crow in cpl_map.items():
        mx = float(crow["PosX"])
        my = float(crow["PosY"])
        px, py, _ = pcb_pop[ref]
        err = ((mx - px) ** 2 + (my - py) ** 2) ** 0.5
        if err > max_cpl_err:
            max_cpl_err = err
        if err > 0.005:
            errors.append(f"[CPL COORD] {ref} CPL=({mx:.4f},{my:.4f}) vs PCB_pad_bbox=({px:.4f},{py:.4f}) err={err:.4f}mm")

    # 3. Gerber / Drill / Finish / Antenna Silkscreen Keepout Checks (100% zero silk in X >= 50 mm!)
    if gbrjob.get("GeneralSpecs", {}).get("Finish") != "ENIG":
        errors.append(f"[GBRJOB] Surface finish must be ENIG, got {gbrjob.get('GeneralSpecs', {}).get('Finish')!r}")

    max_fsilk_x = _max_silkscreen_x_mm(fsilk)
    max_bsilk_x = _max_silkscreen_x_mm(bsilk)
    if max_fsilk_x >= 50.0 or max_bsilk_x >= 50.0:
        errors.append(
            f"[SILK KEEPOUT] Silkscreen ink encroaches into X >= 50.0 mm antenna zone "
            f"(F.Silk Gerber max_x={max_fsilk_x:.2f} mm, B.Silk Gerber max_x={max_bsilk_x:.2f} mm)!"
        )

    pth_hits = _parse_excellon_hits(pth_drl)
    npth_hits = _parse_excellon_hits(npth_drl)
    via_hits = [h for h in pth_hits if abs(h[0] - 0.30) < 0.01]
    tht_hits = [h for h in pth_hits if h[0] >= 0.70]
    if len(via_hits) != 131 or len(tht_hits) != 13 or len(npth_hits) != 4:
        errors.append(
            f"[DRILLS] Expected 131x0.30mm vias + 13 THT + 4 NPTH, "
            f"got vias={len(via_hits)}, tht={len(tht_hits)}, npth={len(npth_hits)}"
        )

    # 4. Firmware Provisioning-Key Hygiene & Symbol Check
    for sub in ("src", "include"):
        sdir = os.path.join(ROOT, "firmware", sub)
        for fn in os.listdir(sdir):
            if fn.endswith((".c", ".h")):
                txt = open(os.path.join(sdir, fn), "r", encoding="utf-8").read().lower()
                if "2b7e1516" in txt or "0x2b, 0x7e" in txt:
                    errors.append(f"[FW KEY LEAK] Hardcoded test key pattern found in firmware/{sub}/{fn}!")

    for bpath in (ELF_PATH, BIN_PATH):
        blob = open(bpath, "rb").read()
        if TEST_KEY_BYTES in blob or TEST_KEY_ASCII.encode("ascii") in blob.lower():
            errors.append(f"[FW BIN LEAK] Test AppKey bytes present in compiled binary {os.path.basename(bpath)}!")

    nm_proc = subprocess.run(["arm-none-eabi-nm", ELF_PATH], capture_output=True, text=True)
    if nm_proc.returncode != 0:
        errors.append(f"[FW NM] arm-none-eabi-nm failed on {ELF_PATH}")
    else:
        nm_out = nm_proc.stdout
        for sym in (
            "ISAC_NVM_ReadProvision",
            "ISAC_NVM_LoadSession",
            "ISAC_NVM_SaveSession",
            "ISAC_HAL_DelayUs",
            "ISAC_HAL_GPIO_SetBatMonEnable",
            "ISAC_HAL_SubGhz_EnsureAwake",
            "ISAC_HAL_ADC_ReadDieTempDegCx10",
            "ISAC_Sensing_SetCalibration2Pt",
            "ISAC_LoRaWAN_NextJoinBackoffMs",
            "g_selftest_report",
            "g_reset_cause",
        ):
            if sym not in nm_out:
                errors.append(f"[FW SYM] Required symbol {sym!r} missing from {os.path.basename(ELF_PATH)}!")

    print(
        f"[CROSS-CHECK E.5] Sch=92 == PCB=(67 pop + 10 DNP + 15 board_only) | "
        f"BOM={len(bom_rows)} lines | CPL={len(cpl_rows)} pure-SMD (max_err={max_cpl_err:.4f}mm) | "
        f"Drills={len(via_hits)}v+{len(tht_hits)}tht+{len(npth_hits)}npth | "
        f"Silk_maxX=({max_fsilk_x:.2f},{max_bsilk_x:.2f})mm <50.0 | B_Paste=omitted | FW keys=0."
    )

    if errors:
        sys.stderr.write(f"\n[CROSS-CHECK FAILED] {len(errors)} violation(s):\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    print("[CONSISTENCY PASS] Rev E.5 schematic, PCB, BOM, CPL, Gerber, and firmware checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
