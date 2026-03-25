resource "kubernetes_deployment_v1" "echo" {
  metadata {
    name      = "echo"
    namespace = "default"
    labels = {
      app = "echo"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "echo"
      }
    }

    template {
      metadata {
        labels = {
          app = "echo"
        }
      }

      spec {
        container {
          name  = "echo"
          image = "ealen/echo-server:latest"

          port {
            container_port = 80
          }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "echo" {
  metadata {
    name      = "echo"
    namespace = "default"
  }

  spec {
    selector = {
      app = "echo"
    }

    port {
      name        = "http"
      port        = 80
      target_port = 80
    }
  }
}

resource "kubernetes_ingress_v1" "echo" {
  metadata {
    name      = "echo"
    namespace = "default"
    annotations = {
      "cert-manager.io/cluster-issuer" = "homelab-ca"
    }
  }

  spec {
    ingress_class_name = "cilium"

    tls {
      hosts       = ["echo.home.arpa"]
      secret_name = "echo-tls"
    }

    rule {
      host = "echo.home.arpa"

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service_v1.echo.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_manifest.echo_certificate
  ]
}

resource "kubernetes_manifest" "echo_certificate" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "echo-tls"
      namespace = "default"
    }
    spec = {
      secretName = "echo-tls"
      dnsNames   = ["echo.home.arpa"]
      issuerRef = {
        name = "homelab-ca"
        kind = "ClusterIssuer"
      }
    }
  }

  depends_on = [kubernetes_manifest.homelab_ca_clusterissuer]
}
