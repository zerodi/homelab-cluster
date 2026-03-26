locals {
  effective_proxmox = merge(
    var.proxmox,
    {
      api_token = coalesce(var.proxmox_api_token, try(var.proxmox.api_token, null))
    }
  )
}

module "bootstrap" {
  source = "./bootstrap"

  providers = {
    proxmox = proxmox
    talos   = talos
    helm    = helm
  }

  proxmox                      = local.effective_proxmox
  talos                        = var.talos
  cilium_chart_version         = var.cilium_chart_version
  cluster_name                 = var.cluster_name
  controlplane_vip             = var.controlplane_vip
  cluster_endpoint             = var.cluster_endpoint
  kubernetes_version           = var.kubernetes_version
  cluster_health_check_timeout = var.cluster_health_check_timeout
  gateway                      = var.gateway
  nameservers                  = var.nameservers
  controlplane_node_defaults   = var.controlplane_node_defaults
  controlplane_nodes           = var.controlplane_nodes
  worker_node_defaults         = var.worker_node_defaults
  worker_nodes                 = var.worker_nodes
  write_configs_to_files       = var.write_configs_to_files
  kubeconfig_file_path         = var.kubeconfig_file_path
  cilium_interface             = var.cilium_interface
  cilium_lb_pool_start         = var.cilium_lb_pool_start
  cilium_lb_pool_stop          = var.cilium_lb_pool_stop
}

module "infrastructure" {
  source = "./infrastructure"

  depends_on = [module.bootstrap]

  providers = {
    kubernetes = kubernetes
    helm       = helm.cluster
  }

  kubeconfig_path           = var.kubeconfig_file_path
  argocd_enabled            = var.argocd_enabled
  argocd_host               = var.argocd_host
  trust_manager_enabled     = var.trust_manager_enabled
  piraeus_namespace         = var.piraeus_namespace
  piraeus_storage_device    = var.piraeus_storage_device
  piraeus_storage_nodes     = [for node in values(var.worker_nodes) : node.hostname]
  piraeus_storage_pool_name = var.piraeus_storage_pool_name
  piraeus_replica_count     = var.piraeus_replica_count
}
