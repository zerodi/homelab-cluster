# Platform runtime layout

`argocd/platform` разделён по функциональным доменам. В каждом домене
`applications/` содержит только Argo CD `Application`, а каталоги компонентов
содержат читаемый ими Helm/Kustomize payload.

| Домен | Компоненты |
| --- | --- |
| `core/` | Gateway API resources, Hubble, Reloader |
| `identity/` | Authentik |
| `delivery/` | Forgejo, Harbor, Woodpecker |
| `storage/` | Garage, Velero |
| `observability/` | VictoriaMetrics, Loki, Tempo, OTel Collector, Grafana |
| `policy/` | Kyverno и platform policies |
| `messaging/` | Stalwart |

Root Application рендерит `platform/kustomization.yaml`, который подключает
только `applications/`-индексы доменов. Component payload не добавляется в
корневой Kustomize напрямую: его жизненным циклом владеет дочерняя Application.

## Добавление компонента

1. Выберите домен и создайте payload в `platform/<domain>/<component>/`.
2. Добавьте Application manifests в
   `platform/<domain>/applications/<component>/`.
3. Зарегистрируйте их в domain `applications/kustomization.yaml` в порядке
   зависимостей; фактический порядок применения задавайте через sync waves.
4. Добавьте namespace в `AppProject/platform` и обновите environment/OpenBao
   contracts, если компонент использует hostnames или secrets.

Не помещайте runtime manifests в `cluster/` или `infrastructure/`.
