resource "helm_release" "trust_manager" {
  name             = "trust-manager"
  namespace        = "cert-manager"
  create_namespace = false

  repository = "https://charts.jetstack.io"
  chart      = "trust-manager"
  version    = local.chart_versions["trust_manager"]

  timeout = 900
  wait    = true

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_labels" "trusted_namespace_cert_manager" {
  api_version = "v1"
  kind        = "Namespace"

  metadata {
    name = "cert-manager"
  }

  labels = {
    "trust.home.arpa/enabled" = "true"
  }

  force = true

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_labels" "trusted_namespace_argocd" {
  api_version = "v1"
  kind        = "Namespace"

  metadata {
    name = "argocd"
  }

  labels = {
    "trust.home.arpa/enabled" = "true"
  }

  force = true

  depends_on = [helm_release.argocd]
}

resource "kubernetes_manifest" "homelab_trust_bundle" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "trust.cert-manager.io/v1alpha1"
    kind       = "Bundle"
    metadata = {
      name = "homelab-root-ca"
    }
    spec = {
      sources = [
        {
          useDefaultCAs = true
        },
        {
          secret = {
            name = "homelab-root-ca"
            key  = "tls.crt"
          }
        },
      ]
      target = {
        configMap = {
          key = "ca-bundle.crt"
        }
        namespaceSelector = {
          matchLabels = {
            "trust.home.arpa/enabled" = "true"
          }
        }
      }
    }
  }

  depends_on = [
    helm_release.trust_manager,
    kubernetes_manifest.homelab_root_ca,
    kubernetes_labels.trusted_namespace_cert_manager,
    kubernetes_labels.trusted_namespace_argocd,
  ]
}
