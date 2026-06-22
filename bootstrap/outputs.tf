output "controlplane_ips" {
  value = { for name, node in var.controlplane_nodes : name => node.ip }
}

output "worker_ips" {
  value = { for name, node in var.worker_nodes : name => node.ip }
}

output "talosconfig_path" {
  value       = abspath(local_sensitive_file.talosconfig.filename)
  description = "Local path to talosconfig"
}

output "kubeconfig_path" {
  value       = abspath(local_sensitive_file.kubeconfig.filename)
  description = "Local path to kubeconfig"
}

output "worker_hostnames" {
  value       = [for node in values(var.worker_nodes) : node.hostname]
  description = "Worker hostnames exported for the separate infrastructure entrypoint."
}

output "controlplane_ips_csv" {
  value       = join(",", [for name in sort(keys(var.controlplane_nodes)) : var.controlplane_nodes[name].ip])
  description = "Comma-separated control plane IPs used by local health helpers."
}

output "worker_ips_csv" {
  value       = join(",", [for name in sort(keys(var.worker_nodes)) : var.worker_nodes[name].ip])
  description = "Comma-separated worker IPs used by local health helpers."
}

output "platform_bootstrap" {
  value = {
    kubeconfig_path           = abspath(local_sensitive_file.kubeconfig.filename)
  }
  description = "Non-secret inputs consumed by the separate infrastructure entrypoint."
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
