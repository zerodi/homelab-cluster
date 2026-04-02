# ArgoCD GitOps Scaffold

Этот каталог содержит каркас GitOps-репозитория для ArgoCD.

Структура:

- `bootstrap/`: root `Application` и базовые `AppProject`
- `platform/`: prereqs, runtime и bootstrap для `authentik` и `forgejo`
- `apps/`: demo `echo`

В `platform/` теперь также лежат отдельные runtime data services:

- `authentik-postgresql`
- `authentik-redis`
- `forgejo-postgresql`
- `forgejo-valkey`

И runtime network foundation:

- `gateway` application с `GatewayClass` и базовыми `Gateway`

Они считаются частью runtime/GitOps слоя и не должны возвращаться в `infrastructure/`.

Текущий baseline остаётся смешанным:

- `Ingress` продолжает обслуживать `authentik`, `forgejo`, `echo`
- Gateway API добавлен как foundation для будущего `HTTPRoute`-migration path

`echo` теперь служит reference manifest для минимального runtime baseline:

- явные `resources`
- `livenessProbe` / `readinessProbe`
- pod-level `seccompProfile`
- минимальный `NetworkPolicy`

По умолчанию каркас использует намеренно невалидный `repoURL`:

```text
https://git.example.invalid/replace-me/gitops.git
```

Перед использованием обязательно замените:

- значения в [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- `repoURL` во всех `Application`
- `sourceRepos` в `AppProject`
- домены `*.home.arpa`
- значения в `values.yaml`
- `authentik_host` и blueprint contents в `platform/authentik/prereqs/forgejo-sso-configmap.yaml`

Mapping того, какие файлы нужно обновить после изменения environment contract, описан в [docs/environment-contract.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/environment-contract.md).

Пока эти значения не заменены, bootstrap применять нельзя.

Базовый bootstrap после замены значений:

```bash
kubectl apply -n argocd -f argocd/bootstrap/root-application.yaml
```

Локальный SSH-стенд для тестов вынесен в `test-ssh-git/`. Он не является частью tracked GitOps source of truth и не должен влиять на содержимое манифестов в `argocd/`.
