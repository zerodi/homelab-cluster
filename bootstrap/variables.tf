###
# Proxmox variables
###
variable "proxmox" {
  description = "Base proxmox configuration"
  type = object({
    endpoint        = string
    api_token       = optional(string)
    insecure        = optional(bool, true)
    node_name       = string
    vm_datastore    = string
    image_datastore = string
    ssh_username    = string

  })
}

variable "proxmox_api_token" {
  type        = string
  description = "Sensitive Proxmox API token. Prefer TF_VAR_proxmox_api_token or an encrypted SOPS tfvars file over terraform.tfvars."
  default     = null
  nullable    = true
  sensitive   = true
}

###
# Nodes variables
###
variable "node_prefix" {
  type    = string
  default = "talos"
}

variable "controlplane_node_defaults" {
  description = "Shared hardware and network settings for all control plane nodes."
  type = object({
    cpu_cores = number
    memory_mb = number
    disk_gb   = number
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
    additional_disk_gb = number
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

###
# Talos variables
###
variable "talos_version" {
  description = "Talos release version. Must include the `v` prefix, for example `v1.12.6`."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+$", var.talos_version))
    error_message = "talos_version must be a Talos release in the form `v1.12.6` with the required `v` prefix."
  }
}

variable "talos_schematic_id" {
  description = "Talos Image Factory schematic ID used to build/download installer artifacts."
  type        = string
  default     = null
  nullable    = true
}

###
# Cluster variables
###
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

###
# Cilium variables
###
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

variable "talosconfig_file_path" {
  type        = string
  description = "Path to write talosconfig"
  default     = "../out/talosconfig"
}

variable "kubeconfig_file_path" {
  type        = string
  description = "Path to write kubeconfig"
  default     = "../out/kubeconfig"
}
