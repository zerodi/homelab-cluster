#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="argocd-bootstrap"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=scripts/lib/argocd.sh
source "$SCRIPT_DIR/lib/argocd.sh"

log() { common::log "$SCRIPT_COMPONENT" "$@"; }

usage() {
  cat <<'EOF'
Usage:
  apply-bootstrap.sh \
    --kubeconfig <path> \
    [--root-manifest <path>] \
    [--test-ssh-git] \
    [--timeout <duration>]
EOF
}

kubeconfig=""
root_manifest="argocd/bootstrap/root-application.yaml"
timeout="10m"
test_ssh_git_dir="test-ssh-git"
force_test_ssh_git=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --root-manifest)
      root_manifest="$2"
      shift 2
      ;;
    --timeout)
      timeout="$2"
      shift 2
      ;;
    --test-ssh-git)
      force_test_ssh_git=true
      shift
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

common::use_kubeconfig "$kubeconfig"
root_manifest="$(common::resolve_from_root "$root_manifest")"
common::require_file "Root manifest" "$root_manifest"
common::require_commands kubectl rg

test_ssh_git_dir="$(common::resolve_from_root "$test_ssh_git_dir")"
test_known_hosts="$test_ssh_git_dir/keys/known_hosts"
test_repo_secret_manifest="$test_ssh_git_dir/templates/argocd-repository-secret.yaml"
test_root_manifest="$test_ssh_git_dir/templates/root-application-ssh.yaml"

log "Checking ArgoCD readiness"
kubectl get namespace argocd >/dev/null
kubectl wait --for=condition=Established --timeout="$timeout" crd/applications.argoproj.io
kubectl -n argocd rollout status --timeout="$timeout" deploy/argocd-server

log "Selecting the GitOps source"
if [[ "$force_test_ssh_git" == "true" ]] || \
  rg -n 'git\.example\.invalid/replace-me/gitops\.git' "$PROJECT_ROOT/argocd" >/dev/null; then
  if [[ -f "$test_known_hosts" && -f "$test_repo_secret_manifest" && -f "$test_root_manifest" ]]; then
    log "Using test-ssh-git bootstrap mode"
    kubectl -n argocd create configmap argocd-ssh-known-hosts-cm \
      --from-file=ssh_known_hosts="$test_known_hosts" \
      -o yaml \
      --dry-run=client | kubectl apply -f -
    kubectl apply -f "$test_repo_secret_manifest"
    kubectl apply -f "$test_root_manifest"
    argocd::wait_for_application "root-ssh"
    log "ArgoCD root bootstrap completed via test-ssh-git"
    exit 0
  fi

  echo "argocd/ still contains placeholder repoURL values." >&2
  echo "Either replace repoURL values in argocd/ or prepare test-ssh-git via ./test-ssh-git/setup.sh." >&2
  rg -n 'git\.example\.invalid/replace-me/gitops\.git' "$PROJECT_ROOT/argocd" >&2
  exit 1
fi

log "Applying $root_manifest"
kubectl apply -n argocd -f "$root_manifest"
kubectl -n argocd annotate application root \
  argocd.argoproj.io/refresh=hard --overwrite >/dev/null
argocd::wait_for_application "root"

log "ArgoCD root bootstrap completed"
