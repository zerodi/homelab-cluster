# Talos on Proxmox VE via Terraform/OpenTofu

Этот репозиторий поднимает Kubernetes-кластер на Talos поверх Proxmox и дальше разворачивает базовый platform-layer внутри самого кластера.

Что входит сейчас:

- Proxmox управляется через `bpg/proxmox`
- Talos стартует из автоматически скачанного `nocloud-amd64.raw.xz` из Talos Image Factory
- machine config применяется через `siderolabs/talos`
- Terraform пишет `kubeconfig` и `talosconfig` в `out/`
- внутри кластера разворачиваются:
  - `cert-manager`
  - `trust-manager`
  - `openbao`
  - `external-secrets`
  - `piraeus-operator` / LINSTOR
  - тестовый `echo`
  - `argocd`
  - `authentik`
  - `forgejo`

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
- runtime secrets не отдаются через Terraform outputs
- terraform bootstrap secrets передаются через `TF_VAR_*` или локальный `SOPS`-файл, а не через обычный `terraform.tfvars`
- локальные bootstrap-артефакты `out/` и скачанные Talos-образы не должны попадать в git

Подробный day-0 runbook: [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)

## Структура

Запуск идёт из корня репозитория:

- root-модуль хранит `providers`, общие `variables` и `outputs`
- `bootstrap/` создаёт Talos-кластер
- `infrastructure/` ставит всё, что работает уже поверх Kubernetes API
- `docs/day0-bootstrap.md` описывает развёртывание с нуля

Главная точка входа: [main.tf](/home/zerodi/code/talos-proxmox-no-ssh/main.tf)

## Как это работает

1. Terraform скачивает Talos `nocloud-amd64.raw.xz` из Image Factory по `talos.version` и `talos.schematic_id`.
2. Terraform локально распаковывает образ в `raw`.
3. Terraform загружает этот образ в Proxmox.
3. Создаются control plane и worker VM.
4. Talos provider генерирует secrets и machine configuration.
5. Конфиг применяется на ноды ресурсом `talos_machine_configuration_apply`.
6. Выполняется bootstrap первого control plane.
7. Terraform получает `kubeconfig` и `talosconfig`.
8. Через `infrastructure/` ставятся CRD и platform services.
9. `cert-manager` поднимает внутренний CA `homelab-ca`, а `trust-manager` распространяет CA bundle по namespace-ам приложений.
10. `OpenBao` хранит runtime secrets, а `External Secrets Operator` синхронизирует их в Kubernetes.

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

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example) для несекретных значений
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example) для секретов Terraform

Ключевые группы:

- `proxmox`
  - endpoint, datastore'ы, node name
  - `api_token` лучше передавать через `TF_VAR_proxmox_api_token` или `secrets.sops.tfvars`, а не через `terraform.tfvars`
- `talos`
  - `version`
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
- app layer
  - `argocd_enabled`
  - `authentik_enabled`
  - `forgejo_enabled`
  - `trust_manager_enabled`
  - соответствующие `*_host`

Новые Helm-приложения включаются только через feature flags. Если `*_enabled = false`, `tofu plan` их не покажет.

Минимальный обязательный набор для первого запуска из примера:

- `proxmox.endpoint`
- `proxmox.node_name`
- `proxmox.vm_datastore`
- `proxmox.image_datastore`
- `talos.version`
- `talos.schematic_id`
- `controlplane_vip`
- `talos_version`
- `cilium_lb_pool_start`
- `cilium_lb_pool_stop`
- `controlplane_node_defaults`
- `controlplane_nodes`
- `worker_node_defaults`
- `worker_nodes`

## Развертывание с нуля

Развёртывание с нуля теперь состоит из пяти фаз.

### Фаза 1. Подготовка

```bash
make init
cp terraform.tfvars.example terraform.tfvars
# заполните terraform.tfvars только несекретными значениями
```

Секреты Terraform передавайте одним из двух способов.

Через переменные окружения:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!talos=...'
# optional
export TF_VAR_populate_cluster_bearer_token='...'
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

Эти файлы локальные, чувствительные и теперь игнорируются через `.gitignore`.

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

Внутри day-0 runbook теперь есть пошаговые команды для:

- `kubectl port-forward` к `openbao`
- `bao operator init`
- `bao operator unseal`
- `bao auth enable kubernetes`
- создания policy и role для `external-secrets`
- записи `secret/platform/authentik/runtime`
- записи `secret/platform/forgejo/admin`
- записи `secret/platform/forgejo/oidc`

### Фаза 5. Полный runtime apply

После day-0 bootstrap:

```bash
make plan-runtime
make apply-runtime
```

Почему порядок именно такой:

- сначала должен подняться сам Talos-кластер
- затем должны появиться bootstrap-операторы и их CRD
- затем `OpenBao` должен стать доступен и получить стартовые секреты
- только после этого `ESO` сможет синхронизировать runtime secrets, а полный `plan/apply` станет воспроизводимым

Если нужен только быстрый путь до ручного day-0 шага:

```bash
make from-scratch
```

Эта цель выполняет:

- bootstrap кластера
- platform bootstrap
- печать дальнейших day-0 шагов для `OpenBao`

## Readiness checks

В `infrastructure/` добавлены дополнительные проверки готовности:

- для `piraeus-operator` / LINSTOR
- для `argocd`
- для `authentik`
- для `forgejo`

Поэтому `apply` может идти заметно дольше обычного `helm_release`, но завершается ближе к реально рабочему состоянию, а не сразу после создания ресурсов.

## Что будет создано в приложениях

### Argo CD

- namespace `argocd`
- ingress через Cilium
- TLS через `cert-manager` и `homelab-ca`

### Authentik

- namespace `authentik`
- встроенные PostgreSQL и Redis
- persistence через Piraeus storage class
- ingress через Cilium
- TLS через `cert-manager` и `homelab-ca`

### Forgejo

- namespace `forgejo`
- встроенная SQLite
- persistence через Piraeus storage class
- ingress через Cilium
- bootstrap admin user `forgejo`
- TLS через `cert-manager` и `homelab-ca`

После apply можно получить:

```bash
tofu output argocd_url
tofu output authentik_url
tofu output forgejo_url
tofu output forgejo_admin_username
tofu output cluster_ca_secret_name
```

`forgejo_admin_password` больше не должен использоваться как источник runtime-секрета: он сохранён только как deprecated output и возвращает `null`.

Корневой сертификат кластера хранится в секрете `homelab-root-ca` в namespace `cert-manager`. `trust-manager` раскладывает bundle в ConfigMap `homelab-root-ca` по namespace-ам, помеченным label `trust.home.arpa/enabled=true`.

Чтобы доверять этим сертификатам локально, можно выгрузить корневой CA:

```bash
kubectl -n cert-manager get secret homelab-root-ca -o jsonpath='{.data.tls\.crt}' | base64 -d > homelab-root-ca.crt
```

После этого импортируйте `homelab-root-ca.crt` в trust store вашей ОС или браузера.

Если включён `populate_enabled = true`, дополнительно создаются:

- Authentik application/provider для Forgejo OIDC
- auth source `authentik` в Forgejo
- репозиторий `platform/gitops` в Forgejo
- `AppProject` и repository secret в Argo CD

Проверить outputs можно так:

```bash
tofu output populate_forgejo_sso_name
tofu output populate_authentik_application_slug
tofu output populate_argocd_project_name
tofu output populate_argocd_repository_secret_name
```

## Проверка SSO и GitOps

### 1. Проверка Authentik -> Forgejo SSO

Откройте `forgejo_url` в браузере и выберите вход через `authentik`.

Ожидаемое поведение:

- Forgejo редиректит на `authentik_url`
- после успешного входа Authentik возвращает пользователя в Forgejo
- в Forgejo создаётся или используется связанная учётная запись

Проверка со стороны кластера:

```bash
kubectl -n forgejo exec deploy/forgejo -- forgejo admin auth list --vertical-bars
```

В списке должен быть источник аутентификации `authentik`.

### 2. Проверка репозитория в Forgejo

Проверьте, что bootstrap-репозиторий создан:

```bash
kubectl -n forgejo port-forward svc/forgejo-http 3000:3000
```

В другом терминале:

```bash
curl -u "forgejo:$(kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.password}' | base64 -d)" \
  http://127.0.0.1:3000/api/v1/repos/platform/gitops
```

Ожидается `200 OK` и JSON с репозиторием `platform/gitops`.

### 3. Проверка связки Forgejo -> Argo CD

Проверьте secrets, созданные populate-модулем:

```bash
kubectl -n argocd get secret platform-repo-creds
kubectl -n argocd get secret platform-repository
kubectl -n argocd get appproject platform -o yaml
```

У `platform-repository` должен быть URL вида:

- `http://forgejo-http.forgejo.svc.cluster.local:3000/platform/gitops.git`

Проверить, что Argo CD принял репозиторий:

```bash
kubectl -n argocd get secrets -l argocd.argoproj.io/secret-type=repository
```

Если установлен `argocd` CLI и нужен явный runtime-check:

```bash
argocd repo list
```

В списке должен присутствовать `platform/gitops`.

## Локальные артефакты

`bootstrap` по умолчанию пишет:

- `out/talosconfig`
- `out/kubeconfig`

Содержимое `talosconfig` и `kubeconfig` больше не экспортируется через Terraform outputs. Рабочий способ доступа только один: использовать локальные файлы из `out/`.

## Известные ограничения

- Первый `plan/apply` требует нескольких фаз.
- `kubernetes_manifest` ресурсы зависят от CRD, поэтому полный `plan` до установки CRD может падать.
- Piraeus/LINSTOR заметно увеличивает время первого `apply`.
- Для Authentik и Forgejo persistence завязана на уже готовый storage class от Piraeus.

## Что логично делать дальше

- вынести app-layer в GitOps через Argo CD `Application`
- подключить нормальный issuer вместо `selfsigned-bootstrap`
- вынести секреты из Terraform state
- добавить внешнюю БД для Forgejo и/или Authentik
- добавить ingress auth / SSO между Authentik, Argo CD и Forgejo
