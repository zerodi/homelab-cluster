#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '[test-ssh-git-bootstrap] %s\n' "$*"
}

usage() {
  cat <<'EOF'
Usage:
  test-ssh-git-bootstrap.sh \
    --kubeconfig <path> \
    --hostname <cluster-reachable-hostname-or-ip> \
    [--port <host-port>] \
    [--timeout <duration>]
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

kubeconfig=""
hostname="${TEST_SSH_GIT_HOSTNAME:-}"
port="${TEST_SSH_GIT_PORT:-2222}"
timeout="10m"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    --hostname)
      hostname="$2"
      shift 2
      ;;
    --port)
      port="$2"
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

if [[ -z "$kubeconfig" || -z "$hostname" ]]; then
  echo "--kubeconfig and --hostname are required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$kubeconfig" ]]; then
  echo "Kubeconfig not found: $kubeconfig" >&2
  exit 1
fi

case "$hostname" in
  localhost|localhost.*|127.*|::1|git.localtest.me)
    echo "test-ssh-git hostname must be reachable from Argo CD pods; loopback is not allowed: $hostname" >&2
    exit 1
    ;;
esac

if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo "Invalid test-ssh-git port: $port" >&2
  exit 1
fi

for command in docker git kubectl rg ssh ssh-keygen; do
  require_cmd "$command"
done

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required (docker compose)." >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
test_git_dir="$repo_root/test-ssh-git"
client_key="$test_git_dir/keys/argocd_test_client_ed25519"
known_hosts="$test_git_dir/keys/known_hosts"
repo_url="ssh://git@${hostname}:${port}/home/git/repos/gitops.git"

export TEST_SSH_GIT_HOSTNAME="$hostname"
export TEST_SSH_GIT_PORT="$port"
export SERVER_PORT="$port"

log "Generating keys, manifests, and the seeded GitOps repository"
"$test_git_dir/setup.sh"

log "Building and starting the test SSH Git server"
docker compose \
  --project-directory "$test_git_dir" \
  -f "$test_git_dir/docker-compose.yaml" \
  up -d --build

printf -v ssh_command \
  'ssh -i %q -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%q' \
  "$client_key" "$known_hosts"

log "Waiting for the seeded repository to become reachable"
deadline=$((SECONDS + 120))
until GIT_SSH_COMMAND="$ssh_command" git ls-remote "$repo_url" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Test SSH Git repository did not become reachable within 2 minutes: $repo_url" >&2
    docker compose \
      --project-directory "$test_git_dir" \
      -f "$test_git_dir/docker-compose.yaml" \
      logs >&2 || true
    exit 1
  fi
  sleep 2
done

log "Applying the repository credentials and root-ssh Application"
cd "$repo_root"
"$script_dir/argocd-apply-bootstrap.sh" \
  --kubeconfig "$kubeconfig" \
  --test-ssh-git \
  --timeout "$timeout"

log "Initial Argo CD deployment from test-ssh-git completed"
