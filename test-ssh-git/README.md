# Test SSH Git Server For ArgoCD

Этот каталог поднимает минимальный Git-over-SSH сервер для тестирования ArgoCD с приватным репозиторием.

Это локальный стенд. Он не является частью tracked GitOps source of truth и не должен менять содержимое `argocd/`.

Что делает стенд:

- поднимает `sshd` + `git-shell` в контейнере
- создаёт bare repo `gitops.git`
- заливает в него только tracked GitOps-каркас из `argocd/`:
  - `bootstrap/`
  - `platform/`
  - `apps/`
  - `README.md`
- генерирует клиентский SSH-ключ для ArgoCD
- генерирует манифесты:
  - ArgoCD repository secret
  - root application с `repoURL` по SSH

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

Сценарий автоматически:

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

Последовательность создания постоянного repository в Forgejo, настройки
Argo CD credentials и безопасного переключения `root-ssh` приведена в
[Forgejo cutover runbook](../docs/forgejo-argocd-cutover.md).

## Подготовка

Ручной вариант подготовки стенда:

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

## Запуск сервера

```bash
docker compose up -d --build
```

При ручном запуске без переменных сервер слушает `2222/tcp` и использует URL:

```text
ssh://git@git.localtest.me:2222/home/git/repos/gitops.git
```

`git.localtest.me` резолвится в `127.0.0.1`. Если ArgoCD находится не на той же машине, задайте перед `setup.sh` другой hostname:

```bash
TEST_SSH_GIT_HOSTNAME=192.168.1.10 ./setup.sh
```

## Проверка с локальной машины

```bash
GIT_SSH_COMMAND='ssh -i keys/argocd_test_client_ed25519 -o UserKnownHostsFile=keys/known_hosts' \
  git ls-remote ssh://git@git.localtest.me:2222/home/git/repos/gitops.git
```

## Подключение ArgoCD

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
