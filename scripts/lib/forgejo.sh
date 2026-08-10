# shellcheck shell=bash

# Shared Forgejo Git publishing helpers. Sourcing scripts must load common.sh.

forgejo::require_clean_subtree() {
  local project_root="$1"
  local subtree="$2"

  if ! git -C "$project_root" diff --quiet -- "$subtree" ||
    ! git -C "$project_root" diff --cached --quiet -- "$subtree" ||
    [[ -n "$(git -C "$project_root" ls-files --others --exclude-standard -- "$subtree")" ]]; then
    common::die "${SCRIPT_COMPONENT:-forgejo}" \
      "${subtree}/ has uncommitted changes; commit them before publishing"
  fi
}

forgejo::push_subtree() {
  local project_root="$1"
  local subtree="$2"
  local repo_url="$3"
  local revision="$4"
  local trust_file="$5"
  local forgejo_host="$6"
  local forgejo_ip="$7"
  local username="$8"
  local password="$9"
  local subtree_commit

  subtree_commit="$(git -C "$project_root" subtree split --prefix="$subtree" HEAD)"
  [[ -n "$subtree_commit" ]] || common::die "${SCRIPT_COMPONENT:-forgejo}" \
    "Failed to create the ${subtree} subtree commit"

  env \
    -u SSH_ASKPASS \
    -u VSCODE_GIT_ASKPASS_MAIN \
    -u VSCODE_GIT_ASKPASS_NODE \
    -u VSCODE_GIT_ASKPASS_EXTRA_ARGS \
    -u VSCODE_GIT_IPC_HANDLE \
    GIT_ASKPASS="$project_root/scripts/forgejo-git-askpass.sh" \
    GIT_TERMINAL_PROMPT=0 \
    FORGEJO_GIT_USERNAME="$username" \
    FORGEJO_GIT_PASSWORD="$password" \
    git -C "$project_root" \
      -c credential.helper= \
      -c "http.sslCAInfo=${trust_file}" \
      -c "http.curloptResolve=${forgejo_host}:443:${forgejo_ip}" \
      push "$repo_url" "${subtree_commit}:refs/heads/${revision}"
}
