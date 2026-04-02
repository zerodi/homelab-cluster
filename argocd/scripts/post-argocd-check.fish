#!/usr/bin/env fish

set script_dir (cd (dirname (status --current-filename)); pwd)
set repo_root (cd "$script_dir/../.."; pwd)

function info
    printf '[post-argocd-check] %s\n' $argv
end

function pass
    printf 'PASS %s\n' $argv
end

function fail
    printf 'FAIL %s\n' $argv
end

function require_cmd
    if not command -sq $argv[1]
        fail "missing command: $argv[1]"
        exit 1
    end
end

function run_check
    set -l label $argv[1]
    set -e argv[1]

    if eval $argv
        pass $label
        return 0
    end

    fail $label
    return 1
end

require_cmd kubectl
require_cmd tofu

function application_synced
    set -l app $argv[1]
    set -l app_sync_status (kubectl -n argocd get application $app -o jsonpath='{.status.sync.status}' 2>/dev/null)
    test "$app_sync_status" = "Synced"
end

function application_healthy
    set -l app $argv[1]
    set -l app_health_status (kubectl -n argocd get application $app -o jsonpath='{.status.health.status}' 2>/dev/null)
    test "$app_health_status" = "Healthy"
end

function clustersecretstore_ready
    set -l store $argv[1]
    set -l ready (kubectl get clustersecretstore $store -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
    test "$ready" = "True"
end

set -l kubeconfig (cd "$repo_root/bootstrap"; realpath (tofu output -raw kubeconfig_path))
set -x KUBECONFIG $kubeconfig

set -l failed 0

info "Using kubeconfig $KUBECONFIG"

run_check "argocd namespace exists" "kubectl get namespace argocd >/dev/null"; or set failed 1
run_check "argocd pods ready" "kubectl -n argocd wait --for=condition=Ready pod --all --timeout=120s >/dev/null"; or set failed 1
run_check "argocd applications CRD established" "kubectl wait --for=condition=Established --timeout=60s crd/applications.argoproj.io >/dev/null"; or set failed 1

if kubectl -n argocd get application root-ssh >/dev/null 2>&1
    run_check "root-ssh application synced" "application_synced root-ssh"; or set failed 1
    run_check "root-ssh application healthy" "application_healthy root-ssh"; or set failed 1
else if kubectl -n argocd get application root >/dev/null 2>&1
    run_check "root application synced" "application_synced root"; or set failed 1
    run_check "root application healthy" "application_healthy root"; or set failed 1
else
    fail "no root application found (expected root-ssh or root)"
    set failed 1
end

run_check "platform application exists" "kubectl -n argocd get application platform >/dev/null"; or set failed 1
run_check "apps application exists" "kubectl -n argocd get application apps >/dev/null"; or set failed 1
run_check "gateway application exists" "kubectl -n argocd get application gateway >/dev/null"; or set failed 1
run_check "hubble application exists" "kubectl -n argocd get application hubble >/dev/null"; or set failed 1
run_check "authentik-postgresql application exists" "kubectl -n argocd get application authentik-postgresql >/dev/null"; or set failed 1
run_check "authentik-redis application exists" "kubectl -n argocd get application authentik-redis >/dev/null"; or set failed 1
run_check "forgejo-postgresql application exists" "kubectl -n argocd get application forgejo-postgresql >/dev/null"; or set failed 1
run_check "forgejo-valkey application exists" "kubectl -n argocd get application forgejo-valkey >/dev/null"; or set failed 1
run_check "observability-prereqs application exists" "kubectl -n argocd get application observability-prereqs >/dev/null"; or set failed 1
run_check "velero-prereqs application exists" "kubectl -n argocd get application velero-prereqs >/dev/null"; or set failed 1
run_check "velero application exists" "kubectl -n argocd get application velero >/dev/null"; or set failed 1
run_check "kyverno-prereqs application exists" "kubectl -n argocd get application kyverno-prereqs >/dev/null"; or set failed 1
run_check "kyverno application exists" "kubectl -n argocd get application kyverno >/dev/null"; or set failed 1
run_check "kyverno-policies application exists" "kubectl -n argocd get application kyverno-policies >/dev/null"; or set failed 1
run_check "victoria-metrics application exists" "kubectl -n argocd get application victoria-metrics >/dev/null"; or set failed 1
run_check "loki application exists" "kubectl -n argocd get application loki >/dev/null"; or set failed 1
run_check "tempo application exists" "kubectl -n argocd get application tempo >/dev/null"; or set failed 1
run_check "otel-collector application exists" "kubectl -n argocd get application otel-collector >/dev/null"; or set failed 1
run_check "grafana application exists" "kubectl -n argocd get application grafana >/dev/null"; or set failed 1
run_check "gateway application synced" "application_synced gateway"; or set failed 1
run_check "gateway application healthy" "application_healthy gateway"; or set failed 1
run_check "hubble application synced" "application_synced hubble"; or set failed 1
run_check "hubble application healthy" "application_healthy hubble"; or set failed 1
run_check "authentik-postgresql application synced" "application_synced authentik-postgresql"; or set failed 1
run_check "authentik-postgresql application healthy" "application_healthy authentik-postgresql"; or set failed 1
run_check "authentik-redis application synced" "application_synced authentik-redis"; or set failed 1
run_check "authentik-redis application healthy" "application_healthy authentik-redis"; or set failed 1
run_check "forgejo-postgresql application synced" "application_synced forgejo-postgresql"; or set failed 1
run_check "forgejo-postgresql application healthy" "application_healthy forgejo-postgresql"; or set failed 1
run_check "forgejo-valkey application synced" "application_synced forgejo-valkey"; or set failed 1
run_check "forgejo-valkey application healthy" "application_healthy forgejo-valkey"; or set failed 1
run_check "observability-prereqs application synced" "application_synced observability-prereqs"; or set failed 1
run_check "observability-prereqs application healthy" "application_healthy observability-prereqs"; or set failed 1
run_check "velero-prereqs application synced" "application_synced velero-prereqs"; or set failed 1
run_check "velero-prereqs application healthy" "application_healthy velero-prereqs"; or set failed 1
run_check "velero application synced" "application_synced velero"; or set failed 1
run_check "velero application healthy" "application_healthy velero"; or set failed 1
run_check "kyverno-prereqs application synced" "application_synced kyverno-prereqs"; or set failed 1
run_check "kyverno-prereqs application healthy" "application_healthy kyverno-prereqs"; or set failed 1
run_check "kyverno application synced" "application_synced kyverno"; or set failed 1
run_check "kyverno application healthy" "application_healthy kyverno"; or set failed 1
run_check "kyverno-policies application synced" "application_synced kyverno-policies"; or set failed 1
run_check "kyverno-policies application healthy" "application_healthy kyverno-policies"; or set failed 1
run_check "victoria-metrics application synced" "application_synced victoria-metrics"; or set failed 1
run_check "victoria-metrics application healthy" "application_healthy victoria-metrics"; or set failed 1
run_check "loki application synced" "application_synced loki"; or set failed 1
run_check "loki application healthy" "application_healthy loki"; or set failed 1
run_check "tempo application synced" "application_synced tempo"; or set failed 1
run_check "tempo application healthy" "application_healthy tempo"; or set failed 1
run_check "otel-collector application synced" "application_synced otel-collector"; or set failed 1
run_check "otel-collector application healthy" "application_healthy otel-collector"; or set failed 1
run_check "grafana application synced" "application_synced grafana"; or set failed 1
run_check "grafana application healthy" "application_healthy grafana"; or set failed 1

if kubectl get clustersecretstore openbao >/dev/null 2>&1
    run_check "openbao ClusterSecretStore ready" "clustersecretstore_ready openbao"; or set failed 1
else
    fail "openbao ClusterSecretStore missing"
    set failed 1
end

if kubectl api-resources | grep -q '^externalsecrets[[:space:]]'
    run_check "ExternalSecrets listed" "kubectl get externalsecret -A >/dev/null"; or set failed 1
else
    fail "ExternalSecret CRD missing"
    set failed 1
end

run_check "authentik namespace exists" "kubectl get namespace authentik >/dev/null"; or set failed 1
run_check "forgejo namespace exists" "kubectl get namespace forgejo >/dev/null"; or set failed 1
run_check "gateway namespace exists" "kubectl get namespace gateway >/dev/null"; or set failed 1
run_check "kube-system namespace exists" "kubectl get namespace kube-system >/dev/null"; or set failed 1
run_check "observability namespace exists" "kubectl get namespace observability >/dev/null"; or set failed 1
run_check "velero namespace exists" "kubectl get namespace velero >/dev/null"; or set failed 1
run_check "kyverno namespace exists" "kubectl get namespace kyverno >/dev/null"; or set failed 1

run_check "authentik runtime secret exists" "kubectl -n authentik get secret authentik-runtime >/dev/null"; or set failed 1
run_check "authentik tls secret exists" "kubectl -n authentik get secret authentik-tls >/dev/null"; or set failed 1
run_check "authentik postgresql auth secret exists" "kubectl -n authentik get secret authentik-postgresql-auth >/dev/null"; or set failed 1
run_check "authentik redis auth secret exists" "kubectl -n authentik get secret authentik-redis-auth >/dev/null"; or set failed 1
run_check "authentik gateway exists" "kubectl -n authentik get gateway authentik >/dev/null"; or set failed 1
run_check "authentik route exists" "kubectl -n authentik get httproute authentik >/dev/null"; or set failed 1
run_check "authentik redirect route exists" "kubectl -n authentik get httproute authentik-http-redirect >/dev/null"; or set failed 1
run_check "authentik pods ready" "kubectl -n authentik wait --for=condition=Ready pod --all --timeout=180s >/dev/null"; or set failed 1
run_check "forgejo admin secret exists" "kubectl -n forgejo get secret forgejo-admin-secret >/dev/null"; or set failed 1
run_check "forgejo tls secret exists" "kubectl -n forgejo get secret forgejo-tls >/dev/null"; or set failed 1
run_check "forgejo postgresql auth secret exists" "kubectl -n forgejo get secret forgejo-postgresql-auth >/dev/null"; or set failed 1
run_check "forgejo valkey auth secret exists" "kubectl -n forgejo get secret forgejo-valkey-auth >/dev/null"; or set failed 1
run_check "forgejo runtime config secret exists" "kubectl -n forgejo get secret forgejo-runtime-config >/dev/null"; or set failed 1
run_check "forgejo oidc secret exists" "kubectl -n forgejo get secret forgejo-oidc >/dev/null"; or set failed 1
run_check "forgejo gateway exists" "kubectl -n forgejo get gateway forgejo >/dev/null"; or set failed 1
run_check "forgejo route exists" "kubectl -n forgejo get httproute forgejo >/dev/null"; or set failed 1
run_check "forgejo redirect route exists" "kubectl -n forgejo get httproute forgejo-http-redirect >/dev/null"; or set failed 1
run_check "forgejo pods ready" "kubectl -n forgejo wait --for=condition=Ready pod --all --timeout=180s >/dev/null"; or set failed 1
run_check "grafana admin secret exists" "kubectl -n observability get secret grafana-admin-secret >/dev/null"; or set failed 1
run_check "grafana tls secret exists" "kubectl -n observability get secret grafana-tls >/dev/null"; or set failed 1
run_check "grafana gateway exists" "kubectl -n observability get gateway grafana >/dev/null"; or set failed 1
run_check "grafana route exists" "kubectl -n observability get httproute grafana >/dev/null"; or set failed 1
run_check "grafana redirect route exists" "kubectl -n observability get httproute grafana-http-redirect >/dev/null"; or set failed 1
run_check "observability pods ready" "kubectl -n observability wait --for=condition=Ready pod --all --timeout=240s >/dev/null"; or set failed 1
run_check "velero credentials secret exists" "kubectl -n velero get secret velero-credentials >/dev/null"; or set failed 1
run_check "velero backup storage location exists" "kubectl -n velero get backupstoragelocation default >/dev/null"; or set failed 1
run_check "velero schedules exist" "kubectl -n velero get schedules >/dev/null"; or set failed 1
run_check "velero deployment ready" "kubectl -n velero rollout status deployment/velero --timeout=240s >/dev/null"; or set failed 1
run_check "velero node-agent ready" "kubectl -n velero rollout status daemonset/node-agent --timeout=240s >/dev/null"; or set failed 1
run_check "kyverno admission controller ready" "kubectl -n kyverno rollout status deployment/kyverno-admission-controller --timeout=240s >/dev/null"; or set failed 1
run_check "kyverno background controller ready" "kubectl -n kyverno rollout status deployment/kyverno-background-controller --timeout=240s >/dev/null"; or set failed 1
run_check "kyverno cleanup controller ready" "kubectl -n kyverno rollout status deployment/kyverno-cleanup-controller --timeout=240s >/dev/null"; or set failed 1
run_check "kyverno reports controller ready" "kubectl -n kyverno rollout status deployment/kyverno-reports-controller --timeout=240s >/dev/null"; or set failed 1
run_check "kyverno cluster policies listable" "kubectl get cpol >/dev/null"; or set failed 1
run_check "kyverno disallow-latest policy exists" "kubectl get cpol disallow-latest-tag >/dev/null"; or set failed 1
run_check "kyverno resource policy exists" "kubectl get cpol require-resource-requests-and-limits >/dev/null"; or set failed 1
run_check "kyverno security policy exists" "kubectl get cpol require-basic-security-context >/dev/null"; or set failed 1
run_check "kyverno privileged policy exists" "kubectl get cpol disallow-privileged-containers >/dev/null"; or set failed 1
run_check "kyverno hostpath policy exists" "kubectl get cpol disallow-hostpath-volumes >/dev/null"; or set failed 1

run_check "ingresses listable" "kubectl get ingress -A >/dev/null"; or set failed 1
run_check "gatewayclasses listable" "kubectl get gatewayclass >/dev/null"; or set failed 1
run_check "gateways listable" "kubectl get gateway -A >/dev/null"; or set failed 1
run_check "httproutes listable" "kubectl get httproute -A >/dev/null"; or set failed 1
run_check "echo gateway exists" "kubectl -n echo get gateway echo >/dev/null"; or set failed 1
run_check "echo route exists" "kubectl -n echo get httproute echo >/dev/null"; or set failed 1
run_check "echo redirect route exists" "kubectl -n echo get httproute echo-http-redirect >/dev/null"; or set failed 1
run_check "hubble route exists" "kubectl -n kube-system get httproute hubble >/dev/null"; or set failed 1

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

if test $failed -ne 0
    fail "post-deploy checks completed with errors"
    exit 1
end

pass "post-deploy checks completed"
