output "argocd_url" {
  value = var.argocd_enabled ? "https://${var.argocd_host}" : null
}

output "authentik_url" {
  value = var.authentik_enabled ? "https://${var.authentik_host}" : null
}

output "authentik_blueprints_configmap_name" {
  value = var.authentik_enabled ? kubernetes_config_map_v1.authentik_blueprints[0].metadata[0].name : null
}

output "authentik_in_cluster_url" {
  value = var.authentik_enabled ? "http://authentik-server.authentik.svc.cluster.local" : null
}

output "cluster_ca_secret_name" {
  value = "homelab-root-ca"
}

output "forgejo_url" {
  value = var.forgejo_enabled ? "https://${var.forgejo_host}" : null
}

output "forgejo_in_cluster_url" {
  value = var.forgejo_enabled ? "http://forgejo-http.forgejo.svc.cluster.local:3000" : null
}

output "forgejo_admin_username" {
  value = var.forgejo_enabled ? "forgejo" : null
}

output "forgejo_admin_password" {
  value       = null
  description = "Deprecated. Runtime secrets are sourced from OpenBao via ESO and are no longer exposed via Terraform outputs."
}

output "forgejo_admin_secret_name" {
  value = var.forgejo_enabled ? "forgejo-admin-secret" : null
}

output "authentik_runtime_secret_name" {
  value = var.authentik_enabled ? "authentik-runtime" : null
}
