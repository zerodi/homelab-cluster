---
name: gitops-runtime-change
description: Implement or review application and runtime GitOps changes in this repository. Use for argocd/ applications, Helm values, Kustomize resources, ExternalSecrets, namespaces, Gateway API routes, Authentik, Forgejo, Harbor, Woodpecker, observability, Velero, Kyverno, Garage, or echo; do not move these resources into cluster/ or infrastructure/.
---

# GitOps Runtime Change

Read `argocd/README.md` and the relevant sections of
`docs/day0-bootstrap.md`. For environment changes, also read
`docs/environment-contract.md` before a significant runtime change.

## Preserve runtime ownership

- Keep runtime applications, app namespaces, app-level ExternalSecrets,
  routing, certificates, policies, and Argo CD Applications under `argocd/`.
- Use `envs/homelab.yaml` plus optional `envs/homelab.override.yaml` only for
  non-secret environment contracts. Update all mapped consumers when changing
  hostnames, repository coordinates, storage names, chart pins, or runtime
  naming.
- Keep OpenBao as the runtime secret source of truth and ESO as delivery. Add
  only secret paths and key references to manifests; never add values to Git,
  tfvars, Terraform outputs, or `values.yaml`.
- Do not assume runtime namespaces or materialized Secrets already exist. Make
  prerequisites declarative and respect Argo CD sync ordering.
- Use `argocd/apps/echo` as the minimum workload baseline for resources,
  probes, security context, NetworkPolicy, namespaced Gateway, TLS, and routes.

## Check dependencies

Trace each changed app through:

1. namespace and Argo CD project/application ownership;
2. OpenBao path -> ExternalSecret -> materialized Secret;
3. database, cache, PVC, and LINSTOR storage prerequisites;
4. Gateway, DNS, Certificate, and HTTPRoute prerequisites;
5. OIDC or application-to-application dependencies;
6. sync waves and health ordering.

Keep manual operator steps manual when they handle recovery material, OAuth app
creation, data migration, Garage layout, or destructive storage operations.

## Validate

Run checks relevant to the changed subtree:

```bash
task check:env-contract
task check:kustomize-bootstrap
task check:kustomize-platform
task check:yamllint
```

Before a real GitOps bootstrap, use `task gitops:preflight`; it requires valid
environment values and may require OpenBao access. Use
`task ops:post-argocd-check` only when cluster access exists. Do not sync or
mutate a live cluster unless the user requests it.
