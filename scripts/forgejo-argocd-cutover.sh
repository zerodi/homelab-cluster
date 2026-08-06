#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

log() {
  printf '[forgejo-cutover] %s\n' "$*"
}

fail() {
  printf '[forgejo-cutover] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  forgejo-argocd-cutover.sh \
    --kubeconfig <path> \
    --contract <effective-environment-contract> \
    [--timeout <duration>]

Required environment:
  BAO_ADDR   Address of the unsealed OpenBao instance
  BAO_TOKEN  Token allowed to write secret/platform/argocd/repository
EOF
}

kubeconfig=""
contract=""
timeout="10m"

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
    --timeout)
      timeout="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$kubeconfig" ]] || fail "--kubeconfig is required"
[[ -f "$kubeconfig" ]] || fail "Kubeconfig not found: $kubeconfig"
[[ -n "$contract" ]] || fail "--contract is required"
[[ -f "$contract" ]] || fail "Environment contract not found: $contract"
[[ -n "${BAO_ADDR:-}" ]] || fail "BAO_ADDR is required"
[[ -n "${BAO_TOKEN:-}" ]] || fail "BAO_TOKEN is required"

for command in bao base64 curl docker git jq kubectl openssl rg yq; do
  command -v "$command" >/dev/null 2>&1 || fail "Required command not found: $command"
done

export KUBECONFIG="$kubeconfig"

repo_url="$(yq eval -r '.gitops.repo_url // ""' "$contract")"
revision="$(yq eval -r '.gitops.revision // ""' "$contract")"
forgejo_host="$(yq eval -r '.hosts.forgejo // ""' "$contract")"
forgejo_namespace="$(yq eval -r '.platform.forgejo.namespace // ""' "$contract")"
forgejo_admin_secret="$(yq eval -r '.platform.forgejo.admin_secret_name // ""' "$contract")"

[[ "$repo_url" == "https://${forgejo_host}/"*.git ]] || \
  fail "gitops.repo_url must be an HTTPS Forgejo URL for hosts.forgejo"
[[ "$revision" == "main" ]] || fail "Automated cutover currently requires gitops.revision=main"
[[ -n "$forgejo_namespace" ]] || fail "platform.forgejo.namespace is missing"
[[ -n "$forgejo_admin_secret" ]] || fail "platform.forgejo.admin_secret_name is missing"

repo_prefix="https://${forgejo_host}/"
repo_path="${repo_url#"$repo_prefix"}"
repo_path="${repo_path%.git}"
[[ "$repo_path" == */* && "$repo_path" != */*/* ]] || \
  fail "gitops.repo_url path must have exactly <organization>/<repository>"
forgejo_org="${repo_path%%/*}"
forgejo_repo="${repo_path##*/}"
argocd_user="argocd"
argocd_email="argocd@${forgejo_host}"
token_name="argocd-gitops"

for value in "$forgejo_org" "$forgejo_repo" "$argocd_user"; do
  [[ "$value" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "Unsupported Forgejo identifier: $value"
done

if ! git -C "$project_root" diff --quiet -- argocd || \
   ! git -C "$project_root" diff --cached --quiet -- argocd || \
   [[ -n "$(git -C "$project_root" ls-files --others --exclude-standard -- argocd)" ]]; then
  fail "argocd/ has uncommitted changes; commit them before publishing the GitOps repository"
fi

log "Validating the canonical environment contract"
"$project_root/scripts/validate-env-contract.py" --mode strict

log "Checking Forgejo, Argo CD, and OpenBao readiness"
kubectl -n argocd rollout status deployment/argocd-server --timeout="$timeout" >/dev/null
kubectl -n argocd rollout status deployment/argocd-repo-server --timeout="$timeout" >/dev/null
kubectl -n "$forgejo_namespace" rollout status deployment/forgejo --timeout="$timeout" >/dev/null
bao status >/dev/null

forgejo_ip="$(
  kubectl -n "$forgejo_namespace" get service cilium-gateway-forgejo \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
)"
[[ -n "$forgejo_ip" ]] || fail "Forgejo Gateway Service has no LoadBalancer IP"

ca_file="$project_root/out/homelab-root-ca.crt"
mkdir -p "$(dirname "$ca_file")"
kubectl -n cert-manager get secret homelab-root-ca \
  -o go-template='{{ index .data "tls.crt" }}' | base64 -d > "$ca_file"
[[ -s "$ca_file" ]] || fail "Exported homelab root CA is empty"

admin_user="$(
  kubectl -n "$forgejo_namespace" get secret "$forgejo_admin_secret" \
    -o jsonpath='{.data.username}' | base64 -d
)"
admin_password="$(
  kubectl -n "$forgejo_namespace" get secret "$forgejo_admin_secret" \
    -o jsonpath='{.data.password}' | base64 -d
)"
[[ -n "$admin_user" && -n "$admin_password" ]] || fail "Forgejo admin Secret is incomplete"
[[ "$admin_user" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "Unsupported Forgejo admin username"

work_dir="$(mktemp -d)"
api_body="$work_dir/api-body.json"
repo_token=""
argocd_password=""

cleanup() {
  admin_password=""
  argocd_password=""
  repo_token=""
  rm -rf "$work_dir"
}
trap cleanup EXIT

api_status=""
api_call() {
  local auth="$1"
  local method="$2"
  local path="$3"
  local data="${4:-}"
  local -a args=(
    --silent
    --show-error
    --cacert "$ca_file"
    --resolve "${forgejo_host}:443:${forgejo_ip}"
    --request "$method"
    --output "$api_body"
    --write-out '%{http_code}'
    --header 'Accept: application/json'
  )

  case "$auth" in
    admin)
      args+=(--user "${admin_user}:${admin_password}")
      ;;
    argocd-basic)
      args+=(--user "${argocd_user}:${argocd_password}")
      ;;
    repository-token)
      args+=(--header "Authorization: token ${repo_token}")
      ;;
    *)
      fail "Unknown API authentication mode: $auth"
      ;;
  esac

  if [[ -n "$data" ]]; then
    args+=(--header 'Content-Type: application/json' --data "$data")
  fi

  api_status="$(curl "${args[@]}" "https://${forgejo_host}/api/v1${path}")"
}

expect_api_status() {
  local expected="$1"
  local action="$2"
  [[ "$api_status" == "$expected" ]] || \
    fail "$action failed with Forgejo API status $api_status"
}

log "Ensuring Forgejo organization ${forgejo_org}"
api_call admin GET "/orgs/${forgejo_org}"
if [[ "$api_status" == "404" ]]; then
  api_call admin POST "/admin/users/${admin_user}/orgs" "$(
    jq -cn --arg username "$forgejo_org" \
      '{username:$username,visibility:"private",description:"Platform repositories"}'
  )"
  expect_api_status 201 "Creating organization ${forgejo_org}"
else
  expect_api_status 200 "Reading organization ${forgejo_org}"
fi

log "Ensuring Forgejo repository ${forgejo_org}/${forgejo_repo}"
api_call admin GET "/repos/${forgejo_org}/${forgejo_repo}"
if [[ "$api_status" == "404" ]]; then
  api_call admin POST "/orgs/${forgejo_org}/repos" "$(
    jq -cn --arg name "$forgejo_repo" \
      '{name:$name,private:true,auto_init:false,default_branch:"main",description:"Argo CD GitOps source"}'
  )"
  expect_api_status 201 "Creating repository ${forgejo_org}/${forgejo_repo}"
else
  expect_api_status 200 "Reading repository ${forgejo_org}/${forgejo_repo}"
fi

log "Ensuring dedicated Forgejo user ${argocd_user}"
api_call admin GET "/users/${argocd_user}"
if [[ "$api_status" == "404" ]]; then
  argocd_password="$(openssl rand -base64 48 | tr -d '\n')"
  api_call admin POST /admin/users "$(
    jq -cn \
      --arg username "$argocd_user" \
      --arg email "$argocd_email" \
      --arg password "$argocd_password" \
      '{username:$username,email:$email,password:$password,must_change_password:false,restricted:true,send_notify:false}'
  )"
  expect_api_status 201 "Creating user ${argocd_user}"
else
  expect_api_status 200 "Reading user ${argocd_user}"
fi

api_call admin PUT "/repos/${forgejo_org}/${forgejo_repo}/collaborators/${argocd_user}" \
  '{"permission":"read"}'
expect_api_status 204 "Granting read access to ${argocd_user}"

stored_username="$(bao kv get -field=username secret/platform/argocd/repository 2>/dev/null || true)"
repo_token="$(bao kv get -field=token secret/platform/argocd/repository 2>/dev/null || true)"

token_valid=false
if [[ "$stored_username" == "$argocd_user" && -n "$repo_token" ]]; then
  api_call repository-token GET "/repos/${forgejo_org}/${forgejo_repo}"
  if [[ "$api_status" == "200" ]]; then
    token_valid=true
  fi
fi

if [[ "$token_valid" != "true" ]]; then
  log "Creating repository-scoped read token for ${argocd_user}"
  argocd_password="$(openssl rand -base64 48 | tr -d '\n')"
  api_call admin PATCH "/admin/users/${argocd_user}" "$(
    jq -cn --arg password "$argocd_password" \
      '{password:$password,must_change_password:false,restricted:true}'
  )"
  expect_api_status 200 "Rotating the service-account password"

  api_call argocd-basic DELETE "/users/${argocd_user}/tokens/${token_name}"
  if [[ "$api_status" != "204" && "$api_status" != "404" ]]; then
    fail "Removing the previous access token failed with Forgejo API status $api_status"
  fi

  api_call argocd-basic POST "/users/${argocd_user}/tokens" "$(
    jq -cn \
      --arg name "$token_name" \
      --arg owner "$forgejo_org" \
      --arg repo "$forgejo_repo" \
      '{name:$name,scopes:["read:repository"],repositories:[{owner:$owner,name:$repo}]}'
  )"
  expect_api_status 201 "Creating the Argo CD repository token"
  repo_token="$(jq -r '.sha1 // ""' "$api_body")"
  [[ -n "$repo_token" ]] || fail "Forgejo did not return the new repository token"

  bao kv put secret/platform/argocd/repository \
    username="$argocd_user" \
    token="$repo_token" >/dev/null
fi

log "Publishing the committed argocd/ subtree to Forgejo"
subtree_commit="$(git -C "$project_root" subtree split --prefix=argocd HEAD)"
[[ -n "$subtree_commit" ]] || fail "Failed to create the argocd subtree commit"

env \
  -u SSH_ASKPASS \
  -u VSCODE_GIT_ASKPASS_MAIN \
  -u VSCODE_GIT_ASKPASS_NODE \
  -u VSCODE_GIT_ASKPASS_EXTRA_ARGS \
  -u VSCODE_GIT_IPC_HANDLE \
  GIT_ASKPASS="$project_root/scripts/forgejo-git-askpass.sh" \
  GIT_TERMINAL_PROMPT=0 \
  FORGEJO_GIT_USERNAME="$admin_user" \
  FORGEJO_GIT_PASSWORD="$admin_password" \
  git -C "$project_root" \
    -c credential.helper= \
    -c "http.sslCAInfo=${ca_file}" \
    -c "http.curloptResolve=${forgejo_host}:443:${forgejo_ip}" \
    push "$repo_url" "${subtree_commit}:refs/heads/main"

log "Configuring the Forgejo CA and repository credential in Argo CD"
if ! kubectl -n argocd get configmap argocd-tls-certs-cm >/dev/null 2>&1; then
  kubectl -n argocd create configmap argocd-tls-certs-cm >/dev/null
fi
ca_patch="$(jq -Rs --arg host "$forgejo_host" '{data:{($host):.}}' < "$ca_file")"
kubectl -n argocd patch configmap argocd-tls-certs-cm --type=merge -p "$ca_patch" >/dev/null
kubectl -n argocd rollout restart deployment/argocd-repo-server >/dev/null
kubectl -n argocd rollout status deployment/argocd-repo-server --timeout="$timeout" >/dev/null

kubectl apply -f "$project_root/argocd/bootstrap/forgejo-gitops-repository.yaml" >/dev/null
kubectl -n argocd wait \
  --for=condition=Ready \
  externalsecret/forgejo-gitops-repository \
  --timeout="$timeout" >/dev/null
kubectl -n argocd get secret forgejo-gitops-repository >/dev/null

wait_for_application() {
  local name="$1"
  local deadline=$((SECONDS + 600))
  local sync_status
  local health_status

  while ((SECONDS < deadline)); do
    sync_status="$(
      kubectl -n argocd get application "$name" \
        -o jsonpath='{.status.sync.status}' 2>/dev/null || true
    )"
    health_status="$(
      kubectl -n argocd get application "$name" \
        -o jsonpath='{.status.health.status}' 2>/dev/null || true
    )"
    if [[ "$sync_status" == "Synced" && "$health_status" == "Healthy" ]]; then
      return
    fi
    sleep 5
  done

  kubectl -n argocd get application "$name" -o yaml >&2 || true
  fail "Application/${name} did not reach Synced/Healthy within 10 minutes"
}

if kubectl -n argocd get application root-ssh >/dev/null 2>&1; then
  log "Switching Application/root-ssh to Forgejo"
  kubectl -n argocd patch application root-ssh --type=json -p="$(
    jq -cn --arg url "$repo_url" \
      '[{op:"replace",path:"/spec/source/repoURL",value:$url}]'
  )" >/dev/null
  wait_for_application root-ssh
fi

log "Applying and verifying canonical Application/root"
"$project_root/scripts/argocd-apply-bootstrap.sh" \
  --kubeconfig "$kubeconfig" \
  --root-manifest "$project_root/argocd/bootstrap/root-application.yaml" \
  --timeout "$timeout"
wait_for_application root

unexpected_git_sources="$(
  kubectl -n argocd get applications -o json | jq -r \
    --arg expected "$repo_url" '
      .items[]
      | .metadata.name as $name
      | ([.spec.source.repoURL] + [.spec.sources[]?.repoURL])[]?
      | select(type == "string")
      | select(startswith("ssh://") or endswith("/gitops.git"))
      | select(. != $expected)
      | "\($name): \(.)"
    '
)"
[[ -z "$unexpected_git_sources" ]] || {
  printf '%s\n' "$unexpected_git_sources" >&2
  fail "Some Argo CD Applications still use a non-canonical Git source"
}

log "Removing the verified temporary SSH bootstrap"
kubectl -n argocd delete application root-ssh --ignore-not-found >/dev/null
kubectl -n argocd delete secret test-ssh-gitops-repo --ignore-not-found >/dev/null
docker compose \
  --project-directory "$project_root/test-ssh-git" \
  -f "$project_root/test-ssh-git/docker-compose.yaml" \
  down

log "Cutover completed: Application/root is Synced/Healthy on ${repo_url}"
