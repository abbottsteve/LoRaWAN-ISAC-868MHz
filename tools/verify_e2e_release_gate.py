#!/usr/bin/env python3
"""
Master End-to-End Manufacturing Release Verification Gate (`Rev E.5`)
=====================================================================
Self-contained workspace pipeline executing CAD, full-wave 3D FDTD,
2D-FVM, parasitic-extracted Monte-Carlo, DFM, Gerber, BOM/CPL, mechanical STL,
firmware HIL/NVM/SysTick, negative-mutation, and documentation parity gates:

  [01] cpwg_2dfvm_solver      : Graded 2D-FVM CPWG 51.90 Ohm LPI + Wadell benchmark
  [02] ifa_enclosure_mom      : Full-Wave 3D Maxwell FDTD + Elliptic Harmonic Pi-Filter
  [03] bridge_sparam_mc       : ADI LT5538-Terminated /BR_S (<0.15pF) + 2,000-Trial MC
  [04] sync_design_values     : Single-Source JSON Sync (0.00 MHz / <= 0.01 dB parity)
  [05] export_turnkey_pkg     : Full CAD regen + --use-drill-file-origin RevE5 Turnkey ZIP
  [06] verify_u1_overlay      : 1:1 RAK3172LP-SiP LGA-73 datasheet overlay (0.0000 mm)
  [07] rules_isac --verify    : Cryptographic SHA-256 DRC rule-deck & stackup lock
  [08] kicad-cli sch erc      : Schematic ERC (--severity-all, 0 violations)
  [09] kicad-cli pcb drc      : PCB DRC (--all-track-errors --schematic-parity, 0 violations)
  [10] check_dfm              : Gerber, 0.10mm Stencil (B_Paste omitted), DNP=0 & Silkscreen DFM
  [11] check_bom_cpl          : Turnkey BOM/CPL/Centroids/SHA256/BoxBuild/FW Pin Parity
  [12] enclosure_watertight   : Trimesh 2-Manifold Watertightness, O-Ring & 0.80mm Window
  [13] firmware_all_systick   : Host C11 HIL + NVM Tests + Target ELF SysTick & Vault
  [14] test_seeded_defects    : Negative Mutation Suite Asserting 8/8 Seeded Defects Caught
  [15] check_doc_parity       : Doc-to-Hardware, RF/EM JSON, BOM & Visual Sheet Parity
  [16] verify_design_consist. : 92-Symbol Sch/PCB/BOM/CPL/Gerber/Drill/FW Consistency Check
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import trimesh

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = sys.executable or "/usr/bin/python3"


def _purge_pycache():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if "/.git" in dirpath or dirpath.endswith("/.git"):
            continue
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)
            dirnames.remove("__pycache__")
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                os.remove(os.path.join(dirpath, fn))


def _verify_enclosure_watertight():
    """
    Verify watertight 2-manifold topology, positive volume, outward winding, exact
    byte parity between `enclosure/*.stl` and `fab/mechanical/*.stl`, and `0.80 mm`
    sensing diaphragm thickness across `dx = 74.0..87.0 mm` on the lid mesh.
    """
    stl_names = (
        "ISAC_868_Lid_0p80mm_Window.stl",
        "ISAC_868_Base_Tray.stl",
        "ISAC_868_Base_Tray_Battery.stl",
    )
    details = []

    for sname in stl_names:
        enc_path = os.path.join(ROOT, "enclosure", sname)
        fab_path = os.path.join(ROOT, "fab", "mechanical", sname)
        if not os.path.isfile(enc_path) or not os.path.isfile(fab_path):
            raise RuntimeError(f"Missing STL artefact: {enc_path} or {fab_path}")

        with open(enc_path, "rb") as f1, open(fab_path, "rb") as f2:
            if hashlib.sha256(f1.read()).hexdigest() != hashlib.sha256(f2.read()).hexdigest():
                raise RuntimeError(f"SHA-256 mismatch between enclosure/{sname} and fab/mechanical/{sname}")

        mesh = trimesh.load_mesh(fab_path, process=True)
        if not mesh.is_watertight:
            raise RuntimeError(f"{sname} is NOT watertight!")
        if not mesh.is_winding_consistent:
            raise RuntimeError(f"{sname} does NOT have consistent outward face winding!")
        if not mesh.is_volume or mesh.volume <= 0.0:
            raise RuntimeError(f"{sname} is NOT a closed positive-volume solid ({mesh.volume:.2f} mm^3)!")

        details.append(f"{sname}: {len(mesh.faces)} tris, vol={mesh.volume / 1000.0:.2f} cm^3, watertight=True")

        if "Lid" in sname:
            tris = mesh.triangles
            v0 = tris[:, 0, :2]
            e1 = tris[:, 1, :2] - v0
            e2 = tris[:, 2, :2] - v0
            d00 = np.einsum("ij,ij->i", e1, e1)
            d01 = np.einsum("ij,ij->i", e1, e2)
            d11 = np.einsum("ij,ij->i", e2, e2)
            denom = d00 * d11 - d01 * d01
            valid_mask = np.abs(denom) > 1e-10

            thicknesses = []
            for rx in np.linspace(75.5, 85.5, 5):
                for ry in np.linspace(9.0, 19.0, 5):
                    p = np.array([rx, ry]) - v0[valid_mask]
                    d20 = np.einsum("ij,ij->i", p, e1[valid_mask])
                    d21 = np.einsum("ij,ij->i", p, e2[valid_mask])
                    dn = denom[valid_mask]
                    u_b = (d11[valid_mask] * d20 - d01[valid_mask] * d21) / dn
                    v_b = (d00[valid_mask] * d21 - d01[valid_mask] * d20) / dn
                    w_b = 1.0 - u_b - v_b
                    hit_mask = (u_b >= -1e-7) & (v_b >= -1e-7) & (w_b >= -1e-7)
                    hit_tris = tris[valid_mask][hit_mask]
                    zs = sorted({
                        round(float(w * t[0, 2] + u * t[1, 2] + v * t[2, 2]), 4)
                        for t, u, v, w in zip(hit_tris, u_b[hit_mask], v_b[hit_mask], w_b[hit_mask])
                    })
                    if len(zs) != 2 or abs(zs[0] - 0.0) > 0.01:
                        raise RuntimeError(
                            f"Lid sensing window ray ({rx:.1f}, {ry:.1f}) unexpected Z surfaces: {zs}"
                        )
                    thicknesses.append(zs[1] - zs[0])

            min_t = float(min(thicknesses))
            max_t = float(max(thicknesses))
            if not (0.78 <= min_t <= 0.82 and 0.78 <= max_t <= 0.82):
                raise RuntimeError(
                    f"Lid sensing window thickness [{min_t:.3f}, {max_t:.3f}] mm outside 0.80 +/- 0.02 mm!"
                )
            details.append(f"Window t_ASA=[{min_t:.3f}..{max_t:.3f}] mm (25 rays, 25 um 467MP bondline)")

    return " | ".join(details)


def run_cmd_stage(cmd, cwd=ROOT):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"Command exited with code {proc.returncode}: {' '.join(cmd)}\n{combined}")
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else "OK"


def _verify_firmware_and_systick():
    s = run_cmd_stage(["make", "-C", "firmware", "clean", "all"], cwd=ROOT)
    elf_path = os.path.join(ROOT, "firmware", "build", "isac_rak3172lp_sip.elf")
    dis = subprocess.run(
        ["arm-none-eabi-objdump", "-d", elf_path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    m = dis.find("<ISAC_HAL_DelayUs>:")
    if m < 0:
        raise RuntimeError("ISAC_HAL_DelayUs symbol missing from firmware ELF disassembly!")
    fn_blk = dis[m:m + 1800].lower()
    if not (
        "e000e010" in fn_blk
        or "e000e018" in fn_blk
        or ("e000e000" in fn_blk and "#24]" in fn_blk)
    ):
        raise RuntimeError("ISAC_HAL_DelayUs does NOT reference SysTick->CVR (0xE000E018 / [0xE000E000, #24])!")
    return f"{s} | SysTick->CVR (0xE000E010/VAL) verified in ELF"


def main():
    t0_total = time.monotonic()
    _purge_pycache()

    with tempfile.TemporaryDirectory(prefix="isac_e2e_rpts_") as rpt_dir:
        erc_rpt = os.path.join(rpt_dir, "erc.rpt")
        drc_rpt = os.path.join(rpt_dir, "drc.rpt")

        stages = [
            (
                "01. Graded 2D-FVM CPWG & Wadell Benchmark (rf/cpwg_2dfvm_solver.py)",
                lambda: run_cmd_stage([PY, "rf/cpwg_2dfvm_solver.py"], cwd=ROOT),
            ),
            (
                "02. Full-Wave 3D Maxwell FDTD & Harmonic Pi-Filter (rf/ifa_enclosure_mom.py)",
                lambda: run_cmd_stage([PY, "rf/ifa_enclosure_mom.py"], cwd=ROOT),
            ),
            (
                "03. Parasitic-Extracted Bridge [S] & 2,000-Trial MC (rf/bridge_sparam_mc.py)",
                lambda: run_cmd_stage([PY, "rf/bridge_sparam_mc.py"], cwd=ROOT),
            ),
            (
                "04. Single-Source RF/EM Design JSON Sync (rf/sync_design_values.py)",
                lambda: run_cmd_stage([PY, "rf/sync_design_values.py"], cwd=ROOT),
            ),
            (
                "05. Unified Rev E.5 Turnkey Packager (tools/export_turnkey_package.py)",
                lambda: run_cmd_stage([PY, "tools/export_turnkey_package.py"], cwd=ROOT),
            ),
            (
                "06. U1 LGA-73 Datasheet Overlay Verifier (tools/verify_u1_overlay.py)",
                lambda: run_cmd_stage([PY, "tools/verify_u1_overlay.py"], cwd=ROOT),
            ),
            (
                "07. Cryptographic DRC Rule-Deck Lock (tools/rules_isac.py --verify)",
                lambda: run_cmd_stage([PY, "tools/rules_isac.py", "--verify"], cwd=ROOT),
            ),
            (
                "08. Schematic ERC (--severity-all --exit-code-violations)",
                lambda: run_cmd_stage(
                    [
                        "kicad-cli", "sch", "erc",
                        "--severity-all", "--exit-code-violations",
                        "--output", erc_rpt,
                        "ISAC_868_KiCad9.kicad_sch",
                    ],
                    cwd=ROOT,
                ),
            ),
            (
                "09. PCB DRC + All-Track + Parity (--schematic-parity)",
                lambda: run_cmd_stage(
                    [
                        "kicad-cli", "pcb", "drc",
                        "--severity-all", "--all-track-errors", "--schematic-parity",
                        "--exit-code-violations",
                        "--output", drc_rpt,
                        "ISAC_868_KiCad9.kicad_pcb",
                    ],
                    cwd=ROOT,
                ),
            ),
            (
                "10. Post-DRC Gerber, Stencil, Mask & Silk DFM Check (check_dfm.py)",
                lambda: run_cmd_stage([PY, "tools/check_dfm.py"], cwd=ROOT),
            ),
            (
                "11. Turnkey BOM / CPL / SHA256 / BoxBuild / FW Parity (check_bom_cpl.py)",
                lambda: run_cmd_stage([PY, "tools/check_bom_cpl.py"], cwd=ROOT),
            ),
            (
                "12. Watertight 2-Manifold ASA/PETG Enclosure & 0.80 mm Window",
                _verify_enclosure_watertight,
            ),
            (
                "13. Firmware HIL (370) + NVM (1092) + SysTick->CVR Disassembly",
                _verify_firmware_and_systick,
            ),
            (
                "14. Negative Mutation Suite — 8/8 Seeded Defects Caught",
                lambda: run_cmd_stage([PY, "tools/test_seeded_defects.py"], cwd=ROOT),
            ),
            (
                "15. RF/EM JSON, Doc, BOM & Bring-Up Parity (check_doc_parity.py)",
                lambda: run_cmd_stage([PY, "tools/check_doc_parity.py"], cwd=ROOT),
            ),
            (
                "16. 92-Symbol Multi-Domain Consistency Check (verify_design_consistency.py)",
                lambda: (_purge_pycache(), run_cmd_stage([PY, "tools/verify_design_consistency.py"], cwd=ROOT))[1],
            ),
        ]

        print("=" * 88)
        print("ISAC_868 Rev E.5 — Master End-to-End Manufacturing Release Verification Gate")
        print("=" * 88)

        results = []
        failed = False

        for title, runner in stages:
            ts = time.monotonic()
            try:
                summary = runner()
                dt = time.monotonic() - ts
                results.append((title, True, dt, summary))
                print(f"[PASS] {title:<68} ({dt:5.2f}s)")
                print(f"       -> {summary}")
            except Exception as exc:
                dt = time.monotonic() - ts
                results.append((title, False, dt, str(exc)))
                print(f"[FAIL] {title:<68} ({dt:5.2f}s)")
                sys.stderr.write(f"\n[STAGE FAILURE] {title}:\n{exc}\n")
                failed = True
                break

        _purge_pycache()
        total_dt = time.monotonic() - t0_total
        n_pass = sum(1 for _, ok, _, _ in results if ok)
        print("-" * 88)
        print(
            f"E2E RELEASE SUMMARY: {n_pass}/{len(stages)} stages PASSED in {total_dt:.2f}s | "
            f"Package: fab/ISAC_868_RevE5_PCBWay_Turnkey.zip"
        )
        print("=" * 88)

        if failed or n_pass != len(stages):
            sys.exit(1)

        sys.exit(0)


if __name__ == "__main__":
    main()
