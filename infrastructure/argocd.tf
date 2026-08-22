resource "helm_release" "argocd" {

  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true

  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = local.chart_versions["argo_cd"]

  timeout = 900
  wait    = true

  values = [yamlencode({
    global = {
      domain = local.effective_argocd_host
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
          "p, role:authenticated, projects, get, platform, allow",
          "p, role:authenticated, projects, get, apps, allow",
          "p, role:authenticated, applications, get, platform/*, allow",
          "p, role:authenticated, applications, get, apps/*, allow",
          "g, ${local.effective_platform_admin_group}, role:admin",
          "",
        ])
      }
      params = {
        "controller.diff.server.side" = "true"
        "server.insecure"             = "true"
      }
    }
    controller = {
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
  })]

  depends_on = [kubernetes_manifest.homelab_ca_clusterissuer]
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

  depends_on = [helm_release.argocd]
}
