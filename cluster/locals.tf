locals {
  version_contract     = yamldecode(file("${path.root}/../versions.yaml"))
  environment_contract = yamldecode(file(var.environment_contract_path))
  chart_versions       = local.version_contract.charts
  talos_version        = local.version_contract.platform.talos_linux
  kubernetes_version   = local.version_contract.platform.kubernetes
  cluster_name = coalesce(
    var.cluster_name,
    try(local.environment_contract.cluster.name, null),
    "talos-pve",
  )
  cluster_ipv4_cidr = local.environment_contract.cluster.ipv4_cidr

  effective_proxmox = merge(
    var.proxmox,
    {
      api_token = var.proxmox_api_token
    }
  )

  network_prefix_length = split("/", local.cluster_ipv4_cidr)[1]
  gateway               = cidrhost(local.cluster_ipv4_cidr, 1)
  controlplane_vip      = cidrhost(local.cluster_ipv4_cidr, 200)
  cilium_lb_pool_start  = cidrhost(local.cluster_ipv4_cidr, 230)
  cilium_lb_pool_stop   = cidrhost(local.cluster_ipv4_cidr, 250)

  controlplane_nodes = {
    for index in range(var.controlplane_nodes) :
    format("cp-%02d", index + 1) => {
      vm_id       = 9001 + index
      ip          = cidrhost(local.cluster_ipv4_cidr, 11 + index)
      mac_address = format("BC:24:11:00:01:%02X", index + 1)
      hostname    = format("cp-%02d", index + 1)
    }
  }

  worker_nodes = {
    for index in range(var.worker_nodes) :
    format("wk-%02d", index + 1) => {
      vm_id       = 9101 + index
      ip          = cidrhost(local.cluster_ipv4_cidr, 101 + index)
      mac_address = format("BC:24:11:00:02:%02X", index + 1)
      hostname    = format("wk-%02d", index + 1)
    }
  }

  all_nodes = merge(
    {
      for name, node in local.controlplane_nodes :
      name => merge(var.controlplane_node_defaults, node, {
        machine_type = "controlplane"
      })
    },
    {
      for name, node in local.worker_nodes :
      name => merge(var.worker_node_defaults, node, {
        machine_type = "worker"
      })
    }
  )
}
