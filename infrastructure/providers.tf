terraform {
  required_version = ">= 1.6.0"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
    }
  }
}

data "terraform_remote_state" "bootstrap" {
  backend = "local"

  config = {
    path = var.bootstrap_state_path
  }
}

locals {
  bootstrap_platform = try(data.terraform_remote_state.bootstrap.outputs.platform_bootstrap, {})

  effective_kubeconfig_path = coalesce(
    var.kubeconfig_path,
    try(local.bootstrap_platform.kubeconfig_path, null),
  )
  effective_argocd_enabled = coalesce(
    var.argocd_enabled,
    try(local.bootstrap_platform.argocd_enabled, null),
    false,
  )
  effective_argocd_host = coalesce(
    var.argocd_host,
    try(local.bootstrap_platform.argocd_host, null),
    "argocd.home.arpa",
  )
  effective_trust_manager_enabled = coalesce(
    var.trust_manager_enabled,
    try(local.bootstrap_platform.trust_manager_enabled, null),
    true,
  )
  effective_piraeus_namespace = coalesce(
    var.piraeus_namespace,
    try(local.bootstrap_platform.piraeus_namespace, null),
    "piraeus-datastore",
  )
  effective_piraeus_storage_device = coalesce(
    var.piraeus_storage_device,
    try(local.bootstrap_platform.piraeus_storage_device, null),
    "/dev/sdb",
  )
  effective_piraeus_storage_pool_name = coalesce(
    var.piraeus_storage_pool_name,
    try(local.bootstrap_platform.piraeus_storage_pool_name, null),
    "lvm",
  )
  effective_piraeus_replica_count = coalesce(
    var.piraeus_replica_count,
    try(local.bootstrap_platform.piraeus_replica_count, null),
    1,
  )
  effective_piraeus_storage_nodes = sort(distinct(compact(coalescelist(
    var.piraeus_storage_nodes,
    try(local.bootstrap_platform.piraeus_storage_nodes, null),
    try(data.terraform_remote_state.bootstrap.outputs.worker_hostnames, null),
    [for node in values(var.worker_nodes) : try(node.hostname, null)],
    [],
  ))))
}

provider "kubernetes" {
  config_path = local.effective_kubeconfig_path
}

provider "helm" {
  kubernetes = {
    config_path = local.effective_kubeconfig_path
  }
}
