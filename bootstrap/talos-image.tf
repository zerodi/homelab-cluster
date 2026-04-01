locals {
  platform              = "nocloud"
  arch                  = "amd64"
  talos_image_url       = "https://factory.talos.dev/image/${var.talos.schematic_id}/${var.talos.version}/${local.platform}-${local.arch}.raw.xz"
  talos_image_path      = "${path.root}/../out/talos-${var.talos.schematic_id}-${var.talos.version}-${local.platform}-${local.arch}.raw"
  talos_image_file_name = "talos-${var.talos.version}-${local.platform}-${local.arch}.img"
}

resource "terraform_data" "talos_image_download" {
  triggers_replace = [
    local.talos_image_url,
    local.talos_image_path,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      set -eu
      mkdir -p "$(dirname "${local.talos_image_path}")"
      tmp_file="${local.talos_image_path}.xz.tmp"
      curl -fL --retry 5 --retry-delay 2 "${local.talos_image_url}" -o "$tmp_file"
      xz -dc "$tmp_file" > "${local.talos_image_path}.tmp"
      mv "${local.talos_image_path}.tmp" "${local.talos_image_path}"
      rm -f "$tmp_file"
    EOT
  }
}

resource "proxmox_virtual_environment_file" "talos_image" {
  content_type = "iso"
  datastore_id = var.proxmox.image_datastore
  node_name    = var.proxmox.node_name

  depends_on = [terraform_data.talos_image_download]

  source_file {
    path      = local.talos_image_path
    file_name = local.talos_image_file_name
  }
}
