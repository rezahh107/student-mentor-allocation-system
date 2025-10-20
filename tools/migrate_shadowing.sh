#!/usr/bin/env bash
set -euo pipefail

CORRELATION_ID="${CORRELATION_ID:-migration-shadowing}" 

log_json() {
  local level="$1"; shift
  local event="$1"; shift
  local message="$1"; shift
  python - "$message" "$level" "$event" "$CORRELATION_ID" "$@" <<'PY'
import json
import sys

message = sys.argv[1]
level = sys.argv[2]
event = sys.argv[3]
correlation_id = sys.argv[4]
extras = {}
for item in sys.argv[5:]:
    key, _, value = item.partition("=")
    extras[key] = value
payload = {
    "correlation_id": correlation_id,
    "event": event,
    "level": level,
    "message": message,
}
payload.update(extras)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_DIR="${REPO_ROOT}/src"
TARGET_DIR="${SRC_DIR}/sma"

if [[ ! -d "${SRC_DIR}" ]]; then
  log_json "error" "migration_missing_src" "خطا: پوشهٔ src در مخزن یافت نشد." "path=${SRC_DIR}" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"

log_json "info" "migration_start" "آغاز مهاجرت پوشه‌های first-party به sma." "src=${SRC_DIR}" "target=${TARGET_DIR}"

critical_names=(fastapi sqlalchemy pytest pydantic requests numpy pandas uvicorn redis fakeredis observe observability opentelemetry openpyxl prometheus_client pytest_asyncio pytest_timeout orjson xdist tools)

is_git_repo=false
if command -v git >/dev/null 2>&1 && git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  is_git_repo=true
fi

move_entry() {
  local source_path="$1"
  local base_name
  base_name="$(basename "${source_path}")"

  if [[ "${base_name}" == "sma" ]]; then
    return
  fi

  local dest_name="${base_name}"
  for critical in "${critical_names[@]}"; do
    if [[ "${base_name}" == "${critical}" ]]; then
      dest_name="_local_${base_name}"
      break
    fi
  done

  local destination_path="${TARGET_DIR}/${dest_name}"

  if [[ -e "${destination_path}" ]]; then
    log_json "debug" "migration_skip_existing" "پروندهٔ مقصد از پیش وجود دارد؛ جابجایی حذف شد." "destination=${destination_path}"
    return
  fi

  if [[ ! -e "${source_path}" ]]; then
    return
  fi

  local mover=(mv)
  if ${is_git_repo}; then
    if git -C "${REPO_ROOT}" ls-files --error-unmatch "${source_path#${REPO_ROOT}/}" >/dev/null 2>&1; then
      mover=(git mv)
    fi
  fi

  log_json "info" "migration_move" "انتقال ماژول به فضای نام sma." "source=${source_path}" "destination=${destination_path}" "mover=${mover[0]}"
  if ! "${mover[@]}" "${source_path}" "${destination_path}"; then
    log_json "error" "migration_failure" "خطا: انتقال ماژول انجام نشد." "module=${base_name}" >&2
    exit 1
  fi
}

shopt -s nullglob
entries=("${SRC_DIR}"/*)
IFS=$'\n' entries=($(printf '%s\n' "${entries[@]}" | sort))

for entry in "${entries[@]}"; do
  if [[ "${entry}" == "${TARGET_DIR}" ]]; then
    continue
  fi
  move_entry "${entry}"
done

MAIN_FILE="${SRC_DIR}/main.py"
if [[ -f "${MAIN_FILE}" ]]; then
  move_entry "${MAIN_FILE}"
fi

touch "${TARGET_DIR}/__init__.py"

log_json "info" "migration_complete" "مهاجرت پوشه‌های first-party به sma پایان یافت." "target=${TARGET_DIR}"
