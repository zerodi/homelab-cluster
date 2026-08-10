#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="bootstrap-linstor-storage"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

log() { common::log "$SCRIPT_COMPONENT" "$@"; }

usage() {
  cat <<'EOF'
Usage:
  bootstrap-linstor-storage.sh \
    --kubeconfig <path> \
    --namespace <namespace> \
    --pool-name <name> \
    --device <path> \
    --nodes "<node1 node2 ...>"
EOF
}

kubeconfig=""
namespace=""
pool_name=""
device=""
nodes=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --namespace)
      namespace="$2"
      shift 2
      ;;
    --pool-name)
      pool_name="$2"
      shift 2
      ;;
    --device)
      device="$2"
      shift 2
      ;;
    --nodes)
      nodes="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$kubeconfig" || -z "$namespace" || -z "$pool_name" || -z "$device" || -z "$nodes" ]]; then
  echo "All arguments are required." >&2
  usage >&2
  exit 1
fi

common::require_commands kubectl
common::use_kubeconfig "$kubeconfig"

if ! kubectl linstor --help >/dev/null 2>&1; then
  echo "kubectl linstor plugin is required for storage bootstrap." >&2
  exit 1
fi

log "Waiting for Piraeus datastore pods in namespace $namespace"
kubectl wait pod --timeout=15m --for=condition=Ready -n "$namespace" -l app.kubernetes.io/name=piraeus-datastore

deadline=$((SECONDS + 900))
log "Waiting for LinstorCluster/linstor to exist"
until kubectl -n "$namespace" get linstorcluster/linstor >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "LinstorCluster/linstor was not created in namespace $namespace." >&2
    echo "Run the Terraform stage that applies kubernetes_manifest.linstor_cluster before bootstrap-piraeus-storage." >&2
    exit 1
  fi
  sleep 5
done

log "Waiting for LinstorCluster/linstor to become Available"
kubectl wait --timeout=15m -n "$namespace" --for=condition=Available linstorcluster/linstor

for node in $nodes; do
  log "Waiting for default diskless pool on node $node"
  deadline=$((SECONDS + 300))
  while true; do
    node_pools="$(kubectl linstor storage-pool list --node "$node" 2>&1 | tr -d '\r')"
    if [[ "$node_pools" == *"DfltDisklessStorPool"* ]]; then
      break
    fi

    if (( SECONDS >= deadline )); then
      echo "Default diskless storage pool did not appear on node $node within 5 minutes." >&2
      printf '%s\n' "$node_pools" >&2
      exit 1
    fi
    sleep 3
  done

  log "Checking whether storage pool $pool_name already exists on node $node"
  node_target_pool="$(kubectl linstor storage-pool list --node "$node" --storage-pool "$pool_name" 2>&1 | tr -d '\r')"
  if [[ "$node_target_pool" != *"$pool_name"* ]]; then
    log "Creating storage pool $pool_name on node $node using device $device"
    kubectl linstor physical-storage create-device-pool \
      --pool-name "$pool_name" \
      --storage-pool "$pool_name" \
      lvm \
      "$node" \
      "$device"

    log "Waiting for storage pool $pool_name to appear on node $node"
    deadline=$((SECONDS + 300))
    while true; do
      node_target_pool="$(kubectl linstor storage-pool list --node "$node" --storage-pool "$pool_name" 2>&1 | tr -d '\r')"
      if [[ "$node_target_pool" == *"$pool_name"* ]]; then
        break
      fi

      if (( SECONDS >= deadline )); then
        echo "Storage pool $pool_name was not reported on node $node within 5 minutes after create-device-pool." >&2
        printf '%s\n' "$node_target_pool" >&2
        exit 1
      fi
      sleep 3
    done
  else
    log "Storage pool $pool_name already exists on node $node"
  fi
done

log "LINSTOR storage bootstrap completed"
