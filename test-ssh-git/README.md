# Test SSH Git server for Argo CD

Этот локальный стенд предоставляет временный приватный Git source для первого
Argo CD sync. Он не является tracked source of truth и не изменяет содержимое
`argocd/`; все ключи, repository data и сгенерированные manifests остаются в
игнорируемых каталогах `test-ssh-git/`.

## Автоматизированный bootstrap

Укажите адрес этой машины, доступный из pod Argo CD, в `.env`:

```bash
TEST_SSH_GIT_HOSTNAME='192.168.100.10'
TEST_SSH_GIT_PORT='2222'
```

Затем выполните:

```bash
task gitops:test-ssh-bootstrap
```

Сценарий:

1. генерирует SSH host/client keys и Argo CD manifests;
2. создаёт bare `gitops.git` из текущего `argocd/`;
3. заменяет tracked GitOps repository URL на test SSH URL внутри seed;
4. собирает и запускает контейнер;
5. проверяет репозиторий через `git ls-remote`;
6. создаёт known-hosts ConfigMap и repository Secret в Argo CD;
7. применяет `Application/root-ssh`;
8. ждёт состояний `Synced` и `Healthy`.

Loopback-адреса запрещены: `127.0.0.1` внутри Argo CD pod указывает на сам pod,
а не на машину с Docker. Сервер должен работать до завершения первичного sync
или до перевода Applications на постоянный Git repository.

Остановка после cutover:

```bash
task gitops:test-ssh-stop
```

Постоянный repository и безопасное переключение `root-ssh` описаны в
[Forgejo cutover runbook](../docs/forgejo-argocd-cutover.md).

## Ручной recovery

Если Task-сценарий недоступен, подготовьте стенд вручную:

```bash
cd test-ssh-git
./setup.sh
```

Скрипт создаст:

- `keys/argocd_test_client_ed25519`
- `keys/known_hosts`
- `repo-data/gitops.git`
- `templates/argocd-repository-secret.yaml`
- `templates/root-application-ssh.yaml`

Каталоги `keys/` и `templates/` создаются с mode `0700`; приватные ключи и
`argocd-repository-secret.yaml` — с mode `0600`. Эти generated-файлы остаются
локальными и проверяются через `task check:local-security`.

## Запуск сервера

```bash
docker compose up -d --build
```

При ручном запуске без переменных сервер слушает `2222/tcp` и использует URL:

```text
ssh://git@git.localtest.me:2222/home/git/repos/gitops.git
```

`git.localtest.me` резолвится в `127.0.0.1`. Если Argo CD находится не на той
же машине, задайте перед `setup.sh` другой hostname:

```bash
TEST_SSH_GIT_HOSTNAME=192.168.1.10 ./setup.sh
```

## Проверка с локальной машины

```bash
GIT_SSH_COMMAND='ssh -i keys/argocd_test_client_ed25519 -o UserKnownHostsFile=keys/known_hosts' \
  git ls-remote ssh://git@git.localtest.me:2222/home/git/repos/gitops.git
```

## Подключение Argo CD

1. Добавьте `known_hosts` в `argocd-ssh-known-hosts-cm`.
2. Примените `templates/argocd-repository-secret.yaml`.
3. Примените `templates/root-application-ssh.yaml`.

Пример:

```bash
kubectl -n argocd create configmap argocd-ssh-known-hosts-cm \
  --from-file=ssh_known_hosts=keys/known_hosts \
  -o yaml --dry-run=client | kubectl apply -f -

kubectl apply -f templates/argocd-repository-secret.yaml
kubectl apply -f templates/root-application-ssh.yaml
```

## Остановка

```bash
docker compose down
```
