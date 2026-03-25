output "argocd_project_name" {
  value = var.project_name
}

output "argocd_repo_creds_secret_name" {
  value = "${var.project_name}-repo-creds"
}

output "argocd_cluster_secret_name" {
  value     = var.cluster_bearer_token != null ? kubernetes_secret_v1.target_cluster[0].metadata[0].name : null
  sensitive = true
}

output "argocd_repository_secret_name" {
  value = "${var.project_name}-repository"
}

output "forgejo_sso_name" {
  value = var.forgejo_sso_name
}

output "authentik_application_slug" {
  value = var.authentik_application_slug
}
