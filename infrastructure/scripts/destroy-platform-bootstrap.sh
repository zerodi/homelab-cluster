#!/usr/bin/env bash

set -euo pipefail

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
infra_dir="$repo_root/infrastructure"
bootstrap_dir="$repo_root/bootstrap"
destroy_args=("$@")

crd_backed_targets=(
  "kubernetes_manifest.selfsigned_clusterissuer[0]"
  "kubernetes_manifest.homelab_root_ca[0]"
  "kubernetes_manifest.homelab_ca_clusterissuer[0]"
  "kubernetes_manifest.homelab_trust_bundle[0]"
  "kubernetes_manifest.linstor_satellite_configuration_talos[0]"
  "kubernetes_manifest.linstor_cluster[0]"
)

target_missing_from_state() {
  local target="$1"

  tofu -chdir="$infra_dir" state list "$target" >/dev/null 2>&1
}

crd_is_registered() {
  local crd="$1"

  [[ -n "${KUBECONFIG:-}" ]] || return 1
  kubectl get crd "$crd" >/dev/null 2>&1
}

prime_kubeconfig() {
  local kubeconfig_path

  if ! command -v kubectl >/dev/null 2>&1; then
    return 1
  fi

  kubeconfig_path=$(tofu -chdir="$bootstrap_dir" output -raw kubeconfig_path 2>/dev/null || true)
  if [[ -z "$kubeconfig_path" || ! -f "$kubeconfig_path" ]]; then
    return 1
  fi

  export KUBECONFIG="$kubeconfig_path"
  return 0
}

prune_missing_crd_targets() {
  local -a stale_targets=()
  local target=""
  local crd=""

  while read -r target crd; do
    if ! target_missing_from_state "$target"; then
      continue
    fi

    if crd_is_registered "$crd"; then
      continue
    fi

    stale_targets+=("$target")
  done <<'EOF'
kubernetes_manifest.selfsigned_clusterissuer[0] clusterissuers.cert-manager.io
kubernetes_manifest.homelab_root_ca[0] certificates.cert-manager.io
kubernetes_manifest.homelab_ca_clusterissuer[0] clusterissuers.cert-manager.io
kubernetes_manifest.homelab_trust_bundle[0] bundles.trust.cert-manager.io
kubernetes_manifest.linstor_satellite_configuration_talos[0] linstorsatelliteconfigurations.piraeus.io
kubernetes_manifest.linstor_cluster[0] linstorclusters.piraeus.io
EOF

  if [[ ${#stale_targets[@]} -eq 0 ]]; then
    return 0
  fi

  printf 'Removing stale CRD-backed resources from infrastructure state because their CRDs are absent:\n' >&2
  printf '  %s\n' "${stale_targets[@]}" >&2
  tofu -chdir="$infra_dir" state rm "${stale_targets[@]}"
}

destroy_crd_backed_resources() {
  local -a target_args=()
  local target=""

  for target in "${crd_backed_targets[@]}"; do
    if target_missing_from_state "$target"; then
      target_args+=("-target=$target")
    fi
  done

  if [[ ${#target_args[@]} -eq 0 ]]; then
    return 0
  fi

  tofu -chdir="$infra_dir" destroy -refresh=false "${destroy_args[@]}" "${target_args[@]}"
}

main() {
  require_cmd tofu

  if prime_kubeconfig; then
    prune_missing_crd_targets
  fi
  destroy_crd_backed_resources
  tofu -chdir="$infra_dir" destroy -refresh=false "${destroy_args[@]}"
}

main "$@"
