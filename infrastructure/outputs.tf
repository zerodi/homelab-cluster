output "argocd_url" {
  value = var.argocd_enabled ? "https://${var.argocd_host}" : null
}

output "cluster_ca_secret_name" {
  value = "homelab-root-ca"
}

output "openbao_cluster_secret_store_name" {
  value = "openbao"
}

output "piraeus_storage_class_name" {
  value = kubernetes_storage_class_v1.piraeus_replicated.metadata[0].name
}
