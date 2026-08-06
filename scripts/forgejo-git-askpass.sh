#!/usr/bin/env bash

set -euo pipefail

case "${1:-}" in
  *Username*)
    printf '%s\n' "${FORGEJO_GIT_USERNAME:?FORGEJO_GIT_USERNAME is required}"
    ;;
  *Password*)
    printf '%s\n' "${FORGEJO_GIT_PASSWORD:?FORGEJO_GIT_PASSWORD is required}"
    ;;
  *)
    exit 1
    ;;
esac
