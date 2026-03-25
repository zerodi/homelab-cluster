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

output "authentik_url" {
  value = module.infrastructure.authentik_url
}

output "authentik_in_cluster_url" {
  value = module.infrastructure.authentik_in_cluster_url
}

output "forgejo_url" {
  value = module.infrastructure.forgejo_url
}

output "forgejo_in_cluster_url" {
  value = module.infrastructure.forgejo_in_cluster_url
}

output "cluster_ca_secret_name" {
  value = module.infrastructure.cluster_ca_secret_name
}

output "forgejo_admin_username" {
  value = module.infrastructure.forgejo_admin_username
}

output "forgejo_admin_password" {
  value       = null
  description = "Deprecated. Runtime secrets are sourced from OpenBao via ESO and are no longer exposed via Terraform outputs."
}

output "populate_argocd_project_name" {
  value = try(module.populate[0].argocd_project_name, null)
}

output "populate_argocd_repo_creds_secret_name" {
  value     = try(module.populate[0].argocd_repo_creds_secret_name, null)
  sensitive = true
}

output "populate_argocd_cluster_secret_name" {
  value     = try(module.populate[0].argocd_cluster_secret_name, null)
  sensitive = true
}

output "populate_argocd_repository_secret_name" {
  value = try(module.populate[0].argocd_repository_secret_name, null)
}

output "populate_forgejo_sso_name" {
  value = try(module.populate[0].forgejo_sso_name, null)
}

output "populate_authentik_application_slug" {
  value = try(module.populate[0].authentik_application_slug, null)
}
