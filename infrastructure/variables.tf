###
# Configuration sources
###

variable "cluster_state_path" {
  description = "Path to cluster local state used to discover kubeconfig and worker nodes."
  type        = string
  default     = "../cluster/terraform.tfstate"
}

variable "environment_contract_path" {
  description = "Path to the effective non-secret environment contract used for platform naming. Task renders it from homelab.yaml plus the optional local override."
  type        = string
  default     = "../envs/homelab.yaml"
}

###
# Cluster state overrides
###

variable "kubeconfig_path" {
  description = "Optional kubeconfig override for recovery or non-standard state layouts."
  type        = string
  default     = null
  nullable    = true
}

variable "piraeus_storage_nodes" {
  description = "Optional worker hostname override for LINSTOR storage pools."
  type        = list(string)
  default     = null
  nullable    = true
}

###
# Environment contract overrides
###

variable "argocd_host" {
  description = "Optional Argo CD hostname override. Defaults to hosts.argocd in the environment contract."
  type        = string
  default     = null
  nullable    = true
}

variable "piraeus_namespace" {
  description = "Optional Piraeus namespace override."
  type        = string
  default     = null
  nullable    = true
}

variable "piraeus_storage_device" {
  description = "Optional raw block device override used for LINSTOR storage pools."
  type        = string
  default     = null
  nullable    = true
}

variable "piraeus_storage_pool_name" {
  description = "Optional LINSTOR storage pool name override."
  type        = string
  default     = null
  nullable    = true
}

variable "piraeus_replica_count" {
  description = "Optional LINSTOR replica count override."
  type        = number
  default     = null
  nullable    = true
}

###
# Staged apply control
###

variable "crd_backed_resources_enabled" {
  description = "Create manifests whose CRDs must already be registered in API discovery."
  type        = bool
  default     = true
}
