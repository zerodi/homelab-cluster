# shellcheck shell=bash

# Atomic Argo CD readiness helpers. Source lib/common.sh first.

argocd::application_status_is() {
  local app_name="$1"
  local field="$2"
  local expected="$3"
  local actual

  actual="$(kubectl -n argocd get application "$app_name" \
    -o "jsonpath={.status.${field}.status}" 2>/dev/null || true)"
  [[ "$actual" == "$expected" ]]
}

argocd::wait_for_application() {
  local app_name="$1"
  local timeout_seconds="${2:-600}"
  local deadline

  common::log "${SCRIPT_COMPONENT:-argocd}" "Waiting for Application/${app_name} sync"
  deadline=$((SECONDS + timeout_seconds))
  until argocd::application_status_is "$app_name" sync Synced; do
    if ((SECONDS >= deadline)); then
      kubectl -n argocd get application "$app_name" -o yaml >&2 || true
      common::die "${SCRIPT_COMPONENT:-argocd}" \
        "Application/${app_name} did not reach Synced status within ${timeout_seconds}s"
    fi
    sleep 5
  done

  common::log "${SCRIPT_COMPONENT:-argocd}" "Waiting for Application/${app_name} health"
  deadline=$((SECONDS + timeout_seconds))
  until argocd::application_status_is "$app_name" health Healthy; do
    if ((SECONDS >= deadline)); then
      kubectl -n argocd get application "$app_name" -o yaml >&2 || true
      common::die "${SCRIPT_COMPONENT:-argocd}" \
        "Application/${app_name} did not reach Healthy status within ${timeout_seconds}s"
    fi
    sleep 5
  done
}
