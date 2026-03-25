# Proxmox
variable "proxmox" {
  description = ""
  type = object({
    endpoint        = string
    api_token       = optional(string)
    insecure        = optional(bool, true)
    node_name       = string
    vm_datastore    = string
    image_datastore = string

  })
}

variable "proxmox_api_token" {
  type        = string
  description = "Sensitive Proxmox API token. Prefer TF_VAR_proxmox_api_token or an encrypted SOPS tfvars file over terraform.tfvars."
  default     = null
  nullable    = true
  sensitive   = true
}

variable "talos" {
  description = "Talos image and installation settings shared across bootstrap resources."
  type = object({
    # Talos release version. Accepts `v1.12.6`.
    version = string
    # Talos Image Factory schematic ID used to build/download installer artifacts.
    schematic_id = string
  })

  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+$", var.talos.version))
    error_message = "talos.version must be a Talos release in the form `v1.12.6`."
  }
}

variable "prefix" {
  type    = string
  default = "talos"
}

# Talos and Kubernetes
variable "cluster_name" {
  type    = string
  default = "talos-pve"
}

variable "controlplane_vip" {
  type        = string
  description = "Virtual IP for Kubernetes API on the control plane subnet, e.g. 192.168.100.210"
}

variable "cluster_endpoint" {
  type        = string
  description = "Kubernetes/Talos cluster endpoint"
  default     = null
}

variable "talos_version" {
  description = "Talos config schema/version, for example v1.12.2"
  type        = string
}

variable "kubernetes_version" {
  description = "Optional Kubernetes version to bake into Talos machine config"
  type        = string
  default     = null
}

variable "cilium_interface" {
  type        = string
  description = "Cilium network interface"
  default     = "eth0"
}

variable "cilium_chart_version" {
  type        = string
  description = "Cilium Helm chart version"
  default     = "1.19.1"
}

variable "cilium_lb_pool_start" {
  type        = string
  description = "First IP in Cilium LoadBalancer pool"
}

variable "cilium_lb_pool_stop" {
  type        = string
  description = "Last IP in Cilium LoadBalancer pool"
}

variable "cluster_health_check_timeout" {
  type        = string
  description = "Timeout for talos_cluster_health checks after bootstrap"
  default     = "20m"
}

# Network
variable "gateway" {
  description = "Default IPv4 gateway used only if you later switch to static IP patches"
  type        = string
  default     = null
}

variable "nameservers" {
  description = "DNS servers used only if you later switch to static IP patches"
  type        = list(string)
  default     = []
}

# Nodes
variable "controlplane_node_defaults" {
  description = "Shared hardware and network settings for all control plane nodes."
  type = object({
    cpu_cores = number
    memory_mb = number
    disk_gb   = number
    cidr      = number
  })
}

variable "controlplane_nodes" {
  description = "Per-control-plane inventory. Shared characteristics are defined in controlplane_node_defaults."
  type = map(object({
    vm_id       = number
    ip          = string
    mac_address = string
    hostname    = string
  }))
}

variable "worker_node_defaults" {
  description = "Shared hardware and network settings for all worker nodes."
  type = object({
    cpu_cores = number
    memory_mb = number
    disk_gb   = number
    cidr      = number
  })
}

variable "worker_nodes" {
  description = "Per-worker inventory. Shared characteristics are defined in worker_node_defaults."
  type = map(object({
    vm_id       = number
    ip          = string
    mac_address = string
    hostname    = string
  }))
}

# Generated configs
variable "write_configs_to_files" {
  type        = bool
  description = "Write talosconfig and kubeconfig to local files"
  default     = true
}

variable "talosconfig_file_path" {
  type        = string
  description = "Path to write talosconfig"
  default     = "out/talosconfig"
}

variable "kubeconfig_file_path" {
  type        = string
  description = "Path to write kubeconfig"
  default     = "out/kubeconfig"
}

# Add-ons and apps
variable "ingress_host" {
  type        = string
  description = "Hostname for test ingress"
  default     = "echo.home.arpa"
}

variable "ingress_domain" {
  type        = string
  description = "Base DNS domain used for application ingresses"
  default     = "home.arpa"
}

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

variable "authentik_enabled" {
  type        = bool
  description = "Deploy Authentik into the cluster"
  default     = false
}

variable "authentik_host" {
  type        = string
  description = "Ingress hostname for Authentik"
  default     = "auth.home.arpa"
}

variable "forgejo_enabled" {
  type        = bool
  description = "Deploy Forgejo into the cluster"
  default     = false
}

variable "forgejo_host" {
  type        = string
  description = "Ingress hostname for Forgejo"
  default     = "git.home.arpa"
}

variable "forgejo_admin_email" {
  type        = string
  description = "Bootstrap admin email for Forgejo"
  default     = "forgejo@home.arpa"
}

variable "trust_manager_enabled" {
  type        = bool
  description = "Deploy trust-manager and distribute the internal CA bundle into selected namespaces"
  default     = true
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

variable "piraeus_storage_pool_name" {
  type    = string
  default = "pool1"
}

variable "piraeus_volume_group_name" {
  type    = string
  default = "linstor_vg"
}

variable "piraeus_thin_pool_name" {
  type    = string
  default = "thinpool"
}

variable "piraeus_replica_count" {
  type    = number
  default = 2
}

variable "populate_enabled" {
  type        = bool
  description = "Populate Argo CD bootstrap resources after infrastructure is ready"
  default     = false
}

variable "populate_argocd_namespace" {
  type        = string
  description = "Namespace where Argo CD is installed for the populate module"
  default     = "argocd"
}

variable "populate_project_name" {
  type        = string
  description = "Argo CD AppProject name created by the populate module"
  default     = "platform"
}

variable "populate_project_description" {
  type        = string
  description = "Argo CD AppProject description created by the populate module"
  default     = "Platform workloads"
}

variable "populate_repo_base_url" {
  type        = string
  description = "Optional base URL for Git repository credentials; defaults to the Forgejo URL output"
  default     = null
  nullable    = true
}

variable "populate_repo_url" {
  type        = string
  description = "Optional GitOps repository URL; defaults to <forgejo_url>/platform/gitops.git"
  default     = null
  nullable    = true
}

variable "populate_repo_username" {
  type        = string
  description = "Optional repository username; defaults to the Forgejo admin username output"
  default     = null
  nullable    = true
}

variable "populate_repo_password" {
  type        = string
  description = "Deprecated. Runtime secrets should come from OpenBao via ESO, not from Terraform variables."
  default     = null
  nullable    = true
  sensitive   = true
}

variable "populate_cluster_name" {
  type        = string
  description = "Optional Argo CD cluster secret name; defaults to cluster_name"
  default     = null
  nullable    = true
}

variable "populate_cluster_server" {
  type        = string
  description = "Kubernetes API server URL registered in Argo CD"
  default     = "https://kubernetes.default.svc"
}

variable "populate_cluster_bearer_token" {
  type        = string
  description = "Optional bearer token for an explicit Argo CD cluster secret. Prefer TF_VAR_populate_cluster_bearer_token or an encrypted SOPS tfvars file."
  default     = null
  nullable    = true
  sensitive   = true
}

variable "populate_authentik_application_slug" {
  type        = string
  description = "Authentik application slug used for the Forgejo OIDC provider"
  default     = "forgejo"
}

variable "populate_forgejo_sso_name" {
  type        = string
  description = "Forgejo authentication source name for Authentik OIDC"
  default     = "authentik"
}

variable "populate_gitops_owner" {
  type        = string
  description = "Forgejo owner or organization that will hold the GitOps repository"
  default     = "platform"
}

variable "populate_gitops_repo" {
  type        = string
  description = "Forgejo repository name used by Argo CD"
  default     = "gitops"
}

variable "populate_gitops_repo_description" {
  type        = string
  description = "Description for the bootstrap GitOps repository"
  default     = "Cluster GitOps repository"
}

variable "populate_gitops_repo_private" {
  type        = bool
  description = "Create the bootstrap GitOps repository as private"
  default     = true
}
