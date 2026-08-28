resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name = "argocd"
  }

  lifecycle {
    # Namespace labels are managed independently (including the trust-manager
    # selector) and may also be extended by cluster controllers.
    ignore_changes = [metadata[0].labels]
  }
}

resource "helm_release" "argocd" {

  name             = "argocd"
  namespace        = "argocd"
  create_namespace = false

  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = local.chart_versions["argo_cd"]

  timeout = 900
  wait    = true

  values = [yamlencode({
    global = {
      domain = local.effective_argocd_host
      networkPolicy = {
        create = false
      }
    }
    configs = {
      cm = {
        "application.resourceTrackingMethod" = "annotation+label"
        url                                  = "https://${local.effective_argocd_host}"
        "oidc.config" = yamlencode({
          name            = "Authentik"
          issuer          = "https://${local.effective_identity_provider_host}/application/o/argocd/"
          clientID        = "$argocd-oidc:client_id"
          clientSecret    = "$argocd-oidc:client_secret"
          requestedScopes = ["openid", "profile", "email", "groups"]
        })
      }
      rbac = {
        scopes           = "[groups]"
        "policy.default" = "role:authenticated"
        "policy.csv" = join("\n", [
          "p, role:authenticated, projects, get, platform-*, allow",
          "p, role:authenticated, projects, get, apps, allow",
          "p, role:authenticated, projects, get, apps-orchestration, allow",
          "p, role:authenticated, applications, get, platform-*/*, allow",
          "p, role:authenticated, applications, get, apps/*, allow",
          "p, role:authenticated, applications, get, apps-orchestration/*, allow",
          "g, ${local.effective_platform_admin_group}, role:admin",
          "",
        ])
      }
      params = {
        "controller.diff.server.side"       = "true"
        "controller.repo.server.strict.tls" = "true"
        "server.insecure"                   = "true"
        "server.repo.server.strict.tls"     = "true"
      }
    }
    controller = {
      replicas = 1
      resources = {
        requests = {
          cpu    = "100m"
          memory = "700Mi"
        }
        limits = {
          memory = "4Gi"
        }
      }
    }
    dex = {
      enabled = false
      resources = {
        requests = {
          cpu    = "10m"
          memory = "32Mi"
        }
        limits = {
          memory = "128Mi"
        }
      }
    }
    redis = {
      resources = {
        requests = {
          cpu    = "100m"
          memory = "64Mi"
        }
        limits = {
          memory = "1Gi"
        }
      }
    }
    server = {
      replicas = 1
      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          memory = "1Gi"
        }
      }
      ingress = {
        enabled          = true
        ingressClassName = "cilium"
        annotations = {
          "cert-manager.io/cluster-issuer" = "homelab-ca"
        }
        hostname = local.effective_argocd_host
        tls      = true
      }
    }
    repoServer = {
      replicas = 1
      resources = {
        requests = {
          cpu    = "100m"
          memory = "256Mi"
        }
        limits = {
          memory = "2Gi"
        }
      }
      containerSecurityContext = {
        readOnlyRootFilesystem = true
      }
    }
    applicationSet = {
      replicas = 1
      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          memory = "1Gi"
        }
      }
    }
    notifications = {
      enabled = false
    }
    "redis-ha" = {
      enabled = false
    }
  })]

  depends_on = [kubernetes_manifest.argocd_repo_server_tls_certificate]
}

resource "kubernetes_manifest" "argocd_repo_server_tls_certificate" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "argocd-repo-server"
      namespace = "argocd"
    }
    spec = {
      secretName  = "argocd-repo-server-tls"
      duration    = "2160h"
      renewBefore = "360h"
      dnsNames = [
        "argocd-repo-server",
        "argocd-repo-server.argocd",
        "argocd-repo-server.argocd.svc",
        "argocd-repo-server.argocd.svc.cluster.local",
      ]
      privateKey = {
        algorithm = "ECDSA"
        size      = 256
      }
      usages = ["server auth"]
      issuerRef = {
        name = "homelab-ca"
        kind = "ClusterIssuer"
      }
    }
  }

  depends_on = [
    kubernetes_manifest.homelab_ca_clusterissuer,
    kubernetes_namespace_v1.argocd,
  ]
}

resource "terraform_data" "argocd_ready" {
  triggers_replace = [
    helm_release.argocd.id,
    local.effective_kubeconfig_path,
    local.effective_argocd_host,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local.effective_kubeconfig_path
    }

    command = <<-EOT
      set -eu
      for dep in $(kubectl -n argocd get deployment -o name); do
        kubectl -n argocd rollout status --timeout=15m "$dep"
      done

      for sts in $(kubectl -n argocd get statefulset -o name); do
        kubectl -n argocd rollout status --timeout=15m "$sts"
      done
    EOT
  }

  depends_on = [
    helm_release.argocd,
    kubernetes_manifest.argocd_network_policy,
    kubernetes_manifest.argocd_repo_server_tls_certificate,
    kubernetes_manifest.argocd_server_ingress_policy,
    kubernetes_manifest.argocd_server_kube_apiserver_policy,
  ]
}
