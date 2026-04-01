output "controlplane_ips" {
  value = { for name, node in var.controlplane_nodes : name => node.ip }
}

output "worker_ips" {
  value = { for name, node in var.worker_nodes : name => node.ip }
}

output "talosconfig_path" {
  value       = var.write_configs_to_files ? abspath(local_sensitive_file.talosconfig.filename) : null
  description = "Local path to talosconfig"
}

output "kubeconfig_path" {
  value       = var.write_configs_to_files ? abspath(local_sensitive_file.kubeconfig.filename) : null
  description = "Local path to kubeconfig"
}

output "worker_hostnames" {
  value       = [for node in values(var.worker_nodes) : node.hostname]
  description = "Worker hostnames exported for the separate infrastructure entrypoint."
}

output "platform_bootstrap" {
  value = {
    kubeconfig_path           = var.write_configs_to_files ? abspath(local_sensitive_file.kubeconfig.filename) : null
    argocd_enabled            = var.argocd_enabled
    argocd_host               = var.argocd_host
    trust_manager_enabled     = var.trust_manager_enabled
    piraeus_namespace         = var.piraeus_namespace
    piraeus_storage_device    = var.piraeus_storage_device
    piraeus_storage_pool_name = var.piraeus_storage_pool_name
    piraeus_replica_count     = var.piraeus_replica_count
    piraeus_storage_nodes     = [for node in values(var.worker_nodes) : node.hostname]
  }
  description = "Non-secret inputs consumed by the separate infrastructure entrypoint."
}

output "piraeus_storage_nodes_csv" {
  value       = join(" ", [for node in values(var.worker_nodes) : node.hostname])
  description = "Space-separated worker hostnames used by the storage bootstrap helper."
}

output "piraeus_storage_device" {
  value       = var.piraeus_storage_device
  description = "Raw block device used by the storage bootstrap helper."
}

output "piraeus_storage_pool_name" {
  value       = var.piraeus_storage_pool_name
  description = "LINSTOR storage pool name used by the storage bootstrap helper."
}

output "piraeus_namespace" {
  value       = var.piraeus_namespace
  description = "Piraeus namespace used by the storage bootstrap helper."
}

resource "local_sensitive_file" "talosconfig" {
  filename        = var.talosconfig_file_path
  file_permission = "0600"
  content         = data.talos_client_configuration.this.talos_config
}

resource "local_sensitive_file" "kubeconfig" {
  depends_on = [talos_cluster_kubeconfig.this]

  filename        = var.kubeconfig_file_path
  file_permission = "0600"
  content         = talos_cluster_kubeconfig.this.kubeconfig_raw
}
