#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="runtime-secrets"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  generate-runtime-secret-puts.sh
  generate-runtime-secret-puts.sh --apply-missing
  generate-runtime-secret-puts.sh --list-paths
  generate-runtime-secret-puts.sh --list-contract

Without arguments, print a complete set of bao kv put commands.

--apply-missing creates only paths that do not yet exist. Existing OpenBao
paths are never overwritten. BAO_ADDR and BAO_TOKEN must already be set.

Optional final integration credentials:
  WOODPECKER_FORGEJO_CLIENT
  WOODPECKER_FORGEJO_SECRET
  VELERO_S3_ACCESS_KEY_ID
  VELERO_S3_SECRET_ACCESS_KEY

Required external credentials:
  CLOUDFLARE_API_TOKEN
  PLATFORM_ADMIN_PASSWORD

Each pair must be supplied together. When omitted, random bootstrap credentials
are created with bootstrap_provisional=true.
EOF
}

mode="print"
case "${1:-}" in
  "")
    ;;
  --apply-missing)
    mode="apply-missing"
    ;;
  --list-paths)
    mode="list-paths"
    ;;
  --list-contract)
    mode="list-contract"
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

runtime_secret_contract=(
  "platform/cert-manager/cloudflare:api_token"
  "platform/authentik/runtime:secret_key,bootstrap_password"
  "platform/authentik/platform-admin:password"
  "platform/authentik/postgresql:password"
  "platform/authentik/redis:password"
  "platform/forgejo/admin:username,password"
  "platform/forgejo/postgresql:password"
  "platform/forgejo/valkey:password"
  "platform/forgejo/oidc:client_id,client_secret"
  "platform/argocd/oidc:client_id,client_secret"
  "platform/harbor/runtime:admin_password,secret_key,core_secret,xsrf_key,jobservice_secret,registry_http_secret,registry_password,registry_htpasswd"
  "platform/harbor/postgresql:password"
  "platform/harbor/valkey:password"
  "platform/harbor/oidc:client_id,client_secret"
  "platform/stalwart/runtime:recovery_admin_password"
  "platform/observability/grafana:username,password"
  "platform/observability/grafana-oidc:client_id,client_secret"
  "platform/woodpecker/runtime:agent_secret,forgejo_client,forgejo_secret"
  "platform/garage/runtime:rpc_secret,admin_token,metrics_token"
  "platform/velero/s3:access_key_id,secret_access_key"
)

if [[ "$mode" == "list-paths" ]]; then
  for entry in "${runtime_secret_contract[@]}"; do
    printf '%s\n' "${entry%%:*}"
  done
  exit 0
fi

if [[ "$mode" == "list-contract" ]]; then
  printf '%s\n' "${runtime_secret_contract[@]}"
  exit 0
fi

common::require_commands htpasswd

if [[ "$mode" == "apply-missing" ]]; then
  common::require_commands bao
  if [[ -z "${BAO_TOKEN:-}" ]]; then
    echo "BAO_TOKEN is required for --apply-missing." >&2
    exit 1
  fi
  bao status >/dev/null
fi

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "CLOUDFLARE_API_TOKEN is required for cert-manager DNS-01." >&2
  exit 1
fi
if [[ -z "${PLATFORM_ADMIN_PASSWORD:-}" ]]; then
  echo "PLATFORM_ADMIN_PASSWORD is required for the permanent Authentik administrator." >&2
  exit 1
fi

rand_chars() {
  local alphabet="$1"
  local length="$2"
  local out=""
  while ((${#out} < length)); do
    out+="$(
      set +o pipefail
      tr -dc "$alphabet" </dev/urandom 2>/dev/null | head -c "$length"
    )"
  done
  printf '%s' "${out:0:length}"
}

rand_alnum() {
  rand_chars 'A-Za-z0-9' "$1"
}

rand_b64ish() {
  rand_chars 'A-Za-z0-9._~!@#%^*-+=' "$1"
}

rand_hex() {
  rand_chars 'a-f0-9' "$1"
}

print_entry() {
  local path="$1"
  local item key value
  shift

  printf 'bao kv put %s' "$path"
  for item in "$@"; do
    key="${item%%=*}"
    value="${item#*=}"
    printf ' \\\n  %s=%q' "$key" "$value"
  done
  printf '\n\n'
}

created=0
skipped=0

write_entry() {
  local path="$1"
  local get_output
  shift

  if [[ "$mode" == "print" ]]; then
    print_entry "$path" "$@"
    return
  fi

  if get_output="$(bao kv get -format=json "$path" 2>&1)"; then
    printf '[runtime-secrets] existing path preserved: %s\n' "$path" >&2
    skipped=$((skipped + 1))
    return
  fi

  if [[ "$get_output" != *"No value found at"* ]]; then
    printf '[runtime-secrets] cannot verify path without risking overwrite: %s\n' \
      "$path" >&2
    printf '%s\n' "$get_output" >&2
    return 1
  fi

  bao kv put "$path" "$@" >/dev/null
  printf '[runtime-secrets] created missing path: %s\n' "$path" >&2
  created=$((created + 1))
}

mount_path="${BAO_KV_MOUNT:-secret}"

if { [[ -n "${WOODPECKER_FORGEJO_CLIENT:-}" ]] &&
  [[ -z "${WOODPECKER_FORGEJO_SECRET:-}" ]]; } ||
  { [[ -z "${WOODPECKER_FORGEJO_CLIENT:-}" ]] &&
    [[ -n "${WOODPECKER_FORGEJO_SECRET:-}" ]]; }; then
  echo "WOODPECKER_FORGEJO_CLIENT and WOODPECKER_FORGEJO_SECRET must be set together." >&2
  exit 1
fi
if { [[ -n "${VELERO_S3_ACCESS_KEY_ID:-}" ]] &&
  [[ -z "${VELERO_S3_SECRET_ACCESS_KEY:-}" ]]; } ||
  { [[ -z "${VELERO_S3_ACCESS_KEY_ID:-}" ]] &&
    [[ -n "${VELERO_S3_SECRET_ACCESS_KEY:-}" ]]; }; then
  echo "VELERO_S3_ACCESS_KEY_ID and VELERO_S3_SECRET_ACCESS_KEY must be set together." >&2
  exit 1
fi

authentik_secret_key="$(rand_b64ish 64)"
authentik_bootstrap_password="$(rand_alnum 40)"
authentik_postgresql_password="$(rand_b64ish 40)"
authentik_redis_password="$(rand_b64ish 40)"
forgejo_admin_password="$(rand_alnum 40)"
forgejo_postgresql_password="$(rand_alnum 40)"
forgejo_valkey_password="$(rand_alnum 40)"
forgejo_oidc_client_id="$(rand_alnum 32)"
forgejo_oidc_client_secret="$(rand_b64ish 64)"
argocd_oidc_client_id="$(rand_alnum 32)"
argocd_oidc_client_secret="$(rand_b64ish 64)"
harbor_admin_password="$(rand_alnum 40)"
harbor_postgresql_password="$(rand_alnum 40)"
harbor_valkey_password="$(rand_alnum 40)"
harbor_secret_key="$(rand_alnum 16)"
harbor_core_secret="$(rand_alnum 16)"
harbor_xsrf_key="$(rand_alnum 32)"
harbor_jobservice_secret="$(rand_alnum 16)"
harbor_registry_http_secret="$(rand_alnum 16)"
harbor_registry_password="$(rand_alnum 40)"
harbor_oidc_client_id="$(rand_alnum 32)"
harbor_oidc_client_secret="$(rand_b64ish 64)"
harbor_registry_htpasswd="$(
  htpasswd -nbBC 10 harbor_registry_user "$harbor_registry_password" |
    tr -d '\n'
)"
stalwart_recovery_admin_password="$(rand_alnum 40)"
grafana_password="$(rand_b64ish 32)"
grafana_oidc_client_id="$(rand_alnum 32)"
grafana_oidc_client_secret="$(rand_b64ish 64)"
woodpecker_agent_secret="$(rand_b64ish 64)"
garage_rpc_secret="$(rand_hex 64)"
garage_admin_token="$(rand_b64ish 64)"
garage_metrics_token="$(rand_b64ish 64)"

woodpecker_credentials=()
if [[ -n "${WOODPECKER_FORGEJO_CLIENT:-}" ]]; then
  woodpecker_credentials=(
    "forgejo_client=$WOODPECKER_FORGEJO_CLIENT"
    "forgejo_secret=$WOODPECKER_FORGEJO_SECRET"
  )
else
  woodpecker_credentials=(
    "forgejo_client=$(rand_alnum 32)"
    "forgejo_secret=$(rand_b64ish 64)"
    "bootstrap_provisional=true"
  )
fi

velero_credentials=()
if [[ -n "${VELERO_S3_ACCESS_KEY_ID:-}" ]]; then
  velero_credentials=(
    "access_key_id=$VELERO_S3_ACCESS_KEY_ID"
    "secret_access_key=$VELERO_S3_SECRET_ACCESS_KEY"
  )
else
  velero_credentials=(
    "access_key_id=$(rand_alnum 32)"
    "secret_access_key=$(rand_b64ish 64)"
    "bootstrap_provisional=true"
  )
fi

if [[ "$mode" == "print" ]]; then
  cat <<'EOF'
# Complete runtime secret seed for OpenBao day-0 bootstrap.
# Review before applying. Woodpecker OAuth and Velero S3 values are temporary
# bootstrap credentials and must be rotated after their external resources exist.

EOF
fi

write_entry "$mount_path/platform/cert-manager/cloudflare" \
  "api_token=$CLOUDFLARE_API_TOKEN"
write_entry "$mount_path/platform/authentik/runtime" \
  "secret_key=$authentik_secret_key" \
  "bootstrap_password=$authentik_bootstrap_password"
write_entry "$mount_path/platform/authentik/platform-admin" \
  "password=$PLATFORM_ADMIN_PASSWORD"
write_entry "$mount_path/platform/authentik/postgresql" \
  "password=$authentik_postgresql_password"
write_entry "$mount_path/platform/authentik/redis" \
  "password=$authentik_redis_password"
write_entry "$mount_path/platform/forgejo/admin" \
  "username=forgejo" \
  "password=$forgejo_admin_password"
write_entry "$mount_path/platform/forgejo/postgresql" \
  "password=$forgejo_postgresql_password"
write_entry "$mount_path/platform/forgejo/valkey" \
  "password=$forgejo_valkey_password"
write_entry "$mount_path/platform/forgejo/oidc" \
  "client_id=$forgejo_oidc_client_id" \
  "client_secret=$forgejo_oidc_client_secret"
write_entry "$mount_path/platform/argocd/oidc" \
  "client_id=$argocd_oidc_client_id" \
  "client_secret=$argocd_oidc_client_secret"
write_entry "$mount_path/platform/harbor/runtime" \
  "admin_password=$harbor_admin_password" \
  "secret_key=$harbor_secret_key" \
  "core_secret=$harbor_core_secret" \
  "xsrf_key=$harbor_xsrf_key" \
  "jobservice_secret=$harbor_jobservice_secret" \
  "registry_http_secret=$harbor_registry_http_secret" \
  "registry_password=$harbor_registry_password" \
  "registry_htpasswd=$harbor_registry_htpasswd"
write_entry "$mount_path/platform/harbor/postgresql" \
  "password=$harbor_postgresql_password"
write_entry "$mount_path/platform/harbor/valkey" \
  "password=$harbor_valkey_password"
write_entry "$mount_path/platform/harbor/oidc" \
  "client_id=$harbor_oidc_client_id" \
  "client_secret=$harbor_oidc_client_secret"
write_entry "$mount_path/platform/stalwart/runtime" \
  "recovery_admin_password=$stalwart_recovery_admin_password"
write_entry "$mount_path/platform/observability/grafana" \
  "username=admin" \
  "password=$grafana_password"
write_entry "$mount_path/platform/observability/grafana-oidc" \
  "client_id=$grafana_oidc_client_id" \
  "client_secret=$grafana_oidc_client_secret"
write_entry "$mount_path/platform/woodpecker/runtime" \
  "agent_secret=$woodpecker_agent_secret" \
  "${woodpecker_credentials[@]}"
write_entry "$mount_path/platform/garage/runtime" \
  "rpc_secret=$garage_rpc_secret" \
  "admin_token=$garage_admin_token" \
  "metrics_token=$garage_metrics_token"
write_entry "$mount_path/platform/velero/s3" \
  "${velero_credentials[@]}"

if [[ "$mode" == "apply-missing" ]]; then
  printf '[runtime-secrets] summary: created=%d preserved=%d\n' \
    "$created" "$skipped" >&2
  cat >&2 <<'EOF'
[runtime-secrets] Woodpecker OAuth and Velero S3 bootstrap credentials are
temporary. Rotate those two OpenBao paths after creating the real Forgejo OAuth
application and S3 key.
EOF
fi
