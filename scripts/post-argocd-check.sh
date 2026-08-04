#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

info() {
  printf '[post-argocd-check] %s\n' "$*"
}

pass() {
  printf 'PASS %s\n' "$*"
}

fail() {
  printf 'FAIL %s\n' "$*" >&2
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "missing command: $1"
    exit 1
  fi
}

run_check() {
  local label="$1"
  shift

  if "$@"; then
    pass "$label"
    return 0
  fi

  fail "$label"
  return 1
}

application_synced() {
  local app="$1"
  local status
  status="$(kubectl -n argocd get application "$app" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
  [[ "$status" == "Synced" ]]
}

application_healthy() {
  local app="$1"
  local status
  status="$(kubectl -n argocd get application "$app" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
  [[ "$status" == "Healthy" ]]
}

clustersecretstore_ready() {
  local store="$1"
  local ready
  ready="$(kubectl get clustersecretstore "$store" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
  [[ "$ready" == "True" ]]
}

require_cmd kubectl
require_cmd tofu

kubeconfig="$(cd "$repo_root/cluster" && realpath "$(tofu output -raw kubeconfig_path)")"
export KUBECONFIG="$kubeconfig"

failed=0

app_names=(
  platform
  apps
  gateway
  hubble
  authentik-prereqs
  authentik-postgresql
  authentik-redis
  authentik
  forgejo-prereqs
  forgejo-postgresql
  forgejo-valkey
  forgejo
  harbor-prereqs
  harbor-postgresql
  harbor-valkey
  harbor
  stalwart-prereqs
  stalwart
  woodpecker-prereqs
  woodpecker
  garage-prereqs
  garage
  observability-prereqs
  victoria-metrics
  loki
  tempo
  otel-collector
  grafana
  velero-prereqs
  velero
  kyverno-prereqs
  kyverno
  kyverno-policies
)

namespaces=(
  authentik
  forgejo
  gateway
  garage
  harbor
  stalwart
  kube-system
  observability
  velero
  woodpecker
  kyverno
  echo
)

info "Using kubeconfig $KUBECONFIG"

run_check "argocd namespace exists" kubectl get namespace argocd >/dev/null || failed=1
run_check "argocd pods ready" kubectl -n argocd wait --for=condition=Ready pod --all --timeout=120s >/dev/null || failed=1
run_check "argocd applications CRD established" kubectl wait --for=condition=Established --timeout=60s crd/applications.argoproj.io >/dev/null || failed=1

if kubectl -n argocd get application root-ssh >/dev/null 2>&1; then
  run_check "root-ssh application synced" application_synced root-ssh || failed=1
  run_check "root-ssh application healthy" application_healthy root-ssh || failed=1
elif kubectl -n argocd get application root >/dev/null 2>&1; then
  run_check "root application synced" application_synced root || failed=1
  run_check "root application healthy" application_healthy root || failed=1
else
  fail "no root application found (expected root-ssh or root)"
  failed=1
fi

for app in "${app_names[@]}"; do
  run_check "${app} application exists" kubectl -n argocd get application "$app" >/dev/null || failed=1
  run_check "${app} application synced" application_synced "$app" || failed=1
  run_check "${app} application healthy" application_healthy "$app" || failed=1
done

if kubectl get clustersecretstore openbao >/dev/null 2>&1; then
  run_check "openbao ClusterSecretStore ready" clustersecretstore_ready openbao || failed=1
else
  fail "openbao ClusterSecretStore missing"
  failed=1
fi

if kubectl api-resources | grep -q '^externalsecrets[[:space:]]'; then
  run_check "ExternalSecrets listed" kubectl get externalsecret -A >/dev/null || failed=1
else
  fail "ExternalSecret CRD missing"
  failed=1
fi

for namespace in "${namespaces[@]}"; do
  run_check "${namespace} namespace exists" kubectl get namespace "$namespace" >/dev/null || failed=1
done

run_check "authentik runtime secret exists" kubectl -n authentik get secret authentik-runtime >/dev/null || failed=1
run_check "authentik tls secret exists" kubectl -n authentik get secret authentik-tls >/dev/null || failed=1
run_check "authentik postgresql auth secret exists" kubectl -n authentik get secret authentik-postgresql-auth >/dev/null || failed=1
run_check "authentik redis auth secret exists" kubectl -n authentik get secret authentik-redis-auth >/dev/null || failed=1
run_check "authentik gateway exists" kubectl -n authentik get gateway authentik >/dev/null || failed=1
run_check "authentik route exists" kubectl -n authentik get httproute authentik >/dev/null || failed=1
run_check "authentik redirect route exists" kubectl -n authentik get httproute authentik-http-redirect >/dev/null || failed=1
run_check "authentik pods ready" kubectl -n authentik wait --for=condition=Ready pod --all --timeout=180s >/dev/null || failed=1

run_check "forgejo admin secret exists" kubectl -n forgejo get secret forgejo-admin-secret >/dev/null || failed=1
run_check "forgejo tls secret exists" kubectl -n forgejo get secret forgejo-tls >/dev/null || failed=1
run_check "forgejo postgresql auth secret exists" kubectl -n forgejo get secret forgejo-postgresql-auth >/dev/null || failed=1
run_check "forgejo valkey auth secret exists" kubectl -n forgejo get secret forgejo-valkey-auth >/dev/null || failed=1
run_check "forgejo runtime config secret exists" kubectl -n forgejo get secret forgejo-runtime-config >/dev/null || failed=1
run_check "forgejo oidc secret exists" kubectl -n forgejo get secret forgejo-oidc >/dev/null || failed=1
run_check "forgejo gateway exists" kubectl -n forgejo get gateway forgejo >/dev/null || failed=1
run_check "forgejo route exists" kubectl -n forgejo get httproute forgejo >/dev/null || failed=1
run_check "forgejo redirect route exists" kubectl -n forgejo get httproute forgejo-http-redirect >/dev/null || failed=1
run_check "forgejo pods ready" kubectl -n forgejo wait --for=condition=Ready pod --all --timeout=180s >/dev/null || failed=1

run_check "harbor runtime secret exists" kubectl -n harbor get secret harbor-runtime >/dev/null || failed=1
run_check "harbor postgresql auth secret exists" kubectl -n harbor get secret harbor-postgresql-auth >/dev/null || failed=1
run_check "harbor valkey auth secret exists" kubectl -n harbor get secret harbor-valkey-auth >/dev/null || failed=1
run_check "harbor tls secret exists" kubectl -n harbor get secret harbor-tls >/dev/null || failed=1
run_check "harbor gateway exists" kubectl -n harbor get gateway harbor >/dev/null || failed=1
run_check "harbor route exists" kubectl -n harbor get httproute harbor >/dev/null || failed=1
run_check "harbor redirect route exists" kubectl -n harbor get httproute harbor-http-redirect >/dev/null || failed=1
run_check "harbor pods ready" kubectl -n harbor wait --for=condition=Ready pod --all --timeout=240s >/dev/null || failed=1

run_check "stalwart runtime secret exists" kubectl -n stalwart get secret stalwart-runtime >/dev/null || failed=1
run_check "stalwart mail tls secret exists" kubectl -n stalwart get secret stalwart-mail-tls >/dev/null || failed=1
run_check "stalwart admin route exists" kubectl -n stalwart get httproute stalwart >/dev/null || failed=1
run_check "stalwart redirect route exists" kubectl -n stalwart get httproute stalwart-http-redirect >/dev/null || failed=1
run_check "stalwart mail load balancer exists" kubectl -n stalwart get service stalwart-mail >/dev/null || failed=1
run_check "stalwart statefulset ready" kubectl -n stalwart rollout status statefulset/stalwart --timeout=240s >/dev/null || failed=1

run_check "woodpecker runtime secret exists" kubectl -n woodpecker get secret woodpecker-runtime >/dev/null || failed=1
run_check "woodpecker agent secret exists" kubectl -n woodpecker get secret woodpecker-default-agent-secret >/dev/null || failed=1
run_check "woodpecker tls secret exists" kubectl -n woodpecker get secret woodpecker-tls >/dev/null || failed=1
run_check "woodpecker gateway exists" kubectl -n woodpecker get gateway woodpecker >/dev/null || failed=1
run_check "woodpecker route exists" kubectl -n woodpecker get httproute woodpecker >/dev/null || failed=1
run_check "woodpecker redirect route exists" kubectl -n woodpecker get httproute woodpecker-http-redirect >/dev/null || failed=1
run_check "woodpecker pods ready" kubectl -n woodpecker wait --for=condition=Ready pod --all --timeout=240s >/dev/null || failed=1

run_check "garage config secret exists" kubectl -n garage get secret garage-config >/dev/null || failed=1
run_check "garage tls secret exists" kubectl -n garage get secret garage-tls >/dev/null || failed=1
run_check "garage gateway exists" kubectl -n garage get gateway garage >/dev/null || failed=1
run_check "garage route exists" kubectl -n garage get httproute garage >/dev/null || failed=1
run_check "garage redirect route exists" kubectl -n garage get httproute garage-http-redirect >/dev/null || failed=1
run_check "garage pods ready" kubectl -n garage wait --for=condition=Ready pod --all --timeout=240s >/dev/null || failed=1

run_check "grafana admin secret exists" kubectl -n observability get secret grafana-admin-secret >/dev/null || failed=1
run_check "grafana tls secret exists" kubectl -n observability get secret grafana-tls >/dev/null || failed=1
run_check "grafana gateway exists" kubectl -n observability get gateway grafana >/dev/null || failed=1
run_check "grafana route exists" kubectl -n observability get httproute grafana >/dev/null || failed=1
run_check "grafana redirect route exists" kubectl -n observability get httproute grafana-http-redirect >/dev/null || failed=1
run_check "observability pods ready" kubectl -n observability wait --for=condition=Ready pod --all --timeout=240s >/dev/null || failed=1

run_check "velero credentials secret exists" kubectl -n velero get secret velero-credentials >/dev/null || failed=1
run_check "velero backup storage location exists" kubectl -n velero get backupstoragelocation default >/dev/null || failed=1
run_check "velero schedules exist" kubectl -n velero get schedules >/dev/null || failed=1
run_check "velero deployment ready" kubectl -n velero rollout status deployment/velero --timeout=240s >/dev/null || failed=1
run_check "velero node-agent ready" kubectl -n velero rollout status daemonset/node-agent --timeout=240s >/dev/null || failed=1

run_check "kyverno admission controller ready" kubectl -n kyverno rollout status deployment/kyverno-admission-controller --timeout=240s >/dev/null || failed=1
run_check "kyverno background controller ready" kubectl -n kyverno rollout status deployment/kyverno-background-controller --timeout=240s >/dev/null || failed=1
run_check "kyverno cleanup controller ready" kubectl -n kyverno rollout status deployment/kyverno-cleanup-controller --timeout=240s >/dev/null || failed=1
run_check "kyverno reports controller ready" kubectl -n kyverno rollout status deployment/kyverno-reports-controller --timeout=240s >/dev/null || failed=1
run_check "kyverno validating policies listable" kubectl get validatingpolicies.policies.kyverno.io >/dev/null || failed=1
run_check "kyverno disallow-latest policy exists" kubectl get validatingpolicy.policies.kyverno.io disallow-latest-tag >/dev/null || failed=1
run_check "kyverno resource policy exists" kubectl get validatingpolicy.policies.kyverno.io require-resource-requests-and-limits >/dev/null || failed=1
run_check "kyverno security policy exists" kubectl get validatingpolicy.policies.kyverno.io require-basic-security-context >/dev/null || failed=1
run_check "kyverno privileged policy exists" kubectl get validatingpolicy.policies.kyverno.io disallow-privileged-containers >/dev/null || failed=1
run_check "kyverno hostpath policy exists" kubectl get validatingpolicy.policies.kyverno.io disallow-hostpath-volumes >/dev/null || failed=1

run_check "ingresses listable" kubectl get ingress -A >/dev/null || failed=1
run_check "gatewayclasses listable" kubectl get gatewayclass >/dev/null || failed=1
run_check "gateways listable" kubectl get gateway -A >/dev/null || failed=1
run_check "httproutes listable" kubectl get httproute -A >/dev/null || failed=1
run_check "echo gateway exists" kubectl -n echo get gateway echo >/dev/null || failed=1
run_check "echo route exists" kubectl -n echo get httproute echo >/dev/null || failed=1
run_check "echo redirect route exists" kubectl -n echo get httproute echo-http-redirect >/dev/null || failed=1
run_check "echo pods ready" kubectl -n echo wait --for=condition=Ready pod --all --timeout=120s >/dev/null || failed=1
run_check "hubble route exists" kubectl -n kube-system get httproute hubble >/dev/null || failed=1

info "Applications:"
kubectl -n argocd get applications || true

info "ClusterSecretStores:"
kubectl get clustersecretstore || true

info "ExternalSecrets:"
kubectl get externalsecret -A || true

info "Ingresses:"
kubectl get ingress -A || true

info "GatewayClasses:"
kubectl get gatewayclass || true

info "Gateways:"
kubectl get gateway -A || true

info "HTTPRoutes:"
kubectl get httproute -A || true

if [[ "$failed" -ne 0 ]]; then
  fail "post-deploy checks completed with errors"
  exit 1
fi

pass "post-deploy checks completed"
