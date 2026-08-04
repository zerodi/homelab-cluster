data "terraform_remote_state" "cluster" {
  backend = "local"

  config = {
    path = var.cluster_state_path
  }
}

locals {
  environment_contract = yamldecode(file(var.environment_contract_path))
  version_contract     = yamldecode(file("${path.root}/../versions.yaml"))
  chart_versions       = local.version_contract.charts
  cluster_outputs      = data.terraform_remote_state.cluster.outputs

  effective_kubeconfig_path = coalesce(
    var.kubeconfig_path,
    try(local.cluster_outputs.kubeconfig_path, null),
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
    try(local.cluster_outputs.worker_hostnames, [])
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
