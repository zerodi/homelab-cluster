# Day-0 Bootstrap

Этот документ описывает только сценарий развёртывания кластера и platform-layer с нуля.

Day-1 operator actions после bootstrap вынесены в [docs/day1-operations.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/day1-operations.md).

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
4. runtime credentials для приложений:
   `platform/authentik/runtime`, `platform/authentik/postgresql`, `platform/authentik/redis`,
   `platform/forgejo/admin`, `platform/forgejo/oidc`, `platform/forgejo/postgresql`, `platform/forgejo/valkey`,
   `platform/observability/grafana`, `platform/garage/runtime`, `platform/velero/s3`

## Порядок шагов

### 1. Инициализация репозитория

```bash
task init
cp terraform.tfvars.example terraform.tfvars
# заполните terraform.tfvars только несекретными значениями
```

`task init` теперь инициализирует оба entrypoint:

- `bootstrap/`
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
sops -d secrets.sops.tfvars > secrets.auto.tfvars
```

`secrets.auto.tfvars` должен оставаться только локальным рабочим файлом.

### 2. Bootstrap кластера

```bash
task bootstrap:plan-cluster
task bootstrap:apply-cluster
```

После этого должны появиться:

- `out/kubeconfig`
- `out/talosconfig`

Проверка:

```bash
task bootstrap:health
```

`bootstrap/` требует `write_configs_to_files = true`, потому что platform bootstrap использует локальный `out/kubeconfig`.
Platform bootstrap выполняется из отдельного entrypoint `infrastructure/`, который читает не-секретные входы из `bootstrap/terraform.tfstate`.

### 3. Bootstrap platform operators

```bash
task infra:plan-bootstrap
task infra:apply-bootstrap
```

`task infra:plan-bootstrap` строит план только для первой стадии platform bootstrap, где ещё нет CRD-зависимых manifests.

Эта фаза поднимает:

- `cert-manager`
- `openbao`
- `external-secrets`
- `trust-manager`
- `piraeus-operator`

Проверка:

```bash
task infra:health
```

Во время `task infra:apply-bootstrap` сначала поэтапно ставятся CRD-delivering releases и CRD-backed manifests, затем LINSTOR device pools создаются отдельным helper-скриптом вне Terraform graph, и только после этого выполняется финальный `infrastructure` apply.

Для обратного teardown используйте `task infra:destroy` перед `task bootstrap:destroy`. Этот helper сначала удаляет CRD-backed manifests при живых CRD, а если какие-то CRD уже отсутствуют, вычищает только соответствующие адреса из `infrastructure` state и завершает `tofu destroy -refresh=false`.

Первая стадия запускается с отключёнными `crd_backed_resources`, чтобы `tofu plan/apply` не пытался резолвить `ClusterIssuer`, `Certificate`, `Bundle` и `Linstor*` до появления их CRD в API discovery.

### 4. Ручной bootstrap OpenBao

Нужно вручную:

1. Инициализировать и разлочить `OpenBao`
2. Получить `BAO_TOKEN` с правами на конфигурацию `auth/policy/role`

Для напоминания можно использовать:

```bash
task ops:day0-guide
```

После `init + unseal` можно автоматизировать post-init настройку:

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

Ниже остаётся практический сценарий и расшифровка действий helper-скрипта.

#### 4.1. Подключение к OpenBao

Откройте локальный port-forward:

```bash
kubectl -n openbao port-forward svc/openbao 8200:8200
```

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

Получите service account token и CA из кластера:

```bash
SA_SECRET_NAME="$(kubectl -n external-secrets get sa external-secrets -o jsonpath='{.secrets[0].name}')"
SA_JWT_TOKEN="$(kubectl -n external-secrets get secret "$SA_SECRET_NAME" -o jsonpath='{.data.token}' | base64 -d)"
KUBE_CA_CRT="$(kubectl -n external-secrets get secret "$SA_SECRET_NAME" -o jsonpath='{.data.ca\.crt}' | base64 -d)"
```

Включите auth method:

```bash
bao auth enable kubernetes
```

Если auth method уже существует, это тоже нормально.

Настройте его:

```bash
bao write auth/kubernetes/config \
  token_reviewer_jwt="$SA_JWT_TOKEN" \
  kubernetes_host="https://kubernetes.default.svc" \
  kubernetes_ca_cert="$KUBE_CA_CRT"
```

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
```

Запишите её в OpenBao:

```bash
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

- `secret/platform/authentik/runtime`
  - `secret_key`
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
- `secret/platform/observability/grafana`
  - `username`
  - `password`
- `secret/platform/garage/runtime`
  - `rpc_secret`
  - `admin_token`
  - `metrics_token`
- `secret/platform/velero/s3`
  - `access_key_id`
  - `secret_access_key`

Практические команды:

Сгенерировать starter snippet можно так:

```bash
task ops:generate-runtime-secret-puts
```

Helper печатает только `bao kv put secret/platform/...` команды:

- случайные значения генерируются для локально управляемых паролей и `secret_key`
- поля, которые должны совпадать с внешними системами, остаются с `REPLACE_WITH_*`

```bash
bao kv put secret/platform/authentik/runtime \
  secret_key='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/authentik/postgresql \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/authentik/redis \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/forgejo/admin \
  username='forgejo' \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/forgejo/postgresql \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/forgejo/valkey \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/forgejo/oidc \
  client_id='REPLACE_WITH_CLIENT_ID' \
  client_secret='REPLACE_WITH_CLIENT_SECRET'
```

```bash
bao kv put secret/platform/observability/grafana \
  username='admin' \
  password='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/garage/runtime \
  rpc_secret='REPLACE_WITH_LONG_RANDOM_VALUE' \
  admin_token='REPLACE_WITH_LONG_RANDOM_VALUE' \
  metrics_token='REPLACE_WITH_LONG_RANDOM_VALUE'
```

```bash
bao kv put secret/platform/velero/s3 \
  access_key_id='REPLACE_WITH_ACCESS_KEY_ID' \
  secret_access_key='REPLACE_WITH_SECRET_ACCESS_KEY'
```

Проверка:

```bash
bao kv get secret/platform/authentik/runtime
bao kv get secret/platform/authentik/postgresql
bao kv get secret/platform/authentik/redis
bao kv get secret/platform/forgejo/admin
bao kv get secret/platform/forgejo/postgresql
bao kv get secret/platform/forgejo/valkey
bao kv get secret/platform/forgejo/oidc
bao kv get secret/platform/observability/grafana
bao kv get secret/platform/garage/runtime
bao kv get secret/platform/velero/s3
```

### 6. GitOps bootstrap

После записи runtime secrets:

1. сначала обновите [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
2. замените placeholder `repoURL` и `sourceRepos` в `argocd/`
3. замените домены `*.home.arpa`, если они отличаются от целевых
4. сверьтесь с [docs/environment-contract.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/environment-contract.md), чтобы обновить все затронутые manifests
5. примените root application

```bash
task gitops:apply-bootstrap
```

Этот helper:

- проверяет readiness `argocd`
- валидирует отсутствие `https://git.example.invalid/replace-me/gitops.git`
- применяет `argocd/bootstrap/root-application.yaml`
- ждёт `Application/root` в состояниях `Synced` и `Healthy`

После этого можно проверить, что ESO начал синхронизацию:

```bash
kubectl -n authentik get secret authentik-runtime
kubectl -n forgejo get secret forgejo-admin-secret
kubectl -n authentik get secret forgejo-oidc
```

Данные для первого входа администратора:

Forgejo:

```bash
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.username}' | base64 -d && echo
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
```

Authentik:

- отдельный admin `Secret` в Kubernetes не создаётся
- на первом входе используйте initial setup flow в `https://auth.home.arpa`
- если инстанс уже инициализирован и нужен recovery/reset, выполните:

```bash
kubectl -n authentik exec deploy/authentik-server -- ak shell -c "python /manage.py createsuperuser"
kubectl -n authentik exec deploy/authentik-server -- ak shell -c "python /manage.py changepassword <username>"
```

### 6. Отдельный runtime/GitOps запуск

После bootstrap `OpenBao` и записи секретов runtime-слой больше не поднимается через Terraform bootstrap entrypoint.
Используйте manifests из [argocd/](/home/zerodi/code/talos-proxmox-no-ssh/argocd) и их отдельный bootstrap/apply.

Перед этим проверьте:

- что bootstrap из `argocd/` уже применён и `ClusterSecretStore openbao` создан
- что `external-secrets` controller запущен
- что OpenBao unsealed
- что пути `secret/platform/...` реально существуют

## Что пока остаётся bootstrap-исключением

- `Proxmox API token`
- `SSH`-доступ к Proxmox node для `proxmox_virtual_environment_file`
- `Talos machine secrets`, которые генерирует Talos provider
- `kubeconfig` и `talosconfig`
- `OpenBao init/unseal` и recovery material

## Дальше

- экспортировать корневой CA `homelab-root-ca`: `task ops:export-root-ca`
- импортировать экспортированный CA в локальный trust store
- проверить ESO-синхронизацию секретов
- проверить SSO и связку Forgejo + Argo CD по README
- если используете `Garage` для `Velero`, выполнить ручной bootstrap bucket/key по [docs/garage-velero-plan.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/garage-velero-plan.md)
