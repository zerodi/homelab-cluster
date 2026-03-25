resource "terraform_data" "forgejo_population" {
  count = var.forgejo_enabled ? 1 : 0

  triggers_replace = {
    kubeconfig_path     = var.kubeconfig_path
    forgejo_host        = var.forgejo_host
    forgejo_sso_name    = var.forgejo_sso_name
    authentik_host      = var.authentik_host
    authentik_app_slug  = var.authentik_application_slug
    gitops_owner        = var.gitops_owner
    gitops_repo         = var.gitops_repo
    gitops_repo_private = tostring(var.gitops_repo_private)
    gitops_repo_desc    = var.gitops_repo_description
  }

  provisioner "local-exec" {
    environment = {
      KUBECONFIG                 = var.kubeconfig_path
      FORGEJO_HOST               = var.forgejo_host
      FORGEJO_SSO_NAME           = var.forgejo_sso_name
      AUTHENTIK_HOST             = var.authentik_host
      AUTHENTIK_IN_CLUSTER_URL   = var.authentik_in_cluster_url
      AUTHENTIK_APPLICATION_SLUG = var.authentik_application_slug
      GITOPS_OWNER               = var.gitops_owner
      GITOPS_REPO                = var.gitops_repo
      GITOPS_REPO_DESCRIPTION    = var.gitops_repo_description
      GITOPS_REPO_PRIVATE        = var.gitops_repo_private ? "true" : "false"
    }

    command = <<-EOT
      set -eu

      authentik_port_forward_pid=""
      authentik_port_forward_log=""
      port_forward_pid=""
      port_forward_log=""

      cleanup() {
        if [ -n "$authentik_port_forward_pid" ]; then
          kill "$authentik_port_forward_pid" >/dev/null 2>&1 || true
        fi
        if [ -n "$port_forward_pid" ]; then
          kill "$port_forward_pid" >/dev/null 2>&1 || true
        fi
        if [ -n "$authentik_port_forward_log" ] || [ -n "$port_forward_log" ]; then
          rm -f "$authentik_port_forward_log" "$port_forward_log"
        fi
      }

      trap cleanup EXIT

      for binary in kubectl curl awk grep sed; do
        if ! command -v "$binary" >/dev/null 2>&1; then
          echo "missing required binary: $binary" >&2
          exit 1
        fi
      done

      kubectl -n forgejo wait --for=create secret/forgejo-admin-secret --timeout=10m
      FORGEJO_ADMIN_USERNAME="$(kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.username}' | base64 -d)"
      FORGEJO_ADMIN_PASSWORD="$(kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.password}' | base64 -d)"

      forgejo_pod="$(
        kubectl -n forgejo get pods \
          -l app.kubernetes.io/instance=forgejo,app.kubernetes.io/name=forgejo \
          -o jsonpath='{.items[0].metadata.name}'
      )"

      if [ -z "$forgejo_pod" ]; then
        echo "failed to locate a Forgejo pod" >&2
        exit 1
      fi

      if kubectl -n authentik get secret forgejo-oidc >/dev/null 2>&1; then
        OIDC_CLIENT_ID="$(kubectl -n authentik get secret forgejo-oidc -o jsonpath='{.data.client_id}' | base64 -d)"
        OIDC_CLIENT_SECRET="$(kubectl -n authentik get secret forgejo-oidc -o jsonpath='{.data.client_secret}' | base64 -d)"
        discovery_base="$${AUTHENTIK_IN_CLUSTER_URL:-http://authentik-server.authentik.svc.cluster.local}"
        discovery_url="$${discovery_base}/application/o/$${AUTHENTIK_APPLICATION_SLUG}/.well-known/openid-configuration"
        for workload in deployment/authentik-server deployment/authentik-worker; do
          kubectl -n authentik rollout restart "$workload"
          kubectl -n authentik rollout status --timeout=10m "$workload"
        done
        authentik_service_port="$(
          kubectl -n authentik get svc authentik-server -o jsonpath='{.spec.ports[0].port}'
        )"
        authentik_port_forward_log="$(mktemp)"
        kubectl -n authentik port-forward svc/authentik-server 19000:"$authentik_service_port" >"$authentik_port_forward_log" 2>&1 &
        authentik_port_forward_pid="$!"

        blueprint_ready=""
        for _ in $(seq 1 150); do
          if curl -fsS "http://127.0.0.1:19000/application/o/$${AUTHENTIK_APPLICATION_SLUG}/.well-known/openid-configuration" >/dev/null 2>&1; then
            blueprint_ready="yes"
            break
          fi
          sleep 2
        done

        if [ -z "$blueprint_ready" ]; then
          echo "authentik OIDC discovery endpoint did not become ready for application '$${AUTHENTIK_APPLICATION_SLUG}'" >&2
          exit 1
        fi

        auth_id="$(
          kubectl -n forgejo exec "$forgejo_pod" -- forgejo admin auth list --vertical-bars 2>/dev/null \
            | awk -F'|' -v name="$FORGEJO_SSO_NAME" '
                $0 ~ /^\|/ {
                  gsub(/^[ \t]+|[ \t]+$/, "", $2)
                  gsub(/^[ \t]+|[ \t]+$/, "", $3)
                  if ($2 == name) {
                    gsub(/^[ \t]+|[ \t]+$/, "", $1)
                    print $1
                  }
                }
              ' \
            | head -n1
        )"

        if [ -n "$auth_id" ]; then
          kubectl -n forgejo exec "$forgejo_pod" -- forgejo admin auth update-oauth \
            --id "$auth_id" \
            --name "$FORGEJO_SSO_NAME" \
            --provider openidConnect \
            --key "$OIDC_CLIENT_ID" \
            --secret "$OIDC_CLIENT_SECRET" \
            --auto-discover-url "$discovery_url" \
            --skip-local-2fa \
            --scopes openid \
            --scopes email \
            --scopes profile
        else
          kubectl -n forgejo exec "$forgejo_pod" -- forgejo admin auth add-oauth \
            --name "$FORGEJO_SSO_NAME" \
            --provider openidConnect \
            --key "$OIDC_CLIENT_ID" \
            --secret "$OIDC_CLIENT_SECRET" \
            --auto-discover-url "$discovery_url" \
            --skip-local-2fa \
            --scopes openid \
            --scopes email \
            --scopes profile
        fi
      fi

      port_forward_log="$(mktemp)"
      kubectl -n forgejo port-forward svc/forgejo-http 13000:3000 >"$port_forward_log" 2>&1 &
      port_forward_pid="$!"

      for _ in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:13000/api/v1/version >/dev/null 2>&1; then
          break
        fi
        sleep 2
      done

      api_call() {
        method="$1"
        path="$2"
        body="$${3:-}"
        response_file="$(mktemp)"

        if [ -n "$body" ]; then
          status="$(
            curl -sS -o "$response_file" -w "%%{http_code}" \
              -u "$${FORGEJO_ADMIN_USERNAME}:$${FORGEJO_ADMIN_PASSWORD}" \
              -H "Content-Type: application/json" \
              -X "$method" \
              --data "$body" \
              "http://127.0.0.1:13000$path"
          )"
        else
          status="$(
            curl -sS -o "$response_file" -w "%%{http_code}" \
              -u "$${FORGEJO_ADMIN_USERNAME}:$${FORGEJO_ADMIN_PASSWORD}" \
              -X "$method" \
              "http://127.0.0.1:13000$path"
          )"
        fi

        cat "$response_file"
        rm -f "$response_file"
        printf '\nHTTP_STATUS=%s\n' "$status"
      }

      json_escape() {
        printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
      }

      org_response="$(api_call GET "/api/v1/orgs/$${GITOPS_OWNER}")"
      org_status="$(printf '%s\n' "$org_response" | sed -n 's/^HTTP_STATUS=//p')"

      if [ "$org_status" = "404" ]; then
        create_org_body=$(cat <<EOF
      {"username":"$(json_escape "$${GITOPS_OWNER}")","visibility":"private","repo_admin_change_team_access":true}
      EOF
        )
        create_org_response="$(api_call POST "/api/v1/admin/users/$${FORGEJO_ADMIN_USERNAME}/orgs" "$create_org_body")"
        create_org_status="$(printf '%s\n' "$create_org_response" | sed -n 's/^HTTP_STATUS=//p')"
        if [ "$create_org_status" != "201" ]; then
          printf '%s\n' "$create_org_response" >&2
          exit 1
        fi
      elif [ "$org_status" != "200" ]; then
        printf '%s\n' "$org_response" >&2
        exit 1
      fi

      repo_response="$(api_call GET "/api/v1/repos/$${GITOPS_OWNER}/$${GITOPS_REPO}")"
      repo_status="$(printf '%s\n' "$repo_response" | sed -n 's/^HTTP_STATUS=//p')"

      if [ "$repo_status" = "404" ]; then
        create_repo_body=$(cat <<EOF
      {"name":"$(json_escape "$${GITOPS_REPO}")","description":"$(json_escape "$${GITOPS_REPO_DESCRIPTION}")","private":$${GITOPS_REPO_PRIVATE},"auto_init":true,"default_branch":"main"}
      EOF
        )
        create_repo_response="$(api_call POST "/api/v1/orgs/$${GITOPS_OWNER}/repos" "$create_repo_body")"
        create_repo_status="$(printf '%s\n' "$create_repo_response" | sed -n 's/^HTTP_STATUS=//p')"
        if [ "$create_repo_status" != "201" ]; then
          printf '%s\n' "$create_repo_response" >&2
          exit 1
        fi
      elif [ "$repo_status" != "200" ]; then
        printf '%s\n' "$repo_response" >&2
        exit 1
      fi
    EOT
  }

  depends_on = [
    terraform_data.argocd_repo_creds_external_secret,
    terraform_data.argocd_repository_external_secret,
    terraform_data.project_platform,
    terraform_data.forgejo_oidc_secret_ready,
  ]
}
