---
name: diagnose-platform-readiness
description: Diagnose bootstrap, Kubernetes, platform-operator, storage, secret-delivery, or Argo CD readiness failures in this repository. Use for stuck applies, unhealthy pods, missing CRDs, Piraeus/LINSTOR issues, sealed OpenBao, ExternalSecret failures, Argo CD sync errors, or runtime dependency outages; default to read-only evidence gathering.
---

# Diagnose Platform Readiness

Diagnose without changing the cluster. Use the configured Kubernetes MCP for
read-only inspection when it is available; otherwise use read-only `task`,
`kubectl`, `talosctl`, and `tofu` commands.

## Establish the failed layer

Read `docs/deployment/day0-bootstrap.md` and
`docs/configuration/day1-operations.md` as needed. Then trace in order:

1. Proxmox VM and Talos node/API health.
2. Cilium networking and Kubernetes node readiness.
3. CRD-delivering releases: cert-manager, trust-manager, ESO, and Piraeus.
4. CRD-backed issuers, certificates, bundles, LINSTOR resources, and storage
   classes.
5. OpenBao initialized/unsealed state, Kubernetes auth, policy, and role.
6. ClusterSecretStore and ExternalSecret readiness without reading or printing
   secret values.
7. Argo CD controller/repository health, Application dependencies, sync waves,
   PVCs, routes, and workload events.

Start with repository helpers where they cover the layer:

```bash
task bootstrap:health
task infra:health
task check:env-contract
task ops:openbao-runtime-preflight
task ops:post-argocd-check
```

Run only commands whose prerequisites exist. Never expose Kubernetes Secret
data, OpenBao values, tokens, kubeconfigs, Talos configs, or Terraform-sensitive
outputs in the response.

## Report the diagnosis

Separate observed evidence from inference. Identify the earliest failed
dependency, explain downstream symptoms, and propose the smallest recovery or
code change in the owning layer. Do not implement a fix during a diagnosis-only
request. Require explicit authorization before apply, sync, rollout, unseal,
secret writes, state changes, deletion, or storage-device operations.
