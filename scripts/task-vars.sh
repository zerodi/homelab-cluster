#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="task-vars"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

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
    common::absolute_path "$configured"
    return
  fi

  configured="${TF_VAR_environment_contract_path:-}"
  if [[ -n "$configured" ]]; then
    # Keep Terraform's entrypoint-relative convention for the legacy TF_VAR.
    # Both tracked entrypoints have the same directory depth, so ../out/... is
    # resolved consistently and exported back to Terraform as an absolute path.
    common::absolute_path "$configured" "${PROJECT_ROOT}/cluster"
    return
  fi

  "${PROJECT_ROOT}/scripts/render-environment-contract.sh"
}

kubeconfig_path() {
  local configured="${KUBECONFIG:-}"

  if [[ -n "$configured" ]]; then
    common::absolute_path "$configured"
    return
  fi

  configured="${TF_VAR_kubeconfig_path:-}"
  if [[ -n "$configured" ]]; then
    common::absolute_path "$configured" "${PROJECT_ROOT}/infrastructure"
    return
  fi

  configured="$(cluster_output kubeconfig_path raw)"
  [[ -z "$configured" ]] || common::absolute_path "$configured" "${PROJECT_ROOT}/cluster"
}

talosconfig_path() {
  local configured="${TALOSCONFIG:-}"

  if [[ -n "$configured" ]]; then
    common::absolute_path "$configured"
    return
  fi

  configured="$(cluster_output talosconfig_path raw)"
  [[ -z "$configured" ]] || common::absolute_path "$configured" "${PROJECT_ROOT}/cluster"
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
