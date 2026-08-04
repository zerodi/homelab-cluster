locals {
  bootstrap_node_name = sort(keys(local.controlplane_nodes))[0]
  bootstrap_node_ip   = local.controlplane_nodes[local.bootstrap_node_name].ip

  kubernetes_endpoint = coalesce(var.cluster_endpoint, "https://${local.controlplane_vip}:6443")

  common_cluster_patch = {
    # disable kubernetes discovery as its no longer compatible with k8s 1.32+.
    # NB we actually disable the discovery altogether, at the other discovery
    #    mechanism, service discovery, requires the public discovery service
    #    from https://discovery.talos.dev/ (or a custom and paid one running
    #    locally in your network).
    # NB without this, talosctl get members, always returns an empty set.
    # see https://docs.siderolabs.com/talos/v1.12/configure-your-talos-cluster/system-configuration/discovery
    # see https://docs.siderolabs.com/talos/v1.12/reference/configuration/v1alpha1/config#discovery
    # see https://github.com/siderolabs/talos/issues/9980
    # see https://github.com/siderolabs/talos/commit/c12b52491456d1e52204eb290d0686a317358c7c    
    discovery = {
      enabled = false
      registries = {
        kubernetes = {
          disabled = true
        }
        service = {
          disabled = true
        }
      }
    }

    network = {
      cni = {
        name = "none"
      }
    }
    proxy = {
      disabled = true
    }
  }

  drbd_patch = {
    modules = [
      // piraeus dependencies.
      {
        name = "drbd"
        parameters = [
          "usermode_helper=disabled",
        ]
      },
      {
        name = "drbd_transport_tcp"
      },
      {
        name = "zfs"
      },
    ]
  }

  # see https://docs.cilium.io/en/stable/network/lb-ipam/
  cilium_lb_pool_manifest = yamlencode({
    apiVersion = "cilium.io/v2"
    kind       = "CiliumLoadBalancerIPPool"
    metadata = {
      name = "external"
    }
    spec = {
      blocks = [
        {
          start = local.cilium_lb_pool_start
          stop  = local.cilium_lb_pool_stop
        }
      ]
    }
  })
  # see https://docs.cilium.io/en/stable/network/l2-announcements/
  cilium_l2_policy_manifest = yamlencode({
    apiVersion = "cilium.io/v2alpha1"
    kind       = "CiliumL2AnnouncementPolicy"
    metadata = {
      name = "external"
    }
    spec = {
      loadBalancerIPs = true
      interfaces      = [var.cilium_interface]
      nodeSelector = {
        matchExpressions = [
          {
            key      = "node-role.kubernetes.io/control-plane"
            operator = "DoesNotExist"
          }
        ]
      }
    }
  })

  cilium_bootstrap_manifest = join("\n---\n", [
    data.helm_template.cilium.manifest,
    local.cilium_lb_pool_manifest,
    local.cilium_l2_policy_manifest,
  ])
}

// see https://docs.siderolabs.com/kubernetes-guides/cni/deploying-cilium#method-4%3A-helm-manifests-inline-install
// see https://docs.cilium.io/en/stable/network/servicemesh/ingress/
// see https://docs.cilium.io/en/stable/gettingstarted/hubble_setup/
// see https://docs.cilium.io/en/stable/gettingstarted/hubble/
// see https://docs.cilium.io/en/stable/helm-reference/#helm-reference
// see https://github.com/cilium/cilium/releases
// see https://github.com/cilium/cilium/tree/v1.19.0/install/kubernetes/cilium
// see https://registry.terraform.io/providers/hashicorp/helm/latest/docs/data-sources/template
data "helm_template" "cilium" {
  namespace    = "kube-system"
  name         = "cilium"
  repository   = "https://helm.cilium.io"
  chart        = "cilium"
  version      = local.chart_versions["cilium"]
  kube_version = local.kubernetes_version
  api_versions = []
  set = [
    {
      name  = "ipam.mode"
      value = "kubernetes"
    },
    {
      name  = "kubeProxyReplacement"
      value = "true"
    },
    {
      name  = "k8sServiceHost"
      value = "localhost"
    },
    {
      name  = "k8sServicePort"
      value = "7445"
    },
    {
      name  = "cgroup.autoMount.enabled"
      value = "false"
    },
    {
      name  = "cgroup.hostRoot"
      value = "/sys/fs/cgroup"
    },
    {
      name  = "securityContext.capabilities.ciliumAgent"
      value = "{CHOWN,KILL,NET_ADMIN,NET_RAW,IPC_LOCK,SYS_ADMIN,SYS_RESOURCE,DAC_OVERRIDE,FOWNER,SETGID,SETUID}"
    },
    {
      name  = "securityContext.capabilities.cleanCiliumState"
      value = "{NET_ADMIN,SYS_ADMIN,SYS_RESOURCE}"
    },
    {
      name  = "devices"
      value = "{${var.cilium_interface}}"
    },
    # Ingress    
    {
      name  = "ingressController.enabled"
      value = "true"
    },
    {
      name  = "ingressController.default"
      value = "true"
    },
    {
      name  = "ingressController.loadbalancerMode"
      value = "shared"
    },
    {
      name  = "ingressController.enforceHttps"
      value = "false"
    },
    {
      name  = "envoy.enabled"
      value = "true"
    },
    {
      name  = "gatewayAPI.enabled"
      value = "true"
    },
    # Hubble    
    {
      name  = "hubble.enabled"
      value = "true"
    },
    {
      name  = "hubble.relay.enabled"
      value = "true"
    },
    {
      name  = "hubble.relay.rollOutPods"
      value = "true"
    },
    {
      name  = "hubble.ui.enabled"
      value = "true"
    },
    {
      name  = "hubble.ui.rollOutPods"
      value = "true"
    },
    {
      name  = "prometheus.enabled"
      value = "true"
    },
    {
      name  = "operator.prometheus.enabled"
      value = "true"
    },
    {
      name  = "hubble.metrics.enableOpenMetrics"
      value = "true"
    },
    {
      name  = "hubble.metrics.enabled[0]"
      value = "dns:query;ignoreAAAA"
    },
    {
      name  = "hubble.metrics.enabled[1]"
      value = "drop"
    },
    {
      name  = "hubble.metrics.enabled[2]"
      value = "tcp"
    },
    {
      name  = "hubble.metrics.enabled[3]"
      value = "flow"
    },
    {
      name  = "hubble.metrics.enabled[4]"
      value = "icmp"
    },
    {
      name  = "hubble.metrics.enabled[5]"
      value = "http"
    },
    # Cilium L2 / LB IPAM platform decision
    {
      name  = "l2announcements.enabled"
      value = "true"
    },
    {
      name  = "k8sClientRateLimit.qps"
      value = "20"
    },
    {
      name  = "k8sClientRateLimit.burst"
      value = "40"
    }
  ]
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/data-sources/machine_configuration
data "talos_machine_configuration" "node" {
  for_each = local.all_nodes

  cluster_name       = var.cluster_name
  cluster_endpoint   = local.kubernetes_endpoint
  machine_type       = each.value.machine_type
  machine_secrets    = talos_machine_secrets.this.machine_secrets
  talos_version      = local.talos_version
  kubernetes_version = local.kubernetes_version

  config_patches = [
    yamlencode({
      cluster = merge(
        local.common_cluster_patch,
        {
          extraManifests = each.value.machine_type == "controlplane" ? [
            "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.1/standard-install.yaml",
            "https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/v1.4.1/config/crd/experimental/gateway.networking.k8s.io_tlsroutes.yaml",
          ] : []
          inlineManifests = each.value.machine_type == "controlplane" ? [
            {
              name     = "cilium-bootstrap"
              contents = local.cilium_bootstrap_manifest
            }
          ] : []
        }
      )
      machine = {
        kernel = local.drbd_patch
      }
    })
  ]
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/resources/machine_secrets
resource "talos_machine_secrets" "this" {
  talos_version = local.talos_version
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/resources/machine_configuration_apply
resource "talos_machine_configuration_apply" "node" {
  for_each = local.all_nodes

  depends_on = [
    proxmox_virtual_environment_vm.node,
  ]

  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.node[each.key].machine_configuration
  node                        = each.value.ip
  endpoint                    = each.value.ip

  config_patches = concat(
    [
      // see https://docs.siderolabs.com/talos/v1.12/reference/configuration/network/hostnameconfig
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        auto       = "off"
        hostname   = each.value.hostname
      }),
    ],
    each.value.machine_type == "controlplane" ? [
      // see https://docs.siderolabs.com/talos/v1.12/reference/configuration/network/layer2vipconfig
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "Layer2VIPConfig"
        name       = local.controlplane_vip
        link       = var.cilium_interface
      }),
    ] : [],
  )
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/resources/machine_bootstrap
resource "talos_machine_bootstrap" "this" {
  depends_on = [talos_machine_configuration_apply.node]

  client_configuration = talos_machine_secrets.this.client_configuration
  endpoint             = local.bootstrap_node_ip
  node                 = local.bootstrap_node_ip
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/resources/cluster_kubeconfig
resource "talos_cluster_kubeconfig" "this" {
  depends_on = [talos_machine_bootstrap.this]

  client_configuration = talos_machine_secrets.this.client_configuration
  endpoint             = local.bootstrap_node_ip
  node                 = local.bootstrap_node_ip
}

// see https://registry.terraform.io/providers/siderolabs/talos/0.10.1/docs/data-sources/client_configuration
data "talos_client_configuration" "this" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.this.client_configuration
  endpoints            = [for node in values(local.controlplane_nodes) : node.ip]
  nodes = concat(
    [for node in values(local.controlplane_nodes) : node.ip],
    [for node in values(local.worker_nodes) : node.ip]
  )
}

data "talos_cluster_health" "this" {
  client_configuration = talos_machine_secrets.this.client_configuration
  control_plane_nodes  = [for node in values(local.controlplane_nodes) : node.ip]
  worker_nodes         = [for node in values(local.worker_nodes) : node.ip]
  endpoints            = [for node in values(local.controlplane_nodes) : node.ip]

  skip_kubernetes_checks = true

  timeouts = {
    read = var.cluster_health_check_timeout
  }

  depends_on = [
    talos_machine_configuration_apply.node,
    talos_cluster_kubeconfig.this
  ]
}
