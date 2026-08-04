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
