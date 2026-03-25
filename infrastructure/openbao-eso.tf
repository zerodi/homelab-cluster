resource "helm_release" "openbao" {
  name             = "openbao"
  namespace        = "openbao"
  create_namespace = true

  repository = "https://openbao.github.io/openbao-helm"
  chart      = "openbao"
  version    = "0.19.2"

  timeout = 900
  wait    = true

  values = [yamlencode({
    server = {
      standalone = {
        enabled = true
      }
      dataStorage = {
        enabled      = true
        storageClass = local.piraeus_storage_class_name
        size         = "10Gi"
      }
    }
    injector = {
      enabled = false
    }
    csi = {
      enabled = false
    }
    ui = {
      enabled = true
    }
  })]

  depends_on = [kubernetes_storage_class_v1.piraeus_replicated]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true

  repository = "https://charts.external-secrets.io"
  chart      = "external-secrets"
  version    = "1.3.1"

  timeout = 900
  wait    = true

  values = [yamlencode({
    installCRDs = true
  })]
}

resource "kubernetes_cluster_role_binding_v1" "external_secrets_openbao_auth_delegator" {
  metadata {
    name = "external-secrets-openbao-auth-delegator"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "system:auth-delegator"
  }

  subject {
    kind      = "ServiceAccount"
    name      = "external-secrets"
    namespace = "external-secrets"
  }

  depends_on = [helm_release.external_secrets]
}

resource "terraform_data" "openbao_cluster_secret_store" {
  triggers_replace = [
    var.kubeconfig_path,
    "openbao",
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      cat <<'EOF' | kubectl apply -f -
      apiVersion: external-secrets.io/v1
      kind: ClusterSecretStore
      metadata:
        name: openbao
      spec:
        provider:
          vault:
            server: http://openbao.openbao.svc.cluster.local:8200
            path: secret
            version: v2
            auth:
              kubernetes:
                mountPath: kubernetes
                role: external-secrets
                serviceAccountRef:
                  name: external-secrets
                  namespace: external-secrets
      EOF
    EOT
  }

  depends_on = [
    helm_release.openbao,
    helm_release.external_secrets,
    kubernetes_cluster_role_binding_v1.external_secrets_openbao_auth_delegator,
  ]
}

resource "terraform_data" "authentik_runtime_external_secret" {
  count = var.authentik_enabled ? 1 : 0

  triggers_replace = [
    var.kubeconfig_path,
    "authentik-runtime",
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
        name: authentik-runtime
        namespace: authentik
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: ClusterSecretStore
          name: openbao
        target:
          name: authentik-runtime
          creationPolicy: Owner
        data:
          - secretKey: AUTHENTIK_SECRET_KEY
            remoteRef:
              key: platform/authentik/runtime
              property: secret_key
          - secretKey: AUTHENTIK_POSTGRESQL__PASSWORD
            remoteRef:
              key: platform/authentik/runtime
              property: postgresql_password
          - secretKey: postgresql-password
            remoteRef:
              key: platform/authentik/runtime
              property: postgresql_password
      EOF
    EOT
  }

  depends_on = [
    terraform_data.openbao_cluster_secret_store,
    terraform_data.authentik_namespace,
  ]
}

resource "terraform_data" "authentik_runtime_secret_ready" {
  count = var.authentik_enabled ? 1 : 0

  triggers_replace = [
    "authentik-runtime",
    var.kubeconfig_path,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl -n authentik wait --for=create secret/authentik-runtime --timeout=10m

      for _ in $(seq 1 120); do
        if kubectl -n authentik get secret authentik-runtime -o jsonpath='{.data.AUTHENTIK_SECRET_KEY}' 2>/dev/null | grep -q . \
          && kubectl -n authentik get secret authentik-runtime -o jsonpath='{.data.AUTHENTIK_POSTGRESQL__PASSWORD}' 2>/dev/null | grep -q .; then
          exit 0
        fi
        sleep 5
      done

      echo "authentik-runtime secret exists but does not contain the expected secret keys yet" >&2
      exit 1
    EOT
  }
}

resource "terraform_data" "forgejo_admin_external_secret" {
  count = var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    var.kubeconfig_path,
    "forgejo-admin-secret",
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
        name: forgejo-admin-secret
        namespace: forgejo
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: ClusterSecretStore
          name: openbao
        target:
          name: forgejo-admin-secret
          creationPolicy: Owner
        data:
          - secretKey: username
            remoteRef:
              key: platform/forgejo/admin
              property: username
          - secretKey: password
            remoteRef:
              key: platform/forgejo/admin
              property: password
      EOF
    EOT
  }

  depends_on = [
    terraform_data.openbao_cluster_secret_store,
    terraform_data.forgejo_namespace,
  ]
}

resource "terraform_data" "forgejo_admin_secret_ready" {
  count = var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    "forgejo-admin-secret",
    var.kubeconfig_path,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl -n forgejo wait --for=create secret/forgejo-admin-secret --timeout=10m
    EOT
  }
}
