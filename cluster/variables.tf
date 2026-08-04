###
# Proxmox
###

variable "proxmox" {
  description = "Non-secret Proxmox connection, node, and datastore settings."
  type = object({
    endpoint        = string
    insecure        = optional(bool, true)
    node_name       = string
    vm_datastore    = string
    image_datastore = string
    ssh_username    = string
  })
}

variable "proxmox_api_token" {
  description = "Sensitive Proxmox API token. Set it through TF_VAR_proxmox_api_token or an encrypted SOPS tfvars file."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true
}

###
# Talos cluster
###

variable "cluster_name" {
  description = "Talos and Kubernetes cluster name."
  type        = string
  default     = "talos-pve"
}

variable "talos_schematic_id" {
  description = "Talos Image Factory schematic ID used to download the installer image."
  type        = string
}

variable "cluster_endpoint" {
  description = "Optional Kubernetes API URL. When unset, it is derived from the generated control plane VIP."
  type        = string
  default     = null
  nullable    = true
}

variable "cluster_health_check_timeout" {
  description = "Timeout used by talos_cluster_health after bootstrap."
  type        = string
  default     = "20m"
}

###
# VM inventory
###

variable "node_prefix" {
  description = "Prefix added to Proxmox VM names."
  type        = string
  default     = "talos"
}

variable "cluster_ipv4_cidr" {
  description = "IPv4 /24 subnet used to derive the gateway, node addresses, control plane VIP, and Cilium LoadBalancer pool."
  type        = string

  validation {
    condition = (
      can(cidrhost(var.cluster_ipv4_cidr, 250)) &&
      can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/24$", var.cluster_ipv4_cidr)) &&
      try(cidrhost(var.cluster_ipv4_cidr, 0) == split("/", var.cluster_ipv4_cidr)[0], false)
    )
    error_message = "cluster_ipv4_cidr must be a canonical IPv4 /24 network, for example 192.168.100.0/24."
  }
}

variable "controlplane_node_defaults" {
  description = "Shared hardware settings for control plane VMs."
  type = object({
    cpu_cores = number
    memory_mb = number
    disk_gb   = number
  })
}

variable "controlplane_nodes" {
  description = "Number of control plane VMs. Node identity and addressing are generated deterministically."
  type        = number

  validation {
    condition     = var.controlplane_nodes >= 1 && var.controlplane_nodes <= 89 && floor(var.controlplane_nodes) == var.controlplane_nodes
    error_message = "controlplane_nodes must be an integer from 1 to 89."
  }
}

variable "worker_node_defaults" {
  description = "Shared hardware settings for worker VMs."
  type = object({
    cpu_cores          = number
    memory_mb          = number
    disk_gb            = number
    additional_disk_gb = number
  })
}

variable "worker_nodes" {
  description = "Number of worker VMs. Node identity and addressing are generated deterministically."
  type        = number

  validation {
    condition     = var.worker_nodes >= 1 && var.worker_nodes <= 99 && floor(var.worker_nodes) == var.worker_nodes
    error_message = "worker_nodes must be an integer from 1 to 99."
  }
}

###
# Cilium bootstrap
###

variable "cilium_interface" {
  description = "Talos network interface used by Cilium and the control plane VIP."
  type        = string
  default     = "eth0"
}

###
# Local bootstrap artifacts
###

variable "talosconfig_file_path" {
  description = "Path where bootstrap writes talosconfig."
  type        = string
  default     = "../out/talosconfig"
}

variable "kubeconfig_file_path" {
  description = "Path where bootstrap writes kubeconfig."
  type        = string
  default     = "../out/kubeconfig"
}
