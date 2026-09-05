###
# Proxmox
###

variable "proxmox" {
  description = "Non-secret Proxmox connection, node, and datastore settings."
  type = object({
    endpoint        = string
    insecure        = optional(bool, false)
    node_name       = string
    vm_datastore    = string
    image_datastore = string
    ssh_username    = string
    vlan_id         = optional(number)
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

variable "environment_contract_path" {
  description = "Path to the materialized non-secret environment contract used for cluster networking."
  type        = string
  default     = "../out/homelab.effective.yaml"
}

variable "cluster_name" {
  description = "Optional Talos and Kubernetes cluster name override. Defaults to cluster.name in the environment contract, then talos-pve."
  type        = string
  default     = null
  nullable    = true
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
