output "argocd_url" {
  value = local.effective_argocd_enabled ? "https://${local.effective_argocd_host}" : null
}

output "cluster_ca_secret_name" {
  value = "homelab-root-ca"
}

output "piraeus_storage_class_name" {
  value = kubernetes_storage_class_v1.piraeus_replicated.metadata[0].name
}
