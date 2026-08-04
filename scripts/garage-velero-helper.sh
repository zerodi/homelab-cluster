#!/usr/bin/env bash

set -euo pipefail

log() {
  printf '[garage-velero-helper] %s\n' "$*"
}

usage() {
  cat <<'EOF'
Usage:
  garage-velero-helper.sh --kubeconfig <path> status
  garage-velero-helper.sh --kubeconfig <path> detect-node-id
  garage-velero-helper.sh --kubeconfig <path> print-bootstrap

Options:
  --kubeconfig <path>  Path to kubeconfig

Environment:
  GARAGE_NAMESPACE   default: garage
  GARAGE_POD         default: garage-0
  GARAGE_ZONE        default: homelab
  GARAGE_CAPACITY    default: 20G
  GARAGE_BUCKET      default: homelab-velero
  GARAGE_KEY_NAME    default: velero
  GARAGE_NODE_ID     optional override for print-bootstrap
EOF
}

KUBECONFIG_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig)
      KUBECONFIG_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ -z "${KUBECONFIG_PATH}" ]]; then
  echo "--kubeconfig is required" >&2
  usage >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "command is required" >&2
  usage >&2
  exit 1
fi

COMMAND="$1"
shift || true

GARAGE_NAMESPACE="${GARAGE_NAMESPACE:-garage}"
GARAGE_POD="${GARAGE_POD:-garage-0}"
GARAGE_ZONE="${GARAGE_ZONE:-homelab}"
GARAGE_CAPACITY="${GARAGE_CAPACITY:-20G}"
GARAGE_BUCKET="${GARAGE_BUCKET:-homelab-velero}"
GARAGE_KEY_NAME="${GARAGE_KEY_NAME:-velero}"
GARAGE_NODE_ID="${GARAGE_NODE_ID:-}"

garage_status() {
  KUBECONFIG="${KUBECONFIG_PATH}" kubectl -n "${GARAGE_NAMESPACE}" exec "${GARAGE_POD}" -- /garage status
}

detect_node_id() {
  local output
  output="$(garage_status)"
  if [[ -n "${GARAGE_NODE_ID}" ]]; then
    printf '%s\n' "${GARAGE_NODE_ID}"
    return 0
  fi

  local node_id=""
  node_id="$(printf '%s\n' "${output}" | awk -v pod="${GARAGE_POD}" '
    /^==== HEALTHY NODES ====$/ {
      in_healthy_nodes = 1
      next
    }

    /^==== / {
      if (in_healthy_nodes) {
        exit
      }
      next
    }

    in_healthy_nodes && $1 == "ID" {
      next
    }

    in_healthy_nodes && $1 ~ /^[0-9A-Fa-f]+$/ && length($1) >= 16 && length($1) <= 64 {
      healthy_node_count++
      only_healthy_node_id = $1

      if ($2 == pod || index($2, pod ".") == 1) {
        matched_pod = 1
        print $1
        exit
      }
    }

    END {
      if (!matched_pod && healthy_node_count == 1) {
        print only_healthy_node_id
      }
    }'
  )"

  if [[ -z "${node_id}" ]]; then
    echo "failed to detect Garage node id automatically" >&2
    echo >&2
    echo "garage status output:" >&2
    printf '%s\n' "${output}" >&2
    return 1
  fi

  printf '%s\n' "${node_id}"
}

print_bootstrap() {
  local node_id
  node_id="$(detect_node_id)"

  printf '%s\n' \
    "Detected Garage node id: ${node_id}" \
    "" \
    "Run the following commands:" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage layout assign -z ${GARAGE_ZONE} -c ${GARAGE_CAPACITY} ${node_id}" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage layout apply --version 1" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage bucket create ${GARAGE_BUCKET}" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage key create ${GARAGE_KEY_NAME}" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage bucket allow --read --write --owner ${GARAGE_BUCKET} --key ${GARAGE_KEY_NAME}" \
    "kubectl -n ${GARAGE_NAMESPACE} exec ${GARAGE_POD} -- /garage key info ${GARAGE_KEY_NAME} --show-secret" \
    "" \
    "Then update OpenBao:" \
    "bao kv put secret/platform/velero/s3 \\" \
    "  access_key_id='REPLACE_WITH_GARAGE_KEY_ID' \\" \
    "  secret_access_key='REPLACE_WITH_GARAGE_SECRET_KEY'"
}

case "${COMMAND}" in
  status)
    garage_status
    ;;
  detect-node-id)
    detect_node_id
    ;;
  print-bootstrap)
    print_bootstrap
    ;;
  *)
    echo "unknown command: ${COMMAND}" >&2
    usage >&2
    exit 1
    ;;
esac
