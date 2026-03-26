output "controlplane_ips" {
  value = module.bootstrap.controlplane_ips
}

output "worker_ips" {
  value = module.bootstrap.worker_ips
}

output "talosconfig" {
  value       = null
  sensitive   = true
  description = "Deprecated. talosconfig is written only to a local file in out/ and is no longer exposed via Terraform outputs."
}

output "kubeconfig" {
  value       = null
  sensitive   = true
  description = "Deprecated. kubeconfig is written only to a local file in out/ and is no longer exposed via Terraform outputs."
}

output "talosconfig_path" {
  value       = module.bootstrap.talosconfig_path
  description = "Local path to talosconfig"
}

output "kubeconfig_path" {
  value       = module.bootstrap.kubeconfig_path
  description = "Local path to kubeconfig"
}

output "argocd_url" {
  value = module.infrastructure.argocd_url
}

output "cluster_ca_secret_name" {
  value = module.infrastructure.cluster_ca_secret_name
}

output "openbao_cluster_secret_store_name" {
  value = module.infrastructure.openbao_cluster_secret_store_name
}

output "piraeus_storage_class_name" {
  value = module.infrastructure.piraeus_storage_class_name
}
