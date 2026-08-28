locals {
  kube_system_namespace_selector = {
    matchLabels = {
      "kubernetes.io/metadata.name" = "kube-system"
    }
  }
  argocd_dns_egress = {
    to = [{
      namespaceSelector = local.kube_system_namespace_selector
      podSelector = {
        matchLabels = {
          "k8s-app" = "kube-dns"
        }
      }
    }]
    ports = [
      { port = 53, protocol = "UDP" },
      { port = 53, protocol = "TCP" },
    ]
  }
  argocd_network_policies = {
    application-controller = {
      pod_name = "argocd-application-controller"
      ingress = [{
        from  = [{ namespaceSelector = {} }]
        ports = [{ port = 8082, protocol = "TCP" }]
      }]
      egress       = null
      policy_types = ["Ingress"]
    }
    applicationset-controller = {
      pod_name = "argocd-applicationset-controller"
      ingress = [{
        from  = [{ namespaceSelector = {} }]
        ports = [{ port = 8085, protocol = "TCP" }]
      }]
      egress       = null
      policy_types = ["Ingress"]
    }
    redis = {
      pod_name = "argocd-redis"
      ingress = [{
        from = [
          { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-server" } } },
          { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-repo-server" } } },
          { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-application-controller" } } },
        ]
        ports = [{ port = 6379, protocol = "TCP" }]
      }]
      egress       = null
      policy_types = ["Ingress"]
    }
    repo-server = {
      pod_name = "argocd-repo-server"
      ingress = [
        {
          from = [
            { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-server" } } },
            { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-application-controller" } } },
            { podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-applicationset-controller" } } },
          ]
          ports = [{ port = 8081, protocol = "TCP" }]
        },
        {
          from  = [{ namespaceSelector = {} }]
          ports = [{ port = 8084, protocol = "TCP" }]
        },
      ]
      egress = [
        local.argocd_dns_egress,
        {
          to    = [{ podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-redis" } } }]
          ports = [{ port = 6379, protocol = "TCP" }]
        },
        {
          to = [{ ipBlock = { cidr = "0.0.0.0/0" } }]
          ports = [
            { port = 22, protocol = "TCP" },
            { port = 443, protocol = "TCP" },
          ]
        },
      ]
      policy_types = ["Ingress", "Egress"]
    }
    server = {
      pod_name = "argocd-server"
      ingress = [
        {
          from  = [{ ipBlock = { cidr = "0.0.0.0/0" } }]
          ports = [{ port = 8080, protocol = "TCP" }]
        },
        {
          from  = [{ namespaceSelector = {} }]
          ports = [{ port = 8083, protocol = "TCP" }]
        },
      ]
      egress = [
        local.argocd_dns_egress,
        {
          to    = [{ podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-repo-server" } } }]
          ports = [{ port = 8081, protocol = "TCP" }]
        },
        {
          to    = [{ podSelector = { matchLabels = { "app.kubernetes.io/name" = "argocd-redis" } } }]
          ports = [{ port = 6379, protocol = "TCP" }]
        },
        {
          to    = [{ ipBlock = { cidr = "0.0.0.0/0" } }]
          ports = [{ port = 443, protocol = "TCP" }]
        },
      ]
      policy_types = ["Ingress", "Egress"]
    }
  }
}

resource "kubernetes_manifest" "argocd_network_policy" {
  for_each = local.argocd_network_policies

  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = {
      name      = "argocd-${each.key}-restricted"
      namespace = "argocd"
    }
    spec = merge(
      {
        podSelector = {
          matchLabels = {
            "app.kubernetes.io/instance" = "argocd"
            "app.kubernetes.io/name"     = each.value.pod_name
          }
        }
        policyTypes = each.value.policy_types
        ingress     = each.value.ingress
      },
      try(each.value.egress, null) == null ? {} : { egress = each.value.egress },
    )
  }

  depends_on = [helm_release.argocd]
}

resource "kubernetes_manifest" "argocd_server_kube_apiserver_policy" {
  manifest = {
    apiVersion = "cilium.io/v2"
    kind       = "CiliumNetworkPolicy"
    metadata = {
      name      = "argocd-server-kube-apiserver"
      namespace = "argocd"
    }
    spec = {
      endpointSelector = {
        matchLabels = {
          "app.kubernetes.io/instance" = "argocd"
          "app.kubernetes.io/name"     = "argocd-server"
        }
      }
      egress = [{
        toEntities = ["kube-apiserver"]
        toPorts = [{
          ports = [
            { port = "443", protocol = "TCP" },
            { port = "6443", protocol = "TCP" },
          ]
        }]
      }]
    }
  }

  depends_on = [helm_release.argocd]
}

resource "kubernetes_manifest" "argocd_server_ingress_policy" {
  manifest = {
    apiVersion = "cilium.io/v2"
    kind       = "CiliumNetworkPolicy"
    metadata = {
      name      = "argocd-server-ingress"
      namespace = "argocd"
    }
    spec = {
      endpointSelector = {
        matchLabels = {
          "app.kubernetes.io/instance" = "argocd"
          "app.kubernetes.io/name"     = "argocd-server"
        }
      }
      ingress = [{
        fromEntities = ["ingress"]
        toPorts = [{
          ports = [{ port = "8080", protocol = "TCP" }]
        }]
      }]
    }
  }

  depends_on = [helm_release.argocd]
}
