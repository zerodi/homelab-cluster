resource "helm_release" "openbao" {
  name             = "openbao"
  namespace        = "openbao"
  create_namespace = true

  repository = "https://openbao.github.io/openbao-helm"
  chart      = "openbao"
  version    = local.chart_versions["openbao"]

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

  depends_on = [
    terraform_data.linstor_csi_ready,
    kubernetes_storage_class_v1.piraeus_replicated,
  ]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true

  repository = "https://charts.external-secrets.io"
  chart      = "external-secrets"
  version    = local.chart_versions["external_secrets"]

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

resource "kubernetes_cluster_role_binding_v1" "openbao_kubernetes_auth_delegator" {
  metadata {
    name = "openbao-kubernetes-auth-delegator"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "system:auth-delegator"
  }

  subject {
    kind      = "ServiceAccount"
    name      = "openbao"
    namespace = "openbao"
  }

  depends_on = [helm_release.openbao]
}
