resource "helm_release" "argocd" {
  count = local.effective_argocd_enabled && var.crd_backed_resources_enabled ? 1 : 0

  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true

  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = "9.4.2"

  timeout = 900
  wait    = true

  values = [yamlencode({
    global = {
      domain = local.effective_argocd_host
    }
    configs = {
      params = {
        "server.insecure"                                = "true"
        "server.repo.server.plaintext"                   = "true"
        "server.dex.server.plaintext"                    = "true"
        "controller.repo.server.plaintext"               = "true"
        "applicationsetcontroller.repo.server.plaintext" = "true"
        "reposerver.disable.tls"                         = "true"
        "dexserver.disable.tls"                          = "true"
      }
    }
    server = {
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
  })]

  depends_on = [kubernetes_manifest.homelab_ca_clusterissuer]
}

resource "terraform_data" "argocd_ready" {
  count = local.effective_argocd_enabled && var.crd_backed_resources_enabled ? 1 : 0

  triggers_replace = [
    helm_release.argocd[0].id,
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
