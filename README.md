# Talos on Proxmox VE via Terraform/OpenTofu

Этот репозиторий поднимает Kubernetes-кластер на Talos поверх Proxmox и разворачивает минимальный platform bootstrap внутри самого кластера.

Что входит сейчас в root entrypoint:

- Proxmox управляется через `bpg/proxmox`
- Talos стартует из автоматически скачанного `nocloud-amd64.raw.xz` из Talos Image Factory
- machine config применяется через `siderolabs/talos`
- Terraform пишет `kubeconfig` и `talosconfig` в `out/`
- внутри кластера разворачиваются только bootstrap-компоненты:
  - `cert-manager`
  - `trust-manager`
  - `openbao`
  - `external-secrets`
  - `piraeus-operator` / LINSTOR
  - `argocd`

Runtime-слой вынесен отдельно в [gitops/](/home/zerodi/code/talos-proxmox-no-ssh/gitops).
Там находятся `echo`, `authentik`, `forgejo` и текущий GitOps bootstrap.

Важно:

- `SSH` к Talos не используется
- `SSH` к Proxmox node нужен провайдеру `bpg/proxmox` для `proxmox_virtual_environment_file`

## Secret Model

Целевая модель секретов:

- `OpenBao` — source of truth для runtime secrets
- `External Secrets Operator` — sync в Kubernetes
- `SOPS/age` — только day-0 bootstrap

Правила:

- runtime secrets не хранятся в repo
- runtime secrets не передаются через `values.yaml` и `tfvars`
- runtime secrets и runtime outputs не отдаются через Terraform root entrypoint
- terraform bootstrap secrets передаются через `TF_VAR_*` или локальный `SOPS`-файл, а не через обычный `terraform.tfvars`
- локальные bootstrap-артефакты `out/` и скачанные Talos-образы не должны попадать в git

Подробный day-0 runbook: [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)
Roadmap Terraform vs ArgoCD: [docs/roadmap-terraform-vs-argocd.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/roadmap-terraform-vs-argocd.md)

## Структура

Запуск идёт из корня репозитория:

- root-модуль хранит `providers`, общие `variables` и `outputs`
- `bootstrap/` создаёт Talos-кластер
- `infrastructure/` ставит bootstrap-операторы и базовые cluster services поверх Kubernetes API
- `gitops/` содержит отдельный runtime/GitOps модуль и не подключён к текущему root entrypoint
- `docs/day0-bootstrap.md` описывает развёртывание с нуля

Главная точка входа: [main.tf](/home/zerodi/code/talos-proxmox-no-ssh/main.tf)

## Как это работает

1. Terraform скачивает Talos `nocloud-amd64.raw.xz` из Image Factory по `talos.version` и `talos.schematic_id`.
2. Terraform локально распаковывает образ в `raw`.
3. Terraform загружает этот образ в Proxmox.
4. Создаются control plane и worker VM.
5. Talos provider генерирует secrets и machine configuration.
6. Конфиг применяется на ноды ресурсом `talos_machine_configuration_apply`.
7. Выполняется bootstrap первого control plane.
8. Terraform получает `kubeconfig` и `talosconfig`.
9. Через `infrastructure/` ставятся bootstrap-операторы и базовые CRD.
10. `cert-manager` поднимает внутренний CA `homelab-ca`, `trust-manager` распространяет CA bundle по bootstrap namespace'ам, а `OpenBao` и `External Secrets Operator` готовят secret bootstrap-контур.

## Предпосылки

- Нужен `SSH`-доступ к Proxmox node, потому что `proxmox_virtual_environment_file` в `bpg/proxmox` использует SSH для upload/import операций.
- Proxmox storage `proxmox.vm_datastore` должен подходить для VM дисков и EFI disk.
- Нужен исходящий доступ к `factory.talos.dev`, потому что Terraform сам скачивает Talos `nocloud` image под выбранные `version` и `schematic_id`.
- На машине, где запускается Terraform/OpenTofu, нужна утилита `xz` для локальной распаковки образа.
- `talos.schematic_id` должен соответствовать вашему Talos Image Factory schematic.
- IP-адреса нод должны совпадать с тем, что попадёт в VM при первом boot.
- Если используется `net.ifnames=0`, интерфейсы в guest должны называться `eth0`, `eth1` и т.д.

Рекомендуемый schematic должен включать как минимум:

```yaml
customization:
  extraKernelArgs:
    - net.ifnames=0
  systemExtensions:
    officialExtensions:
      - siderolabs/drbd
      - siderolabs/qemu-guest-agent
      - siderolabs/zfs
  bootloader: sd-boot
```

## Переменные

Примеры лежат в:

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example) для несекретных значений bootstrap entrypoint
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example) для секретов Terraform

Ключевые группы:

- `proxmox`
  - endpoint, datastore'ы, node name
  - `api_token` лучше передавать через `TF_VAR_proxmox_api_token` или `secrets.sops.tfvars`, а не через `terraform.tfvars`
- `talos`
  - `version` with required `v` prefix
  - `schematic_id`
- cluster/network
  - `cluster_endpoint`
  - `controlplane_vip`
  - `nameservers`
  - `cilium_lb_pool_start` / `cilium_lb_pool_stop`
- nodes
  - `controlplane_node_defaults`
  - `controlplane_nodes`
  - `worker_node_defaults`
  - `worker_nodes`
- bootstrap layer
  - `argocd_enabled`
  - `trust_manager_enabled`
  - `argocd_host`

Минимальный обязательный набор для первого запуска из примера:

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

## Развертывание с нуля

Развёртывание с нуля теперь состоит из четырёх фаз.

### Фаза 1. Подготовка

```bash
make init
cp terraform.tfvars.example terraform.tfvars
# заполните terraform.tfvars только несекретными bootstrap-значениями
```

Секреты Terraform передавайте одним из двух способов.

Через переменные окружения:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!talos=...'
```

Через локальный SOPS-файл:

```bash
cp secrets.sops.tfvars.example secrets.sops.tfvars
# заполните secrets.sops.tfvars и зашифруйте его
sops -e -i secrets.sops.tfvars
sops -d secrets.sops.tfvars > secrets.auto.tfvars
```

`secrets.auto.tfvars` добавлен в `.gitignore`. После `plan/apply` его лучше удалить.

Обычный рабочий вариант:

```bash
sops -d secrets.sops.tfvars > secrets.auto.tfvars
make plan-cluster
make apply-cluster
rm -f secrets.auto.tfvars
```

### Фаза 2. Bootstrap кластера

```bash
make plan-cluster
make apply-cluster
```

После этого должны появиться:

- [`out/kubeconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/kubeconfig)
- [`out/talosconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/talosconfig)

Эти файлы локальные, чувствительные и игнорируются через `.gitignore`.

Текущий bootstrap-only root требует `write_configs_to_files = true`, потому что `infrastructure` использует локальный `out/kubeconfig`.

### Фаза 3. Platform bootstrap

```bash
make plan-platform-bootstrap
make apply-platform-bootstrap
```

Эта фаза поднимает bootstrap-операторы и CRD:

- `cert-manager`
- `openbao`
- `external-secrets`
- `trust-manager`
- `piraeus-operator`
- `argocd` если `argocd_enabled = true`

### Фаза 4. Day-0 OpenBao bootstrap

После platform bootstrap нужно вручную подготовить `OpenBao`.

Кратко:

1. Инициализировать и разлочить `OpenBao`
2. Включить `KV v2` на `secret/`
3. Включить Kubernetes auth
4. Создать policy для `ESO`
5. Создать role `external-secrets`
6. Записать runtime secrets:
   - `secret/platform/authentik/runtime`
   - `secret/platform/forgejo/admin`
   - `secret/platform/forgejo/oidc`

Подсказку можно вывести прямо из `Makefile`:

```bash
make day0-guide
```

Подробная инструкция и checklist: [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)

После этого runtime/GitOps слой запускается уже отдельно через модуль [gitops/](/home/zerodi/code/talos-proxmox-no-ssh/gitops), а не через root entrypoint.

Если нужен только быстрый путь до ручного day-0 шага:

```bash
make from-scratch
```

Эта цель выполняет:

- bootstrap кластера
- platform bootstrap
- печать дальнейших day-0 шагов для `OpenBao`
