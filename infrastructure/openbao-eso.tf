resource "kubernetes_manifest" "openbao_namespace" {
  manifest = {
    apiVersion = "v1"
    kind       = "Namespace"
    metadata = {
      name = "openbao"
    }
  }
}

resource "kubernetes_manifest" "external_secrets_namespace" {
  manifest = {
    apiVersion = "v1"
    kind       = "Namespace"
    metadata = {
      name = "external-secrets"
    }
  }
}

resource "kubernetes_manifest" "openbao_tls_certificate" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "openbao-tls"
      namespace = "openbao"
    }
    spec = {
      secretName = "openbao-tls"
      commonName = "openbao.openbao.svc.cluster.local"
      dnsNames = [
        "openbao",
        "openbao.openbao",
        "openbao.openbao.svc",
        "openbao.openbao.svc.cluster.local",
        "localhost",
      ]
      ipAddresses = ["127.0.0.1"]
      privateKey = {
        algorithm = "ECDSA"
        size      = 256
      }
      issuerRef = {
        name = "homelab-ca"
        kind = "ClusterIssuer"
      }
    }
  }

  depends_on = [
    kubernetes_manifest.homelab_ca_clusterissuer,
    kubernetes_manifest.openbao_namespace,
  ]
}

resource "helm_release" "openbao" {
  name             = "openbao"
  namespace        = "openbao"
  create_namespace = false

  repository = "https://openbao.github.io/openbao-helm"
  chart      = "openbao"
  version    = local.chart_versions["openbao"]

  timeout = 900
  wait    = true

  values = [yamlencode({
    global = {
      tlsDisable = false
    }
    server = {
      standalone = {
        enabled = true
        config  = <<-EOT
          ui = true

          listener "tcp" {
            address         = "[::]:8200"
            cluster_address = "[::]:8201"
            tls_cert_file   = "/openbao/tls/tls.crt"
            tls_key_file    = "/openbao/tls/tls.key"
          }

          storage "file" {
            path = "/openbao/data"
          }
        EOT
      }
      dataStorage = {
        enabled      = true
        storageClass = local.piraeus_storage_class_name
        size         = "10Gi"
      }
      extraEnvironmentVars = {
        BAO_CACERT = "/openbao/tls/ca.crt"
      }
      volumes = [{
        name = "openbao-tls"
        secret = {
          secretName  = "openbao-tls"
          defaultMode = 288
        }
      }]
      volumeMounts = [{
        name      = "openbao-tls"
        mountPath = "/openbao/tls"
        readOnly  = true
      }]
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
    kubernetes_manifest.openbao_tls_certificate,
    kubernetes_manifest.openbao_namespace,
  ]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = false

  repository = "https://charts.external-secrets.io"
  chart      = "external-secrets"
  version    = local.chart_versions["external_secrets"]

  timeout = 900
  wait    = true

  values = [yamlencode({
    installCRDs = true
  })]

  depends_on = [kubernetes_manifest.external_secrets_namespace]
}

resource "kubernetes_manifest" "openbao_ingress_policy" {
  manifest = {
    apiVersion = "cilium.io/v2"
    kind       = "CiliumNetworkPolicy"
    metadata = {
      name      = "openbao-restricted-ingress"
      namespace = "openbao"
    }
    spec = {
      endpointSelector = {
        matchLabels = {
          "app.kubernetes.io/instance" = "openbao"
          "app.kubernetes.io/name"     = "openbao"
          component                    = "server"
        }
      }
      ingress = [
        {
          fromEndpoints = [{
            matchLabels = {
              "k8s:io.kubernetes.pod.namespace" = "external-secrets"
              "k8s:app.kubernetes.io/instance"  = "external-secrets"
              "k8s:app.kubernetes.io/name"      = "external-secrets"
            }
          }]
          toPorts = [{
            ports = [{ port = "8200", protocol = "TCP" }]
          }]
        },
        {
          fromEntities = ["host", "remote-node"]
          toPorts = [{
            ports = [{ port = "8200", protocol = "TCP" }]
          }]
        },
      ]
    }
  }

  depends_on = [helm_release.openbao]
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
