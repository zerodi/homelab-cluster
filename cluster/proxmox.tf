resource "proxmox_virtual_environment_vm" "node" {
  for_each = local.all_nodes

  name            = "${var.node_prefix}-${each.key}"
  description     = "Managed by Terraform/OpenTofu - Talos ${each.value.machine_type}"
  tags            = ["terraform", "talos", "kubernetes", each.value.machine_type]
  node_name       = var.proxmox.node_name
  vm_id           = each.value.vm_id
  machine         = "q35"
  bios            = "ovmf"
  scsi_hardware   = "virtio-scsi-single"
  on_boot         = true
  started         = true
  stop_on_destroy = true
  boot_order      = ["scsi0"]

  operating_system {
    type = "l26"
  }

  agent {
    enabled = true
    trim    = true
  }

  cpu {
    cores = each.value.cpu_cores
    type  = "host"
  }

  memory {
    dedicated = each.value.memory_mb
    floating  = 0
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = each.value.mac_address
    vlan_id     = 110
  }

  efi_disk {
    datastore_id = var.proxmox.vm_datastore
    file_format  = "raw"
    type         = "4m"
  }

  disk {
    datastore_id = var.proxmox.vm_datastore
    interface    = "scsi0"
    cache        = "writethrough"
    size         = each.value.disk_gb
    file_format  = "raw"
    discard      = "on"
    ssd          = true
    file_id      = proxmox_virtual_environment_file.talos_image.id
  }

  dynamic "disk" {
    for_each = each.value.machine_type == "worker" ? ["apply"] : []

    content {
      datastore_id = var.proxmox.vm_datastore
      interface    = "scsi1"
      size         = each.value.additional_disk_gb
      discard      = "on"
      file_format  = "raw"
      cache        = "writethrough"
      ssd          = true
      backup       = false
    }
  }

  initialization {
    ip_config {
      ipv4 {
        address = "${each.value.ip}/${local.network_prefix_length}"
        gateway = local.gateway
      }
    }
  }

  serial_device {}
}
