---
name: talos-greenfield-bootstrap
description: Plan, implement, or review a greenfield Talos-on-Proxmox bootstrap in this repository. Use for changes to cluster/, infrastructure/, Talos VM or image lifecycle, Cilium bootstrap, platform operators, OpenBao day-0 setup, or the from-scratch task sequence; do not use for app-level runtime manifests under argocd/.
---

# Talos Greenfield Bootstrap

Treat an empty state and a new cluster as the default. Read `README.md` and
`docs/day0-bootstrap.md` before making significant changes.

## Classify ownership

- Put Talos images, Proxmox VMs, machine configuration, cluster bootstrap,
  `out/kubeconfig`, `out/talosconfig`, and minimum Cilium in `cluster/`.
- Put cert-manager, trust-manager, OpenBao, External Secrets Operator, Piraeus
  and LINSTOR bootstrap, Argo CD, and their readiness resources in
  `infrastructure/`.
- Keep application workloads and app-level GitOps resources in `argocd/`; use
  `$gitops-runtime-change` for those changes.
- Keep the repository root free of Terraform entrypoints.

If a change crosses a boundary, explain why and minimize the coupling before
editing. Never use `terraform_data` plus `local-exec` to own long-lived runtime
objects.

## Follow the bootstrap path

1. Inspect the relevant Taskfile tasks and existing dependency/readiness chain.
2. Preserve this order:
   `task cluster:apply` -> `task infra:apply` -> manual
   OpenBao init/unseal -> `task ops:openbao-day0` -> separate GitOps bootstrap.
3. Assume no existing namespaces, CRDs, secrets, or runtime resources unless a
   task explicitly concerns migration, recovery, or partial reconciliation.
4. Keep runtime secrets in OpenBao, delivered by ESO. Use SOPS/age only for
   day-0 Terraform secrets; never add runtime values to tfvars, examples,
   outputs, state, or Git-tracked values files.
5. Preserve CRD delivery before CRD-backed resources and preserve the Piraeus,
   OpenBao, ESO, and Argo CD readiness chain.

## Validate

Run the narrowest checks first, then the repository baseline when practical:

```bash
tofu -chdir=cluster fmt -check
tofu -chdir=infrastructure fmt -check
tofu -chdir=cluster validate
tofu -chdir=infrastructure validate
task check:validate
```

For bootstrap graph changes, also run the applicable plan task. Do not apply or
destroy live infrastructure unless the user explicitly requests it. Report
missing tools, credentials, initialized entrypoints, or cluster access instead
of claiming an unavailable check passed.
