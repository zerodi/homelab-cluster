output "controlplane_ips" {
  value = { for name, node in local.controlplane_nodes : name => node.ip }
}

output "worker_ips" {
  value = { for name, node in local.worker_nodes : name => node.ip }
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
  value       = [for node in values(local.worker_nodes) : node.hostname]
  description = "Worker hostnames exported for the separate infrastructure entrypoint."
}

output "controlplane_ips_csv" {
  value       = join(",", [for name in sort(keys(local.controlplane_nodes)) : local.controlplane_nodes[name].ip])
  description = "Comma-separated control plane IPs used by local health helpers."
}

output "worker_ips_csv" {
  value       = join(",", [for name in sort(keys(local.worker_nodes)) : local.worker_nodes[name].ip])
  description = "Comma-separated worker IPs used by local health helpers."
}

output "cilium_lb_pool_manifest" {
  value       = local.cilium_lb_pool_manifest
  description = "Rendered Cilium LoadBalancer IP pool manifest used for post-apply reconciliation."
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
