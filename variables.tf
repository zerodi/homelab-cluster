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
    version      = string
    schematic_id = string
  })

  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+$", var.talos.version))
    error_message = "talos.version must be a Talos release in the form `v1.12.6` with the required `v` prefix."
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
  description = "Write talosconfig and kubeconfig to local files required by the bootstrap-only root entrypoint"
  default     = true

  validation {
    condition     = var.write_configs_to_files
    error_message = "bootstrap-only root entrypoint requires write_configs_to_files = true because infrastructure uses the local kubeconfig file."
  }
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

# Platform bootstrap
variable "argocd_enabled" {
  type        = bool
  description = "Deploy Argo CD into the bootstrap platform layer"
  default     = false
}

variable "argocd_host" {
  type        = string
  description = "Ingress hostname for Argo CD"
  default     = "argocd.home.arpa"
}

variable "trust_manager_enabled" {
  type        = bool
  description = "Deploy trust-manager and distribute the internal CA bundle into bootstrap namespaces"
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

variable "piraeus_replica_count" {
  type    = number
  default = 2
}
