# Cutover Argo CD с test-ssh-git на Forgejo

Этот runbook описывает перевод уже развёрнутого через `test-ssh-git` runtime
слоя на постоянный GitOps repository в Forgejo. До завершения проверки не
останавливайте test SSH server и не удаляйте `Application/root-ssh`.

## Автоматизированный cutover

Основной greenfield-путь выполняется task-командой. Предварительно:

- дождитесь `Synced/Healthy` для `Application/forgejo`;
- закоммитьте все изменения в `argocd/`;
- экспортируйте `BAO_ADDR`, `BAO_CACERT` и административный `BAO_TOKEN`.

```bash
export BAO_ADDR='https://127.0.0.1:8200'
export BAO_CACERT="$PWD/out/homelab-root-ca.crt"
export BAO_TOKEN='...'
task gitops:forgejo-cutover
```

Если локальный `BAO_ADDR=https://127.0.0.1:8200` недоступен, task сам поднимает
временный port-forward к `service/openbao` и останавливает его при завершении.
Уже работающий port-forward переиспользуется и не останавливается.

Task идемпотентно выполняет весь сценарий:

1. читает Forgejo hostname, repository URL и namespace из effective
   environment contract;
2. экспортирует TLS trust bundle из Certificate Secret Forgejo и использует
   его без `insecureSkipVerify`;
3. создаёт organization, private repository и restricted пользователя
   `argocd` через Forgejo API;
4. выдаёт пользователю только `Read` и создаёт token со scope
   `read:repository`, ограниченный целевым repository;
5. записывает credential в `secret/platform/argocd/repository` в OpenBao;
6. публикует committed subtree `argocd/` в ветку `main`, не помещая password
   или token в URL, Git config либо repository;
7. настраивает `argocd-tls-certs-cm`, применяет ExternalSecret и ждёт его
   готовности;
8. переключает `root-ssh` на Forgejo, ждёт `Synced/Healthy`, применяет
   канонический `root` и снова проверяет источник;
9. удаляет временные Application/Secret и останавливает test SSH Git только
   после успешных проверок.

Если проверка завершается ошибкой, временный bootstrap не удаляется. Повторный
запуск продолжает с уже созданными Forgejo/OpenBao ресурсами. Последующие
разделы описывают те же операции вручную и используются для диагностики или
recovery.

## 1. Ручная подготовка Forgejo

Проверьте, что Forgejo доступен и его Application готово:

```bash
kubectl -n argocd get application forgejo
kubectl -n forgejo get pods
```

В Forgejo:

1. создайте organization `platform`;
2. создайте пустой repository `gitops` без README, `.gitignore` и license;
3. создайте отдельного пользователя `argocd`;
4. предоставьте ему только `Read` для `platform/gitops`;
5. создайте token с доступом только к этому repository и scope
   `read:repository`.

Forgejo позволяет ограничить token конкретным repository; используйте наиболее
узкий доступ. Подробности приведены в
[официальном описании token scopes](https://forgejo.org/docs/latest/user/token-scope/).

Для текущего environment постоянный URL выглядит так:

```bash
export FORGEJO_HOST='git.home.arpa'
export FORGEJO_GITOPS_URL="https://${FORGEJO_HOST}/platform/gitops.git"
```

Не добавляйте token в URL, shell history или Git remote.

## 2. Подготовка GitOps tree

Замените `gitops.repo_url` в `envs/homelab.override.yaml` на
`https://git.home.arpa/platform/gitops.git`, затем синхронизируйте все
tracked consumers:

```bash
task sync-env-contract
task check:env-contract
task check:kustomize-bootstrap
task check:kustomize-platform
```

Не переносите `test-ssh-git/repo-data/gitops.git`: внутри seed URL намеренно
переписаны на временный SSH endpoint. Пока не отправляйте subtree: сначала
добавьте tracked credential manifest из шага 4.

## 3. Доверие TLS-сертификату Forgejo

TLS-сертификат Forgejo проверяют два независимых клиента: локальный Git во
время первого push и `argocd-repo-server` при последующих sync. Экспортируйте
полный certificate bundle, который использует Forgejo Gateway, и передайте его
локальному Git в текущей shell session:

```bash
kubectl -n forgejo get secret forgejo-tls \
  -o go-template='{{ index .data "tls.crt" }}' | base64 -d \
  > out/forgejo-repository-trust.pem
export GIT_SSL_CAINFO="$PWD/out/forgejo-repository-trust.pem"
```

Затем добавьте тот же bundle для Forgejo hostname в специальный Argo CD
ConfigMap:

```bash
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file="${FORGEJO_HOST}=out/forgejo-repository-trust.pem" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Не используйте `insecureSkipVerify`. Argo CD хранит доверенные Git TLS CA в
`argocd-tls-certs-cm`; изменение может распространяться на repo-server
несколько минут. См.
[документацию Argo CD по private repositories](https://argo-cd.readthedocs.io/en/latest/user-guide/private-repositories/).

## 4. Credential через OpenBao и ESO

Запишите username и token в OpenBao. Значение token не должно попадать в Git:

```bash
export FORGEJO_ARGOCD_TOKEN='...'
bao kv put secret/platform/argocd/repository \
  username='argocd' \
  token="$FORGEJO_ARGOCD_TOKEN"
unset FORGEJO_ARGOCD_TOKEN
```

Создайте `argocd/bootstrap/forgejo-gitops-repository.yaml` со следующим
`ExternalSecret` и добавьте файл в `argocd/bootstrap/kustomization.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: forgejo-gitops-repository
  namespace: argocd
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: openbao
  target:
    name: forgejo-gitops-repository
    creationPolicy: Owner
    template:
      engineVersion: v2
      metadata:
        labels:
          argocd.argoproj.io/secret-type: repository
      data:
        type: git
        name: forgejo-gitops
        url: https://git.home.arpa/platform/gitops.git
        username: "{{ .username }}"
        password: "{{ .token }}"
  data:
    - secretKey: username
      remoteRef:
        key: platform/argocd/repository
        property: username
    - secretKey: token
      remoteRef:
        key: platform/argocd/repository
        property: token
```

Закоммитьте изменения, затем создайте ветку, в которой содержимое `argocd/`
становится корнем repository, и отправьте её в Forgejo. Для первого push
используйте отдельные credentials оператора с правом записи и token со scope
`write:repository`. Read-only token пользователя `argocd` из этого runbook
предназначен только для pull со стороны Argo CD и не подходит для push.

Git, запущенный из VS Code, может наследовать `GIT_ASKPASS`, указывающий на уже
закрытый IPC socket. Следующая команда на один запуск отключает VS Code askpass
и credential helper, после чего Git запросит username и write token прямо в
терминале:

```bash
git subtree split --prefix=argocd -b forgejo-gitops-main
env -u GIT_ASKPASS \
  -u SSH_ASKPASS \
  -u VSCODE_GIT_ASKPASS_MAIN \
  -u VSCODE_GIT_ASKPASS_NODE \
  -u VSCODE_GIT_ASKPASS_EXTRA_ARGS \
  -u VSCODE_GIT_IPC_HANDLE \
  GIT_TERMINAL_PROMPT=1 \
  GIT_SSL_CAINFO="$PWD/out/forgejo-repository-trust.pem" \
  git -c credential.helper= \
    push "$FORGEJO_GITOPS_URL" forgejo-gitops-main:main
unset GIT_SSL_CAINFO
```

На prompts укажите username оператора Forgejo и write token вместо password.
Token не вставляйте в repository URL и не сохраняйте в Git config.

Убедитесь в Forgejo UI, что ветка `main` содержит каталоги `bootstrap/`,
`platform/` и `apps/`. Для разрыва bootstrap-зависимости один раз примените тот
же tracked `ExternalSecret` напрямую; после cutover им будет владеть GitOps
repository:

```bash
kubectl apply -f argocd/bootstrap/projects/bootstrap.yaml
kubectl apply -f argocd/bootstrap/argocd-repo-server-forgejo-networkpolicy.yaml
kubectl apply -f argocd/bootstrap/forgejo-gitops-repository.yaml
kubectl -n argocd wait \
  --for=condition=Ready \
  externalsecret/forgejo-gitops-repository \
  --timeout=2m
kubectl -n argocd get secret forgejo-gitops-repository
```

Argo CD распознаёт Secret по label
`argocd.argoproj.io/secret-type: repository`; для HTTPS используются поля
`username` и `password`. Формат описан в
[Argo CD declarative setup](https://argo-cd.readthedocs.io/en/latest/operator-manual/declarative-setup/#repositories).

Если repository публичный, отдельный token и `ExternalSecret` не нужны, но
настройка доверенного CA остаётся обязательной.

## 5. Безопасное переключение root Application

Сначала переключите существующий `root-ssh` на Forgejo. Это позволяет одному
root Application обновить дочерние Applications на постоянный `repoURL`, не
создавая конфликт между старым и новым источником:

```bash
kubectl -n argocd patch application root-ssh \
  --type=json \
  -p="[{\"op\":\"replace\",\"path\":\"/spec/source/repoURL\",\"value\":\"${FORGEJO_GITOPS_URL}\"}]"
kubectl -n argocd get application root-ssh -w
```

Дождитесь `Synced` и `Healthy`, затем примените канонический root Application:

```bash
task gitops:preflight
task gitops:apply-bootstrap
kubectl -n argocd get applications
```

Убедитесь, что `Application/root` и все дочерние Applications имеют состояния
`Synced` и `Healthy` и используют Forgejo URL. Только после этого удалите
временный root и repository credential:

```bash
kubectl -n argocd delete application root-ssh
kubectl -n argocd delete secret test-ssh-gitops-repo
task gitops:test-ssh-stop
```

Не удаляйте `argocd-ssh-known-hosts-cm`: он является стандартным объектом Argo
CD и может использоваться другими SSH repositories.

## 6. Проверка и ротация

```bash
kubectl -n argocd get application root \
  -o jsonpath='{.spec.source.repoURL}{" "}{.status.sync.status}{" "}{.status.health.status}{"\n"}'
task ops:post-argocd-check
```

Для ротации создайте новый read-only token в Forgejo и целиком перезапишите
`secret/platform/argocd/repository` в OpenBao. ESO обновит Kubernetes Secret;
ручное изменение materialized Secret не требуется.
