locals {
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
