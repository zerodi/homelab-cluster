# Generated from ../versions.yaml by scripts/check-release-versions.py.
# Do not edit directly; run `task sync-versions`.

terraform {
  required_version = ">= 1.10.6"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.111.1"
    }
    talos = {
      source  = "siderolabs/talos"
      version = "0.11.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "3.2.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "2.9.0"
    }
  }
}
