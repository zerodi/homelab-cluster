terraform {
  required_version = ">= 1.6.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.98"
    }
    talos = {
      source  = "siderolabs/talos"
      version = "~> 0.10"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox.endpoint
  api_token = local.effective_proxmox.api_token
  insecure  = var.proxmox.insecure
  ssh {
    agent    = true
    username = "terraform"
  }
}

provider "talos" {}

provider "kubernetes" {
  config_path = var.kubeconfig_file_path
}

provider "helm" {}

provider "helm" {
  alias = "cluster"

  kubernetes = {
    config_path = var.kubeconfig_file_path
  }
}

check "proxmox_api_token_configured" {
  assert {
    condition     = local.effective_proxmox.api_token != null && trimspace(local.effective_proxmox.api_token) != ""
    error_message = "Set proxmox_api_token via TF_VAR_proxmox_api_token or provide it from an encrypted SOPS tfvars file. proxmox.api_token is kept only as a backward-compatible fallback."
  }
}
