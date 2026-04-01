# Talos on Proxmox VE via Terraform/OpenTofu

Репозиторий поднимает Kubernetes-кластер на Talos поверх Proxmox и доводит его до минимального platform bootstrap.

Текущая модель разделения слоёв:

- root: только `terraform.tfvars`, examples и документация
- `bootstrap/`: самостоятельный Terraform/OpenTofu entrypoint для Talos image, VM lifecycle, machine config, control plane bootstrap, локальных `kubeconfig` и `talosconfig`, базового Cilium bootstrap
- `infrastructure/`: отдельный Terraform/OpenTofu entrypoint для bootstrap-операторов и storage/bootstrap readiness внутри Kubernetes
- `argocd/`: runtime/GitOps scaffold для `authentik`, `forgejo`, `echo`, `ClusterSecretStore openbao` и app-of-apps bootstrap

Root больше не является Terraform/OpenTofu entrypoint.

## Что делает каждый слой

### Root

В корне репозитория остаются только:

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example)
- локальный [terraform.tfvars](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars)
- локальные `out/` артефакты и `.envrc`
- документация и вспомогательные команды

### `bootstrap/`

`bootstrap/` владеет только:

- скачиванием и импортом Talos image
- жизненным циклом VM в Proxmox
- Talos machine secrets и machine config
- bootstrap control plane
- локальными файлами `out/kubeconfig` и `out/talosconfig`
- базовым Cilium bootstrap, необходимым для старта кластера

Рабочий запуск идёт через `tofu -chdir=bootstrap ... -var-file=../terraform.tfvars`.

### `infrastructure/`

`infrastructure/` запускается отдельно и владеет только:

- `cert-manager`
- `trust-manager`
- `openbao`
- `external-secrets`
- `piraeus-operator` / LINSTOR bootstrap
- `argocd`
- bootstrap readiness chain для CRD, issuer, storage и ESO/OpenBao auth prerequisites

Этот entrypoint читает не-секретные bootstrap inputs из `bootstrap/terraform.tfstate` и использует локальный `out/kubeconfig`.

### `argocd/`

`argocd/` содержит runtime/GitOps manifests:

- `bootstrap/`: root `Application` и базовые `AppProject`
- `platform/`: `authentik`, `forgejo` и связанные prereqs/bootstrap manifests
- `apps/`: demo `echo`

Важно: это scaffold. По умолчанию там intentionally invalid `repoURL`, который нужно заменить перед использованием. Детали: [argocd/README.md](/home/zerodi/code/talos-proxmox-no-ssh/argocd/README.md)

## Secret Model

Целевая модель секретов:

- `OpenBao` — source of truth для runtime secrets
- `External Secrets Operator` — доставка runtime secrets в Kubernetes
- `SOPS/age` — только day-0 bootstrap секреты Terraform

Правила:

- runtime secrets не хранятся в repo
- runtime secrets не передаются через `terraform.tfvars`, `values.yaml` или app manifests
- bootstrap secrets Terraform передаются через `TF_VAR_*` или локальный SOPS-файл
- локальные bootstrap-артефакты (`out/`, `*.tfstate`, `*.auto.tfvars`) не должны попадать в git

## Как это работает

1. `bootstrap/` читает общие значения из root `terraform.tfvars`.
2. `bootstrap/` скачивает Talos image из Image Factory по `talos.version` и `talos.schematic_id`.
3. `bootstrap/` локально распаковывает образ и загружает его в Proxmox.
4. `bootstrap/` создаёт control plane и worker VM.
5. `bootstrap/` генерирует Talos secrets и machine config.
6. `bootstrap/` применяет конфигурацию на ноды и делает bootstrap первого control plane.
7. `bootstrap/` получает `kubeconfig` и `talosconfig` и пишет их в `out/`.
8. Отдельный `infrastructure/` entrypoint использует `out/kubeconfig` и `bootstrap/terraform.tfstate` для platform bootstrap.
9. `infrastructure/` поднимает `cert-manager`, `trust-manager`, `openbao`, `external-secrets`, `piraeus-operator` и опционально `argocd`.
10. LINSTOR device pools создаются отдельным операторским шагом вне Terraform graph.
11. После `OpenBao init/unseal` post-init day-0 настраивается операторским helper-скриптом, а runtime-слой разворачивается через ArgoCD manifests из `argocd/`, включая `ClusterSecretStore openbao`.

## Предпосылки

- Нужен `SSH`-доступ к Proxmox node, потому что `proxmox_virtual_environment_file` в `bpg/proxmox` использует SSH для upload/import операций.
- `SSH` к Talos-нодам не нужен.
- Нужен исходящий доступ к `factory.talos.dev`, потому что root сам скачивает Talos image.
- На машине с OpenTofu нужны `xz`, `curl` и рабочий `ssh-agent`.
- `talos.schematic_id` должен соответствовать вашему Talos Image Factory schematic.
- Сетевой inventory должен быть корректным: IP, MAC, `controlplane_vip`, `cilium_lb_pool_*`, а также `cidr` в defaults для control plane и worker.
- Для Piraeus нужен подготовленный raw block device на worker-нодах, например `/dev/sdb`.

## Переменные

Примеры лежат в:

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example)

Ключевые группы переменных в root `terraform.tfvars`:

- `proxmox`
- `proxmox_api_token`
- `talos`
- cluster/network: `cluster_endpoint`, `controlplane_vip`, `cilium_lb_pool_start`, `cilium_lb_pool_stop`
- nodes: `controlplane_node_defaults`, `controlplane_nodes`, `worker_node_defaults`, `worker_nodes`
- platform bootstrap settings, которые `bootstrap/` экспортирует в state для `infrastructure/`: `argocd_enabled`, `argocd_host`, `trust_manager_enabled`, `piraeus_*`

Минимальный обязательный набор для первого запуска:

- `proxmox.endpoint`
- `proxmox.node_name`
- `proxmox.vm_datastore`
- `proxmox.image_datastore`
- `talos.version`
- `talos.schematic_id`
- `controlplane_vip`
- `cilium_lb_pool_start`
- `cilium_lb_pool_stop`
- `controlplane_node_defaults`
- `controlplane_nodes`
- `worker_node_defaults`
- `worker_nodes`

## Развёртывание с нуля

Greenfield bootstrap состоит из четырёх фаз.

### 1. Инициализация

```bash
make init
cp terraform.tfvars.example terraform.tfvars
# заполните terraform.tfvars только несекретными значениями
```

`make init` инициализирует оба entrypoint:

- `bootstrap/`
- `infrastructure/`

Секреты Terraform передавайте отдельно.

Через переменные окружения:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!talos=...'
```

Через локальный SOPS-файл:

```bash
cp secrets.sops.tfvars.example secrets.sops.tfvars
sops -e -i secrets.sops.tfvars
sops -d secrets.sops.tfvars > secrets.auto.tfvars
```

### 2. Bootstrap кластера

```bash
make plan-cluster
make apply-cluster
```

Эквивалент напрямую:

```bash
tofu -chdir=bootstrap plan -var-file=../terraform.tfvars
tofu -chdir=bootstrap apply -var-file=../terraform.tfvars
```

После этого должны появиться:

- [`out/kubeconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/kubeconfig)
- [`out/talosconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/talosconfig)

### 3. Platform bootstrap

```bash
make plan-platform-bootstrap
make apply-platform-bootstrap
```

`infrastructure/` ожидает, что `bootstrap/terraform.tfstate` и `out/kubeconfig` уже существуют после cluster bootstrap.

`make plan-platform-bootstrap` теперь строит план только для первой стадии platform bootstrap, то есть для ресурсов, которые не требуют уже установленных CRD.

Эта фаза запускается из отдельного entrypoint `infrastructure/` и поднимает:

- `cert-manager`
- `openbao`
- `external-secrets`
- `trust-manager`
- `piraeus-operator`
- `argocd`, если `argocd_enabled = true`

`make apply-platform-bootstrap` теперь выполняет staged bootstrap:

1. устанавливает CRD-delivering releases (`cert-manager`, `external-secrets`, `trust-manager`, `piraeus-operator`) без CRD-backed manifests в graph
2. дожидается регистрации CRD в API discovery через `make wait-platform-crds`
3. применяет cert-manager и piraeus manifests только после появления CRD
4. вызывает отдельный helper для `kubectl linstor physical-storage create-device-pool`
5. завершает финальный `tofu -chdir=infrastructure apply`

### 4. Day-0 OpenBao bootstrap и GitOps

После platform bootstrap нужно вручную:

1. Инициализировать и разлочить `OpenBao`
2. Включить `KV v2` на `secret/`
3. Включить Kubernetes auth
4. Создать policy и role для `external-secrets`
5. Записать runtime secrets в `secret/platform/*`

Подсказка:

```bash
make day0-guide
```

После `OpenBao init/unseal` можно автоматизировать post-init настройку и GitOps bootstrap:

```bash
export BAO_TOKEN='...'
make openbao-day0
make apply-gitops-bootstrap
```

`make openbao-day0` не выполняет `bao operator init` и не хранит recovery material. Он только:

- включает `KV v2` на `secret/`
- включает и настраивает `auth/kubernetes`
- создаёт policy и role для `external-secrets`

`make apply-gitops-bootstrap` проверяет readiness `argocd`, валидирует отсутствие placeholder `repoURL` в `argocd/` и применяет root `Application`.

## Полезные команды

```bash
make init
make fmt
make validate
make plan-cluster
make apply-cluster
make plan-platform-bootstrap
make apply-platform-bootstrap
make from-scratch
```

`make from-scratch` выполняет:

- bootstrap кластера через `bootstrap/`
- platform bootstrap через `infrastructure/`
- вывод дальнейших day-0 шагов для `OpenBao`

Для teardown используйте:

```bash
make destroy-infrastructure
make destroy-bootstrap
```

`make destroy-infrastructure` теперь выполняет staged destroy: сначала удаляет CRD-backed manifests, пока CRD ещё доступны, затем дочищает state для уже пропавших CRD и завершает общий `tofu destroy -refresh=false`. Это нужно, чтобы teardown не падал на `Bundle`, `ClusterIssuer`, `Certificate` или `Linstor*`, если соответствующий оператор или его CRD уже были удалены.

## Документация

- [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)
- [docs/roadmap-terraform-vs-argocd.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/roadmap-terraform-vs-argocd.md)
- [argocd/README.md](/home/zerodi/code/talos-proxmox-no-ssh/argocd/README.md)
