# Карта этапов развёртывания

Документ описывает greenfield-развёртывание нового Talos-кластера и разделяет
автоматизированные сценарии от обязательных действий оператора.

Обозначения:

- **Автоматически** — выполняется существующей Task-командой или helper-скриптом.
- **Частично** — команда автоматизирована, но требует заранее подготовленных
  параметров, credentials или последующих действий оператора.
- **Вручную** — действие намеренно не передано Terraform, Argo CD или helper.

## Общая последовательность

```text
Подготовка окружения                                      частично
  |
  v
Инициализация OpenTofu                                   автоматически
  |
  v
Proxmox VM -> Talos -> Kubernetes -> Cilium              автоматически
  |
  v
CRD operators -> PKI -> LINSTOR -> OpenBao -> Argo CD    автоматически
  |
  v
OpenBao init/unseal                                      вручную
  |
  v
OpenBao Kubernetes auth и ESO policy                     автоматически
  |
  v
Начальные runtime secrets                                частично
  |
  v
Сборка test-ssh-git -> Argo CD root-ssh                  автоматически
  |
  v
Первичный sync platform и runtime applications           автоматически
  |
  v
OAuth, Garage/S3 и финальная ротация credentials         вручную/частично
  |
  v
Финальные readiness и smoke checks                       автоматически
```

## 0. Подготовка

| Действие | Статус | Выполнение |
|---|---|---|
| Установить OpenTofu, Task, kubectl, talosctl, bao, SOPS/age и остальные инструменты | Вручную | См. [требования](prerequisites.md) |
| Создать Proxmox API token | Вручную | Передать через `TF_VAR_proxmox_api_token` или локальный SOPS tfvars |
| Настроить SSH-доступ к Proxmox node | Вручную | Нужен provider для загрузки Talos image; SSH к Talos nodes не используется |
| Настроить `terraform.tfvars` и `.env` | Вручную | Выбрать Proxmox node/datastore, адреса, версии и topology |
| Настроить environment contract | Вручную | Обновить `envs/homelab.yaml` или tracked non-secret override |
| Инициализировать OpenTofu entrypoint | Автоматически | `task init` |

## 1. Cluster layer

Команды:

```bash
task cluster:plan
task cluster:apply
task cluster:health
```

`task cluster:apply` автоматически выполняет:

1. загрузку и распаковку Talos image;
2. импорт image в Proxmox;
3. создание control-plane и worker VM;
4. генерацию Talos machine secrets и machine configuration;
5. применение конфигурации к nodes;
6. bootstrap control plane;
7. установку минимального Cilium с Gateway API, LB IPAM и L2 announcements;
8. создание `out/kubeconfig` и `out/talosconfig`.

`task cluster:health` проверяет Talos API, readiness всех Kubernetes nodes,
Cilium agent/operator и CoreDNS.

Статус этапа: **автоматически**, если подготовлены Proxmox credentials, SSH и
корректный `terraform.tfvars`.

## 2. Infrastructure layer

Команды:

```bash
task infra:plan
task infra:apply
task infra:health
```

`task infra:apply` оркестрирует стадии в следующем порядке:

1. устанавливает cert-manager, trust-manager, External Secrets Operator и
   Piraeus Operator;
2. ждёт регистрации их CRD в API discovery;
3. создаёт self-signed issuer, root CA, CA issuer и необходимые auth bindings;
4. создаёт `LinstorSatelliteConfiguration` и `LinstorCluster`;
5. ждёт готовности Piraeus/LINSTOR;
6. создаёт LINSTOR device pools на worker nodes через helper;
7. создаёт StorageClass;
8. устанавливает OpenBao на LINSTOR storage;
9. устанавливает Argo CD;
10. дожидается readiness управляемых компонентов.

Создание LINSTOR pools автоматизировано, но использует raw block device из
environment contract. Оператор должен заранее убедиться, что выбран правильный
диск и на нём нет нужных данных.

Статус этапа: **автоматически**, с обязательной ручной проверкой storage device
до запуска.

## 3. Инициализация OpenBao

Сначала запускается управляемый port-forward:

```bash
task ops:openbao-port-forward-start
task ops:openbao-port-forward-status
```

Следующие действия выполняются **вручную**:

1. `bao operator init -key-shares=3 -key-threshold=2`;
2. сохранение root token, unseal keys и recovery material вне Git и Terraform;
3. выполнение необходимого количества `bao operator unseal`;
4. экспорт `BAO_TOKEN` для day-0 настройки.

Init/unseal намеренно не автоматизированы, чтобы recovery material не попадал в
Terraform state, логи или репозиторий.

После init/unseal post-init конфигурация автоматизирована:

```bash
export BAO_TOKEN='...'
task ops:openbao-day0
```

Helper включает KV v2 и Kubernetes auth, настраивает auth config, policy и role
для External Secrets Operator.

## 4. Runtime secrets

```bash
task ops:seed-runtime-secrets
```

Команда автоматически:

- создаёт только отсутствующие OpenBao paths;
- не перезаписывает существующие credentials;
- генерирует локально управляемые passwords и tokens;
- создаёт согласованные Harbor registry credentials;
- создаёт provisional Woodpecker OAuth и Velero S3 credentials.

Реальные credentials внешних интеграций пока создать автоматически нельзя.
После появления соответствующих ресурсов оператор должен заменить:

- `platform/woodpecker/runtime` — данными Forgejo OAuth application;
- `platform/velero/s3` — данными S3 key из Garage.

После полной перезаписи path marker `bootstrap_provisional` должен исчезнуть.

## 5. Первичный GitOps bootstrap через test-ssh-git

Укажите в `.env` адрес машины с Docker, доступный из Argo CD pods:

```bash
TEST_SSH_GIT_HOSTNAME='192.168.100.10'
TEST_SSH_GIT_PORT='2222'
```

Первичное развёртывание автоматизировано одной командой:

```bash
task gitops:test-ssh-bootstrap
```

Команда:

1. выполняет scaffold environment-contract и OpenBao secret preflight;
2. генерирует SSH keys и manifests;
3. создаёт bare repository из текущего `argocd/`;
4. заменяет GitOps source URL на test SSH URL внутри seed;
5. собирает и запускает test Git server в Docker;
6. проверяет доступность через `git ls-remote`;
7. создаёт known-hosts ConfigMap и repository Secret;
8. применяет `Application/root-ssh`;
9. ждёт `Synced` и `Healthy`.

После этого Argo CD разворачивает platform applications и workloads из
test-ssh-git. Сервер должен оставаться запущенным до завершения первичного sync
или до cutover на постоянный repository.

Если внешний repository уже доступен, альтернативный сценарий остаётся таким:

```bash
task sync-env-contract
task gitops:preflight
task gitops:apply-bootstrap
```

## 6. Внешние интеграции

После первого GitOps sync остаются ручные или полуавтоматические действия.

| Интеграция | Статус | Действие оператора |
|---|---|---|
| Forgejo -> Woodpecker OAuth | Вручную | Создать OAuth application, записать client ID/secret в OpenBao и выполнить первый login |
| Cutover с test-ssh-git | Вручную | Создать постоянный repository, перенести GitOps tree и обновить Argo CD repository/Application sources |
| Garage layout | Частично | Получить node ID и выполнить команды, напечатанные `task ops:garage-velero-bootstrap` |
| Garage bucket и S3 key | Частично | Выполнить напечатанные команды и безопасно получить credentials |
| Velero credentials | Вручную | Перезаписать `secret/platform/velero/s3` в OpenBao |
| Authentik initial setup | Вручную | Завершить initial setup flow через UI |
| DNS или hosts entries | Частично | Получить карту через `task ops:hosts-entries`, затем настроить внешнюю DNS/hosts систему |
| Доверие root CA | Частично | Экспортировать через `task ops:export-root-ca`, затем импортировать CA в клиентские trust stores |

Подробности Garage/Velero приведены в отдельном
[runbook](garage-velero.md).

## 7. Финальная проверка

```bash
task ops:openbao-runtime-preflight-final
task ops:post-argocd-check
task ops:openbao-port-forward-stop
```

Развёртывание считается завершённым, когда:

- `task cluster:health` и `task infra:health` проходят;
- OpenBao initialized и unsealed;
- `task gitops:preflight` проходит;
- root Application имеет состояния `Synced` и `Healthy`;
- обязательные ExternalSecret создали целевые Kubernetes Secrets;
- provisional integration credentials заменены реальными;
- `task ops:openbao-runtime-preflight-final` проходит;
- post-Argo CD smoke checks не находят ошибок.

## Комплексный автоматизированный сценарий

```bash
task from-scratch
```

Эта задача выполняет:

```text
task cluster:apply
  -> task infra:apply
  -> task ops:day0-guide
```

Она намеренно останавливается перед ручным OpenBao init/unseal. Полностью
автоматического unattended-развёртывания до готового runtime сейчас нет.

## Полная операторская последовательность

```bash
task init
task cluster:plan
task cluster:apply
task cluster:health

task infra:plan
task infra:apply
task infra:health

task ops:openbao-port-forward-start
# вручную: bao operator init и bao operator unseal

export BAO_TOKEN='...'
task ops:openbao-day0
task ops:seed-runtime-secrets

export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap

# вручную: Forgejo OAuth, Garage layout/bucket/key и ротация OpenBao paths

task ops:openbao-runtime-preflight-final
task ops:post-argocd-check
task ops:openbao-port-forward-stop
```
