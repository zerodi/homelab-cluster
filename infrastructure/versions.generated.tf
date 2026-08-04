# Generated from ../versions.yaml by scripts/check-release-versions.py.
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
