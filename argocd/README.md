# Argo CD runtime deployment

Этот runbook описывает развёртывание runtime/GitOps слоя после завершения
`cluster/` и `infrastructure/`.

## Структура platform

`platform/` разделён на orchestration и payload:

- `platform/applications/` содержит только дочерние Argo CD Applications;
- `platform/<component>/` содержит Helm values или Kustomize payload этого
  компонента;
- `platform/kustomization.yaml` подключает только application index, поэтому
  root Application не становится совладельцем runtime-ресурсов дочерних apps.

Правила добавления компонентов и структура каталогов описаны в
[`platform/README.md`](platform/README.md).

## Предварительные условия

Перед запуском должны быть готовы:

- `cert-manager`
- `trust-manager`
- `OpenBao`
- `External Secrets Operator`
- `Piraeus` / LINSTOR storage class
- `Argo CD`

Проверьте platform bootstrap:

```bash
task infra:health
```

## Настройка окружения

Замените scaffold-значения в [envs/homelab.yaml](../envs/homelab.yaml) либо
environment-specific `envs/homelab.override.yaml`, затем обновите их consumers в
`argocd/`:

- repository URL, `repoURL` и `sourceRepos`
- `cluster.base_domain` и короткие `service_subdomains`
- `cluster.ipv4_cidr`; адреса Gateway генерируются из неё
- OAuth/OIDC coordinates

Краткий порядок синхронизации consumers приведён в
[environment contract](../docs/environment-contract.md).

Проверьте согласованность:

```bash
task sync-env-contract
task check:env-contract
task check:versions
```

## Runtime secrets

Runtime secrets должны быть записаны в OpenBao до применения root application.
Создать только отсутствующие paths и выполнить preflight можно так:

```bash
task ops:seed-runtime-secrets
task gitops:preflight
```

Для выпуска публичных сертификатов перед seed требуется Cloudflare API token.
Полная настройка DNS-01 описана в
[Cloudflare runbook](../docs/cloudflare-dns01.md).

Команда не перезаписывает существующие paths. Для аудита полного набора
`bao kv put` без записи используйте `task ops:generate-runtime-secret-puts`.
Сгенерированные Woodpecker OAuth и Velero S3 credentials являются временными:
после появления Forgejo OAuth application и S3 key замените соответствующие
значения в OpenBao и удалите marker `bootstrap_provisional`, записав path
целиком через `bao kv put`. Финальная проверка:

```bash
task ops:openbao-runtime-preflight-final
```

`task gitops:preflight` проверяет environment contract и обязательные
OpenBao paths/keys, не печатая secret values.

## Применение

Для первичного развёртывания через временный локальный Git-over-SSH repository:

```bash
export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap
```

Команда собирает `test-ssh-git`, запускает сервер, регистрирует repository в
Argo CD и ждёт `Application/root-ssh` в состояниях `Synced` и `Healthy`.
Временный seed tree не включает `forgejo-gitops-repository`: этот
`ExternalSecret` требует token уже работающего Forgejo и подключается только
при последующем cutover.

Для уже доступного постоянного Git repository:

```bash
task gitops:apply-bootstrap
```

Команда проверяет readiness Argo CD, повторяет preflight, применяет
`argocd/bootstrap/root-application.yaml` и ждёт `Application/root` в состояниях
`Synced` и `Healthy`.

Явный test bootstrap создаёт:

- `argocd-ssh-known-hosts-cm`
- repository Secret
- `Application/root-ssh`

После развёртывания Forgejo переведите Argo CD с временного SSH server на
постоянный repository по отдельному
[cutover runbook](../docs/forgejo-argocd-cutover.md). Основной путь полностью
автоматизирован:

```bash
task ops:openbao-port-forward-start
export BAO_ADDR='http://127.0.0.1:8200'
export BAO_TOKEN='...'
task gitops:forgejo-cutover
```

Task создаёт Forgejo organization, private repository и restricted service
account, выпускает repository-scoped read token, сохраняет его в OpenBao,
публикует committed `argocd/`, настраивает внутренний CA и ESO, безопасно
заменяет `root-ssh` на `root` и только после проверки останавливает временный
Git server. Перед запуском `argocd/` должен быть закоммичен без локальных
изменений.

## Проверка результата

```bash
task ops:post-argocd-check
kubectl -n argocd get applications
```

Начальный пользователь Authentik — `akadmin`. В greenfield bootstrap его
пароль генерируется в OpenBao и получается без чтения других runtime secrets:

```bash
task ops:authentik-admin-password
```

Переменная bootstrap применяется только при первом запуске Authentik. Для уже
инициализированного instance используйте recovery-команду из
[day-0 runbook](../docs/day0-bootstrap.md).

Stalwart доступен по `https://stalwart.lab.zerodi.ru/admin`. Recovery login —
`admin`, пароль выводится из OpenBao без чтения остальных secret values:

```bash
task ops:stalwart-admin-password
```

После создания постоянного администратора recovery credential нужно убрать из
pod environment. Настройка mail LB, TLS и публичных DNS records описана в
[Stalwart runbook](../docs/stalwart.md).

## Первичный доступ к Argo CD

Основной URL публикуется через Ingress и берётся из effective environment
contract. После `task infra:apply` его можно получить из Terraform output:

```bash
tofu -chdir=infrastructure output -raw argocd_url && echo
kubectl -n argocd get ingress argocd-server
```

Настройте DNS для выведенного hostname на адрес Ingress. Сертификат подписан
внутренним homelab CA; экспортировать CA для добавления в trust store клиентской
машины можно командой:

```bash
task ops:hosts-entries
task ops:export-root-ca
```

Первая команда читает фактически назначенные LoadBalancer IP из Kubernetes
status и выводит полный набор строк `IP hostname` для клиентского `/etc/hosts`.
Если хотя бы один адрес ещё не назначен, команда перечислит Pending-ресурсы и
не напечатает неполный набор. Проверьте вывод и добавьте нужные строки в
hosts-файл клиентской машины.

Для первого входа используйте логин `admin`. Сгенерированный Helm chart пароль
хранится только в Kubernetes Secret и выводится так:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

Если DNS или доверие CA ещё не настроены, откройте временный локальный доступ:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
```

Затем откройте `http://127.0.0.1:8080` и войдите как `admin`. После первого
входа смените пароль в `User Info -> Update Password`. Secret
`argocd-initial-admin-secret` предназначен только для начального доступа и
может быть удалён после проверки нового пароля.

Day-1 проверки собраны в
[коротком operations runbook](../docs/day1-operations.md).

Единая схема пользователей, групп, OIDC applications, callback URLs и
break-glass доступа описана в
[runbook авторизации платформы](../docs/platform-authentication.md).
