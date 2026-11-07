#!/usr/bin/env python3
"""
run_cst_batch.py -- Official CST Studio Suite Python API Driver & VBA Static Verifier
                    for ISAC_868_KiCad9 (Hardware Revision E.5).

Supports CST Studio Suite 2022 / 2023 / 2024 / 2025 on Windows and Linux via Dassault
Systemes' `cst.interface` and `cst.results` libraries.

Usage:
  1. Static syntax & History-block verification (no CST license required):
       python3 cst_studio/python/run_cst_batch.py --check-macros

  2. Build `.cst` project and run Enclosed Dry-Air baseline in CST Studio:
       python3 cst_studio/python/run_cst_batch.py --cst-root "/opt/cst/CST_Studio_Suite_2024" --scenario dry_air

  3. Run all 10 superstrate & tolerance benchmark sweeps headlessly and export `.s1p`:
       python3 cst_studio/python/run_cst_batch.py --cst-root "C:/Program Files (x86)/CST Studio Suite 2024" --all
"""
from __future__ import annotations

import argparse
import cmath
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CST_DIR = HERE.parent
MACROS_DIR = CST_DIR / "macros"
RESULTS_DIR = CST_DIR / "results"

SCENARIOS: dict[str, dict[str, float]] = {
    "01_bare_pcb":      {"enclosure_en": 0, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 0},
    "02_dry_air":       {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 0},
    "03_enclosed_lipo": {"enclosure_en": 1, "battery_mode": 1, "er_fr4": 4.40, "superstrate_id": 0},
    "04_fr4_low_4p2":   {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.20, "superstrate_id": 0},
    "05_fr4_high_4p6":  {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.60, "superstrate_id": 0},
    "06_oil_ptfe":      {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 1},
    "07_glaze_ice":     {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 2},
    "08_alumina_al2o3": {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 3},
    "09_ipa_debye":     {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 4},
    "10_water_debye":   {"enclosure_en": 1, "battery_mode": 0, "er_fr4": 4.40, "superstrate_id": 5},
}


def verify_vba_block_balance(code: str, label: str) -> list[str]:
    """Check balanced Sub/End Sub, With/End With, If/End If, For/Next, and quote pairs."""
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    pending = ""
    pending_line = 1

    for lineno, raw in enumerate(code.splitlines(), 1):
        # Strip VBA comments outside quotes
        in_q = False
        clean_chars = []
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == '"':
                if in_q and i + 1 < len(raw) and raw[i + 1] == '"':
                    clean_chars.append('""')
                    i += 2
                    continue
                in_q = not in_q
            if ch == "'" and not in_q:
                break
            clean_chars.append(ch)
            i += 1
        if in_q:
            errors.append(f"{label}:{lineno}: Unclosed string literal")
            continue

        stmt_line = "".join(clean_chars).strip()
        if not stmt_line:
            continue
        if stmt_line.endswith("_"):
            if not pending:
                pending_line = lineno
            pending += stmt_line[:-1].rstrip() + " "
            continue
        if pending:
            stmt_line = pending + stmt_line
            use_line = pending_line
            pending = ""
        else:
            use_line = lineno

        for stmt in [s.strip() for s in stmt_line.split(":") if s.strip()]:
            low = stmt.lower()
            if re.match(r"^sub\b", low):
                stack.append(("sub", use_line))
            elif re.match(r"^end\s+sub\b", low):
                if not stack or stack[-1][0] != "sub":
                    errors.append(f"{label}:{use_line}: Unexpected 'End Sub'")
                else:
                    stack.pop()
            elif re.match(r"^with\b", low):
                stack.append(("with", use_line))
            elif re.match(r"^end\s+with\b", low):
                if not stack or stack[-1][0] != "with":
                    errors.append(f"{label}:{use_line}: Unexpected 'End With'")
                else:
                    stack.pop()
            elif re.match(r"^if\b.*\bthen\s*$", low):
                stack.append(("if", use_line))
            elif re.match(r"^end\s+if\b", low):
                if not stack or stack[-1][0] != "if":
                    errors.append(f"{label}:{use_line}: Unexpected 'End If'")
                else:
                    stack.pop()
            elif re.match(r"^for\b", low):
                stack.append(("for", use_line))
            elif re.match(r"^next\b", low):
                if not stack or stack[-1][0] != "for":
                    errors.append(f"{label}:{use_line}: Unexpected 'Next'")
                else:
                    stack.pop()

    for blk, ln in stack:
        errors.append(f"{label}:{ln}: Unclosed '{blk}' block at EOF")
    return errors


def check_all_macros() -> int:
    macro_files = sorted(MACROS_DIR.glob("*.bas"))
    if not macro_files:
        sys.stderr.write(f"[CST-CHECK] No .bas files found in {MACROS_DIR}\n")
        return 1

    all_errors: list[str] = []
    total_history_blocks = 0

    for mf in macro_files:
        txt = mf.read_text(encoding="utf-8")
        all_errors.extend(verify_vba_block_balance(txt, mf.name))

        # Extract embedded AddToHistory payloads and verify inner CST VBA blocks as well
        hist_chunks: list[tuple[str, list[str]]] = []
        cur_lines: list[str] = []
        for lineno, ln in enumerate(txt.splitlines(), 1):
            m_cat = re.match(r'^\s*sCmd\s*=\s*sCmd\s*&\s*"(.*)"\s*&\s*vbLf\s*$', ln)
            if m_cat:
                cur_lines.append(m_cat.group(1).replace('""', '"'))
                continue
            m_add = re.match(r'^\s*AddToHistory\s+"([^"]+)",\s*sCmd\s*$', ln)
            if m_add:
                hist_chunks.append((m_add.group(1), list(cur_lines)))
                cur_lines.clear()

        for cap, inner_lines in hist_chunks:
            total_history_blocks += 1
            all_errors.extend(verify_vba_block_balance("\n".join(inner_lines), f"{mf.name}[{cap}]"))

    # Check required parameters in ISAC_868_Complete_Antenna_MWS.bas
    mws_txt = (MACROS_DIR / "ISAC_868_Complete_Antenna_MWS.bas").read_text(encoding="utf-8")
    req_params = (
        "f_min", "f_max", "excitation_mode", "enclosure_en", "battery_mode",
        "superstrate_id", "h_superstrate", "h_window", "h_adhesive", "h_fr4",
        "er_fr4", "tand_fr4", "c_m1_pf", "l_m1_nh", "c_mz_pf", "c_m2_pf",
    )
    for rp in req_params:
        if f'StoreDoubleParameter "{rp}"' not in mws_txt:
            all_errors.append(f"Missing parameter declaration: {rp}")

    if all_errors:
        sys.stderr.write(f"[CST-CHECK FAILED] {len(all_errors)} issue(s):\n")
        for err in all_errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    print(
        f"[CST-CHECK PASS] Verified {len(macro_files)} VBA macros and "
        f"{total_history_blocks} embedded CST History blocks (0 syntax/balance errors)."
    )
    return 0


def attach_cst_python_libs(cst_root: str | None) -> None:
    candidates = []
    if cst_root:
        candidates.append(Path(cst_root))
    env_root = os.environ.get("CST_STUDIO_PATH")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([
        Path("/opt/cst/CST_Studio_Suite_2025"),
        Path("/opt/cst/CST_Studio_Suite_2024"),
        Path("/opt/cst/CST_Studio_Suite_2023"),
        Path("C:/Program Files (x86)/CST Studio Suite 2025"),
        Path("C:/Program Files (x86)/CST Studio Suite 2024"),
        Path("C:/Program Files (x86)/CST Studio Suite 2023"),
    ])
    for root in candidates:
        for sub in ("LinuxAMD64/python_cst_libraries", "AMD64/python_cst_libraries", "python_cst_libraries"):
            lib_dir = root / sub
            if lib_dir.is_dir() and str(lib_dir) not in sys.path:
                sys.path.insert(0, str(lib_dir))
                return


def write_touchstone_s1p(out_path: Path, freqs_ghz: list[float], s11_complex: list[complex], comment: str) -> None:
    lines = [
        f"! {comment}",
        "# GHz S RI R 50.0",
    ]
    for fg, s in zip(freqs_ghz, s11_complex):
        lines.append(f"{fg:.7f}  {s.real:+.8e}  {s.imag:+.8e}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_in_cst(cst_root: str | None, project_path: Path, scenarios_to_run: list[str], excitation_mode: int) -> int:
    attach_cst_python_libs(cst_root)
    try:
        import cst.interface  # type: ignore
        import cst.results    # type: ignore
    except ImportError as exc:
        sys.stderr.write(
            "[CST-BATCH] Could not import `cst.interface` / `cst.results`.\n"
            "  Pass `--cst-root /path/to/CST_Studio_Suite_2024` (or set CST_STUDIO_PATH),\n"
            "  or import `cst_studio/macros/ISAC_868_Complete_Antenna_MWS.bas` directly inside CST GUI.\n"
            f"  Detail: {exc}\n"
        )
        return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    project_path.parent.mkdir(parents=True, exist_ok=True)

    de = cst.interface.DesignEnvironment()
    mws = de.new_mws()
    mws.save(str(project_path))

    # Execute the primary 3D model builder macro inside CST Microwave Studio
    mws_bas = (MACROS_DIR / "ISAC_868_Complete_Antenna_MWS.bas").read_text(encoding="utf-8")
    mws.modeler.run_vba(mws_bas)

    for sc_key in scenarios_to_run:
        cfg = SCENARIOS[sc_key]
        print(f"[CST-BATCH] Solving {sc_key} (mode={excitation_mode}, {cfg})...")
        vba_update = (
            "Sub Main()\n"
            f'    StoreDoubleParameter "excitation_mode", {excitation_mode}\n'
            f'    StoreDoubleParameter "enclosure_en", {cfg["enclosure_en"]}\n'
            f'    StoreDoubleParameter "battery_mode", {cfg["battery_mode"]}\n'
            f'    StoreDoubleParameter "er_fr4", {cfg["er_fr4"]}\n'
            f'    StoreDoubleParameter "superstrate_id", {cfg["superstrate_id"]}\n'
            '    StoreDoubleParameter "h_superstrate", 2.00\n'
            "    Rebuild\n"
            "End Sub\n"
        )
        mws.modeler.run_vba(vba_update)
        mws.modeler.run_solver()
        mws.save()

        pf = cst.results.ProjectFile(str(project_path), allow_interactive=True)
        s11_item = pf.get_3d().get_result_item(r"1D Results\S-Parameters\S1,1")
        freqs_ghz = [ float(x) for x in s11_item.get_xdata() ]
        s11_vals = [ complex(y) for y in s11_item.get_ydata() ]

        s1p_out = RESULTS_DIR / f"{sc_key}.s1p"
        write_touchstone_s1p(
            s1p_out,
            freqs_ghz,
            s11_vals,
            comment=f"CST Studio 3D FIT S11 export for {sc_key} (mode={excitation_mode})",
        )
        print(f"[CST-BATCH] Exported {s1p_out.relative_to(CST_DIR.parent)}")

    de.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CST Studio Suite batch runner & macro verifier (Rev E.5).")
    ap.add_argument("--check-macros", action="store_true", help="Verify VBA syntax & History blocks offline.")
    ap.add_argument("--cst-root", default=None, help="Installation directory of CST Studio Suite.")
    ap.add_argument(
        "--project",
        default=str(RESULTS_DIR / "ISAC_868_RevE5_Complete_Antenna.cst"),
        help="Target .cst project file path.",
    )
    ap.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default="02_dry_air",
        help="Single scenario to solve when --all is not set.",
    )
    ap.add_argument("--all", action="store_true", help="Solve all 10 superstrate & tolerance scenarios.")
    ap.add_argument(
        "--mode",
        type=int,
        choices=(0, 1),
        default=1,
        help="1 = /BR_Q port + 3D 0402 elliptic Pi-filter (default); 0 = direct AE1 Pad 1 port.",
    )
    args = ap.parse_args()

    if args.check_macros:
        return check_all_macros()

    rc = check_all_macros()
    if rc != 0:
        return rc

    to_run = list(SCENARIOS.keys()) if args.all else [args.scenario]
    return run_in_cst(args.cst_root, Path(args.project), to_run, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
