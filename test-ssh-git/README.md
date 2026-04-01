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

## Подготовка

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

По умолчанию сервер слушает `2222/tcp` и использует URL:

```text
ssh://git@git.localtest.me:2222/home/git/repos/gitops.git
```

`git.localtest.me` резолвится в `127.0.0.1`. Если ArgoCD находится не на той же машине, задайте перед `setup.sh` другой hostname:

```bash
SERVER_HOSTNAME=192.168.1.10 ./setup.sh
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
