# ArgoCD GitOps Scaffold

Этот каталог содержит каркас GitOps-репозитория для ArgoCD.

Структура:

- `bootstrap/`: root `Application` и базовые `AppProject`
- `platform/`: prereqs, runtime и bootstrap для `authentik`, `forgejo` и observability
- `apps/`: demo `echo`

В `platform/` теперь также лежат отдельные runtime data services:

- `authentik-postgresql`
- `authentik-redis`
- `forgejo-postgresql`
- `forgejo-valkey`
- `victoria-metrics`
- `loki`
- `tempo`
- `grafana`
- `otel-collector`
- `hubble`

Observability baseline сейчас такой:

- `OTel Collector` принимает OTLP и одновременно скрапит собственные метрики, `VictoriaMetrics`, `Loki` и `Tempo`
- `OTel Collector` также скрапит `hubble-metrics` из `kube-system`
- `Grafana` получает заранее provisioned datasources, dashboards и базовые alert rules
- `Tempo` работает через `tempo-distributed`, а datasource и collector идут через `tempo-gateway`

И runtime network foundation:

- `gateway` application с `GatewayClass` и базовыми `Gateway`

Они считаются частью runtime/GitOps слоя и не должны возвращаться в `infrastructure/`.

Текущий baseline такой:

- `authentik`, `echo`, `forgejo` и `grafana` уже переведены на namespaced `Gateway` + `HTTPRoute`
- `hubble` опубликован через shared `internal` gateway как cluster-observability endpoint
- shared `gateway` application даёт только общий HTTP foundation и `GatewayClass`
- Gateway API теперь является реальным runtime path, а не только foundation

Текущая policy-модель такая:

- shared gateways в `platform/gateway` не владеют app-specific TLS secret или hostname routing
- app-owned routing и TLS termination живут в namespace самого приложения
- для `authentik`, `echo`, `forgejo` и `grafana` это выражено через namespaced `Gateway` + `HTTPRoute`

`echo` теперь служит reference manifest для минимального runtime baseline:

- явные `resources`
- `livenessProbe` / `readinessProbe`
- pod-level `seccompProfile`
- минимальный `NetworkPolicy`
- namespaced `Gateway`
- `HTTPRoute` c HTTP -> HTTPS redirect

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
