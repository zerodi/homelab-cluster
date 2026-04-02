# see https://artifacthub.io/packages/helm/cert-manager/cert-manager
# see https://github.com/cert-manager/cert-manager/tree/master/deploy/charts/cert-manager
# see https://cert-manager.io/docs/installation/supported-releases/
# see https://cert-manager.io/docs/configuration/selfsigned/#bootstrapping-ca-issuers
# see https://cert-manager.io/docs/usage/ingress/
# see https://registry.terraform.io/providers/hashicorp/helm/latest/docs/data-sources/template
resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true
  # renovate: datasource=helm depName=cert-manager registryUrl=https://charts.jetstack.io
  version = "v1.20.0"

  timeout = 900
  wait    = true

  values = [yamlencode({
    crds = {
      enabled = true
    }
    extraArgs = [
      "--enable-gateway-api",
    ]
    resources = {
      limits = {
        cpu    = "100m"
        memory = "128Mi"
      }
      requests = {
        cpu    = "10m"
        memory = "64Mi"
      }
    }
    webhook = {
      resources = {
        limits = {
          cpu    = "100m"
          memory = "64Mi"
        }
        requests = {
          cpu    = "10m"
          memory = "32Mi"
        }
      }
    }
    cainjector = {
      resources = {
        limits = {
          cpu    = "100m"
          memory = "128Mi"
        }
        requests = {
          cpu    = "10m"
          memory = "64Mi"
        }
      }
    }
  })]
}

resource "kubernetes_manifest" "homelab_root_ca" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "homelab-root-ca"
      namespace = "cert-manager"
    }
    spec = {
      secretName = "homelab-root-ca"
      isCA       = true
      commonName = "homelab-root-ca"
      subject = {
        organizations = ["homelab"]
      }
      privateKey = {
        algorithm = "ECDSA"
        size      = 256
      }
      issuerRef = {
        name = "selfsigned-bootstrap"
        kind = "ClusterIssuer"
      }
    }
  }

  depends_on = [
    helm_release.cert_manager,
    kubernetes_manifest.selfsigned_clusterissuer,
  ]
}

resource "kubernetes_manifest" "homelab_ca_clusterissuer" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata = {
      name = "homelab-ca"
    }
    spec = {
      ca = {
        secretName = "homelab-root-ca"
      }
    }
  }

  depends_on = [kubernetes_manifest.homelab_root_ca]
}

# see https://cert-manager.io/docs/reference/api-docs/#cert-manager.io/v1.ClusterIssuer
resource "kubernetes_manifest" "selfsigned_clusterissuer" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata = {
      name = "selfsigned-bootstrap"
    }
    spec = {
      selfSigned = {}
    }
  }

  depends_on = [helm_release.cert_manager]
}
