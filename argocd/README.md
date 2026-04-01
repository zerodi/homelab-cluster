# ArgoCD GitOps Scaffold

Этот каталог содержит каркас GitOps-репозитория для ArgoCD.

Структура:

- `bootstrap/`: root `Application` и базовые `AppProject`
- `platform/`: prereqs, runtime и bootstrap для `authentik` и `forgejo`
- `apps/`: demo `echo`

По умолчанию каркас использует намеренно невалидный `repoURL`:

```text
https://git.example.invalid/replace-me/gitops.git
```

Перед использованием обязательно замените:

- `repoURL` во всех `Application`
- `sourceRepos` в `AppProject`
- домены `*.home.arpa`
- значения в `values.yaml`
- `authentik_host` и blueprint contents в `platform/authentik/prereqs/forgejo-sso-settings-configmap.yaml`

Пока эти значения не заменены, bootstrap применять нельзя.

Базовый bootstrap после замены значений:

```bash
kubectl apply -n argocd -f argocd/bootstrap/root-application.yaml
```

Локальный SSH-стенд для тестов вынесен в `test-ssh-git/`. Он не является частью tracked GitOps source of truth и не должен влиять на содержимое манифестов в `argocd/`.
