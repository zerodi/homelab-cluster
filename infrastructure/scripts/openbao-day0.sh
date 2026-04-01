#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '[openbao-day0] %s\n' "$*"
}

usage() {
  cat <<'EOF'
Usage:
  openbao-day0.sh \
    --kubeconfig <path> \
    [--bao-addr <url>] \
    [--eso-namespace <namespace>] \
    [--eso-service-account <name>] \
    [--policy-name <name>] \
    [--role-name <name>] \
    [--kv-path <path>]

Required environment:
  BAO_TOKEN    OpenBao token with rights to configure auth/policy/role.

Notes:
  - OpenBao must already be initialized and unsealed.
  - This script configures post-init day-0 state only.
  - It does not run bao operator init or store recovery material.
EOF
}

kubeconfig=""
bao_addr="${BAO_ADDR:-http://127.0.0.1:8200}"
eso_namespace="external-secrets"
eso_service_account="external-secrets"
policy_name="external-secrets"
role_name="external-secrets"
kv_path="secret"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --bao-addr)
      bao_addr="$2"
      shift 2
      ;;
    --eso-namespace)
      eso_namespace="$2"
      shift 2
      ;;
    --eso-service-account)
      eso_service_account="$2"
      shift 2
      ;;
    --policy-name)
      policy_name="$2"
      shift 2
      ;;
    --role-name)
      role_name="$2"
      shift 2
      ;;
    --kv-path)
      kv_path="$2"
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

if [[ -z "$kubeconfig" ]]; then
  echo "--kubeconfig is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$kubeconfig" ]]; then
  echo "Kubeconfig not found: $kubeconfig" >&2
  exit 1
fi

if [[ -z "${BAO_TOKEN:-}" ]]; then
  echo "BAO_TOKEN is required." >&2
  exit 1
fi

export KUBECONFIG="$kubeconfig"
export BAO_ADDR="$bao_addr"

log "Checking OpenBao status at $BAO_ADDR"
status_output="$(bao status -format=json 2>&1 || bao status 2>&1)"
printf '%s\n' "$status_output"

if [[ "$status_output" == *'"initialized":false'* ]] || [[ "$status_output" == *'Initialized'*false* ]]; then
  echo "OpenBao does not appear to be initialized." >&2
  exit 1
fi

if [[ "$status_output" == *'"sealed":true'* ]] || [[ "$status_output" == *'Sealed'*true* ]]; then
  echo "OpenBao is sealed. Unseal it before running openbao-day0." >&2
  exit 1
fi

log "Checking KV v2 mount at $kv_path/"
if bao secrets list -format=json | grep -q "\"${kv_path}/\""; then
  log "KV mount $kv_path/ already exists"
else
  log "Enabling KV v2 at $kv_path/"
  bao secrets enable -path="$kv_path" kv-v2
fi

log "Checking Kubernetes auth method"
if bao auth list -format=json | grep -q '"kubernetes/"'; then
  log "Kubernetes auth already enabled"
else
  log "Enabling Kubernetes auth"
  bao auth enable kubernetes
fi

log "Building Kubernetes auth config from service account ${eso_namespace}/${eso_service_account}"
sa_jwt_token="$(kubectl -n "$eso_namespace" create token "$eso_service_account")"
kube_ca_crt="$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d)"

log "Writing auth/kubernetes/config"
bao write auth/kubernetes/config \
  token_reviewer_jwt="$sa_jwt_token" \
  kubernetes_host="https://kubernetes.default.svc" \
  kubernetes_ca_cert="$kube_ca_crt"

policy_file="$(mktemp)"
trap 'rm -f "$policy_file"' EXIT

cat >"$policy_file" <<EOF
path "${kv_path}/data/platform/*" {
  capabilities = ["read"]
}

path "${kv_path}/metadata/platform/*" {
  capabilities = ["read", "list"]
}
EOF

log "Writing policy $policy_name"
bao policy write "$policy_name" "$policy_file"

log "Writing Kubernetes auth role $role_name"
bao write "auth/kubernetes/role/${role_name}" \
  bound_service_account_names="$eso_service_account" \
  bound_service_account_namespaces="$eso_namespace" \
  policies="$policy_name" \
  ttl="1h"

log "OpenBao day-0 post-init configuration completed"
