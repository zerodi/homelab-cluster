# shellcheck shell=bash

# Shared, side-effect-free helpers for repository shell scripts.

SCRIPTS_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPTS_DIR="$(cd -- "${SCRIPTS_LIB_DIR}/.." && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPTS_DIR}/.." && pwd -P)"

common::log() {
  local component="$1"
  shift
  printf '[%s] %s\n' "$component" "$*"
}

common::die() {
  local component="$1"
  shift
  printf '[%s] ERROR: %s\n' "$component" "$*" >&2
  exit 1
}

common::require_commands() {
  local command

  for command in "$@"; do
    command -v "$command" >/dev/null 2>&1 || \
      common::die "${SCRIPT_COMPONENT:-script}" "Required command not found: $command"
  done
}

common::resolve_from_root() {
  local path="$1"

  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s/%s\n' "$PROJECT_ROOT" "$path"
  fi
}

common::absolute_path() {
  local path="$1"
  local base_dir="${2:-$PROJECT_ROOT}"
  local parent_dir
  local resolved_parent

  if [[ "$path" != /* ]]; then
    path="${base_dir}/${path}"
  fi

  if realpath "$path" 2>/dev/null; then
    return
  fi

  parent_dir="$(dirname "$path")"
  if resolved_parent="$(cd "$parent_dir" 2>/dev/null && pwd -P)"; then
    printf '%s/%s\n' "$resolved_parent" "$(basename "$path")"
  else
    printf '%s\n' "$path"
  fi
}

common::require_file() {
  local description="$1"
  local path="$2"

  [[ -f "$path" ]] || common::die "${SCRIPT_COMPONENT:-script}" "$description not found: $path"
}

common::use_kubeconfig() {
  local path="$1"

  [[ -n "$path" ]] || common::die "${SCRIPT_COMPONENT:-script}" "Kubeconfig path is required"
  path="$(common::resolve_from_root "$path")"
  common::require_file "Kubeconfig" "$path"
  export KUBECONFIG="$path"
}
