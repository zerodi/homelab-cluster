# Talos on Proxmox VE via Terraform/OpenTofu

Репозиторий разворачивает Kubernetes-кластер на Talos поверх Proxmox и
доводит его до готового platform bootstrap.

## Greenfield deployment

### 1. Tooling

Минимальный toolchain описан в [docs/prerequisites.md](docs/prerequisites.md).

### 2. Bootstrap cluster

```bash
task init
cp terraform.tfvars.example terraform.tfvars
cp .env.example .env
task cluster:apply
task cluster:health
```

### 3. Bootstrap platform operators

```bash
task infra:apply
task infra:health
```

### 4. Day-0 OpenBao and GitOps

Инициализируйте и разлочьте OpenBao вручную, затем держите активным
port-forward из day-0 runbook:

```bash
task ops:day0-guide
task ops:openbao-port-forward-start
export BAO_TOKEN='...'
task ops:openbao-day0
task ops:seed-runtime-secrets
export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap
# создайте Forgejo OAuth application и S3 key, затем обновите OpenBao
task ops:openbao-runtime-preflight-final
task ops:post-argocd-check
task ops:openbao-port-forward-stop
```

`gitops:test-ssh-bootstrap` собирает локальный Git-over-SSH repository из
`argocd/`, запускает его в Docker и выполняет первичный Argo CD sync из него.
Если постоянный внешний Git repository уже доступен, используйте вместо этого
`task gitops:preflight` и `task gitops:apply-bootstrap`.

`seed-runtime-secrets` создаёт только отсутствующие OpenBao paths и не
перезаписывает существующие credentials. Временные Woodpecker OAuth и Velero S3
credentials замените реальными после создания соответствующих внешних
ресурсов. Они помечаются `bootstrap_provisional=true`: обычный GitOps preflight
разрешает bootstrap, а `openbao-runtime-preflight-final` требует их ротации.

`envs/homelab.override.yaml` — tracked environment-specific non-secret overlay
поверх `envs/homelab.yaml`. Task-команды используют их merged effective
contract.
Для обновления tracked GitOps mirrors выполните:

```bash
task sync-env-contract
```

`task gitops:preflight` проверяет:

- strict effective environment contract против `argocd/`
- required runtime secret paths и keys в `OpenBao`

## Validation

Локальный baseline:

```bash
task check:validate
```

Отдельные useful checks:

```bash
task check:cluster-isolation
task check:infrastructure-isolation
task check:chart-versions
task check:env-contract
task check:runtime-secret-contract
task ops:openbao-runtime-preflight
task ops:post-argocd-check
```

Все Helm chart pins задаются только в `versions.yaml`. После изменения файла
выполните `task sync-chart-versions`, чтобы обновить проверяемые
`targetRevision` mirrors в Argo CD Applications.

Если entrypoint ещё не инициализирован, для части локальных проверок сначала выполните:

```bash
task cluster:init -- -backend=false
task infra:init -- -backend=false
```

## Подробный runbook

- [Требования к окружению](docs/prerequisites.md)
- [Day-0 bootstrap](docs/day0-bootstrap.md)
- [Настройка и эксплуатация](docs/README.md)
