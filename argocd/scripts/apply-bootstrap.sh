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
    [--timeout <duration>]
EOF
}

kubeconfig=""
root_manifest="argocd/bootstrap/root-application.yaml"
timeout="10m"

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

log "Checking ArgoCD readiness"
kubectl get namespace argocd >/dev/null
kubectl wait --for=condition=Established --timeout="$timeout" crd/applications.argoproj.io
kubectl -n argocd rollout status --timeout="$timeout" deploy/argocd-server

log "Checking for placeholder repoURL values in argocd/"
if rg -n 'git\.example\.invalid/replace-me/gitops\.git' argocd >/dev/null; then
  echo "argocd/ still contains placeholder repoURL values." >&2
  rg -n 'git\.example\.invalid/replace-me/gitops\.git' argocd >&2
  exit 1
fi

log "Applying $root_manifest"
kubectl apply -n argocd -f "$root_manifest"

log "Waiting for Application/root sync"
deadline=$((SECONDS + 600))
while true; do
  sync_status="$(kubectl -n argocd get application root -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
  if [[ "$sync_status" == "Synced" ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Application/root did not reach Synced status within 10 minutes." >&2
    kubectl -n argocd get application root -o yaml >&2 || true
    exit 1
  fi
  sleep 5
done

log "Waiting for Application/root health"
deadline=$((SECONDS + 600))
while true; do
  health_status="$(kubectl -n argocd get application root -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
  if [[ "$health_status" == "Healthy" ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Application/root did not reach Healthy status within 10 minutes." >&2
    kubectl -n argocd get application root -o yaml >&2 || true
    exit 1
  fi
  sleep 5
done

log "ArgoCD root bootstrap completed"
