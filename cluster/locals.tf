locals {
  chart_versions = yamldecode(file("${path.root}/../versions.yaml")).charts

  effective_proxmox = merge(
    var.proxmox,
    {
      api_token = var.proxmox_api_token
    }
  )

  all_nodes = merge(
    {
      for name, node in var.controlplane_nodes :
      name => merge(var.controlplane_node_defaults, node, {
        machine_type = "controlplane"
      })
    },
    {
      for name, node in var.worker_nodes :
      name => merge(var.worker_node_defaults, node, {
        machine_type = "worker"
      })
    }
  )
}
