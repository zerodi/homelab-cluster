resource "terraform_data" "argocd_repo_creds_external_secret" {
  triggers_replace = [
    var.kubeconfig_path,
    var.argocd_namespace,
    var.project_name,
    var.repo_base_url,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      cat <<'EOF' | kubectl apply -f -
      apiVersion: external-secrets.io/v1
      kind: ExternalSecret
      metadata:
        name: ${var.project_name}-repo-creds
        namespace: ${var.argocd_namespace}
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: ClusterSecretStore
          name: openbao
        target:
          name: ${var.project_name}-repo-creds
          creationPolicy: Owner
          template:
            metadata:
              labels:
                argocd.argoproj.io/secret-type: repo-creds
            data:
              url: ${var.repo_base_url}
              type: git
              insecure: "${startswith(var.repo_base_url, "http://") ? "true" : "false"}"
        data:
          - secretKey: username
            remoteRef:
              key: platform/forgejo/admin
              property: username
          - secretKey: password
            remoteRef:
              key: platform/forgejo/admin
              property: password
      EOF
    EOT
  }
}

resource "terraform_data" "argocd_repository_external_secret" {
  triggers_replace = [
    var.kubeconfig_path,
    var.argocd_namespace,
    var.project_name,
    var.repo_url,
    var.gitops_owner,
    var.gitops_repo,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      cat <<'EOF' | kubectl apply -f -
      apiVersion: external-secrets.io/v1
      kind: ExternalSecret
      metadata:
        name: ${var.project_name}-repository
        namespace: ${var.argocd_namespace}
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: ClusterSecretStore
          name: openbao
        target:
          name: ${var.project_name}-repository
          creationPolicy: Owner
          template:
            metadata:
              labels:
                argocd.argoproj.io/secret-type: repository
            data:
              name: ${var.gitops_owner}-${var.gitops_repo}
              project: ${var.project_name}
              type: git
              url: ${var.repo_url}
              insecure: "${startswith(var.repo_url, "http://") ? "true" : "false"}"
        data:
          - secretKey: username
            remoteRef:
              key: platform/forgejo/admin
              property: username
          - secretKey: password
            remoteRef:
              key: platform/forgejo/admin
              property: password
      EOF
    EOT
  }
}

resource "kubernetes_secret_v1" "target_cluster" {
  count = var.cluster_bearer_token != null ? 1 : 0

  metadata {
    name      = "${var.cluster_name}-cluster"
    namespace = var.argocd_namespace
    labels = {
      "argocd.argoproj.io/secret-type" = "cluster"
    }
  }

  data = {
    name   = var.cluster_name
    server = var.cluster_server
    config = jsonencode({
      bearerToken = var.cluster_bearer_token
      tlsClientConfig = {
        insecure = false
      }
    })
  }
}

resource "terraform_data" "project_platform" {
  triggers_replace = [
    var.kubeconfig_path,
    var.argocd_namespace,
    var.project_name,
    var.project_description,
    var.repo_base_url,
    var.repo_url,
    var.cluster_server,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = var.kubeconfig_path
    }

    command = <<-EOT
      set -eu
      cat <<'EOF' | kubectl apply -f -
      apiVersion: argoproj.io/v1alpha1
      kind: AppProject
      metadata:
        name: ${var.project_name}
        namespace: ${var.argocd_namespace}
      spec:
        description: ${var.project_description}
        sourceRepos:
          - ${var.repo_base_url}/*
          - ${var.repo_url}
        destinations:
          - namespace: "*"
            server: ${var.cluster_server}
        clusterResourceWhitelist:
          - group: "*"
            kind: "*"
        namespaceResourceWhitelist:
          - group: "*"
            kind: "*"
      EOF
    EOT
  }
}
