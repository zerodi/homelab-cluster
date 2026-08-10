#!/usr/bin/env bash
# Bootstrap role: no-deploy (local connectivity helper only).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_COMPONENT="openbao-port-forward"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  openbao-port-forward.sh start --kubeconfig <path>
  openbao-port-forward.sh stop
  openbao-port-forward.sh status

Environment overrides:
  OPENBAO_LOCAL_ADDRESS     default: 127.0.0.1
  OPENBAO_LOCAL_PORT        default: 8200
  OPENBAO_REMOTE_PORT       default: 8200
  OPENBAO_NAMESPACE         default: openbao
  OPENBAO_SERVICE           default: openbao
  OPENBAO_PORT_FORWARD_PID  default: out/openbao-port-forward.pid
  OPENBAO_PORT_FORWARD_LOG  default: out/openbao-port-forward.log
EOF
}

action="${1:-}"
if [[ -z "$action" ]]; then
  usage >&2
  exit 1
fi
shift

kubeconfig=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      kubeconfig="$2"
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

local_address="${OPENBAO_LOCAL_ADDRESS:-127.0.0.1}"
local_port="${OPENBAO_LOCAL_PORT:-8200}"
remote_port="${OPENBAO_REMOTE_PORT:-8200}"
namespace="${OPENBAO_NAMESPACE:-openbao}"
service="${OPENBAO_SERVICE:-openbao}"
pid_file="$(common::resolve_from_root "${OPENBAO_PORT_FORWARD_PID:-out/openbao-port-forward.pid}")"
log_file="$(common::resolve_from_root "${OPENBAO_PORT_FORWARD_LOG:-out/openbao-port-forward.log}")"

read_pid() {
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid
  pid="$(tr -d '[:space:]' <"$pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    echo "Invalid OpenBao port-forward PID file: $pid_file" >&2
    return 2
  fi
  printf '%s\n' "$pid"
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

is_expected_process() {
  local pid="$1"
  local command
  command="$(process_command "$pid")"
  [[ "$command" == *kubectl* ]] &&
    [[ "$command" == *port-forward* ]] &&
    [[ "$command" == *"svc/$service"* ]] &&
    [[ "$command" == *"$local_port:$remote_port"* ]]
}

clean_stale_pid_file() {
  local pid
  if ! pid="$(read_pid 2>/dev/null)"; then
    if [[ -f "$pid_file" ]]; then
      rm -f "$pid_file"
    fi
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
  fi
}

start_port_forward() {
  local pid existing_pid

  if [[ -z "$kubeconfig" ]]; then
    echo "--kubeconfig is required for start." >&2
    exit 1
  fi
  common::require_commands kubectl ps
  kubeconfig="$(common::resolve_from_root "$kubeconfig")"
  common::require_file "Kubeconfig" "$kubeconfig"

  mkdir -p "$(dirname "$pid_file")" "$(dirname "$log_file")"
  clean_stale_pid_file

  if existing_pid="$(read_pid 2>/dev/null)" &&
    kill -0 "$existing_pid" 2>/dev/null; then
    if is_expected_process "$existing_pid"; then
      printf 'OpenBao port-forward is already running: pid=%s addr=http://%s:%s\n' \
        "$existing_pid" "$local_address" "$local_port"
      return
    fi
    echo "PID file points to an unrelated live process; refusing to replace it: $pid_file" >&2
    exit 1
  fi

  : >"$log_file"
  KUBECONFIG="$kubeconfig" nohup kubectl \
    --namespace "$namespace" \
    port-forward \
    --address "$local_address" \
    "svc/$service" \
    "$local_port:$remote_port" \
    >"$log_file" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" >"$pid_file"

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "OpenBao port-forward failed to start:" >&2
      sed -n '1,80p' "$log_file" >&2
      rm -f "$pid_file"
      exit 1
    fi
    if grep -q "Forwarding from" "$log_file"; then
      printf 'OpenBao port-forward started: pid=%s addr=http://%s:%s\n' \
        "$pid" "$local_address" "$local_port"
      return
    fi
    sleep 0.5
  done

  echo "OpenBao port-forward did not become ready; see $log_file" >&2
  kill "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  exit 1
}

stop_port_forward() {
  local pid
  if ! pid="$(read_pid 2>/dev/null)"; then
    clean_stale_pid_file
    echo "OpenBao port-forward is not running."
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "Removed stale OpenBao port-forward PID file."
    return
  fi

  if ! is_expected_process "$pid"; then
    echo "PID $pid is not the expected OpenBao port-forward; refusing to stop it." >&2
    exit 1
  fi

  kill "$pid"
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "OpenBao port-forward stopped."
      return
    fi
    sleep 0.25
  done

  echo "OpenBao port-forward did not stop within 5 seconds: pid=$pid" >&2
  exit 1
}

show_status() {
  local pid
  if ! pid="$(read_pid 2>/dev/null)"; then
    clean_stale_pid_file
    echo "OpenBao port-forward is not running."
    return 1
  fi

  if kill -0 "$pid" 2>/dev/null && is_expected_process "$pid"; then
    printf 'OpenBao port-forward is running: pid=%s addr=http://%s:%s log=%s\n' \
      "$pid" "$local_address" "$local_port" "$log_file"
    return
  fi

  clean_stale_pid_file
  echo "OpenBao port-forward is not running."
  return 1
}

case "$action" in
  start)
    start_port_forward
    ;;
  stop)
    stop_port_forward
    ;;
  status)
    show_status
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown action: $action" >&2
    usage >&2
    exit 1
    ;;
esac
