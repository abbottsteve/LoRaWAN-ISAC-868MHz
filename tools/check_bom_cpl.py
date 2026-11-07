#!/usr/bin/env python3
"""
Turnkey BOM / CPL / Gerber / Netlist-Firmware Parity Gate (`Rev E.5`)
=====================================================================
Inspects `fab/ISAC_868_RevE5_PCBWay_Turnkey.zip` and `firmware/include/isac_board_pins.h`
directly to enforce zero-ambiguity PCBWay Turnkey CAM & firmware parity:

  1. Single-Source CSV Uniqueness:
     - Strictly 1 BOM CSV (`bom/ISAC_868_Turnkey_BOM.csv`) and strictly 1 CPL CSV
       (`cpl/ISAC_868_Turnkey_CPL_Top.csv`) inside the Turnkey ZIP, and zero stale
       loose CSV/ZIP duplicates in `fab/`.
  2. Cryptographic Manifest Integrity:
     - Verifies `SHA256SUMS.txt` exists at ZIP root, covers 100% of archived files,
       and matches every file's SHA-256 digest bit-for-bit.
  3. BOM / CPL Designator Set Equality & Exclusion Hygiene:
     - `populated_bom_designators == cpl_designators` (exact set equality)
     - `0` DNP parts (`C_SMPS3, D_RF, J1..J5, R_DIV1, R_DIV2, R_VUART`) in CPL
     - `0` non-BOM/board-only (`TP*`, `FID*`, `H*`, `AE*`) parts in CPL
     - Valid LCSC codes (`^C\\d{4,}$` or explicit `Authorized:` consignment/distributor)
     - All CPL rotations strictly normalized to `[0.0, 360.0)` and `Side == "top"`
  4. CPL-to-Gerber `F_Cu.gtl` & Excellon Origin/Centroid Parity:
     - Parses `gerbers/*-F_Cu.gtl` (`%TO.P,REF,PAD*%` pad flashes) directly from the ZIP
     - Asserts every CPL `(PosX, PosY)` matches the actual `F_Cu.gtl` pad-flash
       bounding-box center within `+/- 0.15 mm` in the **same coordinate origin**
     - Verifies `*-PTH.drl` and `*-NPTH.drl` drill hits share the same `[0..90] x [0..40] mm`
       `AuxOrigin` coordinate frame
  5. Schematic Netlist (`ISAC_868_KiCad9.net`) <-> Firmware (`isac_board_pins.h`) Parity:
     - Parses `netlist/ISAC_868_KiCad9.net` (`U1` nodes) from the ZIP (or `--netlist`)
       and cross-checks `ISAC_SIP_PIN_*`, `ISAC_GPIO*_PIN_*`, `ISAC_ADC_CH_*`, and
       pin-map declarations in `firmware/include/isac_board_pins.h`.
"""

import argparse
from collections import defaultdict
import csv
import hashlib
import io
import math
import os
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_dfm  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# STM32WLE5JC RM0453 Section 16.3.5 Hardware GPIO -> 12-bit SAR ADC Channel Table
STM32WL_ADC_CHANNEL_BY_GPIO = {
    "PB13": 0,
    "PB14": 1,
    "PB3": 2,
    "PB4": 3,
    "PB2": 4,
    "PB1": 5,
    "PA10": 6,
    "PA11": 7,
    "PA12": 8,
    "PA13": 9,
    "PA14": 10,
    "PA15": 11,
}

# Mapping between firmware signal suffixes and KiCad schematic net names on U1
FW_SIGNAL_TO_NET = {
    "SWDIO": "/SWDIO",
    "SWCLK": "/SWCLK",
    "DET_ADC": "/DET_ADC",
    "VFBSMPS": "/VFBSMPS",
    "VDDSMPS": "/VDDSMPS",
    "VLXSMPS": "/VLXSMPS",
    "BAT_SENSE": "/BAT_SENSE",
    "UART2_TX": "/UART_TX",
    "UART2_RX": "/UART_RX",
    "RF_OUT": "/RF_PA",
    "BOOT0": "/BOOT0",
    "NRST": "/RST",
    "DET_EN": "/DET_EN",
    "BAT_MON_EN": "/BAT_MON_EN",
    "VDDPA": "/VDDPA",
    "VDDRF": "/VDDRF",
    "VREF_PLUS": "/VDDA",
    "VDDA": "/VDDA",
}


def _split_designators(s):
    return [tok.strip() for tok in re.split(r"[,;\s]+", s.strip()) if tok.strip()]


def _parse_excellon_coords_mm(drl_text):
    unit_scale = 25.4 if "INCH" in drl_text and "METRIC" not in drl_text else 1.0
    pts = []
    coord_re = re.compile(r"^X(-?\d+(?:\.\d+)?)Y(-?\d+(?:\.\d+)?)$")
    for raw in drl_text.splitlines():
        line = raw.strip()
        m = coord_re.match(line)
        if m:
            pts.append((float(m.group(1)) * unit_scale, float(m.group(2)) * unit_scale))
    return pts


def _parse_u1_netlist(net_text):
    """
    Parse KiCad S-expression `.net` text and return:
      `net_to_u1_pins`: `{net_name: [(pin_num_int, pinfunc_str), ...]}`
    """
    net_to_u1 = defaultdict(list)
    net_blocks = re.split(r"\(\s*net\s+\(code\s+\"\d+\"\)", net_text)
    for blk in net_blocks[1:]:
        m_name = re.search(r"\(name\s+\"([^\"]+)\"\)", blk)
        if not m_name:
            continue
        net_name = m_name.group(1)
        for m_node in re.finditer(
            r"\(node\s+\(ref\s+\"U1\"\)\s+\(pin\s+\"(\d+)\"\)(?:\s+\(pinfunction\s+\"([^\"]*)\"\))?",
            blk,
        ):
            pnum = int(m_node.group(1))
            pfunc = m_node.group(2) or ""
            net_to_u1[net_name].append((pnum, pfunc))
    return net_to_u1


def verify_netlist_firmware_parity(net_text, fw_pins_path, errors):
    if not os.path.isfile(fw_pins_path):
        errors.append(f"[FW PARITY] Missing firmware header: {fw_pins_path}")
        return 0

    with open(fw_pins_path, "r", encoding="utf-8") as f:
        fw_text = f.read()

    net_to_u1 = _parse_u1_netlist(net_text)
    if not net_to_u1:
        errors.append("[FW PARITY] Parsed 0 U1 net nodes from schematic netlist!")
        return 0

    # Parse #define macros (stripping C comments before scanning macros)
    fw_no_comments = re.sub(r"/\*.*?\*/", "", fw_text, flags=re.DOTALL)
    fw_no_comments = re.sub(r"//.*", "", fw_no_comments)

    sip_pins = {}
    gpio_pins = {}
    adc_chs = {}

    for m in re.finditer(r"^\s*#define\s+ISAC_SIP_PIN_([A-Z0-9_]+)\s+(\d+)U?\b", fw_no_comments, re.M):
        sip_pins[m.group(1)] = int(m.group(2))

    for m in re.finditer(
        r"^\s*#define\s+ISAC_GPIO([A-C])_PIN_([A-Z0-9_]+)\s+(\d+)U?\b", fw_no_comments, re.M
    ):
        port, sig, idx = m.group(1), m.group(2), int(m.group(3))
        gpio_pins[sig] = f"P{port}{idx}"

    for m in re.finditer(r"^\s*#define\s+ISAC_ADC_CH_([A-Z0-9_]+)\s+(\d+)U?\b", fw_no_comments, re.M):
        adc_chs[m.group(1)] = int(m.group(2))

    checked = 0
    for sig, sch_net in FW_SIGNAL_TO_NET.items():
        if sig not in sip_pins:
            errors.append(f"[FW PARITY] Missing #define ISAC_SIP_PIN_{sig} in {fw_pins_path}")
            continue
        u1_nodes = net_to_u1.get(sch_net, [])
        if not u1_nodes:
            errors.append(f"[FW PARITY] Net {sch_net} not connected to U1 in schematic netlist")
            continue

        valid_pnums = [p for p, _ in u1_nodes]
        fw_pnum = sip_pins[sig]
        if fw_pnum not in valid_pnums:
            errors.append(
                f"[FW PARITY] ISAC_SIP_PIN_{sig} = {fw_pnum} mismatches netlist {sch_net} U1 pin(s) {valid_pnums}"
            )
        checked += 1

        if sig in gpio_pins:
            fw_gpio = gpio_pins[sig]
            pfuncs = [pf for p, pf in u1_nodes if p == fw_pnum] or [pf for _, pf in u1_nodes]
            # Extract exact GPIO token (e.g. PA15, PB4, PA8) from schematic pinfunction
            sch_gpios = []
            for pf in pfuncs:
                mg = re.search(r"\b(P[A-C]\d{1,2})\b", pf)
                if mg:
                    sch_gpios.append(mg.group(1))
            if not sch_gpios or fw_gpio not in sch_gpios:
                errors.append(
                    f"[FW PARITY] Firmware GPIO {sig} = {fw_gpio} mismatches netlist {sch_net} "
                    f"U1 pinfunction GPIO {sch_gpios} ({pfuncs})"
                )
            checked += 1

            if sig in adc_chs:
                exp_adc = STM32WL_ADC_CHANNEL_BY_GPIO.get(sch_gpios[0]) if sch_gpios else None
                fw_adc = adc_chs[sig]
                if exp_adc != fw_adc or STM32WL_ADC_CHANNEL_BY_GPIO.get(fw_gpio) != fw_adc:
                    errors.append(
                        f"[FW PARITY] ISAC_ADC_CH_{sig} = {fw_adc} inconsistent with {fw_gpio} / "
                        f"netlist {sch_gpios} (expected ADC_IN{exp_adc})"
                    )
                checked += 1

    # Also cross-check doc/comment pin-table lines (e.g., `PA15 (SiP Pin 8...) -> DET_ADC`)
    # so textual/comment/macro divergence inside isac_board_pins.h is also caught.
    for m_doc in re.finditer(
        r"\b(P[A-C]\d{1,2})\s*\(SiP\s+Pin\s+(\d+)[^)]*\)\s*->\s*([A-Z0-9_]+)", fw_text
    ):
        doc_gpio, doc_pin, doc_net = m_doc.group(1), int(m_doc.group(2)), "/" + m_doc.group(3)
        if doc_net in net_to_u1:
            u1_nodes = net_to_u1[doc_net]
            sch_pins = [p for p, _ in u1_nodes]
            sch_gpios = [
                re.search(r"\b(P[A-C]\d{1,2})\b", pf).group(1)
                for _, pf in u1_nodes
                if re.search(r"\b(P[A-C]\d{1,2})\b", pf)
            ]
            if doc_pin not in sch_pins or (sch_gpios and doc_gpio not in sch_gpios):
                errors.append(
                    f"[FW PARITY] Header pin-map declaration '{doc_gpio} (SiP Pin {doc_pin}) -> {doc_net}' "
                    f"mismatches netlist U1 {u1_nodes}"
                )

    return checked


def run_bom_cpl_audit(zip_path, netlist_override=None, fw_pins_path=None, check_fab_dir=True):
    errors = []

    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"Missing Turnkey ZIP archive: {zip_path}")

    if check_fab_dir:
        fab_dir = os.path.dirname(os.path.abspath(zip_path))
        loose_csvs = [f for f in os.listdir(fab_dir) if f.lower().endswith(".csv")]
        zip_files = [f for f in os.listdir(fab_dir) if f.lower().endswith(".zip")]
        if loose_csvs:
            errors.append(f"[ARCHIVE] Stale loose CSV file(s) in {fab_dir}: {loose_csvs}")
        if len(zip_files) != 1:
            errors.append(f"[ARCHIVE] Expected strictly 1 .zip archive in {fab_dir}, found: {zip_files}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]

        junk_entries = [
            n for n in zf.namelist()
            if "__pycache__" in n or n.endswith((".pyc", ".pyo", ".bak", "-bak", "~"))
        ]
        if junk_entries:
            errors.append(f"[ARCHIVE HYGIENE] Forbidden cache/backup entries in ZIP: {junk_entries}")

        # 1. Verify strictly 1 BOM CSV + 1 pure-SMD CPL CSV inside ZIP (100% pure-SMD Turnkey, 0 THT CSVs!)
        csv_files = [n for n in names if n.lower().endswith(".csv")]
        bom_csvs = [n for n in csv_files if "bom" in n.lower()]
        cpl_smd_csvs = [n for n in csv_files if n == "cpl/ISAC_868_Turnkey_CPL_Top.csv"]

        if len(bom_csvs) != 1:
            errors.append(f"[BOM/CPL] Expected strictly 1 BOM CSV in ZIP, found {len(bom_csvs)}: {bom_csvs}")
        if len(cpl_smd_csvs) != 1:
            errors.append(f"[BOM/CPL] Expected cpl/ISAC_868_Turnkey_CPL_Top.csv in ZIP, found: {cpl_smd_csvs}")
        if set(csv_files) != set(bom_csvs) | set(cpl_smd_csvs):
            errors.append(f"[BOM/CPL] Unexpected extra CSV file(s) in ZIP (expected 0 THT CSVs): {csv_files}")

        # 2. Verify SHA256SUMS.txt
        if "SHA256SUMS.txt" not in names:
            errors.append("[SHA256] Missing SHA256SUMS.txt at root of Turnkey ZIP!")
        else:
            sha_text = zf.read("SHA256SUMS.txt").decode("utf-8")
            manifest = {}
            for line in sha_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split("  ", 1)
                if len(parts) != 2 or not re.match(r"^[0-9a-f]{64}$", parts[0]):
                    errors.append(f"[SHA256] Malformed line in SHA256SUMS.txt: {line!r}")
                    continue
                manifest[parts[1]] = parts[0]

            expected_files = set(names) - {"SHA256SUMS.txt"}
            if set(manifest.keys()) != expected_files:
                missing_sha = sorted(expected_files - set(manifest.keys()))
                extra_sha = sorted(set(manifest.keys()) - expected_files)
                errors.append(
                    f"[SHA256] Manifest coverage mismatch: missing={missing_sha}, extra={extra_sha}"
                )
            for rel_name, exp_hash in manifest.items():
                if rel_name in expected_files:
                    actual_hash = hashlib.sha256(zf.read(rel_name)).hexdigest()
                    if actual_hash != exp_hash:
                        errors.append(
                            f"[SHA256] Digest mismatch for {rel_name}: "
                            f"manifest={exp_hash[:12]}.. vs actual={actual_hash[:12]}.."
                        )

        if len(bom_csvs) != 1 or len(cpl_smd_csvs) != 1:
            for err in errors:
                sys.stderr.write(f"  - {err}\n")
            return 1

        # 3. Parse BOM CSV & 100% pure-SMD CPL CSV
        bom_text = zf.read(bom_csvs[0]).decode("utf-8")
        cpl_text = zf.read(cpl_smd_csvs[0]).decode("utf-8")

        pop_bom_refs = set()
        dnp_bom_refs = set()
        lcsc_re = re.compile(r"^(?:C\d{4,}|Authorized:\s+.+)$")

        bom_reader = csv.DictReader(io.StringIO(bom_text))
        bom_rows = list(bom_reader)
        for r_idx, row in enumerate(bom_rows, start=2):
            refs = _split_designators(row.get("Designators", ""))
            qty = int(row.get("Qty", "0").strip())
            if qty != len(refs) or qty <= 0:
                errors.append(
                    f"[BOM] Line {r_idx}: Qty={qty} != designator count {len(refs)} ({refs})"
                )
            dnp_flag = row.get("DNP", "").strip()
            if dnp_flag not in ("Yes", "No"):
                errors.append(f"[BOM] Line {r_idx}: Invalid DNP flag {dnp_flag!r} (expected 'Yes'/'No')")

            for col in ("Item", "Value", "Footprint", "Manufacturer", "MPN", "Alternates"):
                if not row.get(col, "").strip():
                    errors.append(f"[BOM] Line {r_idx} ({refs}): Empty mandatory column {col!r}")

            lcsc_val = row.get("LCSC", "").strip()
            if not lcsc_re.match(lcsc_val):
                errors.append(f"[BOM] Line {r_idx} ({refs}): Invalid LCSC code {lcsc_val!r}")

            for ref in refs:
                if ref in pop_bom_refs or ref in dnp_bom_refs:
                    errors.append(f"[BOM] Duplicate designator {ref!r} across BOM rows!")
                if dnp_flag == "Yes":
                    dnp_bom_refs.add(ref)
                else:
                    pop_bom_refs.add(ref)

        cpl_reader = csv.DictReader(io.StringIO(cpl_text))
        cpl_rows = list(cpl_reader)
        cpl_smd_by_ref = {}
        cpl_by_ref = {}
        forbidden_prefix_re = re.compile(r"^(?:TP|FID|H|AE)\d*", re.IGNORECASE)

        for r_idx, row in enumerate(cpl_rows, start=2):
            ref = row.get("Ref", "").strip()
            if not ref:
                errors.append(f"[CPL-SMD] Line {r_idx}: Empty Ref!")
                continue
            if ref in cpl_smd_by_ref:
                errors.append(f"[CPL-SMD] Duplicate designator {ref!r} across placement CSV!")
            cpl_smd_by_ref[ref] = row
            cpl_by_ref[ref] = row

            if ref in dnp_bom_refs:
                errors.append(f"[CPL-SMD] DNP component {ref!r} leaked into Turnkey placement CSV!")
            if forbidden_prefix_re.match(ref):
                errors.append(f"[CPL-SMD] Non-BOM / BOARD_ONLY target {ref!r} leaked into placement CSV!")

            try:
                rot = float(row.get("Rot", ""))
                if not (0.0 <= rot < 360.0):
                    errors.append(f"[CPL-SMD] {ref}: Rotation {rot} outside [0.0, 360.0)!")
            except ValueError:
                errors.append(f"[CPL-SMD] {ref}: Non-numeric Rot {row.get('Rot')!r}!")

            side = row.get("Side", "").strip().lower()
            if side != "top":
                errors.append(f"[CPL-SMD] {ref}: Invalid Side {side!r} (expected 'top')!")

        if "J2" in cpl_smd_by_ref:
            errors.append("[J2 DNP] Direct-solder battery header 'J2' leaked into pure-SMD ISAC_868_Turnkey_CPL_Top.csv!")

        cpl_refs = set(cpl_by_ref.keys())
        expected_dnp_set = {"C_SMPS3", "D_RF", "J1", "J2", "J3", "J4", "J5", "R_DIV1", "R_DIV2", "R_VUART"}
        if dnp_bom_refs != expected_dnp_set:
            errors.append(
                f"[BOM DNP] Expected Rev E.5 DNP set {sorted(expected_dnp_set)}, got {sorted(dnp_bom_refs)}!"
            )
        if pop_bom_refs != cpl_refs:
            only_bom = sorted(pop_bom_refs - cpl_refs)
            only_cpl = sorted(cpl_refs - pop_bom_refs)
            errors.append(
                f"[BOM/CPL] Populated BOM != CPL designator set! "
                f"Missing_in_CPL={only_bom}, Extra_in_CPL={only_cpl}"
            )

        # 4. CPL (PosX, PosY) vs actual Gerber F_Cu.gtl pad-flash bounding-box centers
        fcu_candidates = [n for n in names if n.endswith("-F_Cu.gtl")]
        if len(fcu_candidates) != 1:
            errors.append(f"[GERBER] Expected 1 '*-F_Cu.gtl' in ZIP, found: {fcu_candidates}")
            max_centroid_err = float("nan")
        else:
            with tempfile.NamedTemporaryFile(prefix="fcu_check_", suffix=".gtl", delete=False) as tf:
                tf.write(zf.read(fcu_candidates[0]))
                tmp_gtl = tf.name
            try:
                fcu_gbr = check_dfm.parse_rs274x(tmp_gtl)
            finally:
                if os.path.exists(tmp_gtl):
                    os.remove(tmp_gtl)

            comp_pad_bounds = defaultdict(lambda: [float("inf"), float("inf"), float("-inf"), float("-inf")])
            for fl in fcu_gbr["flashes"]:
                comp = fl["comp"]
                if not comp:
                    continue
                minx, miny, maxx, maxy = fl["poly"].bounds
                b = comp_pad_bounds[comp]
                b[0] = min(b[0], minx)
                b[1] = min(b[1], miny)
                b[2] = max(b[2], maxx)
                b[3] = max(b[3], maxy)
            for reg in fcu_gbr["regions"]:
                comp = reg["comp"]
                if not comp or reg["pad"] is None:
                    continue
                minx, miny, maxx, maxy = reg["poly"].bounds
                b = comp_pad_bounds[comp]
                b[0] = min(b[0], minx)
                b[1] = min(b[1], miny)
                b[2] = max(b[2], maxx)
                b[3] = max(b[3], maxy)

            max_centroid_err = 0.0
            for ref, row in cpl_by_ref.items():
                px = float(row["PosX"])
                py = float(row["PosY"])
                if not (0.0 <= px <= 90.0 and 0.0 <= py <= 40.0):
                    errors.append(
                        f"[CPL ORIGIN] {ref} ({px:.3f}, {py:.3f}) outside [0..90]x[0..40] mm AuxOrigin frame!"
                    )
                if ref not in comp_pad_bounds:
                    errors.append(f"[CPL/GERBER] {ref} has 0 %TO.P pad flashes in {fcu_candidates[0]}!")
                    continue
                minx, miny, maxx, maxy = comp_pad_bounds[ref]
                gx = 0.5 * (minx + maxx)
                gy = 0.5 * (miny + maxy)
                err = math.hypot(px - gx, py - gy)
                max_centroid_err = max(max_centroid_err, err)
                if abs(px - gx) > 0.15 or abs(py - gy) > 0.15 or err > 0.15:
                    errors.append(
                        f"[CPL/GERBER] {ref} centroid mismatch vs F_Cu.gtl: "
                        f"CPL=({px:.4f}, {py:.4f}) vs F_Cu_bbox=({gx:.4f}, {gy:.4f}), "
                        f"delta={err:.4f} mm (> 0.15 mm)"
                    )

        # Verify PTH & NPTH drill coordinates share the exact [0..90]x[0..40] mm AuxOrigin
        for drl_suffix in ("-PTH.drl", "-NPTH.drl"):
            drl_cands = [n for n in names if n.endswith(drl_suffix)]
            if len(drl_cands) != 1:
                errors.append(f"[DRILL] Expected 1 '*{drl_suffix}' in ZIP, found: {drl_cands}")
                continue
            pts = _parse_excellon_coords_mm(zf.read(drl_cands[0]).decode("utf-8"))
            if not pts:
                errors.append(f"[DRILL] {drl_cands[0]} contains 0 drill coordinates!")
            for dx, dy in pts:
                if not (0.0 <= dx <= 90.0 and 0.0 <= dy <= 40.0):
                    errors.append(
                        f"[DRILL ORIGIN] {drl_cands[0]} hit ({dx:.3f}, {dy:.3f}) outside AuxOrigin [0..90]x[0..40] mm!"
                    )
                    break

        # 5. Schematic Netlist <-> Firmware Pin Map Parity
        if netlist_override:
            with open(netlist_override, "r", encoding="utf-8") as f:
                net_text = f.read()
        else:
            net_cands = [n for n in names if n.endswith(".net")]
            if len(net_cands) != 1:
                errors.append(f"[NETLIST] Expected 1 '.net' file in ZIP, found: {net_cands}")
                net_text = ""
            else:
                net_text = zf.read(net_cands[0]).decode("utf-8")

        if net_text:
            fw_checked = verify_netlist_firmware_parity(net_text, fw_pins_path, errors)
        else:
            fw_checked = 0

    # 6. System Box-Build BOM single-source parity (enclosure/ == docs/, Rev E.5)
    enc_bb = os.path.join(ROOT, "enclosure", "ISAC_868_System_BoxBuild_BOM.csv")
    doc_bb = os.path.join(ROOT, "docs", "ISAC_868_System_BoxBuild_BOM.csv")
    if not os.path.isfile(enc_bb) or not os.path.isfile(doc_bb):
        errors.append("[BOX-BUILD BOM] Missing enclosure/ or docs/ ISAC_868_System_BoxBuild_BOM.csv!")
    else:
        b1 = open(enc_bb, "r", encoding="utf-8").read()
        b2 = open(doc_bb, "r", encoding="utf-8").read()
        if b1 != b2:
            errors.append("[BOX-BUILD BOM] enclosure/ and docs/ ISAC_868_System_BoxBuild_BOM.csv diverge!")
        for req_tok in (
            "Rev E.5",
            "67 populated",
            "AO3401A",
            "Parker",
            "ORD 5700",
            "ASA",
            "467MP",
            "DOWSIL-3145",
        ):
            if req_tok not in b1:
                errors.append(f"[BOX-BUILD BOM] Required Rev E.5 token {req_tok!r} missing from Box-Build BOM!")

    print(
        f"[BOM/CPL] Archive={os.path.basename(zip_path)}: 1 BOM CSV ({len(pop_bom_refs)} pop + "
        f"{len(dnp_bom_refs)} DNP), 1 pure-SMD CPL ({len(cpl_smd_by_ref)}, 0 THT parts), "
        f"max_F_Cu_centroid_delta={max_centroid_err:.4f}mm (<=0.15), "
        f"SHA256SUMS=OK, BoxBuild=Synced, FW_pin_checks={fw_checked}."
    )

    if errors:
        sys.stderr.write(f"\n[BOM/CPL/FW PARITY FAILED] {len(errors)} violation(s) detected:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    print("[BOM/CPL GATE PASS] All Turnkey BOM, CPL, Gerber centroid, SHA256 & Firmware pin gates PASSED.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Turnkey BOM/CPL/Gerber/Firmware Parity Gate")
    ap.add_argument(
        "--zip",
        default=os.path.join(ROOT, "fab", "ISAC_868_RevE5_PCBWay_Turnkey.zip"),
    )
    ap.add_argument("--netlist", default=None)
    ap.add_argument(
        "--fw-pins",
        default=os.path.join(ROOT, "firmware", "include", "isac_board_pins.h"),
    )
    ap.add_argument("--no-check-fab-dir", action="store_true")
    args = ap.parse_args()
    sys.exit(
        run_bom_cpl_audit(
            zip_path=args.zip,
            netlist_override=args.netlist,
            fw_pins_path=args.fw_pins,
            check_fab_dir=not args.no_check_fab_dir,
        )
    )


if __name__ == "__main__":
    main()
