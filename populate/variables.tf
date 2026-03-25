variable "kubeconfig_path" {
  type        = string
  description = "Path to kubeconfig used to populate in-cluster resources"
}

variable "argocd_namespace" {
  type        = string
  description = "Namespace where Argo CD is installed"
  default     = "argocd"
}

variable "project_name" {
  type        = string
  description = "Argo CD AppProject name"
  default     = "platform"
}

variable "project_description" {
  type        = string
  description = "Argo CD AppProject description"
  default     = "Platform workloads"
}

variable "repo_base_url" {
  type        = string
  description = "Base Forgejo URL used for Argo CD repo credentials and project allowlist"
  default     = "https://git.home.arpa"
}

variable "repo_url" {
  type        = string
  description = "GitOps repository URL"
  default     = "https://git.home.arpa/platform/gitops.git"
}

variable "repo_username" {
  type        = string
  description = "Username used by Argo CD to access the Git repository"
}

variable "repo_password" {
  type        = string
  description = "Deprecated. Runtime secrets should come from OpenBao via ESO, not from Terraform variables."
  sensitive   = true
  default     = null
}

variable "cluster_name" {
  type        = string
  description = "Argo CD cluster secret name"
  default     = "homelab-talos"
}

variable "cluster_server" {
  type        = string
  description = "Kubernetes API server URL used by Argo CD"
  default     = "https://kubernetes.default.svc"
}

variable "cluster_bearer_token" {
  type        = string
  description = "Optional bearer token for an explicit Argo CD cluster secret"
  default     = null
  sensitive   = true
}

variable "authentik_enabled" {
  type        = bool
  description = "Whether Authentik population should run"
  default     = false
}

variable "authentik_host" {
  type        = string
  description = "External Authentik hostname used in OIDC discovery URLs"
  default     = "auth.home.arpa"
}

variable "authentik_in_cluster_url" {
  type        = string
  description = "Internal Authentik service URL used by in-cluster clients"
  default     = null
}

variable "authentik_blueprints_configmap_name" {
  type        = string
  description = "ConfigMap name mounted into Authentik for custom blueprints"
  default     = null
}

variable "authentik_application_slug" {
  type        = string
  description = "Authentik application slug used for Forgejo SSO"
  default     = "forgejo"
}

variable "forgejo_enabled" {
  type        = bool
  description = "Whether Forgejo population should run"
  default     = false
}

variable "forgejo_host" {
  type        = string
  description = "External Forgejo hostname used for redirect URIs"
  default     = "git.home.arpa"
}

variable "forgejo_admin_username" {
  type        = string
  description = "Forgejo admin username used for repository bootstrapping"
  default     = null
}

variable "forgejo_admin_password" {
  type        = string
  description = "Deprecated. Runtime secrets should come from OpenBao via ESO, not from Terraform variables."
  default     = null
  sensitive   = true
}

variable "forgejo_sso_name" {
  type        = string
  description = "Forgejo authentication source name for Authentik OIDC"
  default     = "authentik"
}

variable "gitops_owner" {
  type        = string
  description = "Forgejo owner or organization that will hold the GitOps repository"
  default     = "platform"
}

variable "gitops_repo" {
  type        = string
  description = "Forgejo repository name used by Argo CD"
  default     = "gitops"
}

variable "gitops_repo_description" {
  type        = string
  description = "Description for the bootstrap GitOps repository"
  default     = "Cluster GitOps repository"
}

variable "gitops_repo_private" {
  type        = bool
  description = "Create the bootstrap GitOps repository as private"
  default     = true
}
