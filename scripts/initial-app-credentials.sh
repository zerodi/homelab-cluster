#!/usr/bin/env bash
# Bootstrap role: no-deploy (read-only operator credential display).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="initial-app-credentials"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: initial-app-credentials.sh --kubeconfig <path> --contract <effective-environment-contract>

Print initial interactive administrator credentials. Runtime application
credentials are read from OpenBao. The Argo CD bootstrap password is read from
argocd-initial-admin-secret when that Secret still exists.

Required environment:
  BAO_TOKEN       token allowed to read the runtime application secret paths

Optional environment:
  BAO_ADDR        OpenBao address (normally http://127.0.0.1:8200)
  BAO_KV_MOUNT    KV v2 mount name (default: secret)
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
      common::die "$SCRIPT_COMPONENT" "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$kubeconfig" ]] || common::die "$SCRIPT_COMPONENT" "--kubeconfig is required"
[[ -n "$contract" ]] || common::die "$SCRIPT_COMPONENT" "--contract is required"
[[ -n "${BAO_TOKEN:-}" ]] || common::die "$SCRIPT_COMPONENT" "BAO_TOKEN is required"

kubeconfig="$(common::resolve_from_root "$kubeconfig")"
contract="$(common::resolve_from_root "$contract")"
common::require_file "Kubeconfig" "$kubeconfig"
common::require_file "Environment contract" "$contract"
common::require_commands bao base64 kubectl yq

bao_mount="${BAO_KV_MOUNT:-secret}"

read_bao_field() {
  local path="$1"
  local field="$2"
  local value

  if ! value="$(bao kv get -field="$field" "${bao_mount}/${path}")"; then
    common::die "$SCRIPT_COMPONENT" \
      "Cannot read ${bao_mount}/${path} field ${field} from OpenBao"
  fi
  [[ -n "$value" ]] || common::die "$SCRIPT_COMPONENT" \
    "OpenBao field is empty: ${bao_mount}/${path}:${field}"
  printf '%s' "$value"
}

host_for() {
  local app="$1"
  local host

  host="$(yq eval -r ".hosts.${app} // \"\"" "$contract")"
  [[ -n "$host" ]] || common::die "$SCRIPT_COMPONENT" \
    "Environment contract does not define hosts.${app}"
  printf '%s' "$host"
}

# Resolve every OpenBao value before printing anything to avoid partial output.
authentik_password="$(read_bao_field platform/authentik/runtime bootstrap_password)"
platform_admin_password="$(read_bao_field platform/authentik/platform-admin password)"
platform_admin_username="$(yq eval -r '.identity.administrator.username // ""' "$contract")"
[[ -n "$platform_admin_username" ]] || common::die "$SCRIPT_COMPONENT" \
  "Environment contract does not define identity.administrator.username"
forgejo_login="$(read_bao_field platform/forgejo/admin username)"
forgejo_password="$(read_bao_field platform/forgejo/admin password)"
grafana_login="$(read_bao_field platform/observability/grafana username)"
grafana_password="$(read_bao_field platform/observability/grafana password)"
harbor_password="$(read_bao_field platform/harbor/runtime admin_password)"
stalwart_password="$(read_bao_field platform/stalwart/runtime recovery_admin_password)"

argocd_password=""
if encoded_password="$(
  kubectl --kubeconfig "$kubeconfig" -n argocd \
    get secret argocd-initial-admin-secret \
    -o jsonpath='{.data.password}' 2>/dev/null
)" && [[ -n "$encoded_password" ]]; then
  argocd_password="$(printf '%s' "$encoded_password" | base64 -d)"
else
  argocd_password="<bootstrap secret unavailable>"
  common::log "$SCRIPT_COMPONENT" \
    "Argo CD initial password is unavailable; the Secret may have been deleted after password rotation." >&2
fi

printf 'WARNING: sensitive bootstrap credentials; do not save this output in Git or shell history.\n' >&2
printf 'APPLICATION\tURL\tLOGIN\tPASSWORD\n'
printf 'Authentik\thttps://%s/if/admin/\takadmin\t%s\n' \
  "$(host_for authentik)" "$authentik_password"
printf 'Authentik Administrator\thttps://%s/\t%s\t%s\n' \
  "$(host_for authentik)" "$platform_admin_username" "$platform_admin_password"
printf 'Argo CD\thttps://%s\tadmin\t%s\n' \
  "$(host_for argocd)" "$argocd_password"
printf 'Forgejo\thttps://%s\t%s\t%s\n' \
  "$(host_for forgejo)" "$forgejo_login" "$forgejo_password"
printf 'Grafana\thttps://%s\t%s\t%s\n' \
  "$(host_for grafana)" "$grafana_login" "$grafana_password"
printf 'Harbor\thttps://%s\tadmin\t%s\n' \
  "$(host_for harbor)" "$harbor_password"
printf 'Stalwart\thttps://%s/admin\tadmin\t%s\n' \
  "$(host_for stalwart)" "$stalwart_password"
