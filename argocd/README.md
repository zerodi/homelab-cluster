# Argo CD runtime deployment

Этот каталог содержит отдельный runtime/GitOps слой. Он применяется только
после завершения `cluster/` и `infrastructure/` и не является частью OpenTofu
bootstrap entrypoint.

## Структура и ownership

- `bootstrap/` содержит root Applications, AppProjects и repository metadata;
- `platform/applications/` индексирует дочерние platform Applications;
- `platform/<component>/` содержит Helm values или Kustomize payload;
- `apps/` содержит application workloads вне platform baseline.

`platform/kustomization.yaml` подключает только application index, поэтому root
Application не становится совладельцем ресурсов дочерних приложений. Правила
добавления компонентов описаны в [`platform/README.md`](platform/README.md).

Runtime secrets остаются в OpenBao и доставляются через ESO. В `argocd/`
хранятся только `ExternalSecret` references, но не secret values.

## Перед bootstrap

Должны быть готовы cert-manager, trust-manager, OpenBao, ESO, LINSTOR
StorageClass и Argo CD:

```bash
task infra:health
```

Синхронизируйте non-secret environment consumers по
[environment contract](../docs/environment-contract.md), затем проверьте
runtime secret contract из [day-0 runbook](../docs/day0-bootstrap.md#5-запись-стартовых-runtime-secrets):

```bash
task sync-env-contract
task check:env-contract
task check:versions
task gitops:preflight
```

`gitops:preflight` отклоняет scaffold coordinates и проверяет обязательные
OpenBao paths/keys без вывода значений.

## Первичный bootstrap

Выберите один Git source.

### Временный test-SSH

```bash
export TEST_SSH_GIT_HOSTNAME='192.168.100.10'
task gitops:test-ssh-bootstrap
```

Команда применяет `Application/root-ssh` и ждёт `Synced`/`Healthy`. Endpoint
должен быть доступен из Argo CD pods. Устройство стенда и ручной recovery
описаны в [`test-ssh-git/README.md`](../test-ssh-git/README.md).

### Готовый постоянный repository

```bash
task gitops:apply-bootstrap
```

Команда повторяет preflight, применяет
`bootstrap/root-application.yaml` и ждёт `Application/root`.

## Cutover на Forgejo

После появления Forgejo выполните проверяемый cutover временного source:

```bash
task ops:openbao-port-forward-start
export BAO_ADDR='http://127.0.0.1:8200'
export BAO_TOKEN='...'
task gitops:forgejo-cutover
```

Перед запуском `argocd/` должен быть закоммичен без локальных изменений. Полный
сценарий, security properties и recovery находятся в
[Forgejo cutover runbook](../docs/forgejo-argocd-cutover.md).

## Публикация последующих изменений

После cutover публикуйте только закоммиченный `argocd/` subtree:

```bash
git add argocd
git commit -m 'update runtime GitOps'
task gitops:push
```

Task проверяет environment contract и Kustomize, запрещает push при
незакоммиченных изменениях в `argocd/`, валидирует Forgejo TLS и не выполняет
force-push. По умолчанию write credential читается из bootstrap admin Secret.
Отдельные `FORGEJO_GIT_USERNAME` и `FORGEJO_GIT_PASSWORD` должны передаваться
вместе и не сохраняются в Git config или repository URL.

## Проверка результата

```bash
task ops:post-argocd-check
kubectl -n argocd get applications
```

Проверка должна подтверждать `Synced` и `Healthy` для root и дочерних
Applications, готовность ClusterSecretStore/ExternalSecrets и runtime
workloads. Day-1 команды собраны в
[operations runbook](../docs/day1-operations.md).

## Первичный доступ к Argo CD

Получите URL и состояние Ingress:

```bash
tofu -chdir=infrastructure output -raw argocd_url && echo
kubectl -n argocd get ingress argocd-server
```

Для клиентского DNS/hosts и доверия внутреннему CA используйте:

```bash
task ops:hosts-entries
task ops:export-root-ca
```

Начальный логин — `admin`; пароль существует в bootstrap Secret до ротации:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

До настройки DNS и CA можно открыть локальный port-forward:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
```

После проверки нового пароля bootstrap Secret можно удалить. Общая модель
пользователей, OIDC и break-glass доступа находится в
[runbook авторизации](../docs/platform-authentication.md); application-specific
операции — в соответствующих runbook из [индекса документации](../docs/README.md).
