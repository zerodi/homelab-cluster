#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

resolve_from_root() {
  local path="$1"
  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s/%s\n' "$project_root" "$path"
  fi
}

base_path="$(resolve_from_root "${HOMELAB_CONFIG_PATH:-envs/homelab.yaml}")"
override_path="$(resolve_from_root "${HOMELAB_OVERRIDE_PATH:-envs/homelab.override.yaml}")"
output_path="$(resolve_from_root "${HOMELAB_EFFECTIVE_PATH:-out/homelab.effective.yaml}")"
materializer="$project_root/scripts/materialize_environment_contract.py"

if ! command -v yq >/dev/null 2>&1; then
  echo "Required command not found: yq" >&2
  exit 1
fi

if [[ ! -f "$base_path" ]]; then
  echo "Base environment contract not found: $base_path" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_path")"
merged_path="$(mktemp "${output_path}.merged.XXXXXX")"
temporary_path="$(mktemp "${output_path}.tmp.XXXXXX")"
trap 'rm -f "$merged_path" "$temporary_path"' EXIT

if [[ -f "$override_path" ]]; then
  yq eval-all \
    '(select(fileIndex == 0) * select(fileIndex == 1)) | ... style = ""' \
    "$base_path" "$override_path" >"$merged_path"
else
  yq eval '.' "$base_path" >"$merged_path"
fi

if [[ "$(yq eval 'tag' "$merged_path")" != "!!map" ]]; then
  echo "Effective environment contract must be a YAML mapping." >&2
  exit 1
fi

yq eval -o=json '.' "$merged_path" |
  python3 "$materializer" |
  yq eval -P '.' - >"$temporary_path"

mv "$temporary_path" "$output_path"
rm -f "$merged_path"
trap - EXIT
printf '%s\n' "$output_path"
