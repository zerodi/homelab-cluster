output "argocd_url" {
  description = "Argo CD URL derived from the effective environment configuration."
  value       = "https://${local.effective_argocd_host}"
}

output "cluster_ca_secret_name" {
  description = "Name of the internal root CA Secret."
  value       = "homelab-root-ca"
}

output "piraeus_storage_class_name" {
  description = "Name of the LINSTOR-backed StorageClass."
  value       = kubernetes_storage_class_v1.piraeus_replicated.metadata[0].name
}

output "platform_configuration" {
  description = "Effective non-secret inputs owned by the infrastructure entrypoint."
  value = {
    argocd_host               = local.effective_argocd_host
    kubeconfig_path           = local.effective_kubeconfig_path
    piraeus_namespace         = local.effective_piraeus_namespace
    piraeus_storage_device    = local.effective_piraeus_storage_device
    piraeus_storage_pool_name = local.effective_piraeus_storage_pool_name
    piraeus_replica_count     = local.effective_piraeus_replica_count
    piraeus_storage_nodes     = local.effective_piraeus_storage_nodes
  }
}

output "piraeus_storage_nodes_csv" {
  description = "Space-separated worker hostnames used by the storage bootstrap helper."
  value       = join(" ", local.effective_piraeus_storage_nodes)
}

output "piraeus_storage_device" {
  description = "Raw block device used by the storage bootstrap helper."
  value       = local.effective_piraeus_storage_device
}

output "piraeus_storage_pool_name" {
  description = "LINSTOR storage pool name used by the storage bootstrap helper."
  value       = local.effective_piraeus_storage_pool_name
}

output "piraeus_namespace" {
  description = "Piraeus namespace used by the storage bootstrap helper."
  value       = local.effective_piraeus_namespace
}
