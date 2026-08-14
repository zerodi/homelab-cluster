# Day-0 Bootstrap

Этот документ описывает только сценарий развёртывания кластера и
platform-layer с нуля.

Когда использовать:

- первый bootstrap с пустого состояния
- проверка day-0 secret contract
- ручной OpenBao init/unseal и запуск GitOps bootstrap

## Что нужно заранее

### Доступ к Proxmox

Для провайдера `bpg/proxmox` недостаточно только API token, если используется `proxmox_virtual_environment_file`.

Нужно:

- `API token` для Proxmox
- `SSH`-доступ к Proxmox node
- пользователь `terraform` или другой пользователь, через которого provider сможет выполнять file/upload операции
- рабочий `ssh-agent` или другой способ безпарольной аутентификации

Важно:

- `SSH` нужен к Proxmox node
- `SSH` к Talos-нодам не нужен

### Day-0 секреты

До полного runtime apply нужно подготовить:

1. `age`-ключ для `SOPS`, если вы используете SOPS для day-0 артефактов
2. bootstrap-доступ к `OpenBao`
3. план хранения `unseal keys` и recovery material вне repo и вне Terraform state
4. Cloudflare API token и credentials внешних OAuth/S3 интеграций; полный
   OpenBao contract перечислен в шаге 5

## Порядок шагов

### 1. Инициализация репозитория

```bash
task init
cp terraform.tfvars.example terraform.tfvars
cp .env.example .env
# заполните terraform.tfvars только несекретными значениями
# версии OpenTofu, providers, Talos Linux, Kubernetes, charts и images меняйте в versions.yaml
# заполните .env локальными credentials; Taskfile загружает его автоматически
# оставьте в tracked homelab.override.yaml только environment-specific
# non-secret отличия
```

`task init` инициализирует оба entrypoint:

- `cluster/`
- `infrastructure/`

Секреты Terraform передавайте отдельно.

Через переменные окружения:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!talos=...'
```

Или через локальный SOPS-файл:

```bash
cp secrets.sops.tfvars.example secrets.sops.tfvars
# заполните файл и зашифруйте его
sops -e -i secrets.sops.tfvars
sops -d secrets.sops.tfvars > cluster/secrets.auto.tfvars
```

`cluster/secrets.auto.tfvars` должен оставаться только локальным рабочим
файлом. Он создаётся внутри фактического OpenTofu entrypoint, поэтому
автоматически загружается командами `task cluster:*`.

`cluster_name` — optional OpenTofu override: по умолчанию имя читается из
environment contract, а при отсутствии поля используется fallback `talos-pve`.
`talos_version` и `kubernetes_version` не являются OpenTofu inputs; удалите их
из старого локального `terraform.tfvars`, поскольку версии читаются из root
`versions.yaml`.

Имя кластера и сетевой контракт задаются вместе с общим доменом в
`envs/homelab.yaml` или environment-specific override:

```yaml
cluster:
  name: homelab-talos
  base_domain: lab.example.net
  ipv4_cidr: 192.168.100.0/24
```

`terraform.tfvars.example` перечисляет все inputs `cluster/`, включая optional
значения с безопасными defaults. Обычно после настройки Proxmox и schematic ID
достаточно менять количество узлов:

```hcl
controlplane_nodes = 3
worker_nodes       = 2
```

Из подсети автоматически формируются gateway `.1`, control plane nodes
`.11-.99`, worker nodes `.101-.199`, control plane VIP `.200` и Cilium
LoadBalancer pool `.230-.250`. Имена, VM ID и MAC-адреса узлов также
детерминированы их ролью и порядковым номером. Допустимо до 89 control plane
nodes и до 99 workers. Для etcd quorum рекомендуется нечётное количество
control plane nodes.

### 2. Bootstrap кластера

```bash
task cluster:plan
task cluster:apply
```

После этого должны появиться:

- `out/kubeconfig`
- `out/talosconfig`

Проверка:

```bash
task cluster:health
```

Platform bootstrap выполняется из отдельного entrypoint `infrastructure/`, который читает не-секретные входы из `cluster/terraform.tfstate`.

### 3. Bootstrap platform operators

```bash
task infra:plan
task infra:apply
```

`task infra:plan` строит план только для первой стадии platform bootstrap, где ещё нет CRD-зависимых manifests.

Эта первая стадия поднимает только CRD-delivering bootstrap-ресурсы:

- `cert-manager`
- `external-secrets`
- `trust-manager`
- `piraeus-operator`

`openbao` применяется позже, на финальном `tofu -chdir=infrastructure apply`, после readiness chain для CRD, cert-manager manifests и LINSTOR storage bootstrap.

Проверка:

```bash
task infra:health
```

Во время `task infra:apply` сначала поэтапно ставятся CRD-delivering releases и CRD-backed manifests, затем LINSTOR device pools создаются отдельным helper-скриптом вне Terraform graph, и только после этого выполняется финальный `infrastructure` apply.

Параметры LINSTOR helper получает до финального apply:

- namespace, pool name и device — из effective contract
  (`envs/homelab.yaml` + optional `envs/homelab.override.yaml`)
- worker nodes — из `cluster.worker_hostnames`
- kubeconfig — из root `.env` (`KUBECONFIG`), recovery override или cluster state

Helper не зависит от outputs незавершённого `infrastructure` apply.

Первая стадия запускается с отключёнными `crd_backed_resources`, чтобы `tofu plan/apply` не пытался резолвить `ClusterIssuer`, `Certificate`, `Bundle` и `Linstor*` до появления их CRD в API discovery.

### 4. Ручной bootstrap OpenBao

Нужно вручную:

1. Инициализировать и разлочить `OpenBao`
2. Получить `BAO_TOKEN` с правами на конфигурацию `auth/policy/role`

Для напоминания можно использовать:

```bash
task ops:day0-guide
```

После `init + unseal` и запуска port-forward из шага 4.1 можно автоматизировать
post-init настройку:

```bash
export BAO_TOKEN='...'
task ops:openbao-day0
```

Этот helper:

- включает `KV v2` на `secret/`
- включает `auth/kubernetes`
- настраивает `auth/kubernetes/config` без одноразового reviewer JWT
- создаёт policy `external-secrets`
- создаёт role `external-secrets`

Ниже приведён практический сценарий и расшифровка действий helper-скрипта.

#### 4.1. Подключение к OpenBao

Откройте управляемый локальный port-forward:

```bash
task ops:openbao-port-forward-start
task ops:openbao-port-forward-status
```

Он слушает только `127.0.0.1:8200`. PID и лог сохраняются в
`out/openbao-port-forward.pid` и `out/openbao-port-forward.log`.

В другом терминале:

```bash
export BAO_ADDR='http://127.0.0.1:8200'
```

```fish
set -x BAO_ADDR 'http://127.0.0.1:8200'
```

Проверьте статус:

```bash
bao status
```

#### 4.2. Инициализация OpenBao

Если OpenBao ещё не инициализирован:

```bash
bao operator init -key-shares=3 -key-threshold=2
```

Сохраните:

- `Initial Root Token`
- `Unseal Key 1..N`

Их нельзя хранить:

- в repo
- в `terraform.tfvars`
- в Terraform state

#### 4.3. Unseal

Если инстанс sealed:

```bash
bao operator unseal
bao operator unseal
```

После этого проверьте:

```bash
bao status
```

Ожидается:

- `Initialized = true`
- `Sealed = false`

#### 4.4. Логин root token

```bash
bao login
```

Используйте `Initial Root Token` из шага init.

#### 4.5. Включение KV v2

Если `secret/` ещё не включён:

```bash
bao secrets enable -path=secret kv-v2
```

Если движок уже существует, команда вернёт ошибку вида `path is already in use`. Это нормально.

Проверка:

```bash
bao secrets list
```

#### 4.6. Включение Kubernetes auth

Получите CA текущего кластера из kubeconfig:

```bash
KUBE_CA_CRT="$(kubectl config view --raw --minify --flatten \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d)"
```

Включите auth method:

```bash
bao auth enable kubernetes
```

Если auth method уже существует, это тоже нормально.

Настройте его:

```bash
bao write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc" \
  kubernetes_ca_cert="$KUBE_CA_CRT"
```

OpenBao использует JWT аутентифицирующегося service account для TokenReview;
одноразовый reviewer JWT в конфигурации не сохраняется.

#### 4.7. Policy для ESO

Создайте policy:

```bash
cat <<'EOF' > /tmp/external-secrets-policy.hcl
path "secret/data/platform/*" {
  capabilities = ["read"]
}

path "secret/metadata/platform/*" {
  capabilities = ["read", "list"]
}
EOF

bao policy write external-secrets /tmp/external-secrets-policy.hcl
```

```fish
set policy 'path "secret/data/platform/*" {
  capabilities = ["read"]
}

path "secret/metadata/platform/*" {
  capabilities = ["read", "list"]
}'

printf '%s\n' "$policy" > /tmp/external-secrets-policy.hcl

bao policy write external-secrets /tmp/external-secrets-policy.hcl
```

#### 4.8. Role для ESO

```bash
bao write auth/kubernetes/role/external-secrets \
  bound_service_account_names="external-secrets" \
  bound_service_account_namespaces="external-secrets" \
  policies="external-secrets" \
  ttl="1h"
```

#### 4.9. Проверка auth chain

На этом этапе должно работать следующее соответствие:

- `external-secrets/external-secrets` service account
- auth method `auth/kubernetes`
- role `external-secrets`
- policy `external-secrets`

Проверить можно так:

```bash
bao read auth/kubernetes/role/external-secrets
bao policy read external-secrets
```

### 5. Запись стартовых runtime secrets

До полного apply в `OpenBao` должны существовать:

- `secret/platform/cert-manager/cloudflare`
  - `api_token`
- `secret/platform/authentik/runtime`
  - `secret_key`
  - `bootstrap_password`
- `secret/platform/authentik/postgresql`
  - `password`
- `secret/platform/authentik/redis`
  - `password`
- `secret/platform/forgejo/admin`
  - `username`
  - `password`
- `secret/platform/forgejo/postgresql`
  - `password`
- `secret/platform/forgejo/valkey`
  - `password`
- `secret/platform/forgejo/oidc`
  - `client_id`
  - `client_secret`
- `secret/platform/argocd/oidc`
  - `client_id`
  - `client_secret`
- `secret/platform/harbor/runtime`
  - `admin_password`
  - `secret_key`
  - `core_secret`
  - `xsrf_key`
  - `jobservice_secret`
  - `registry_http_secret`
  - `registry_password`
  - `registry_htpasswd`
- `secret/platform/harbor/postgresql`
  - `password`
- `secret/platform/harbor/valkey`
  - `password`
- `secret/platform/harbor/oidc`
  - `client_id`
  - `client_secret`
- `secret/platform/stalwart/runtime`
  - `recovery_admin_password`
- `secret/platform/observability/grafana`
  - `username`
  - `password`
- `secret/platform/observability/grafana-oidc`
  - `client_id`
  - `client_secret`
- `secret/platform/woodpecker/runtime`
  - `agent_secret`
  - `forgejo_client`
  - `forgejo_secret`
- `secret/platform/garage/runtime`
  - `rpc_secret`
  - `admin_token`
  - `metrics_token`
- `secret/platform/velero/s3`
  - `access_key_id`
  - `secret_access_key`

Практические команды:

Безопасно создать только отсутствующие paths можно так:

```bash
export CLOUDFLARE_API_TOKEN='...'
task ops:seed-runtime-secrets
```

Команда:

- не перезаписывает существующие OpenBao paths
- записывает предоставленный Cloudflare API token для DNS-01
- генерирует все локально управляемые credentials
- создаёт согласованные `registry_password` и bcrypt `registry_htpasswd`
- добавляет обязательный `platform/garage/runtime`
- создаёт временные Woodpecker OAuth и Velero S3 credentials для завершения
  greenfield bootstrap

Временные paths содержат дополнительный marker
`bootstrap_provisional=true`. Если реальные credentials уже существуют,
передайте обе пары через environment:

```bash
export WOODPECKER_FORGEJO_CLIENT='...'
export WOODPECKER_FORGEJO_SECRET='...'
export VELERO_S3_ACCESS_KEY_ID='...'
export VELERO_S3_SECRET_ACCESS_KEY='...'
task ops:seed-runtime-secrets
```

Просмотреть полный набор команд без записи:

```bash
task ops:generate-runtime-secret-puts
```

Helper печатает `bao kv put secret/platform/...` команды со всеми обязательными
keys и без `REPLACE_WITH_*`. Не сохраняйте вывод в repo.

После появления реальных внешних ресурсов обязательно замените:

- `platform/woodpecker/runtime` — `forgejo_client` и `forgejo_secret` из
  Forgejo OAuth application
- `platform/velero/s3` — `access_key_id` и `secret_access_key` созданного S3 key

ESO обновит Kubernetes Secrets после изменения OpenBao.

Финальная проверка отклоняет оставшиеся provisional paths:

```bash
task ops:openbao-runtime-preflight-final
```

### 6. GitOps bootstrap

Сначала синхронизируйте tracked consumers по
[environment contract](environment-contract.md), затем выберите временный или
постоянный Git source.

Для первого bootstrap через test-SSH укажите адрес машины с Docker, доступный
из Argo CD pods:

```bash
export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap
```

Команда выполняет environment/OpenBao preflight, поднимает временный Git source
и ждёт `Application/root-ssh` в состояниях `Synced` и `Healthy`. Ограничения,
создаваемые артефакты и ручной recovery описаны в
[test-SSH runbook](../test-ssh-git/README.md). Держите server запущенным до
завершения sync или cutover.

После создания Forgejo перенесите GitOps tree и переключите Argo CD по
[cutover runbook](forgejo-argocd-cutover.md). После commit текущего `argocd/`
основной сценарий выполняется одной командой:

```bash
export BAO_ADDR='http://127.0.0.1:8200'
export BAO_TOKEN='...'
task gitops:forgejo-cutover
```

Task выполняет проверяемый cutover и останавливает временный server только
после успешной проверки. Детали и recovery-путь находятся в отдельном runbook.

Если постоянный repository доступен до первого sync, используйте обычный путь:

```bash
task gitops:preflight
task gitops:apply-bootstrap
```

#### Первичный доступ

- URL, начальный пароль и временный port-forward Argo CD описаны в
  [`argocd/README.md`](../argocd/README.md#первичный-доступ-к-argo-cd).
- Сводный вывод интерактивных bootstrap credentials доступен через
  `task ops:initial-app-credentials`.
- Модель Authentik/OIDC и break-glass доступ описаны в
  [runbook авторизации](platform-authentication.md).
- Специфичные recovery и DNS шаги Stalwart находятся в
  [Stalwart runbook](stalwart.md).

После завершения day-0 операций закройте port-forward:

```bash
task ops:openbao-port-forward-stop
```

## Что пока остаётся bootstrap-исключением

- `Proxmox API token`
- `SSH`-доступ к Proxmox node для `proxmox_virtual_environment_file`
- `Talos machine secrets`, которые генерирует Talos provider
- `kubeconfig` и `talosconfig`
- `OpenBao init/unseal` и recovery material

## Критерий завершения

Развёртывание завершено, когда:

- `task cluster:health` и `task infra:health` проходят
- OpenBao инициализирован и unsealed
- `task gitops:preflight` проходит
- root application имеет состояния `Synced` и `Healthy`
- обязательные `ExternalSecret` создали целевые Kubernetes Secrets
- после настройки внешних интеграций проходит
  `task ops:openbao-runtime-preflight-final`
