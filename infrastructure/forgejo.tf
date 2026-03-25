resource "terraform_data" "forgejo_namespace" {
  count = var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    var.kubeconfig_path,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl create namespace forgejo --dry-run=client -o yaml | kubectl apply -f -
    EOT
  }
}

resource "helm_release" "forgejo" {
  count = var.forgejo_enabled ? 1 : 0

  name             = "forgejo"
  namespace        = "forgejo"
  create_namespace = true

  repository = "oci://code.forgejo.org/forgejo-helm"
  chart      = "forgejo"
  # Verified against the official forgejo-helm releases page:
  # https://code.forgejo.org/forgejo-helm/forgejo-helm/releases
  version = "16.2.1"

  timeout = 900
  wait    = true

  values = [yamlencode({
    valkey-cluster = {
      enabled = false
    }
    valkey = {
      enabled = false
    }
    postgresql = {
      enabled = false
    }
    postgresql-ha = {
      enabled = false
    }
    persistence = {
      enabled      = true
      storageClass = local.piraeus_storage_class_name
      size         = "10Gi"
    }
    gitea = {
      admin = {
        existingSecret = "forgejo-admin-secret"
        email          = var.forgejo_admin_email
      }
      config = {
        database = {
          DB_TYPE = "sqlite3"
        }
        session = {
          PROVIDER = "memory"
        }
        cache = {
          ADAPTER = "memory"
        }
        queue = {
          TYPE = "level"
        }
        server = {
          ROOT_URL = "https://${var.forgejo_host}/"
        }
      }
    }
    service = {
      http = {
        type = "ClusterIP"
        port = 3000
      }
      ssh = {
        type = "ClusterIP"
        port = 22
      }
    }
    ingress = {
      enabled          = true
      ingressClassName = "cilium"
      annotations = {
        "cert-manager.io/cluster-issuer" = "homelab-ca"
      }
      hosts = [
        {
          host = var.forgejo_host
          paths = [
            {
              path     = "/"
              pathType = "Prefix"
            }
          ]
        }
      ]
      tls = [
        {
          secretName = "forgejo-tls"
          hosts      = [var.forgejo_host]
        }
      ]
    }
  })]

  depends_on = [
    kubernetes_manifest.homelab_ca_clusterissuer,
    kubernetes_storage_class_v1.piraeus_replicated,
    terraform_data.forgejo_namespace,
    terraform_data.forgejo_admin_secret_ready,
  ]
}

resource "terraform_data" "forgejo_ready" {
  count = var.forgejo_enabled ? 1 : 0

  triggers_replace = [
    helm_release.forgejo[0].id,
    var.kubeconfig_path,
    var.forgejo_host,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      for pvc in $(kubectl -n forgejo get pvc -o name); do
        kubectl -n forgejo wait --for=jsonpath='{.status.phase}'=Bound --timeout=15m "$pvc"
      done

      for dep in $(kubectl -n forgejo get deployment -o name); do
        kubectl -n forgejo rollout status --timeout=15m "$dep"
      done

      for sts in $(kubectl -n forgejo get statefulset -o name); do
        kubectl -n forgejo rollout status --timeout=15m "$sts"
      done
    EOT
  }

  depends_on = [helm_release.forgejo]
}
