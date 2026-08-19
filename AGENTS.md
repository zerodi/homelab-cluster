# AGENTS

## Scope

This file defines the working rules for agent-driven changes in the
`talos-proxmox-no-ssh` repository.

Always assume that the cluster is being created from scratch by default.
Unless a task explicitly says otherwise, target a greenfield bootstrap rather
than a migration of an existing live cluster.

## Current Architecture

The project is currently split into the following layers:

- repository root: shared orchestration, environment and version contracts,
  `terraform.tfvars`, `terraform.tfvars.example`,
  `secrets.sops.tfvars.example`, and shared documentation; it is not a
  Terraform/OpenTofu entrypoint
- `cluster/`: a standalone Terraform/OpenTofu entrypoint for Proxmox VMs, the
  Talos image, Talos machine configuration, cluster bootstrap, and local
  `kubeconfig` and `talosconfig` files
- `infrastructure/`: a separate Terraform/OpenTofu entrypoint for the minimal
  in-cluster platform bootstrap
- `argocd/`: a separate runtime/GitOps scaffold that is not connected to a
  Terraform entrypoint
- `homelabctl/`: a standalone Python project for repository-local automation,
  invoked by the root Taskfile

Do not move runtime resources back into `cluster/` or `infrastructure/`.
Application workloads and app-level GitOps bootstrap resources live outside
the Terraform bootstrap entrypoints.

## Ownership Rules

`cluster/` owns only:

- Talos image download and import
- Proxmox VM lifecycle
- Talos machine secrets and configuration
- control plane bootstrap
- `kubeconfig` and `talosconfig` files in `out/`
- the minimum Cilium bootstrap required to start the cluster

`infrastructure/` owns only:

- `cert-manager`
- `trust-manager`
- `openbao`
- `external-secrets`
- `piraeus-operator` and LINSTOR bootstrap
- `argocd`
- bootstrap readiness for CRDs, issuers, storage, and secret stores

`argocd/` owns only the runtime layer:

- application workloads such as `echo`, `authentik`, `forgejo`, `harbor`,
  `woodpecker`, `stalwart`, and observability components
- app-level `ExternalSecret` resources
- runtime-related GitOps bootstrap objects
- app namespace labels and similar runtime wiring
- runtime routing, policies, storage declarations, and application dependencies

## Default Working Assumption

Unless a task requires state migration, recovery, or partial reconciliation,
the agent must:

1. Assume a first bootstrap from an empty state.
2. Prefer the clean bootstrap path:
   - `task cluster:apply`
   - `task infra:apply`
   - then run `argocd/` separately when the task concerns runtime resources
3. Do not design the solution around pre-existing runtime resources.

If a task does concern migration of existing state, explicitly record that in
both the response and the changes.

## What Not To Do

Do not do any of the following without an explicit request:

- connect `argocd/` back to a Terraform bootstrap entrypoint
- move runtime resources back into `infrastructure/`
- add app-level manifests to the `default` namespace as part of the bootstrap
  baseline
- store runtime secrets in `terraform.tfvars`, outputs, `values.yaml`, or the
  repository
- assume existing namespaces, CRDs, or secrets are available unless the
  bootstrap contract guarantees them
- use destructive Git commands to discard changes made by others

## Secret Model

Always follow this model:

- `OpenBao` is the source of truth for runtime secrets.
- `External Secrets Operator` delivers runtime secrets to Kubernetes.
- `SOPS/age` is used only for day-0 Terraform bootstrap secrets.
- Root tfvars and examples must not become a source of truth for runtime
  secrets.

Do not add new runtime secrets to the root `terraform.tfvars.example`,
`secrets.sops.tfvars.example`, or runtime manifests.

## Change Strategy

Before making a change, identify its ownership layer:

- Changes to VMs, Talos, bootstrap networking, or `out/` artifacts belong in
  `cluster/`.
- Changes required to reach `Argo CD + OpenBao + ESO + Storage ready` belong in
  `infrastructure/`.
- Changes to applications or app-level manifests belong in `argocd/`.

If a change crosses a layer boundary, explain why before editing and minimize
the coupling.

## Validation Expectations

Run the checks for each changed Terraform/OpenTofu entrypoint:

- `tofu -chdir=cluster fmt -check` and/or
  `tofu -chdir=infrastructure fmt -check`
- `tofu -chdir=cluster validate` and/or
  `tofu -chdir=infrastructure validate`
- the applicable plan task when the change affects the bootstrap path

Run `task check:validate` as the repository baseline when practical.

When only `argocd/` changes, validate it separately in its own entrypoint or
context.

If `tofu` or an accessible cluster is unavailable locally, explicitly state
which validation was not run.

## Review Priority

During audits and reviews, look for these issues first:

- runtime resources leaking back into `cluster/` or `infrastructure/`
- bootstrap depending on pre-existing state
- secrets stored outside the `OpenBao/ESO/SOPS` model
- `terraform_data` plus `local-exec` creating long-lived runtime objects
- unnecessary baseline resources in the `default` namespace
- gaps in the readiness chain for `Piraeus`, `OpenBao`, `ESO`, or `Argo CD`

## Reference Docs

Before significant changes, consult:

- `README.md`
- `docs/day0-bootstrap.md`

If the code and documentation disagree, first restore the ownership boundary in
code, then update the documentation to match.
