# Talos on Proxmox VE via Terraform/OpenTofu

Репозиторий поднимает Kubernetes-кластер на Talos поверх Proxmox и доводит его до минимального platform bootstrap.

## Architecture

Слои разделены жёстко:

- `bootstrap/`
  отвечает за Talos image import, VM lifecycle, machine config/secrets, control plane bootstrap, локальные `out/kubeconfig` и `out/talosconfig`, минимальный Cilium bootstrap
- `infrastructure/`
  отвечает за bootstrap operators и readiness chain: `cert-manager`, `trust-manager`, `openbao`, `external-secrets`, `piraeus-operator`, `argocd`
- `argocd/`
  отвечает за runtime/GitOps manifests: `authentik`, `forgejo`, `harbor`, `woodpecker`, `garage`, observability stack, `velero`, `kyverno`, demo `echo`
- root
  не является Terraform/OpenTofu entrypoint и хранит только examples, `envs/homelab.yaml` и документацию

## Secret Model

- `OpenBao` это source of truth для runtime secrets
- `External Secrets Operator` доставляет runtime secrets в Kubernetes
- `SOPS/age` используется только для day-0 Terraform secrets
- runtime secrets не должны попадать в git, `terraform.tfvars`, `values.yaml` или Terraform state

## Quick Start

### 1. Tooling

Минимальный toolchain описан в [docs/prerequisites.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/prerequisites.md).

### 2. Bootstrap cluster

```bash
task init
cp terraform.tfvars.example terraform.tfvars
task bootstrap:apply-cluster
task bootstrap:health
```

### 3. Bootstrap platform operators

```bash
task infra:apply-bootstrap
task infra:health
```

### 4. Day-0 OpenBao and GitOps

```bash
task ops:day0-guide
export BAO_TOKEN='...'
task ops:openbao-day0
task gitops:preflight
task gitops:apply-bootstrap
task ops:post-argocd-check
```

`task gitops:preflight` проверяет:

- strict environment contract против `envs/homelab.yaml` и `argocd/`
- required runtime secret paths и keys в `OpenBao`

## Validation

Локальный baseline:

```bash
task check:validate
```

Отдельные useful checks:

```bash
task check:bootstrap-isolation
task check:env-contract
task ops:openbao-runtime-preflight
task ops:post-argocd-check
```

Если entrypoint ещё не инициализирован, для части локальных проверок сначала выполните:

```bash
task bootstrap:init -- -backend=false
task infra:init -- -backend=false
```

## Teardown

```bash
task infra:destroy
task bootstrap:destroy
```

`task infra:destroy` выполняет staged destroy, чтобы teardown не падал на CRD-backed resources после удаления операторов.

## Key Files

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example)
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/README.md](/home/zerodi/code/talos-proxmox-no-ssh/argocd/README.md)

## Docs

- [docs/prerequisites.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/prerequisites.md)
- [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)
- [docs/day1-operations.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day1-operations.md)
- [docs/environment-contract.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/environment-contract.md)
- [docs/runtime-dependency-matrix.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/runtime-dependency-matrix.md)
- [docs/runtime-recovery-boundaries.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/runtime-recovery-boundaries.md)
- [docs/backup-restore.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/backup-restore.md)
- [docs/kyverno-policies.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/kyverno-policies.md)

## To Add
Stalwart - https://stalw.art/
