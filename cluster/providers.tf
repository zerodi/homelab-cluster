provider "proxmox" {
  endpoint  = var.proxmox.endpoint
  api_token = local.effective_proxmox.api_token
  insecure  = var.proxmox.insecure
  ssh {
    agent    = true
    username = var.proxmox.ssh_username
  }
}

provider "talos" {}

provider "helm" {}

check "proxmox_api_token_configured" {
  assert {
    condition     = local.effective_proxmox.api_token != null && trimspace(local.effective_proxmox.api_token) != ""
    error_message = "Set proxmox_api_token via TF_VAR_proxmox_api_token or provide it from an encrypted SOPS tfvars file."
  }
}

check "cluster_ipv4_cidr_valid" {
  assert {
    condition = (
      can(cidrhost(local.cluster_ipv4_cidr, 250)) &&
      can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+/24$", local.cluster_ipv4_cidr)) &&
      try(cidrhost(local.cluster_ipv4_cidr, 0) == split("/", local.cluster_ipv4_cidr)[0], false)
    )
    error_message = "cluster.ipv4_cidr must be a canonical IPv4 /24 network."
  }
}
