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
4. runtime credentials для приложений:
   `platform/authentik/runtime`, `platform/authentik/postgresql`, `platform/authentik/redis`,
   `platform/forgejo/admin`, `platform/forgejo/oidc`, `platform/forgejo/postgresql`, `platform/forgejo/valkey`,
   `platform/harbor/runtime`, `platform/harbor/postgresql`, `platform/harbor/valkey`,
   `platform/stalwart/runtime`,
   `platform/woodpecker/runtime`,
   `platform/observability/grafana`, `platform/garage/runtime`, `platform/velero/s3`

## Порядок шагов

### 1. Инициализация репозитория

```bash
task init
cp terraform.tfvars.example terraform.tfvars
cp .env.example .env
# заполните terraform.tfvars только несекретными значениями
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
- `secret/platform/stalwart/runtime`
  - `recovery_admin_password`
- `secret/platform/observability/grafana`
  - `username`
  - `password`
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
task ops:seed-runtime-secrets
```

Команда:

- не перезаписывает существующие OpenBao paths
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

После записи runtime secrets:

1. обновите [envs/homelab.yaml](../envs/homelab.yaml) или environment-specific
   `envs/homelab.override.yaml`
2. запустите `task sync-env-contract`, чтобы обновить repository coordinates,
   домены и остальные tracked mirrors в `argocd/`
3. запустите `task check:env-contract`, чтобы проверить результат
4. укажите адрес машины с Docker, доступный из Argo CD pods
5. соберите test-ssh-git и примените root application из него

```bash
export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap
```

Этот сценарий:

- запускает scaffold effective contract validation против `argocd/`
- валидирует наличие required runtime secret paths/keys в `OpenBao`
- не печатает secret values
- создаёт seed repository из текущего `argocd/` и переписывает его Git source
  URL на локальный SSH endpoint
- собирает и запускает `test-ssh-git` в Docker
- проверяет repository через `git ls-remote`
- проверяет readiness `argocd`
- создаёт known-hosts ConfigMap и repository Secret
- применяет сгенерированный `Application/root-ssh`
- ждёт `Application/root-ssh` в состояниях `Synced` и `Healthy`

`TEST_SSH_GIT_HOSTNAME` не может быть loopback-адресом: endpoint должен быть
доступен из Argo CD pods. Держите test server запущенным до завершения sync или
до перевода Applications на постоянный Git repository.

После создания Forgejo перенесите GitOps tree и переключите Argo CD по
[cutover runbook](forgejo-argocd-cutover.md). Он сохраняет token в OpenBao,
доставляет repository Secret через ESO и предотвращает конфликт между
`root-ssh` и каноническим `root`. Только после успешного cutover остановите
временный сервер командой `task gitops:test-ssh-stop`.

Если постоянный repository доступен до первого sync, используйте обычный путь:

```bash
task gitops:preflight
task gitops:apply-bootstrap
```

#### Первичный вход в Argo CD

Получите опубликованный URL и состояние Ingress:

```bash
tofu -chdir=infrastructure output -raw argocd_url && echo
kubectl -n argocd get ingress argocd-server
```

Hostname должен разрешаться в адрес Ingress. Для доверия выпущенному внутренним
CA TLS-сертификату экспортируйте homelab CA командой `task ops:export-root-ca`
и добавьте `out/homelab-root-ca.crt` в trust store клиентской машины.

Полный набор строк для клиентского `/etc/hosts` по фактически назначенным
LoadBalancer IP из Kubernetes status выводится командой:

```bash
task ops:hosts-entries
```

Если хотя бы один Ingress или Gateway ещё не получил адрес, команда перечислит
Pending-ресурсы и не выведет неполный набор.

Начальный логин — `admin`. Пароль хранится в Kubernetes Secret:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

До настройки DNS и CA можно использовать локальный доступ:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
```

Откройте `http://127.0.0.1:8080`, войдите как `admin`, затем смените пароль в
`User Info -> Update Password`. После проверки нового пароля initial Secret
можно удалить:

```bash
kubectl -n argocd delete secret argocd-initial-admin-secret
```

После этого можно проверить, что ESO начал синхронизацию:

```bash
kubectl -n authentik get secret authentik-runtime
kubectl -n forgejo get secret forgejo-admin-secret
kubectl -n forgejo get secret forgejo-oidc
kubectl -n harbor get secret harbor-runtime harbor-postgresql-auth harbor-valkey-auth
kubectl -n stalwart get secret stalwart-runtime
kubectl -n woodpecker get secret woodpecker-runtime woodpecker-default-agent-secret
```

Данные для первого входа администратора:

Authentik (`akadmin`):

```bash
task ops:authentik-admin-password
```

То же значение из materialized Kubernetes Secret:

```bash
kubectl -n authentik get secret authentik-runtime \
  -o jsonpath='{.data.AUTHENTIK_BOOTSTRAP_PASSWORD}' | base64 -d && echo
```

`AUTHENTIK_BOOTSTRAP_PASSWORD` читается Authentik только при первом старте.
Если instance уже запускался без этого значения, существующий пароль получить
нельзя: он хранится в базе как verifier. Задайте новый пароль интерактивно и
затем сохраните согласованное значение в OpenBao:

```bash
kubectl -n authentik exec -it deployment/authentik-server -c server -- \
  ak changepassword akadmin
```

Не перезаписывайте весь `platform/authentik/runtime`, не сохранив существующий
`secret_key`; для добавления поля в существующий KV v2 path используйте
`bao kv patch`.

Forgejo:

```bash
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.username}' | base64 -d && echo
kubectl -n forgejo get secret forgejo-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
```

Harbor:

```bash
kubectl -n harbor get secret harbor-runtime -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d && echo
```

Harbor получает пароль Valkey из `OpenBao` через `ExternalSecret`
`harbor-valkey-auth`. ESO формирует в этом Secret готовые Redis URL, а
Harbor-компоненты читают их через runtime environment variables. Это необходимо,
потому что Argo CD выполняет client-side Helm render и не может обработать
`lookup` секрета из Harbor chart. Не переносите пароль в
`redis.external.password` внутри `values.yaml`.

Stalwart (`admin`):

```bash
task ops:stalwart-admin-password
```

Recovery administrator нужен только для первоначальной настройки и аварийного
доступа. После создания постоянного администратора удалите его `envFrom` из
StatefulSet и синхронизируйте Argo CD. Полная настройка LB, TLS и DNS описана в
[Stalwart runbook](stalwart.md).

Woodpecker:

- до первого входа должен существовать OAuth application в Forgejo
- callback URL должен быть `https://ci.lab.zerodi.ru/authorize`
- `forgejo_client` и `forgejo_secret` в `secret/platform/woodpecker/runtime` должны совпадать с этой application
- после sync полезно открыть `https://ci.lab.zerodi.ru/` и завершить OAuth login через Forgejo

Authentik:

- отдельный admin `Secret` в Kubernetes не создаётся
- на первом входе используйте initial setup flow в `https://auth.lab.zerodi.ru`

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
