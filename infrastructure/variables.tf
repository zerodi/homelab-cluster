variable "argocd_enabled" {
  type        = bool
  description = "Deploy Argo CD into the cluster"
  default     = false
}

variable "argocd_host" {
  type        = string
  description = "Ingress hostname for Argo CD"
  default     = "argocd.home.arpa"
}

variable "trust_manager_enabled" {
  type        = bool
  description = "Deploy trust-manager and distribute the internal CA bundle into selected namespaces"
  default     = true
}

variable "kubeconfig_path" {
  type        = string
  description = "Path to kubeconfig used by local kubectl-based orchestration steps"
}

variable "piraeus_namespace" {
  type    = string
  default = "piraeus-datastore"
}

variable "piraeus_storage_device" {
  type        = string
  description = "Raw block device for LINSTOR storage pool, e.g. /dev/sdb"
  default     = "/dev/sdb"
}

variable "piraeus_storage_nodes" {
  type        = list(string)
  description = "Kubernetes node names where LINSTOR device pools should be created"
  default     = []
}

variable "piraeus_storage_pool_name" {
  type    = string
  default = "lvm"
}

variable "piraeus_replica_count" {
  type    = number
  default = 2
}
