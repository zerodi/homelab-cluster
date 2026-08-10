#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="reconcile-cilium-lb-pool"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

common::require_commands tofu kubectl realpath

kubeconfig="$(
  cd "$PROJECT_ROOT/cluster"
  realpath "$(tofu output -raw kubeconfig_path)"
)"
manifest="$(tofu -chdir="$PROJECT_ROOT/cluster" output -raw cilium_lb_pool_manifest)"

common::require_file "Kubeconfig" "$kubeconfig"

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
