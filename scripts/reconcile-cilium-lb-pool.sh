#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in tofu kubectl realpath; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

kubeconfig="$(
  cd "$project_root/cluster"
  realpath "$(tofu output -raw kubeconfig_path)"
)"
manifest="$(tofu -chdir="$project_root/cluster" output -raw cilium_lb_pool_manifest)"

if [[ ! -f "$kubeconfig" ]]; then
  echo "Kubeconfig not found: $kubeconfig" >&2
  exit 1
fi

for attempt in {1..300}; do
  if kubectl --kubeconfig "$kubeconfig" get \
    crd/ciliumloadbalancerippools.cilium.io >/dev/null 2>&1; then
    printf '%s\n' "$manifest" | kubectl --kubeconfig "$kubeconfig" apply -f -
    kubectl --kubeconfig "$kubeconfig" get ciliumloadbalancerippool external \
      -o jsonpath='{.spec.blocks}{"\n"}'
    exit 0
  fi
  if ((attempt < 300)); then
    sleep 2
  fi
done

echo "CiliumLoadBalancerIPPool CRD did not become available within 10 minutes." >&2
exit 1
