resource "terraform_data" "authentik_namespace" {
  count = var.authentik_enabled ? 1 : 0

  triggers_replace = [
    var.kubeconfig_path,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl create namespace authentik --dry-run=client -o yaml | kubectl apply -f -
    EOT
  }
}

resource "kubernetes_config_map_v1" "authentik_blueprints" {
  count = var.authentik_enabled ? 1 : 0

  metadata {
    name      = "authentik-blueprints"
    namespace = "authentik"
  }

  data = {}

  depends_on = [terraform_data.authentik_namespace]
}

data "kubernetes_secret_v1" "authentik_runtime" {
  count = var.authentik_enabled ? 1 : 0

  metadata {
    name      = "authentik-runtime"
    namespace = "authentik"
  }

  depends_on = [terraform_data.authentik_runtime_secret_ready]
}

resource "helm_release" "authentik" {
  count = var.authentik_enabled ? 1 : 0

  name             = "authentik"
  namespace        = "authentik"
  create_namespace = false

  repository = "https://charts.goauthentik.io"
  chart      = "authentik"
  version    = "2026.2.1"

  timeout       = 1800
  wait          = true
  wait_for_jobs = true

  set_sensitive = [
    {
      name  = "authentik.secret_key"
      value = data.kubernetes_secret_v1.authentik_runtime[0].data["AUTHENTIK_SECRET_KEY"]
    },
    {
      name  = "authentik.postgresql.password"
      value = data.kubernetes_secret_v1.authentik_runtime[0].data["AUTHENTIK_POSTGRESQL__PASSWORD"]
    },
  ]

  values = [yamlencode({
    authentik = {
      host = "https://${var.authentik_host}"
      error_reporting = {
        enabled = false
      }
      outposts = {
        authentik_host         = "https://${var.authentik_host}"
        authentik_host_browser = "https://${var.authentik_host}"
      }
      postgresql = {
        host = "authentik-postgresql"
        name = "authentik"
        user = "authentik"
      }
      redis = {
        host = "authentik-redis-master"
      }
    }
    server = {
      ingress = {
        enabled          = true
        ingressClassName = "cilium"
        annotations = {
          "cert-manager.io/cluster-issuer" = "homelab-ca"
        }
        hosts = [
          var.authentik_host
        ]
        tls = [
          {
            secretName = "authentik-tls"
            hosts      = [var.authentik_host]
          }
        ]
      }
    }
    blueprints = {
      configMaps = [
        kubernetes_config_map_v1.authentik_blueprints[0].metadata[0].name,
      ]
    }
    postgresql = {
      enabled = true
      auth = {
        existingSecret = "authentik-runtime"
        secretKeys = {
          userPasswordKey  = "postgresql-password"
          adminPasswordKey = "postgresql-password"
        }
      }
      primary = {
        persistence = {
          enabled      = true
          storageClass = local.piraeus_storage_class_name
          size         = "10Gi"
        }
      }
    }
    redis = {
      enabled = true
      master = {
        persistence = {
          enabled      = true
          storageClass = local.piraeus_storage_class_name
          size         = "5Gi"
        }
      }
    }
  })]

  depends_on = [
    kubernetes_manifest.homelab_ca_clusterissuer,
    kubernetes_storage_class_v1.piraeus_replicated,
    kubernetes_config_map_v1.authentik_blueprints,
    terraform_data.authentik_runtime_secret_ready,
    terraform_data.authentik_namespace,
  ]
}

resource "terraform_data" "authentik_ready" {
  count = var.authentik_enabled ? 1 : 0

  triggers_replace = [
    helm_release.authentik[0].id,
    var.kubeconfig_path,
    var.authentik_host,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      for pvc in $(kubectl -n authentik get pvc -o name); do
        kubectl -n authentik wait --for=jsonpath='{.status.phase}'=Bound --timeout=15m "$pvc"
      done

      for dep in $(kubectl -n authentik get deployment -o name); do
        kubectl -n authentik rollout status --timeout=15m "$dep"
      done

      for sts in $(kubectl -n authentik get statefulset -o name); do
        kubectl -n authentik rollout status --timeout=15m "$sts"
      done
    EOT
  }

  depends_on = [helm_release.authentik]
}
