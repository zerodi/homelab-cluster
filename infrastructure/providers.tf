terraform {
  required_version = ">= 1.6.0"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.2"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.2"
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
  environment_contract = yamldecode(file(var.environment_contract_path))
  chart_versions       = yamldecode(file("${path.root}/../versions.yaml")).charts
  bootstrap_outputs    = data.terraform_remote_state.bootstrap.outputs

  effective_kubeconfig_path = coalesce(
    var.kubeconfig_path,
    try(local.bootstrap_outputs.kubeconfig_path, null),
  )

  effective_argocd_host = coalesce(
    var.argocd_host,
    try(local.environment_contract.hosts.argocd, null),
    "argocd.home.arpa",
  )

  effective_piraeus_namespace = coalesce(
    var.piraeus_namespace,
    try(local.environment_contract.storage.piraeus.namespace, null),
    "piraeus-datastore",
  )

  effective_piraeus_storage_device = coalesce(
    var.piraeus_storage_device,
    try(local.environment_contract.storage.piraeus.device, null),
    "/dev/sdb",
  )

  effective_piraeus_storage_pool_name = coalesce(
    var.piraeus_storage_pool_name,
    try(local.environment_contract.storage.piraeus.pool_name, null),
    "pool1",
  )

  effective_piraeus_replica_count = coalesce(
    var.piraeus_replica_count,
    try(local.environment_contract.storage.piraeus.replica_count, null),
    1,
  )

  effective_piraeus_storage_nodes = sort(distinct(compact(
    var.piraeus_storage_nodes != null ?
    var.piraeus_storage_nodes :
    try(local.bootstrap_outputs.worker_hostnames, [])
  )))
}

provider "kubernetes" {
  config_path = local.effective_kubeconfig_path
}

provider "helm" {
  kubernetes = {
    config_path = local.effective_kubeconfig_path
  }
}
