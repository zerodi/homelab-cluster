#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

usage() {
  cat >&2 <<'EOF'
Usage: task-vars.sh <command> [arguments]

Commands:
  environment-contract
  kubeconfig
  talosconfig
  cluster-output <name> [raw|json]
  contract-value <yq-path> <override-environment-variable>
  piraeus-nodes
EOF
  exit 2
}

absolute_path() {
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

cluster_output() {
  local name="$1"
  local format="${2:-raw}"
  local value

  if ! value="$(tofu -chdir="${PROJECT_ROOT}/cluster" output "-${format}" "$name" 2>/dev/null)"; then
    return 0
  fi
  printf '%s\n' "$value"
}

environment_contract() {
  local configured="${ENVIRONMENT_CONTRACT_PATH:-}"

  if [[ -n "$configured" ]]; then
    absolute_path "$configured"
    return
  fi

  configured="${TF_VAR_environment_contract_path:-}"
  if [[ -n "$configured" ]]; then
    # Keep Terraform's entrypoint-relative convention for the legacy TF_VAR.
    # Both tracked entrypoints have the same directory depth, so ../out/... is
    # resolved consistently and exported back to Terraform as an absolute path.
    absolute_path "$configured" "${PROJECT_ROOT}/cluster"
    return
  fi

  "${PROJECT_ROOT}/scripts/render-environment-contract.sh"
}

kubeconfig_path() {
  local configured="${KUBECONFIG:-}"

  if [[ -n "$configured" ]]; then
    absolute_path "$configured"
    return
  fi

  configured="${TF_VAR_kubeconfig_path:-}"
  if [[ -n "$configured" ]]; then
    absolute_path "$configured" "${PROJECT_ROOT}/infrastructure"
    return
  fi

  configured="$(cluster_output kubeconfig_path raw)"
  [[ -z "$configured" ]] || absolute_path "$configured" "${PROJECT_ROOT}/cluster"
}

talosconfig_path() {
  local configured="${TALOSCONFIG:-}"

  if [[ -n "$configured" ]]; then
    absolute_path "$configured"
    return
  fi

  configured="$(cluster_output talosconfig_path raw)"
  [[ -z "$configured" ]] || absolute_path "$configured" "${PROJECT_ROOT}/cluster"
}

contract_value() {
  local yq_path="$1"
  local override_name="$2"
  local override_value="${!override_name:-}"

  if [[ -n "$override_value" ]]; then
    printf '%s\n' "$override_value"
    return
  fi

  yq eval -r "${yq_path} // \"\"" "$(environment_contract)"
}

piraeus_nodes() {
  local configured="${TF_VAR_piraeus_storage_nodes:-}"
  local nodes_json

  if [[ -n "$configured" ]]; then
    printf '%s' "$configured" | yq eval -p=json -r 'join(" ")' -
    return
  fi

  nodes_json="$(cluster_output worker_hostnames json)"
  [[ -z "$nodes_json" ]] || printf '%s' "$nodes_json" | yq eval -p=json -r 'join(" ")' -
}

command="${1:-}"
case "$command" in
  environment-contract)
    environment_contract
    ;;
  kubeconfig)
    kubeconfig_path
    ;;
  talosconfig)
    talosconfig_path
    ;;
  cluster-output)
    [[ $# -ge 2 && $# -le 3 ]] || usage
    cluster_output "$2" "${3:-raw}"
    ;;
  contract-value)
    [[ $# -eq 3 ]] || usage
    contract_value "$2" "$3"
    ;;
  piraeus-nodes)
    [[ $# -eq 1 ]] || usage
    piraeus_nodes
    ;;
  *)
    usage
    ;;
esac
