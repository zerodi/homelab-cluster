variable "argocd_enabled" {
  type        = bool
  description = "Deploy Argo CD into the cluster"
  default     = null
  nullable    = true
}

variable "argocd_host" {
  type        = string
  description = "Ingress hostname for Argo CD"
  default     = null
  nullable    = true
}

variable "trust_manager_enabled" {
  type        = bool
  description = "Deploy trust-manager and distribute the internal CA bundle into selected namespaces"
  default     = null
  nullable    = true
}

variable "bootstrap_state_path" {
  type        = string
  description = "Path to the bootstrap state file used to discover non-secret infrastructure inputs"
  default     = "../bootstrap/terraform.tfstate"
}

variable "kubeconfig_path" {
  type        = string
  description = "Path to kubeconfig used by local kubectl-based orchestration steps"
  default     = null
  nullable    = true
}

variable "piraeus_namespace" {
  type     = string
  default  = null
  nullable = true
}

variable "piraeus_storage_device" {
  type        = string
  description = "Raw block device for LINSTOR storage pool, e.g. /dev/sdb"
  default     = null
  nullable    = true
}

variable "piraeus_storage_nodes" {
  type        = list(string)
  description = "Kubernetes node names where LINSTOR device pools should be created; if unset, values are discovered from bootstrap state"
  default     = null
  nullable    = true
}

variable "piraeus_storage_pool_name" {
  type     = string
  default  = null
  nullable = true
}

variable "piraeus_replica_count" {
  type     = number
  default  = null
  nullable = true
}

variable "worker_nodes" {
  type        = map(any)
  description = "Compatibility fallback for deriving worker hostnames when bootstrap state outputs are unavailable"
  default     = {}
}

variable "crd_backed_resources_enabled" {
  type        = bool
  description = "Create resources that require CRDs to already exist in the cluster API discovery"
  default     = true
}
