output "controlplane_ips" {
  value = { for name, node in var.controlplane_nodes : name => node.ip }
}

output "worker_ips" {
  value = { for name, node in var.worker_nodes : name => node.ip }
}

output "talosconfig" {
  value       = null
  sensitive   = true
  description = "Deprecated. talosconfig is written only to a local file and is no longer exposed via Terraform outputs."
}

output "kubeconfig" {
  value       = null
  sensitive   = true
  description = "Deprecated. kubeconfig is written only to a local file and is no longer exposed via Terraform outputs."
}

output "talosconfig_path" {
  value       = var.write_configs_to_files ? local_sensitive_file.talosconfig[0].filename : null
  description = "Local path to talosconfig"
}

output "kubeconfig_path" {
  value       = var.write_configs_to_files ? local_sensitive_file.kubeconfig[0].filename : null
  description = "Local path to kubeconfig"
}

resource "local_sensitive_file" "talosconfig" {
  count = var.write_configs_to_files ? 1 : 0

  filename        = var.talosconfig_file_path
  file_permission = "0600"
  content         = data.talos_client_configuration.this.talos_config
}

resource "local_sensitive_file" "kubeconfig" {
  count = var.write_configs_to_files ? 1 : 0

  depends_on = [talos_cluster_kubeconfig.this]

  filename        = var.kubeconfig_file_path
  file_permission = "0600"
  content         = talos_cluster_kubeconfig.this.kubeconfig_raw
}
