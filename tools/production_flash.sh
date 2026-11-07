#!/usr/bin/env bash
# ==============================================================================
# ISAC_868 Rev E.5 — Production & Pilot SWD Programming / Provisioning Script
#   Key safeguards:
#     1) Validates all CLI options, firmware image, IEEE EUI-64s, and mandatory
#        factory dry-air tare (--cal-dry-mv + optional --cal-ref-cdb 2-pt ref,
#        or --uncalibrated-bench) BEFORE issuing `-e all` mass-erase.
#     2) Persists generated CSPRNG AppKey credentials into an fsynced 0600
#        append-only vault (`provisioning_vault/provisioned_units_secret.csv`),
#        never deleting secret keys via TMP_PROV_DIR cleanup!
#     3) Reads back STM32WLE5JC UID64 (0x1FFF7580) over SWD when `--deveui auto`
#        is used so LNS registration works even after RDP = 0xBB readout lock.
# ==============================================================================
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FW="${ISAC_FW_HEX:-${ROOT_DIR}/firmware/build/isac_rak3172lp_sip.hex}"
CLI="${STM32_PROGRAMMER_CLI:-STM32_Programmer_CLI}"
LEDGER_CSV="${ISAC_PROV_LEDGER:-${ROOT_DIR}/provisioning_vault/provisioned_units_secret.csv}"

PROV_HEX=""
DEVEUI=""
JOINEUI=""
APPKEY=""
CAL_DRY_MV=""
CAL_REF_CDB=""
SERIAL_TAG=""
ALLOW_LAB_EUI=0
UNCALIBRATED_BENCH=0
LOCK_RDP=0
DRY_RUN=0
TMP_PROV_DIR=""

cleanup() {
  if [[ -n "${TMP_PROV_DIR}" && -d "${TMP_PROV_DIR}" ]]; then
    rm -rf "${TMP_PROV_DIR}"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage:
  1) Pre-generated provisioning HEX:
     tools/production_flash.sh [--prov-hex] <prov_file.hex> [--fw <fw.hex>]
                               [--uncalibrated-bench] [--lock | --no-rdp] [--dry-run]

  2) On-the-fly per-unit OTAA provisioning (persists AppKey to provisioning_vault/):
     tools/production_flash.sh --deveui <16hex|auto> --joineui <16hex>
                               (--cal-dry-mv <mV1,mV2,mV3> | --uncalibrated-bench)
                               [--app-key <32hex>] [--serial <tag>] [--ledger <csv>]
                               [--allow-lab-local-eui] [--fw <fw.hex>] [--lock | --no-rdp] [--dry-run]
EOF
}

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --prov-hex)
      PROV_HEX="${2:?--prov-hex requires path}"
      shift 2
      ;;
    --fw)
      FW="${2:?--fw requires path}"
      shift 2
      ;;
    --deveui|--dev-eui)
      DEVEUI="${2:?--deveui requires 16-hex or auto}"
      shift 2
      ;;
    --joineui|--join-eui)
      JOINEUI="${2:?--joineui requires 16-hex}"
      shift 2
      ;;
    --app-key)
      APPKEY="${2:?--app-key requires 32-hex}"
      shift 2
      ;;
    --cal-dry-mv)
      CAL_DRY_MV="${2:?--cal-dry-mv requires mV1,mV2,mV3}"
      shift 2
      ;;
    --cal-ref-cdb)
      CAL_REF_CDB="${2:?--cal-ref-cdb requires signed integer in 0.01 dB}"
      shift 2
      ;;
    --serial|--tag)
      SERIAL_TAG="${2:?--serial requires unit identifier}"
      shift 2
      ;;
    --ledger)
      LEDGER_CSV="${2:?--ledger requires CSV path}"
      shift 2
      ;;
    --allow-lab-local-eui)
      ALLOW_LAB_EUI=1
      shift
      ;;
    --uncalibrated-bench)
      UNCALIBRATED_BENCH=1
      shift
      ;;
    --lock|--lock-rdp1)
      LOCK_RDP=1
      shift
      ;;
    --no-rdp)
      LOCK_RDP=0
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -*)
      echo "ERROR: Unknown option '$1' (aborting BEFORE any SWD erase!)" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "${PROV_HEX}" ]]; then
        PROV_HEX="$1"
        shift
      else
        echo "ERROR: Unexpected positional argument '$1' (aborting BEFORE any SWD erase!)" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [[ ! -f "${FW}" || ! -s "${FW}" ]]; then
  echo "ERROR: Target firmware HEX not found: '${FW}'. Run 'make -C firmware target_elf' first (target NOT erased)." >&2
  exit 2
fi
if ! grep -q '^:' "${FW}"; then
  echo "ERROR: '${FW}' is not a valid Intel HEX file (target NOT erased)." >&2
  exit 2
fi
FW_SHA256="$(sha256sum "${FW}" | awk '{print $1}')"
ALREADY_ERASED=0
USED_VAULT_LEDGER=0

if [[ "${DRY_RUN}" -eq 0 ]] && ! command -v "${CLI}" >/dev/null 2>&1; then
  echo "ERROR: STM32CubeProgrammer CLI '${CLI}' not found in PATH (target NOT erased)." >&2
  exit 2
fi

read_swd_uid64() {
  local raw_uid
  raw_uid="$("${CLI}" -c port=SWD mode=UR -r32 0x1FFF7580 2 2>/dev/null || true)"
  python3 - "${raw_uid}" <<'PY'
import re, sys
txt = sys.argv[1]
m = re.search(r"0x1FFF7580\s*:\s*([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})", txt)
if m:
    w0, w1 = int(m.group(1), 16), int(m.group(2), 16)
    uid64 = (w1 << 32) | w0
    print(f"{uid64:016X}")
PY
}

# 1. Validate or synthesize provisioning HEX & persist credentials BEFORE locking target flash!
if [[ -n "${DEVEUI}" || -n "${JOINEUI}" ]]; then
  USED_VAULT_LEDGER=1
  if [[ -n "${PROV_HEX}" ]]; then
    echo "ERROR: Specify either <prov.hex> OR --deveui/--joineui, not both." >&2
    exit 2
  fi
  if [[ -z "${JOINEUI}" ]]; then
    echo "ERROR: --joineui <16hex> is required when using --deveui." >&2
    exit 2
  fi
  if [[ -z "${CAL_DRY_MV}" && "${UNCALIBRATED_BENCH}" -ne 1 ]]; then
    echo "ERROR: Production units require --cal-dry-mv <mV1,mV2,mV3> (or explicit --uncalibrated-bench)." >&2
    exit 2
  fi

  DEV_HEX="${DEVEUI:-0000000000000000}"
  if [[ "${DEV_HEX}" == "auto" ]]; then
    DEV_HEX="0000000000000000"
  fi

  TMP_PROV_DIR="$(mktemp -d)"

  # Validate JoinEUI/DevEUI/AppKey/calibration syntax in scratch dir BEFORE any SWD unlock/erase!
  PRECHECK_ARGS=(
    --join-eui "${JOINEUI}"
    --dev-eui "${DEV_HEX}"
    --out-dir "${TMP_PROV_DIR}/precheck"
    --tag "PRECHECK"
  )
  if [[ -n "${APPKEY}" ]]; then PRECHECK_ARGS+=(--app-key "${APPKEY}"); fi
  if [[ -n "${CAL_DRY_MV}" ]]; then PRECHECK_ARGS+=(--cal-dry-mv "${CAL_DRY_MV}"); fi
  if [[ -n "${CAL_REF_CDB}" ]]; then PRECHECK_ARGS+=(--cal-ref-cdb "${CAL_REF_CDB}"); fi
  if [[ "${ALLOW_LAB_EUI}" -eq 1 ]]; then PRECHECK_ARGS+=(--allow-lab-local-eui); fi
  python3 "${SCRIPT_DIR}/provision_unit.py" "${PRECHECK_ARGS[@]}" >/dev/null
  rm -rf "${TMP_PROV_DIR}/precheck"

  UID64_HEX=""
  if [[ "${DEV_HEX}" == "0000000000000000" ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      UID64_HEX="0080E1150000DRY0"
    else
      UID64_HEX="$(read_swd_uid64)"
      # On reworked units locked at RDP=0xBB, 0x1FFF7580 readout is blocked until
      # RDP regression (0xAA) + mass erase. Regress & re-read BEFORE generating vault ledger or locking RDP!
      if [[ -z "${UID64_HEX}" ]]; then
        "${CLI}" -c port=SWD mode=UR reset=HWrst -ob RDP=0xAA >/dev/null 2>&1 || true
        "${CLI}" -c port=SWD mode=UR reset=HWrst -e all
        ALREADY_ERASED=1
        UID64_HEX="$(read_swd_uid64)"
      fi
      if [[ ! "${UID64_HEX}" =~ ^[0-9A-F]{16}$ || "${UID64_HEX}" == "0000000000000000" || "${UID64_HEX}" == "FFFFFFFFFFFFFFFF" ]]; then
        echo "ERROR: Failed to read valid 64-bit IEEE UID64 at 0x1FFF7580 (got '${UID64_HEX}'); aborting BEFORE credential vault commit or RDP=0xBB lock!" >&2
        exit 2
      fi
    fi
  fi

  UNIT_TAG="${SERIAL_TAG:-$( [[ "${DEV_HEX}" != "0000000000000000" ]] && echo "${DEV_HEX^^}" || echo "UNIT-$(date -u +%Y%m%dT%H%M%SZ)" )}"
  PROV_ARGS=(
    --join-eui "${JOINEUI}"
    --dev-eui "${DEV_HEX}"
    --out-dir "${TMP_PROV_DIR}"
    --tag "${UNIT_TAG}"
    --ledger-csv "${LEDGER_CSV}"
    --uid64-hex "${UID64_HEX}"
    --fw-sha256 "${FW_SHA256}"
    --rdp-locked "${LOCK_RDP}"
  )
  if [[ -n "${APPKEY}" ]]; then
    PROV_ARGS+=(--app-key "${APPKEY}")
  fi
  if [[ -n "${CAL_DRY_MV}" ]]; then
    PROV_ARGS+=(--cal-dry-mv "${CAL_DRY_MV}")
  fi
  if [[ -n "${CAL_REF_CDB}" ]]; then
    PROV_ARGS+=(--cal-ref-cdb "${CAL_REF_CDB}")
  fi
  if [[ "${ALLOW_LAB_EUI}" -eq 1 ]]; then
    PROV_ARGS+=(--allow-lab-local-eui)
  fi
  python3 "${SCRIPT_DIR}/provision_unit.py" "${PROV_ARGS[@]}" >/dev/null
  PROV_HEX="${TMP_PROV_DIR}/${UNIT_TAG}.hex"

  if [[ ! -f "${LEDGER_CSV}" || ! -s "${LEDGER_CSV}" ]] || ! grep -q "${UNIT_TAG}" "${LEDGER_CSV}"; then
    echo "ERROR: Persistent credential ledger verification failed at '${LEDGER_CSV}' (aborting BEFORE SWD/RDP!)." >&2
    exit 2
  fi
else
  # Pre-built provisioning HEX supplied: verify CAL_DRY_VALID bit unless --uncalibrated-bench
  if [[ -z "${PROV_HEX}" || ! -f "${PROV_HEX}" || ! -s "${PROV_HEX}" ]]; then
    echo "ERROR: Provisioning Intel HEX not found or empty: '${PROV_HEX}' (target NOT erased)." >&2
    exit 2
  fi
  if [[ "${UNCALIBRATED_BENCH}" -ne 1 ]]; then
    python3 - "${PROV_HEX}" <<'PY'
import sys
hex_path = sys.argv[1]
first_data = None
for line in open(hex_path, "r", encoding="utf-8"):
    line = line.strip()
    if line.startswith(":") and len(line) >= 11 and line[7:9] == "00":
        first_data = bytes.fromhex(line[9:-2])
        break
if not first_data or len(first_data) < 8:
    sys.exit("ERROR: Cannot parse provisioning header from Intel HEX (target NOT erased).")
cal_flags = first_data[6] | (first_data[7] << 8)
if (cal_flags & 0x0001) == 0:
    sys.exit("ERROR: Pre-built provisioning HEX lacks CAL_DRY_VALID (0x0001) factory tare; pass --uncalibrated-bench for bench tests.")
PY
  fi
fi

if [[ -z "${PROV_HEX}" || ! -f "${PROV_HEX}" || ! -s "${PROV_HEX}" ]]; then
  echo "ERROR: Provisioning Intel HEX not found or empty: '${PROV_HEX}' (target NOT erased)." >&2
  exit 2
fi
if ! grep -q '^:' "${PROV_HEX}"; then
  echo "ERROR: '${PROV_HEX}' is not a valid Intel HEX file (target NOT erased)." >&2
  exit 2
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[DRY-RUN PASS] Validated FW='${FW}', PROV='${PROV_HEX}', LEDGER='${LEDGER_CSV}' (LOCK_RDP=${LOCK_RDP}). No SWD commands issued."
  exit 0
fi

if ! command -v "${CLI}" >/dev/null 2>&1; then
  echo "ERROR: STM32CubeProgrammer CLI '${CLI}' not found in PATH (target NOT erased)." >&2
  exit 2
fi

# 2. All inputs & persistent credential ledger verified: execute atomic SWD program + verify + option bytes
if [[ "${ALREADY_ERASED}" -ne 1 ]]; then
  if ! "${CLI}" -c port=SWD mode=UR reset=HWrst -e all; then
    "${CLI}" -c port=SWD mode=UR reset=HWrst -ob RDP=0xAA >/dev/null 2>&1 || true
    "${CLI}" -c port=SWD mode=UR reset=HWrst -e all
  fi
fi
"${CLI}" -c port=SWD -d "${FW}" -v
"${CLI}" -c port=SWD -d "${PROV_HEX}" -v
# Watchdog frozen in STOP2 (safe with 900 s RTC sleep), software-started, BOR level 3 (nSWBOOT0=1 preserved for PH3/BOOT0)
"${CLI}" -c port=SWD -ob IWDG_SW=1 IWDG_STOP=0 BOR_LEV=3
if [[ "${LOCK_RDP}" -eq 1 ]]; then
  if [[ "${USED_VAULT_LEDGER}" -eq 1 ]]; then
    python3 - "${LEDGER_CSV}" "${UNIT_TAG}" <<'PY'
import csv, re, sys
ledger_path, tag = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open(ledger_path, "r", encoding="utf-8")) if r.get("serial") == tag]
if not rows:
    sys.exit(f"ERROR: Unit '{tag}' missing from ledger '{ledger_path}'; refusing RDP=0xBB lock!")
deveui = (rows[-1].get("deveui_hex") or "").strip().upper()
if not re.match(r"^[0-9A-F]{16}$", deveui) or deveui in ("0" * 16, "F" * 16):
    sys.exit(f"ERROR: Invalid effective DevEUI '{deveui}' in ledger for '{tag}'; refusing RDP=0xBB lock!")
PY
  fi
  echo "Setting RDP Level 1 (0xBB readout protection; credentials verified in ${LEDGER_CSV})"
  "${CLI}" -c port=SWD -ob RDP=0xBB
fi
"${CLI}" -c port=SWD -hardRst
echo "[PASS] Target programmed and verified successfully."
