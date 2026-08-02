#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '[argocd-bootstrap] %s\n' "$*"
}

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

if [[ ! -f "$kubeconfig" ]]; then
  echo "Kubeconfig not found: $kubeconfig" >&2
  exit 1
fi

if [[ ! -f "$root_manifest" ]]; then
  echo "Root manifest not found: $root_manifest" >&2
  exit 1
fi

export KUBECONFIG="$kubeconfig"

test_known_hosts="$test_ssh_git_dir/keys/known_hosts"
test_repo_secret_manifest="$test_ssh_git_dir/templates/argocd-repository-secret.yaml"
test_root_manifest="$test_ssh_git_dir/templates/root-application-ssh.yaml"

wait_for_application() {
  local app_name="$1"

  log "Waiting for Application/${app_name} sync"
  deadline=$((SECONDS + 600))
  while true; do
    sync_status="$(kubectl -n argocd get application "$app_name" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    if [[ "$sync_status" == "Synced" ]]; then
      break
    fi

    if (( SECONDS >= deadline )); then
      echo "Application/${app_name} did not reach Synced status within 10 minutes." >&2
      kubectl -n argocd get application "$app_name" -o yaml >&2 || true
      exit 1
    fi
    sleep 5
  done

  log "Waiting for Application/${app_name} health"
  deadline=$((SECONDS + 600))
  while true; do
    health_status="$(kubectl -n argocd get application "$app_name" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [[ "$health_status" == "Healthy" ]]; then
      break
    fi

    if (( SECONDS >= deadline )); then
      echo "Application/${app_name} did not reach Healthy status within 10 minutes." >&2
      kubectl -n argocd get application "$app_name" -o yaml >&2 || true
      exit 1
    fi
    sleep 5
  done
}

log "Checking ArgoCD readiness"
kubectl get namespace argocd >/dev/null
kubectl wait --for=condition=Established --timeout="$timeout" crd/applications.argoproj.io
kubectl -n argocd rollout status --timeout="$timeout" deploy/argocd-server

log "Selecting the GitOps source"
if [[ "$force_test_ssh_git" == "true" ]] || rg -n 'git\.example\.invalid/replace-me/gitops\.git' argocd >/dev/null; then
  if [[ -f "$test_known_hosts" && -f "$test_repo_secret_manifest" && -f "$test_root_manifest" ]]; then
    log "Using test-ssh-git bootstrap mode"
    kubectl -n argocd create configmap argocd-ssh-known-hosts-cm \
      --from-file=ssh_known_hosts="$test_known_hosts" \
      -o yaml \
      --dry-run=client | kubectl apply -f -
    kubectl apply -f "$test_repo_secret_manifest"
    kubectl apply -f "$test_root_manifest"
    wait_for_application "root-ssh"
    log "ArgoCD root bootstrap completed via test-ssh-git"
    exit 0
  fi

  echo "argocd/ still contains placeholder repoURL values." >&2
  echo "Either replace repoURL values in argocd/ or prepare test-ssh-git via ./test-ssh-git/setup.sh." >&2
  rg -n 'git\.example\.invalid/replace-me/gitops\.git' argocd >&2
  exit 1
fi

log "Applying $root_manifest"
kubectl apply -n argocd -f "$root_manifest"
wait_for_application "root"

log "ArgoCD root bootstrap completed"
