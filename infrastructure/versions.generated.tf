# Generated from ../versions.yaml by `task sync-versions` (homelabctl).
# Do not edit directly; run `task sync-versions`.

terraform {
  required_version = ">= 1.10.6"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "3.2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "3.2.1"
    }
  }
}
