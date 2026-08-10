#!/usr/bin/env bash
# Bootstrap role: no-deploy (client configuration rendering only).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="hosts-entries"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: hosts-entries.sh --kubeconfig <path> --contract <effective-environment-contract>
EOF
}

kubeconfig=""
contract=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --contract)
      contract="$2"
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

if [[ -z "$kubeconfig" || -z "$contract" ]]; then
  echo "--kubeconfig and --contract are required." >&2
  usage >&2
  exit 1
fi

common::require_commands awk kubectl
common::require_file "Kubeconfig" "$kubeconfig"
common::require_file "Environment contract" "$contract"

hostname_for() {
  local wanted_key="$1"

  awk -v wanted_key="$wanted_key" '
    /^hosts:$/ {
      in_hosts = 1
      next
    }
    /^platform:$/ {
      in_hosts = 0
    }
    in_hosts && $0 ~ /^  [a-z_]+: / {
      key = $1
      sub(/:$/, "", key)
      hostname = $2
      gsub(/"/, "", hostname)
      if (key == wanted_key) {
        print hostname
        exit
      }
    }
  ' "$contract"
}

resources=(
  'argocd|Ingress|argocd|argocd-server'
  'authentik|Service|authentik|cilium-gateway-authentik'
  'forgejo|Service|forgejo|cilium-gateway-forgejo'
  'garage|Service|garage|cilium-gateway-garage'
  'harbor|Service|harbor|cilium-gateway-harbor'
  'stalwart|Service|gateway|cilium-gateway-external'
  'mail|Service|stalwart|stalwart-mail'
  'woodpecker|Service|woodpecker|cilium-gateway-woodpecker'
  'echo|Service|echo|cilium-gateway-echo'
  'grafana|Service|observability|cilium-gateway-grafana'
  'hubble|Service|gateway|cilium-gateway-internal'
)

entries=()
missing=()

for resource in "${resources[@]}"; do
  IFS='|' read -r key kind namespace name <<< "$resource"
  hostname="$(hostname_for "$key")"

  if [[ -z "$hostname" ]]; then
    missing+=("environment contract hostname: hosts.$key")
    continue
  fi

  address="$(
    kubectl --kubeconfig "$kubeconfig" -n "$namespace" get "$kind" "$name" \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true
  )"

  if [[ -z "$address" ]]; then
    missing+=("$kind $namespace/$name for $hostname")
    continue
  fi

  entries+=("$address $hostname")
done

if (( ${#missing[@]} > 0 )); then
  echo "Cannot build a complete hosts file: actual LoadBalancer IPs are missing:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

printf '%s\n' "${entries[@]}"
