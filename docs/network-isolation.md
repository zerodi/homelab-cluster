# Runtime network isolation

Namespace isolation относится к runtime/GitOps-слою и управляется manifests
в `argocd/`. Базовый контракт применяется к `authentik`, `forgejo`, `harbor`,
`garage`, `woodpecker` и `observability`: все Pods выбраны namespace-wide
`default-deny` для ingress и egress, а каждый разрешённый поток объявлен
отдельно.

## Модель policy

- Kubernetes `NetworkPolicy` описывает DNS, namespace/pod selectors и
  service-to-service flows.
- `CiliumNetworkPolicy` используется только там, где Kubernetes API не имеет
  подходящего peer selector: Cilium Gateway имеет identity `ingress`, API
  server — `kube-apiserver`, node-local kubelet/metrics — `host`, внешний
  интернет — `world`.
- Gateway допускается только к конкретному backend selector и container port;
  правило `namespaceSelector: {}` не используется.
- PostgreSQL, Redis и Valkey chart-owned policies отключены. Их исходные
  defaults разрешали ingress на service port от любого источника и
  unrestricted egress, а объединяющая семантика policy не позволяла бы
  перекрыть это дополнительным `default-deny`.
- OpenBao и ESO не являются peers application Pods. ESO читает OpenBao и
  создаёт Kubernetes Secret через API server; runtime workloads используют
  уже материализованные Secrets.

## Матрица разрешённых потоков

| Namespace / source | Destination | Ports | Назначение |
| --- | --- | --- | --- |
| любой из шести namespaces | CoreDNS | TCP/UDP 53 | DNS |
| Cilium `ingress` | Authentik server | TCP 9000 | HTTPS Gateway backend |
| Authentik server/worker | Authentik PostgreSQL / Redis | TCP 5432 / 6379 | state/cache |
| Authentik server/worker | Cilium `world` | TCP 443 | внешние HTTPS integrations |
| Cilium `ingress` | Forgejo | TCP 3000 | HTTPS Gateway backend |
| Forgejo | Forgejo PostgreSQL / Valkey | TCP 5432 / 6379 | state/cache |
| Forgejo | Authentik Gateway | TCP 443 | OIDC discovery/token/userinfo |
| Forgejo | Cilium `world` | TCP 22, 80, 443 | Git remotes, webhooks, updates |
| Cilium `ingress` | Harbor nginx | TCP 8080 | HTTPS Gateway backend |
| Harbor components | Harbor components | component ports | registry internal API |
| Harbor components | Harbor PostgreSQL / Valkey | TCP 5432 / 6379 | state/cache |
| Harbor components | OTel Collector | TCP 4318 | OTLP traces |
| Harbor components | Authentik Gateway / `world` | TCP 443 | OIDC и external registry/Trivy HTTPS |
| Cilium `ingress` | Garage S3 | TCP 3900 | HTTPS Gateway backend |
| Velero | Garage S3 | TCP 3900 | backup object storage |
| Garage peer | Garage peer | TCP 3901 | cluster RPC |
| Cilium `ingress` | Woodpecker server | TCP 8000 | HTTPS Gateway backend |
| Woodpecker agent | Woodpecker server | TCP 9000 | agent gRPC |
| Woodpecker agent | Kubernetes API | TCP 443/6443 | Kubernetes backend |
| Woodpecker workloads | Forgejo Gateway / `world` | TCP 22, 80, 443 | SCM и pipeline network |
| Harbor / OTel Agent / operator host | OTel Collector | TCP 4318 / 4317 | telemetry ingest / smoke |
| OTel Collector | VictoriaMetrics, Loki, Tempo, Grafana, OTel Agent | TCP 8428, 3100, 3200/4317, 3000, 8888 | export, health и metrics |
| OTel Collector | selected platform metrics Pods / Cilium host and remote nodes | TCP 8000, 8085, 9121, 9153, 9962-9965 | Prometheus scrape |
| OTel Collector / Agent | Kubernetes API | TCP 443/6443 | discovery и metadata |
| OTel Agent | node host | TCP 10250 | kubelet metrics |
| Grafana | VictoriaMetrics / Loki / Tempo | TCP 8428 / 3100 / 3200 | datasources |
| Grafana | OTel Collector | TCP 4318 / 8888 | synthetic OTLP и exporter metrics smoke |
| Grafana | Authentik Gateway | TCP 443 | OIDC |
| Grafana | Echo | TCP 80 | внутренний alert webhook smoke |

SMTP egress в этих namespaces не открыт: ни один текущий workload не имеет
mailer endpoint в declarative config. При добавлении mailer сначала задайте
точный Stalwart peer и порт 587, затем расширьте соответствующую policy и эту
матрицу.

## Проверка rollout

После публикации проверяйте namespaces по одному:

```bash
kubectl --kubeconfig out/kubeconfig -n <namespace> get networkpolicy,ciliumnetworkpolicy
kubectl --kubeconfig out/kubeconfig -n <namespace> get pods
kubectl --kubeconfig out/kubeconfig -n <namespace> get events --sort-by=.lastTimestamp
```

Положительные проверки выполняются существующими runtime gates:

```bash
task ops:post-argocd-check
task ops:observability-smoke
task ops:harbor-smoke
```

Дополнительно проверьте Authentik/Forgejo/Garage/Woodpecker через их Gateway и
убедитесь, что свежий Velero Backup имеет фазу `Completed`. Для отрицательной
проверки временный probe без workload labels в одном из изолированных
namespaces должен резолвить DNS, но не устанавливать TCP-соединение с
`garage-s3.garage.svc.cluster.local:3900`; probe всегда удаляется после теста.
Ожидаемые policy drops проверяются через Hubble, без чтения Secret values.

При отказе откатывайте policy только в owning runtime namespace. Не переносите
эти ресурсы в `cluster/` или `infrastructure/`.
