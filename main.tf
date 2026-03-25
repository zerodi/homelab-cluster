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
  talos_version                = var.talos_version
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
  ingress_host                 = var.ingress_host
}

module "infrastructure" {
  source = "./infrastructure"

  depends_on = [module.bootstrap]

  providers = {
    kubernetes = kubernetes
    helm       = helm.cluster
  }

  ingress_host              = var.ingress_host
  ingress_domain            = var.ingress_domain
  kubeconfig_path           = var.kubeconfig_file_path
  argocd_enabled            = var.argocd_enabled
  argocd_host               = var.argocd_host
  authentik_enabled         = var.authentik_enabled
  authentik_host            = var.authentik_host
  forgejo_enabled           = var.forgejo_enabled
  forgejo_host              = var.forgejo_host
  forgejo_admin_email       = var.forgejo_admin_email
  trust_manager_enabled     = var.trust_manager_enabled
  piraeus_namespace         = var.piraeus_namespace
  piraeus_storage_device    = var.piraeus_storage_device
  piraeus_storage_nodes     = [for node in values(var.worker_nodes) : node.hostname]
  piraeus_storage_pool_name = var.piraeus_storage_pool_name
  piraeus_volume_group_name = var.piraeus_volume_group_name
  piraeus_thin_pool_name    = var.piraeus_thin_pool_name
  piraeus_replica_count     = var.piraeus_replica_count
}

module "populate" {
  count  = var.populate_enabled ? 1 : 0
  source = "./populate"

  depends_on = [module.infrastructure]

  providers = {
    kubernetes = kubernetes
  }

  kubeconfig_path                     = var.kubeconfig_file_path
  argocd_namespace                    = var.populate_argocd_namespace
  project_name                        = var.populate_project_name
  project_description                 = var.populate_project_description
  repo_base_url                       = coalesce(var.populate_repo_base_url, module.infrastructure.forgejo_in_cluster_url, module.infrastructure.forgejo_url)
  repo_url                            = coalesce(var.populate_repo_url, module.infrastructure.forgejo_in_cluster_url != null ? "${module.infrastructure.forgejo_in_cluster_url}/${var.populate_gitops_owner}/${var.populate_gitops_repo}.git" : null, module.infrastructure.forgejo_url != null ? "${module.infrastructure.forgejo_url}/${var.populate_gitops_owner}/${var.populate_gitops_repo}.git" : null)
  repo_username                       = coalesce(var.populate_repo_username, module.infrastructure.forgejo_admin_username)
  cluster_name                        = coalesce(var.populate_cluster_name, var.cluster_name)
  cluster_server                      = var.populate_cluster_server
  cluster_bearer_token                = var.populate_cluster_bearer_token
  authentik_enabled                   = var.authentik_enabled
  authentik_host                      = var.authentik_host
  authentik_in_cluster_url            = module.infrastructure.authentik_in_cluster_url
  authentik_blueprints_configmap_name = module.infrastructure.authentik_blueprints_configmap_name
  forgejo_enabled                     = var.forgejo_enabled
  forgejo_host                        = var.forgejo_host
  forgejo_sso_name                    = var.populate_forgejo_sso_name
  authentik_application_slug          = var.populate_authentik_application_slug
  gitops_owner                        = var.populate_gitops_owner
  gitops_repo                         = var.populate_gitops_repo
  gitops_repo_description             = var.populate_gitops_repo_description
  gitops_repo_private                 = var.populate_gitops_repo_private
}
