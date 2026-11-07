#!/usr/bin/env python3
"""Per-unit LoRaWAN provisioning page generator (Rev E.5 ).

Creates the 2 KB provisioning page consumed by firmware/src/isac_nvm.c
(ISAC_NVM_PROVISION_ADDR = 0x0803E000) with a fresh CSPRNG AppKey, IEEE EUI-64
validation, optional 2-point factory calibration (Point-1 dry-air tare 100..2400 mV
+ Point-2 Al2O3/load intercept offset in 0.01 dB), and fsynced append-only
credential ledger output (`0600` permissions, git-ignored).

    tools/provision_unit.py --join-eui 70B3D57ED0000001 [--dev-eui <16 hex>] \\
                            [--cal-dry-mv 818,759,884] [--cal-ref-cdb 0] --out-dir prov/
    -> prov/<DevEUI>.bin / .hex   (flash at 0x0803E000)
    -> prov/credentials.csv       (git-ignored, chmod 0600, fsynced)

If --dev-eui is omitted (or 0000000000000000), the DevEUI field in NVM is zero
and firmware derives DevEUI from the STM32WLE5JC factory UID64 (0x1FFF7580).
"""
import argparse
import binascii
import csv
from datetime import datetime, timezone
import os
import secrets
import struct
import sys

BASE = 0x0803E000
PAGE = 2048
MAGIC = 0x56504F52
VERSION = 2
CAL_DRY_VALID = 0x0001
CAL_REF_VALID = 0x0002
FMT = "<IBBH8s8s16sI16s16s3Hh"     # 84 bytes + 4-byte crc32 appended = 88 bytes


def validate_eui64(eui: bytes, label: str, allow_zero: bool, allow_lab_local: bool) -> None:
    if len(eui) != 8:
        sys.exit(f"{label} must be 8 bytes (16 hex chars)")
    if eui == b"\x00" * 8:
        if allow_zero:
            return
        sys.exit(f"ERROR: {label} cannot be all-zero (0000000000000000)!")
    if eui == b"\xFF" * 8:
        sys.exit(f"ERROR: {label} cannot be broadcast all-FF (FFFFFFFFFFFFFFFF)!")
    if (eui[0] & 0x01) != 0 and not allow_lab_local:
        sys.exit(
            f"ERROR: {label} {eui.hex().upper()} has IEEE multicast bit set (byte[0] & 0x01); "
            f"pass --allow-lab-local-eui only for isolated bench tests."
        )
    if (eui[0] & 0x02) != 0 and not allow_lab_local:
        sys.exit(
            f"ERROR: {label} {eui.hex().upper()} has IEEE locally-administered bit set (byte[0] & 0x02); "
            f"use a registered universal IEEE OUI or pass --allow-lab-local-eui for lab tests."
        )


def build(
    dev_eui: bytes,
    join_eui: bytes,
    app_key: bytes,
    otaa=True,
    abp=None,
    cal_dry_mv=None,
    cal_ref_cdb=None,
) -> bytes:
    abp_addr, nwk, app = abp or (0, bytes(16), bytes(16))
    cal_flags = 0
    if cal_dry_mv is not None:
        assert len(cal_dry_mv) == 3, "cal_dry_mv must be 3 uint16 millivolt values (f1, f2, f3)"
        cal_flags |= CAL_DRY_VALID
        cal_vals = (int(cal_dry_mv[0]), int(cal_dry_mv[1]), int(cal_dry_mv[2]))
    else:
        cal_vals = (0, 0, 0)
    if cal_ref_cdb is not None:
        cal_flags |= CAL_REF_VALID
        ref_val = int(cal_ref_cdb)
    else:
        ref_val = 0
    body = struct.pack(
        FMT,
        MAGIC,
        VERSION,
        1 if otaa else 0,
        cal_flags,
        dev_eui,
        join_eui,
        app_key,
        abp_addr,
        nwk,
        app,
        cal_vals[0],
        cal_vals[1],
        cal_vals[2],
        ref_val,
    )
    crc = binascii.crc32(body) & 0xFFFFFFFF
    blob = body + struct.pack("<I", crc)
    assert len(blob) == 88
    return blob + b"\xFF" * (PAGE - len(blob))


def ihex(addr: int, data: bytes) -> str:
    out, ext = [], (addr >> 16) & 0xFFFF
    rec = lambda n, a, t, d: ":%02X%04X%02X%s%02X" % (n, a, t, d.hex().upper(),
                                                      (-(n + (a >> 8) + (a & 255) + t + sum(d))) & 255)
    out.append(rec(2, 0, 4, struct.pack(">H", ext)))
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        out.append(rec(len(chunk), (addr + i) & 0xFFFF, 0, chunk))
    out.append(":00000001FF")
    return "\n".join(out) + "\n"


def _append_secure_csv(csv_path: str, headers: list[str], row: list[str]) -> None:
    parent = os.path.dirname(os.path.abspath(csv_path))
    os.makedirs(parent, mode=0o700, exist_ok=True)
    new = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    fd = os.open(csv_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(headers)
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(csv_path, 0o600)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--join-eui", required=True, help="16 hex chars (universal IEEE EUI-64)")
    ap.add_argument("--dev-eui", default="0" * 16, help="16 hex chars (default: 0000000000000000 -> chip UID64)")
    ap.add_argument("--app-key", default=None, help="Optional 32 hex chars (default: random CSPRNG)")
    ap.add_argument("--cal-dry-mv", default=None,
                    help="Point-1 factory dry-air tare 'v1,v2,v3' in mV [100..2400] (e.g. '818,759,884')")
    ap.add_argument("--cal-ref-cdb", default=None,
                    help="Point-2 factory Al2O3/load gain+intercept offset in 0.01 dB [-1200..+1200]")
    ap.add_argument("--allow-lab-local-eui", action="store_true",
                    help="Allow locally-administered / lab test EUIs")
    ap.add_argument("--ledger-csv", default=None,
                    help="Optional persistent secret credential vault CSV path (fsynced, chmod 0600)")
    ap.add_argument("--uid64-hex", default="", help="Optional readback STM32 UID64 hex for ledger")
    ap.add_argument("--fw-sha256", default="", help="Optional firmware HEX SHA-256 digest for ledger")
    ap.add_argument("--rdp-locked", default="0", help="Optional RDP lock flag ('0' or '1') for ledger")
    ap.add_argument("--tag", default=None, help="Optional output filename stem")
    ap.add_argument("--out-dir", default="prov")
    a = ap.parse_args()

    try:
        dev = bytes.fromhex(a.dev_eui)
        join = bytes.fromhex(a.join_eui)
    except ValueError as exc:
        sys.exit(f"ERROR: Invalid hex string in EUI argument: {exc}")

    validate_eui64(join, "JoinEUI", allow_zero=False, allow_lab_local=a.allow_lab_local_eui)
    validate_eui64(dev, "DevEUI", allow_zero=True, allow_lab_local=a.allow_lab_local_eui)

    try:
        key = bytes.fromhex(a.app_key) if a.app_key else secrets.token_bytes(16)
    except ValueError as exc:
        sys.exit(f"ERROR: Invalid hex string in --app-key: {exc}")
    if len(key) != 16 or key == b"\x00" * 16 or key == b"\xFF" * 16:
        sys.exit("ERROR: AppKey must be 16 non-trivial bytes (32 hex chars)")

    cal_mv = None
    if a.cal_dry_mv:
        try:
            parts = [int(x.strip()) for x in a.cal_dry_mv.split(",")]
        except ValueError:
            sys.exit("ERROR: --cal-dry-mv must be 3 comma-separated millivolt integers")
        if len(parts) != 3 or any(p < 100 or p > 2400 for p in parts):
            sys.exit("ERROR: --cal-dry-mv must be 3 comma-separated millivolt integers in 100..2400")
        cal_mv = tuple(parts)

    cal_ref = None
    if a.cal_ref_cdb is not None and str(a.cal_ref_cdb).strip() != "":
        try:
            cal_ref = int(str(a.cal_ref_cdb).strip())
        except ValueError:
            sys.exit("ERROR: --cal-ref-cdb must be a signed integer in 0.01 dB units (-1200..+1200)")
        if cal_ref < -1200 or cal_ref > 1200:
            sys.exit("ERROR: --cal-ref-cdb out of range [-1200..+1200] (0.01 dB units)")

    page = build(dev, join, key, cal_dry_mv=cal_mv, cal_ref_cdb=cal_ref)
    os.makedirs(a.out_dir, exist_ok=True)
    tag = a.tag if a.tag else (a.dev_eui.upper() if a.dev_eui.strip("0") else "UID64-%s" % key[:3].hex().upper())
    open(os.path.join(a.out_dir, tag + ".bin"), "wb").write(page)
    open(os.path.join(a.out_dir, tag + ".hex"), "w").write(ihex(BASE, page))

    cred_csv = os.path.join(a.out_dir, "credentials.csv")
    _append_secure_csv(
        cred_csv,
        ["tag", "dev_eui", "join_eui", "app_key", "cal_dry_mv", "cal_ref_cdb"],
        [
            tag,
            a.dev_eui.upper(),
            a.join_eui.upper(),
            key.hex().upper(),
            a.cal_dry_mv or "",
            "" if cal_ref is None else str(cal_ref),
        ],
    )

    if a.ledger_csv:
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        eff_deveui = a.uid64_hex.upper() if (not a.dev_eui.strip("0") and a.uid64_hex) else a.dev_eui.upper()
        _append_secure_csv(
            a.ledger_csv,
            [
                "timestamp_utc", "serial", "uid64_hex", "deveui_hex",
                "joineui_hex", "appkey_hex", "dry_tare_mv", "cal_ref_cdb", "fw_sha256", "rdp_locked",
            ],
            [
                ts_utc, tag, a.uid64_hex.upper(), eff_deveui,
                a.join_eui.upper(), key.hex().upper(), a.cal_dry_mv or "",
                "" if cal_ref is None else str(cal_ref), a.fw_sha256, str(a.rdp_locked),
            ],
        )

    print("wrote", tag, "- upload credentials.csv to the LNS; DO NOT COMMIT prov/ or provisioning_vault/")


if __name__ == "__main__":
    main()
