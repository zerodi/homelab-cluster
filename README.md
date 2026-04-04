# Talos on Proxmox VE via Terraform/OpenTofu

Репозиторий поднимает Kubernetes-кластер на Talos поверх Proxmox и доводит его до минимального platform bootstrap.

Текущая модель разделения слоёв:

- root: только `terraform.tfvars`, examples и документация
- `bootstrap/`: самостоятельный Terraform/OpenTofu entrypoint для Talos image, VM lifecycle, machine config, control plane bootstrap, локальных `kubeconfig` и `talosconfig`, базового Cilium bootstrap
- `infrastructure/`: отдельный Terraform/OpenTofu entrypoint для bootstrap-операторов и storage/bootstrap readiness внутри Kubernetes
- `argocd/`: runtime/GitOps scaffold для `authentik`, `forgejo`, `harbor`, `woodpecker`, `echo`, observability stack, `ClusterSecretStore openbao` и app-of-apps bootstrap

Root больше не является Terraform/OpenTofu entrypoint.

## Что делает каждый слой

### Root

В корне репозитория остаются только:

- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)
- [secrets.sops.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/secrets.sops.tfvars.example)
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml) как единый non-secret environment contract
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
- `platform/`: `authentik`, `forgejo`, `harbor`, `woodpecker`, observability stack и связанные prereqs/bootstrap manifests
- `platform/`: также включает `velero` и `kyverno` как runtime platform services
- `apps/`: demo `echo`

Runtime stateful services для приложений тоже живут здесь:

- `authentik` использует отдельные runtime `Application` для PostgreSQL и Redis
- `forgejo` использует отдельные runtime `Application` для PostgreSQL и Valkey
- `harbor` использует отдельные runtime `Application` для PostgreSQL и Valkey
- observability stack состоит из `VictoriaMetrics`, `Loki`, `Tempo`, `Grafana` и `OpenTelemetry Collector`
- backup/restore baseline обеспечивается `Velero`
- policy guardrails baseline обеспечивается `Kyverno`
- observability stack сразу приезжает с self-scrape через `OTel Collector`, Hubble metrics scrape, provisioned dashboards и базовыми Grafana alert rules
- observability stack также скрапит базовые metrics endpoints у `Velero` и `Kyverno`
- `gateway` используется как shared runtime Gateway API foundation
- `authentik`, `echo`, `forgejo`, `grafana`, `harbor` и `woodpecker` используют собственные namespaced `Gateway` и `HTTPRoute`
- `hubble` публикуется через отдельный `HTTPRoute` на shared `internal` gateway
- runtime workloads с credentials получают их только через `OpenBao` + `External Secrets`

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
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [docs/prerequisites.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/prerequisites.md)

Mapping non-secret naming contract между Terraform и `argocd/` описан в [docs/environment-contract.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/environment-contract.md).
План cutover Forgejo на runtime PostgreSQL и Valkey описан в [docs/forgejo-postgresql-migration.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/forgejo-postgresql-migration.md).
Day-1 operator actions и границы автоматизации описаны в [docs/day1-operations.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day1-operations.md).
Текущий day-0 secret contract для runtime приложений и observability описан в [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md).
Backup/restore runbook описан в [docs/backup-restore.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/backup-restore.md).
Kyverno policy rollout описан в [docs/kyverno-policies.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/kyverno-policies.md).

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
task init
cp terraform.tfvars.example terraform.tfvars
# заполните terraform.tfvars только несекретными значениями
```

`task init` инициализирует оба entrypoint:

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
task bootstrap:plan-cluster
task bootstrap:apply-cluster
```

Эквивалент напрямую:

```bash
tofu -chdir=bootstrap plan -var-file=../terraform.tfvars
tofu -chdir=bootstrap apply -var-file=../terraform.tfvars
```

После этого должны появиться:

- [`out/kubeconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/kubeconfig)
- [`out/talosconfig`](/home/zerodi/code/talos-proxmox-no-ssh/out/talosconfig)

Проверка после cluster bootstrap:

```bash
task bootstrap:health
```

### 3. Platform bootstrap

```bash
task infra:plan-bootstrap
task infra:apply-bootstrap
```

`infrastructure/` ожидает, что `bootstrap/terraform.tfstate` и `out/kubeconfig` уже существуют после cluster bootstrap.

`task infra:plan-bootstrap` теперь строит план только для первой стадии platform bootstrap, то есть для ресурсов, которые не требуют уже установленных CRD.

Эта фаза запускается из отдельного entrypoint `infrastructure/` и поднимает:

- `cert-manager`
- `openbao`
- `external-secrets`
- `trust-manager`
- `piraeus-operator`
- `argocd`, если `argocd_enabled = true`

`task infra:apply-bootstrap` теперь выполняет staged bootstrap:

1. устанавливает CRD-delivering releases (`cert-manager`, `external-secrets`, `trust-manager`, `piraeus-operator`) без CRD-backed manifests в graph
2. дожидается регистрации CRD в API discovery через `task infra:wait-crds`
3. применяет cert-manager и piraeus manifests только после появления CRD
4. вызывает отдельный helper для `kubectl linstor physical-storage create-device-pool`
5. завершает финальный `tofu -chdir=infrastructure apply`

Проверка после platform bootstrap:

```bash
task infra:health
```

### 4. Day-0 OpenBao bootstrap и GitOps

После platform bootstrap нужно вручную:

1. Инициализировать и разлочить `OpenBao`
2. Включить `KV v2` на `secret/`
3. Включить Kubernetes auth
4. Создать policy и role для `external-secrets`
5. Записать runtime secrets в `secret/platform/*`

Подсказка:

```bash
task ops:day0-guide
```

После `OpenBao init/unseal` можно автоматизировать post-init настройку и GitOps bootstrap:

```bash
export BAO_TOKEN='...'
task ops:openbao-day0
task gitops:apply-bootstrap
```

`task ops:openbao-day0` не выполняет `bao operator init` и не хранит recovery material. Он только:

- включает `KV v2` на `secret/`
- включает и настраивает `auth/kubernetes` через in-cluster service account самого `OpenBao`
- создаёт policy и role для `external-secrets`

Чтобы сгенерировать starter commands для записи runtime secrets в `OpenBao`:

```bash
task ops:generate-runtime-secret-puts
```

Этот helper печатает `bao kv put secret/platform/...` команды:

- случайные значения генерируются только для локально управляемых паролей и `secret_key`
- поля, завязанные на внешние интеграции, остаются с `REPLACE_WITH_*` placeholder

`task gitops:apply-bootstrap` проверяет readiness `argocd` и работает в двух режимах:

- обычный режим: требует заменить placeholder `repoURL` в `argocd/` и применяет root `Application`
- test mode: если подготовлен `test-ssh-git/`, автоматически применяет `known_hosts`, repository secret и `root-application-ssh.yaml` без изменения tracked manifests в `argocd/`

Initial admin password для Argo CD можно получить так:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
```

Initial admin login для Forgejo можно получить так:

```bash
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.username}' | base64 -d && echo
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
```

Initial admin password для Harbor можно получить так:

```bash
kubectl -n harbor get secret harbor-runtime -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d && echo
```

Для Woodpecker нужно заранее создать OAuth application в Forgejo с callback URL:

```text
https://ci.home.arpa/authorize
```

Минимальный day-0 contract для новых сервисов:

- `Harbor` требует `secret/platform/harbor/runtime`, `secret/platform/harbor/postgresql`, `secret/platform/harbor/valkey`
- в `secret/platform/harbor/runtime` поле `registry_htpasswd` должно быть готовой bcrypt htpasswd-строкой
- `Woodpecker` требует `secret/platform/woodpecker/runtime`
- `forgejo_client` и `forgejo_secret` в `secret/platform/woodpecker/runtime` должны совпадать с OAuth application в Forgejo

Минимальная проверка после GitOps apply:

```bash
kubectl -n harbor get secret harbor-runtime harbor-postgresql-auth harbor-valkey-auth
kubectl -n woodpecker get secret woodpecker-runtime
kubectl -n harbor get gateway,httproute
kubectl -n woodpecker get gateway,httproute
```

Для Authentik отдельный admin `Secret` в Kubernetes не создаётся. На первом входе используйте initial setup flow в `https://auth.home.arpa`, а если нужен recovery/reset уже инициализированного инстанса:

```bash
kubectl -n authentik exec deploy/authentik-server -- ak shell -c "python /manage.py createsuperuser"
kubectl -n authentik exec deploy/authentik-server -- ak shell -c "python /manage.py changepassword <username>"
```

## Полезные команды

```bash
task --list
task init
task check:tofu-fmt
task check:validate
task bootstrap:plan-cluster
task bootstrap:apply-cluster
task infra:plan-bootstrap
task infra:apply-bootstrap
task from-scratch
```

Локальные quality checks для репозитория также описаны в [`/.pre-commit-config.yaml`](/home/zerodi/code/talos-proxmox-no-ssh/.pre-commit-config.yaml).
Если у вас установлен `pre-commit`, можно запускать тот же baseline, что и в CI:

```bash
pre-commit run --all-files
```

Локальный operator toolchain и минимальный bootstrap workflow описаны в [docs/prerequisites.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/prerequisites.md).

`task from-scratch` выполняет:

`Makefile` остаётся только как compatibility wrapper и считается deprecated. Основной локальный entrypoint теперь `task`.

Для CI и локальной валидации используется один и тот же `task`-baseline. Если entrypoint ещё не инициализирован, сначала выполните:

```bash
task bootstrap:init -- -backend=false
task infra:init -- -backend=false
task check:validate
```

- bootstrap кластера через `bootstrap/`
- platform bootstrap через `infrastructure/`
- вывод дальнейших day-0 шагов для `OpenBao`

Для teardown используйте:

```bash
task infra:destroy
task bootstrap:destroy
```

`task infra:destroy` теперь выполняет staged destroy: сначала удаляет CRD-backed manifests, пока CRD ещё доступны, затем дочищает state для уже пропавших CRD и завершает общий `tofu destroy -refresh=false`. Это нужно, чтобы teardown не падал на `Bundle`, `ClusterIssuer`, `Certificate` или `Linstor*`, если соответствующий оператор или его CRD уже были удалены.

## Документация

- [docs/day0-bootstrap.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day0-bootstrap.md)
- [docs/roadmap-terraform-vs-argocd.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/roadmap-terraform-vs-argocd.md)
- [argocd/README.md](/home/zerodi/code/talos-proxmox-no-ssh/argocd/README.md)
