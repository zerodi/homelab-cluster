resource "terraform_data" "forgejo_oidc_external_secret" {
  count = var.authentik_enabled && var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    var.kubeconfig_path,
    "forgejo-oidc",
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      cat <<'EOF' | kubectl apply -f -
      apiVersion: external-secrets.io/v1
      kind: ExternalSecret
      metadata:
        name: forgejo-oidc
        namespace: authentik
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: ClusterSecretStore
          name: openbao
        target:
          name: forgejo-oidc
          creationPolicy: Owner
        data:
          - secretKey: client_id
            remoteRef:
              key: platform/forgejo/oidc
              property: client_id
          - secretKey: client_secret
            remoteRef:
              key: platform/forgejo/oidc
              property: client_secret
      EOF
    EOT
  }
}

resource "terraform_data" "forgejo_oidc_secret_ready" {
  count = var.authentik_enabled && var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    "forgejo-oidc",
    var.kubeconfig_path,
    tostring(var.authentik_blueprints_configmap_name),
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG                 = var.kubeconfig_path
      AUTHENTIK_BLUEPRINTS_NAME  = var.authentik_blueprints_configmap_name
      AUTHENTIK_APPLICATION_SLUG = var.authentik_application_slug
      FORGEJO_HOST               = var.forgejo_host
      FORGEJO_SSO_NAME           = var.forgejo_sso_name
    }

    command = <<-EOT
      set -eu

      kubectl -n authentik wait --for=create secret/forgejo-oidc --timeout=10m

      if [ -z "$${AUTHENTIK_BLUEPRINTS_NAME:-}" ]; then
        echo "missing authentik blueprints configmap name" >&2
        exit 1
      fi

      client_id="$(kubectl -n authentik get secret forgejo-oidc -o jsonpath='{.data.client_id}' | base64 -d)"
      client_secret="$(kubectl -n authentik get secret forgejo-oidc -o jsonpath='{.data.client_secret}' | base64 -d)"

      tmpdir="$(mktemp -d)"
      trap 'rm -rf "$tmpdir"' EXIT

      cat >"$tmpdir/forgejo-sso.yaml" <<EOF
      version: 1
      metadata:
        name: forgejo-sso
        labels:
          blueprints.goauthentik.io/instantiate: "true"
          blueprints.goauthentik.io/description: "Forgejo SSO"
      entries:
        - model: authentik_providers_oauth2.oauth2provider
          state: present
          identifiers:
            name: Forgejo
          attrs:
            name: Forgejo
            authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
            invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
            client_type: confidential
            client_id: "$client_id"
            client_secret: "$client_secret"
            access_code_validity: "minutes=10"
            access_token_validity: "minutes=30"
            refresh_token_validity: "days=30"
            redirect_uris:
              - matching_mode: strict
                url: "https://$${FORGEJO_HOST}/user/oauth2/$${FORGEJO_SSO_NAME}/callback"
            property_mappings:
              - !Find [authentik_providers_oauth2.scopemapping, [scope_name, openid]]
              - !Find [authentik_providers_oauth2.scopemapping, [scope_name, email]]
              - !Find [authentik_providers_oauth2.scopemapping, [scope_name, profile]]
              - !Find [authentik_providers_oauth2.scopemapping, [scope_name, offline_access]]
            signing_key: !Find [authentik_crypto.certificatekeypair, [name, authentik Self-signed Certificate]]
        - model: authentik_core.application
          state: present
          identifiers:
            slug: "$${AUTHENTIK_APPLICATION_SLUG}"
          attrs:
            name: Forgejo
            slug: "$${AUTHENTIK_APPLICATION_SLUG}"
            policy_engine_mode: any
            provider: !Find [authentik_providers_oauth2.oauth2provider, [name, Forgejo]]
            meta_launch_url: "https://$${FORGEJO_HOST}/"
            open_in_new_tab: true
      EOF

      kubectl -n authentik create configmap "$AUTHENTIK_BLUEPRINTS_NAME" \
        --dry-run=client \
        -o yaml \
        --from-file=forgejo-sso.yaml="$tmpdir/forgejo-sso.yaml" \
        | kubectl apply -f -
    EOT
  }

  depends_on = [terraform_data.forgejo_oidc_external_secret]
}
