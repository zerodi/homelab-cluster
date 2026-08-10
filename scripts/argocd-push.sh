#!/usr/bin/env bash
# Bootstrap role: deploy (publishes the committed runtime tree to GitOps).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="argocd-push"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=scripts/lib/forgejo.sh
source "$SCRIPT_DIR/lib/forgejo.sh"

usage() {
  cat <<'EOF'
Usage: argocd-push.sh --kubeconfig <path> --contract <effective-environment-contract>

Publishes the committed argocd/ subtree to the Forgejo repository and branch
declared by the effective environment contract. The command never commits,
configures a Git remote, or force-pushes.

Optional environment (must be supplied together):
  FORGEJO_GIT_USERNAME  Forgejo user with repository write access
  FORGEJO_GIT_PASSWORD  password or write-scoped token

When omitted, credentials are read from the Forgejo bootstrap admin Secret.
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

kubeconfig="$(common::resolve_from_root "$kubeconfig")"
contract="$(common::resolve_from_root "$contract")"
common::require_file "Kubeconfig" "$kubeconfig"
common::require_file "Environment contract" "$contract"
common::require_commands base64 git kubectl yq
common::use_kubeconfig "$kubeconfig"

repo_url="$(yq eval -r '.gitops.repo_url // ""' "$contract")"
revision="$(yq eval -r '.gitops.revision // ""' "$contract")"
forgejo_host="$(yq eval -r '.hosts.forgejo // ""' "$contract")"
forgejo_namespace="$(yq eval -r '.platform.forgejo.namespace // ""' "$contract")"
forgejo_admin_secret="$(yq eval -r '.platform.forgejo.admin_secret_name // ""' "$contract")"

[[ "$repo_url" == "https://${forgejo_host}/"*.git ]] || common::die "$SCRIPT_COMPONENT" \
  "gitops.repo_url must be an HTTPS Forgejo URL for hosts.forgejo"
[[ "$revision" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || common::die "$SCRIPT_COMPONENT" \
  "Unsupported gitops.revision: ${revision}"
[[ "$revision" != *..* && "$revision" != *//* && "$revision" != */ ]] || \
  common::die "$SCRIPT_COMPONENT" "Unsafe gitops.revision: ${revision}"
[[ -n "$forgejo_namespace" ]] || common::die "$SCRIPT_COMPONENT" \
  "platform.forgejo.namespace is missing"
[[ -n "$forgejo_admin_secret" ]] || common::die "$SCRIPT_COMPONENT" \
  "platform.forgejo.admin_secret_name is missing"

forgejo::require_clean_subtree "$PROJECT_ROOT" argocd

forgejo_ip="$(
  kubectl -n "$forgejo_namespace" get service cilium-gateway-forgejo \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
)"
[[ -n "$forgejo_ip" ]] || common::die "$SCRIPT_COMPONENT" \
  "Forgejo Gateway Service has no LoadBalancer IP"

forgejo_tls_secret="$(
  kubectl -n "$forgejo_namespace" get gateway forgejo \
    -o jsonpath='{.spec.listeners[?(@.protocol=="HTTPS")].tls.certificateRefs[0].name}'
)"
[[ -n "$forgejo_tls_secret" ]] || common::die "$SCRIPT_COMPONENT" \
  "Forgejo Gateway has no HTTPS certificate reference"

work_dir="$(mktemp -d)"
trust_file="$work_dir/forgejo-repository-trust.pem"
username="${FORGEJO_GIT_USERNAME:-}"
password="${FORGEJO_GIT_PASSWORD:-}"

cleanup() {
  username=""
  password=""
  rm -rf "$work_dir"
}
trap cleanup EXIT

kubectl -n "$forgejo_namespace" get secret "$forgejo_tls_secret" \
  -o go-template='{{ index .data "tls.crt" }}' | base64 -d > "$trust_file"
[[ -s "$trust_file" ]] || common::die "$SCRIPT_COMPONENT" \
  "Exported Forgejo TLS trust bundle is empty"

if [[ -n "$username" || -n "$password" ]]; then
  [[ -n "$username" && -n "$password" ]] || common::die "$SCRIPT_COMPONENT" \
    "FORGEJO_GIT_USERNAME and FORGEJO_GIT_PASSWORD must be supplied together"
else
  username="$(
    kubectl -n "$forgejo_namespace" get secret "$forgejo_admin_secret" \
      -o jsonpath='{.data.username}' | base64 -d
  )"
  password="$(
    kubectl -n "$forgejo_namespace" get secret "$forgejo_admin_secret" \
      -o jsonpath='{.data.password}' | base64 -d
  )"
fi
[[ -n "$username" && -n "$password" ]] || common::die "$SCRIPT_COMPONENT" \
  "Forgejo write credentials are empty"

common::log "$SCRIPT_COMPONENT" \
  "Publishing committed argocd/ to ${repo_url} branch ${revision}"
forgejo::push_subtree \
  "$PROJECT_ROOT" argocd "$repo_url" "$revision" "$trust_file" \
  "$forgejo_host" "$forgejo_ip" "$username" "$password"
common::log "$SCRIPT_COMPONENT" \
  "Push completed; Argo CD will reconcile ${repo_url}@${revision}"
