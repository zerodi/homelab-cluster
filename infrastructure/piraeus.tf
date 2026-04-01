locals {
  piraeus_storage_class_name = "linstor-${local.effective_piraeus_storage_pool_name}-r${local.effective_piraeus_replica_count}"
}

resource "kubernetes_namespace_v1" "piraeus" {
  metadata {
    name = local.effective_piraeus_namespace
  }
}

resource "kubernetes_labels" "piraeus_namespace_pod_security" {
  api_version = "v1"
  kind        = "Namespace"

  metadata {
    name = local.effective_piraeus_namespace
  }

  force = true

  labels = {
    "pod-security.kubernetes.io/enforce" = "privileged"
    "pod-security.kubernetes.io/audit"   = "privileged"
    "pod-security.kubernetes.io/warn"    = "privileged"
  }

  depends_on = [kubernetes_namespace_v1.piraeus]
}

resource "helm_release" "piraeus_operator" {
  name             = "piraeus-operator"
  namespace        = local.effective_piraeus_namespace
  create_namespace = false

  repository = "oci://ghcr.io/piraeusdatastore/piraeus-operator"
  chart      = "piraeus"
  version    = "2.10.4"

  timeout = 900
  wait    = true

  set = [
    {
      name  = "installCRDs"
      value = "true"
    }
  ]

  depends_on = [
    kubernetes_namespace_v1.piraeus,
    kubernetes_labels.piraeus_namespace_pod_security,
  ]
}

resource "terraform_data" "piraeus_operator_ready" {
  triggers_replace = [
    helm_release.piraeus_operator.id,
    local.effective_kubeconfig_path,
    local.effective_piraeus_namespace,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local.effective_kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl wait pod --timeout=15m --for=condition=Ready -n "${local.effective_piraeus_namespace}" -l app.kubernetes.io/component=piraeus-operator
      until kubectl -n "${local.effective_piraeus_namespace}" get endpoints piraeus-operator-webhook-service -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null | grep -q .; do
        sleep 5
      done
    EOT
  }
}

resource "kubernetes_manifest" "linstor_satellite_configuration_talos" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "piraeus.io/v1"
    kind       = "LinstorSatelliteConfiguration"
    metadata = {
      name = "talos-loader-override"
    }
    spec = {
      podTemplate = {
        spec = {
          initContainers = [
            {
              name     = "drbd-shutdown-guard"
              "$patch" = "delete"
            },
            {
              name     = "drbd-module-loader"
              "$patch" = "delete"
            },
          ]
          volumes = [
            {
              name     = "run-systemd-system"
              "$patch" = "delete"
            },
            {
              name     = "run-drbd-shutdown-guard"
              "$patch" = "delete"
            },
            {
              name     = "systemd-bus-socket"
              "$patch" = "delete"
            },
            {
              name     = "lib-modules"
              "$patch" = "delete"
            },
            {
              name     = "usr-src"
              "$patch" = "delete"
            },
            {
              name = "etc-lvm-backup"
              hostPath = {
                path = "/var/etc/lvm/backup"
                type = "DirectoryOrCreate"
              }
            },
            {
              name = "etc-lvm-archive"
              hostPath = {
                path = "/var/etc/lvm/archive"
                type = "DirectoryOrCreate"
              }
            },
          ]
        }
      }
    }
  }

  depends_on = [terraform_data.piraeus_operator_ready]
}

resource "kubernetes_manifest" "linstor_cluster" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  manifest = {
    apiVersion = "piraeus.io/v1"
    kind       = "LinstorCluster"
    metadata = {
      name = "linstor"
    }
    spec = {}
  }

  depends_on = [kubernetes_manifest.linstor_satellite_configuration_talos]
}

resource "terraform_data" "linstor_cluster_ready" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  triggers_replace = [
    kubernetes_manifest.linstor_cluster[0].object.metadata.uid,
    local.effective_kubeconfig_path,
    local.effective_piraeus_namespace,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local.effective_kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl wait pod --timeout=15m --for=condition=Ready -n "${local.effective_piraeus_namespace}" -l app.kubernetes.io/name=piraeus-datastore
      kubectl wait --timeout=15m -n "${local.effective_piraeus_namespace}" --for=condition=Available linstorcluster/linstor
    EOT
  }

  depends_on = [kubernetes_manifest.linstor_cluster]
}

resource "terraform_data" "linstor_csi_ready" {
  count = var.crd_backed_resources_enabled ? 1 : 0

  triggers_replace = [
    terraform_data.linstor_cluster_ready[0].id,
    local.effective_kubeconfig_path,
    local.effective_piraeus_namespace,
    local.effective_piraeus_storage_pool_name,
  ]

  lifecycle {
    precondition {
      condition     = length(local.effective_piraeus_storage_nodes) > 0
      error_message = "Piraeus bootstrap requires at least one storage node. Set piraeus_storage_nodes explicitly or run infrastructure after the root bootstrap state is present."
    }
  }

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local.effective_kubeconfig_path
    }

    command = <<-EOT
      set -eu
      kubectl wait pod --timeout=15m --for=condition=Ready -n "${local.effective_piraeus_namespace}" -l app.kubernetes.io/component=linstor-controller
      kubectl wait pod --timeout=15m --for=condition=Ready -n "${local.effective_piraeus_namespace}" -l app.kubernetes.io/component=linstor-csi-controller
      kubectl wait pod --timeout=15m --for=condition=Ready -n "${local.effective_piraeus_namespace}" -l app.kubernetes.io/component=linstor-csi-node

      for node in ${join(" ", local.effective_piraeus_storage_nodes)}; do
        until kubectl linstor storage-pool list --node "$node" --storage-pool "${local.effective_piraeus_storage_pool_name}" 2>/dev/null | grep -q "${local.effective_piraeus_storage_pool_name}"; do
          sleep 5
        done
      done
    EOT
  }

  depends_on = [terraform_data.linstor_cluster_ready]
}

resource "kubernetes_storage_class_v1" "piraeus_replicated" {
  metadata {
    name = local.piraeus_storage_class_name
  }

  storage_provisioner    = "linstor.csi.linbit.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "Immediate"
  allow_volume_expansion = true

  parameters = {
    "csi.storage.k8s.io/fstype"          = "xfs"
    "linstor.csi.linbit.com/autoPlace"   = tostring(local.effective_piraeus_replica_count)
    "linstor.csi.linbit.com/storagePool" = local.effective_piraeus_storage_pool_name
  }

  depends_on = [terraform_data.linstor_csi_ready]
}
