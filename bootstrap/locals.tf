locals {
  effective_proxmox = merge(
    var.proxmox,
    {
      api_token = coalesce(var.proxmox_api_token, try(var.proxmox.api_token, null))
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
