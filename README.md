# Talos on Proxmox VE via Terraform/OpenTofu

Репозиторий разворачивает Kubernetes-кластер на Talos поверх Proxmox и
доводит его до готового platform bootstrap.

## Архитектура

- `cluster/` создаёт Proxmox VM, Talos/Kubernetes, минимальный Cilium и локальные
  `kubeconfig`/`talosconfig`.
- `infrastructure/` доводит кластер до готовых platform operators, OpenBao,
  storage и Argo CD.
- `argocd/` содержит отдельный runtime/GitOps слой приложений.

Корень репозитория связывает entrypoint через Taskfile и общие environment и
version contracts, но сам не является OpenTofu entrypoint.

## Greenfield quick start

```bash
task init
cp terraform.tfvars.example terraform.tfvars
cp .env.example .env
task cluster:apply
task cluster:health
task infra:apply
task infra:health
```

Дальнейшие ручные init/unseal OpenBao, настройка runtime secrets и первичный
GitOps sync выполняются строго по [day-0 runbook](docs/day0-bootstrap.md).
Карта автоматизированных и ручных этапов находится в
[deployment map](docs/deployment-map.md).

## Validation

Локальный baseline:

```bash
task check:validate
```

Версии OpenTofu, providers, Talos Linux, Kubernetes, Helm charts и container
images задаются только в `versions.yaml`. После изменения файла выполните
`task sync-versions`, чтобы обновить статические OpenTofu/provider, CI и Argo CD
mirrors.

Если entrypoint ещё не инициализирован, для части локальных проверок сначала выполните:

```bash
task cluster:init -- -backend=false
task infra:init -- -backend=false
```

## Документация

- [Карта развёртывания и границы автоматизации](docs/deployment-map.md)
- [Day-0 bootstrap](docs/day0-bootstrap.md)
- [Environment contract](docs/environment-contract.md)
- [Runtime/GitOps слой](argocd/README.md)
- [Cloudflare DNS-01 и Cilium Gateway](docs/cloudflare-dns01.md)
- [Единая авторизация приложений платформы](docs/platform-authentication.md)
- [Настройка и эксплуатация](docs/README.md)
