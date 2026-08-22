# Observability: архитектура, настройка и эксплуатация

Observability относится к runtime/GitOps-слою и управляется Argo CD из
[`argocd/platform/observability`](../argocd/platform/observability). OpenTofu
entrypoints `cluster/` и `infrastructure/` не создают эти ресурсы.

Документ описывает фактически реализованный стек, его первичную настройку,
подключение приложений, проверку и типовые изменения. Полная последовательность
greenfield-развёртывания остаётся в [day-0 runbook](day0-bootstrap.md).

## Назначение и поток данных

Стек состоит из шести компонентов:

| Компонент | Назначение | Вход | Хранилище или выход |
| --- | --- | --- | --- |
| OpenTelemetry Collector gateway | приём и маршрутизация телеметрии, cluster metrics/events, Prometheus scraping и synthetic checks | OTLP gRPC/HTTP, Kubernetes API и `/metrics` targets | VictoriaMetrics, Loki, Tempo |
| OpenTelemetry Agent | node-local сбор container logs, host и kubelet metrics, Kubernetes metadata | файлы CRI/containerd и kubelet | Collector gateway |
| VictoriaMetrics Single | метрики и PromQL/MetricsQL запросы | Prometheus remote write | LINSTOR PVC, retention `30d` |
| Loki SingleBinary | логи и LogQL запросы | OTLP/HTTP | LINSTOR PVC |
| Tempo monolithic | трейсы, TraceQL, service graphs и span metrics | OTLP/gRPC от Collector | локальный backend на LINSTOR PVC |
| Grafana | UI, datasources, dashboards и alert rules | VictoriaMetrics, Loki, Tempo | LINSTOR PVC для состояния Grafana |

Поток телеметрии выглядит так:

```text
nodes -- logs/host/kubelet metrics --> OTel Agent --> OTel Collector gateway
applications -- OTLP signals ----------------------> OTel Collector gateway
platform /metrics targets -------------------------> Prometheus receiver

Collector gateway -- remote write --> VictoriaMetrics
Collector gateway -- OTLP/HTTP ----> Loki
Collector gateway -- OTLP/gRPC ----> Tempo

Grafana ---------------------------> VictoriaMetrics / Loki / Tempo
```

Grafana — единственный компонент, опубликованный наружу. VictoriaMetrics,
Loki, Tempo и Collector доступны через ClusterIP только внутри кластера.

## Текущий эксплуатационный профиль

Перед эксплуатацией учитывайте следующие свойства:

- Collector gateway работает как singleton `Deployment`, а node agents — как
  `DaemonSet` с checkpoint и persistent sending queue на каждом узле;
- VictoriaMetrics и Loki работают в single-node режиме;
- Tempo работает в monolithic режиме с LINSTOR PVC и retention `168h`;
- container logs собираются node-local `filelog` receiver, а OTLP logs могут
  отправляться приложениями напрямую в gateway;
- трейсы также появляются только от приложений с OTLP instrumentation;
- Prometheus Operator и `ServiceMonitor` не используются; targets перечислены
  непосредственно и через opt-in service annotations;
- Grafana alert rules, webhook contact point и routing policy создаются
  декларативно; webhook URL поступает из OpenBao через ESO;
- Loki и Tempo не используют multitenancy/auth внутри cluster network;
- namespace защищён baseline NetworkPolicy: OTLP и Grafana доступны другим
  namespaces, backends остаются namespace-local, egress разрешает Kubernetes
  API, kubelet, internal services, DNS и HTTPS webhook;
- текущая конфигурация оптимизирована для homelab, а не для HA или
  multi-cluster telemetry.

## Владение файлами

| Область | Путь |
| --- | --- |
| Argo CD Applications и sync waves | [`platform/observability/applications`](../argocd/platform/observability/applications) |
| Namespace, ESO, TLS и Gateway API | [`platform/observability/prereqs`](../argocd/platform/observability/prereqs) |
| Grafana, datasources, dashboards, alerts | [`grafana/values.yaml`](../argocd/platform/observability/grafana/values.yaml) |
| Prometheus scraping, cluster telemetry и OTLP pipelines | [`otel-collector/values.yaml`](../argocd/platform/observability/otel-collector/values.yaml) |
| Container logs, host и kubelet metrics | [`otel-agent/values.yaml`](../argocd/platform/observability/otel-agent/values.yaml) |
| Метрики: retention, PVC, resources | [`victoria-metrics/values.yaml`](../argocd/platform/observability/victoria-metrics/values.yaml) |
| Логи: schema, PVC, resources | [`loki/values.yaml`](../argocd/platform/observability/loki/values.yaml) |
| Трейсы: topology, PVC, resources | [`tempo/values.yaml`](../argocd/platform/observability/tempo/values.yaml) |
| Hostname, namespace, storage и retention contract | [`envs/homelab.yaml`](../envs/homelab.yaml) |
| Версии Helm charts | [`versions.yaml`](../versions.yaml) |

Не меняйте сгенерированные hostnames, Gateway IP, storage class, secret names
или chart versions только в одном consumer. Для них используются environment и
version contracts.

## Зависимости и порядок синхронизации

До GitOps bootstrap должны быть готовы:

- Argo CD;
- cert-manager и `ClusterIssuer/letsencrypt-cloudflare`;
- trust-manager и `ConfigMap/homelab-root-ca` в помеченных namespace;
- OpenBao, Kubernetes auth и `ClusterSecretStore/openbao`;
- External Secrets Operator;
- Cilium Gateway API и LoadBalancer IPAM;
- LINSTOR StorageClass из environment contract;
- Authentik для входа в Grafana через OIDC.

Applications синхронизируются в следующем порядке:

| Sync wave | Application | Результат |
| --- | --- | --- |
| `5` | `observability-prereqs` | namespace, ExternalSecrets, Certificate, Gateway и HTTPRoutes |
| `10` | `victoria-metrics` | metrics backend |
| `10` | `loki` | logs backend |
| `10` | `tempo` | traces backend |
| `20` | `otel-collector` | telemetry receiver, scraper и exporters |
| `20` | `otel-agent` | node logs, host и kubelet telemetry |
| `25` | `grafana` | UI, datasources, dashboards и alerts |

Sync waves задают порядок отправки Applications родительским приложением. Они
не заменяют readiness-проверки между независимыми Helm releases, поэтому при
первом sync проверяйте health каждого компонента.

## Настройка окружения

### Hostname, namespace, storage и retention

Базовые значения находятся в environment contract:

```yaml
service_subdomains:
  grafana: grafana

platform:
  observability:
    namespace: observability
    grafana:
      admin_secret_name: grafana-admin-secret
    victoriametrics:
      retention: 30d
    loki:
      retention: 336h
    tempo:
      retention: 168h
```

StorageClass берётся из общего контракта Piraeus/LINSTOR. Полный Grafana FQDN,
URL и LoadBalancer IP вычисляются автоматически из `cluster.base_domain`,
`cluster.ipv4_cidr` и короткого поддомена.

Для environment-specific отличий измените
`envs/homelab.override.yaml`, затем синхронизируйте tracked consumers:

```bash
task render-env-contract
task sync-env-contract
task check:env-contract
```

После `task sync-env-contract` обязательно просмотрите `git diff`. Команда
обновляет не только observability, но и другие consumers общего environment
contract.

### Runtime secrets

OpenBao остаётся единственным источником runtime secrets. Для observability
нужны два KV v2 path:

| OpenBao path | Ключи | Kubernetes consumer |
| --- | --- | --- |
| `secret/platform/observability/grafana` | `username`, `password` | `Secret/grafana-admin-secret` в `observability` |
| `secret/platform/observability/grafana-oidc` | `client_id`, `client_secret` | `Secret/grafana-oidc` в `observability` и Authentik blueprint в `authentik` |

В greenfield-сценарии создайте только отсутствующие записи:

```bash
task ops:seed-runtime-secrets
task ops:openbao-runtime-preflight
```

Helper генерирует локально управляемые credentials, записывает переданный
webhook URL и не перезаписывает существующие paths. Не копируйте значения в
Git, Helm values, tfvars или Terraform state.

Одна и та же OIDC-пара используется двумя декларативными consumers:

1. ESO материализует переменные `GF_AUTH_GENERIC_OAUTH_CLIENT_ID` и
   `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET` для Grafana.
2. ESO рендерит Authentik blueprint, который создаёт confidential provider и
   application `grafana` с теми же credentials.

Redirect URI должен быть строго равен:

```text
https://<grafana-host>/login/generic_oauth
```

Доступ к Authentik application ограничен группой администратора из environment
contract. Член этой группы получает в Grafana роль `GrafanaAdmin`; текущая
policy Authentik не пропускает остальных пользователей, даже несмотря на
fallback `Viewer` в Grafana role expression.

## Greenfield-развёртывание

Observability не применяется отдельной OpenTofu-командой. После завершения
`task cluster:apply`, `task infra:apply`, init/unseal OpenBao и заполнения
runtime secret contract выполните стандартный GitOps bootstrap:

```bash
task check:env-contract
task check:versions
task gitops:preflight
task gitops:apply-bootstrap
```

Для временного test-SSH source используйте вариант из
[`argocd/README`](../argocd/README.md), не применяйте observability manifests
вручную через `kubectl apply`.

Проверьте Applications:

```bash
kubectl -n argocd get applications \
  observability-prereqs victoria-metrics loki tempo otel-collector otel-agent grafana
```

Ожидаемое состояние — `Synced` и `Healthy` для всех семи Applications.

Проверьте namespace, secrets, certificate, route и workloads:

```bash
kubectl -n observability get externalsecret,secret
kubectl -n observability get certificate,gateway,httproute
kubectl -n observability get pods,svc,pvc
kubectl -n observability get events --sort-by=.lastTimestamp
```

Комплексная post-bootstrap проверка также включает observability:

```bash
task ops:post-argocd-check
```

## Доступ к Grafana

Получите актуальный hostname и адрес Gateway из environment contract и
состояния кластера:

```bash
task ops:hosts-entries
kubectl -n observability get gateway grafana
kubectl -n observability get certificate grafana-tls
```

Если клиент не использует DNS для lab-зоны, добавьте строку, напечатанную
`task ops:hosts-entries`, в локальный hosts-файл. Для доверия внутренним
сервисам и диагностики CA доступна команда:

```bash
task ops:export-root-ca
```

Основной вход выполняется через Authentik. Локальный Grafana admin остаётся
break-glass credential и читается из OpenBao/ESO, а не из репозитория. Получить
сводку endpoint и credentials можно только в доверенном операторском терминале:

```bash
task ops:credentials
```

Команда выводит секреты на экран; не сохраняйте её вывод в shell history,
тикеты или логи CI.

## Подключение приложения по OTLP

Collector принимает OTLP внутри кластера по адресам:

```text
gRPC: otel-collector.observability.svc.cluster.local:4317
HTTP: http://otel-collector.observability.svc.cluster.local:4318
```

Типовой набор переменных для workload, использующего OTLP/HTTP:

```yaml
env:
  - name: OTEL_SERVICE_NAME
    value: my-service
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://otel-collector.observability.svc.cluster.local:4318
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: http/protobuf
  - name: OTEL_RESOURCE_ATTRIBUTES
    value: service.namespace=my-namespace,deployment.environment=homelab
```

Конкретные SDK могут использовать signal-specific variables
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`, `..._LOGS_ENDPOINT` и
`..._TRACES_ENDPOINT`, а также добавлять к HTTP endpoint пути
`/v1/metrics`, `/v1/logs` и `/v1/traces`. Следуйте правилам SDK приложения и
проверьте effective configuration в его startup log.

Рекомендуемые resource attributes:

- стабильный `service.name`;
- `service.namespace` для логической группы сервисов;
- `service.version` для correlation с release;
- `deployment.environment.name` или используемый SDK-эквивалент;
- Kubernetes resource attributes от auto-instrumentation или resource
  detector, если он доступен.

Не публикуйте OTLP Service через внешний Gateway без отдельной модели
аутентификации, TLS и ограничения tenants.

### Проверка приёма OTLP

Смотрите метрики самого Collector в Grafana dashboard
`OpenTelemetry Collector` или выполните запросы к VictoriaMetrics через
Grafana Explore:

```promql
sum by (receiver) (rate(otelcol_receiver_accepted_spans[5m]))
sum by (receiver) (rate(otelcol_receiver_accepted_log_records[5m]))
sum by (receiver) (rate(otelcol_receiver_accepted_metric_points[5m]))
```

Ошибки exporters:

```promql
sum by (exporter) (rate(otelcol_exporter_send_failed_spans[5m]))
sum by (exporter) (rate(otelcol_exporter_send_failed_log_records[5m]))
sum by (exporter) (rate(otelcol_exporter_send_failed_metric_points[5m]))
```

Если счётчик accepted растёт, а соответствующий sent не растёт или растёт
failed, проблема находится между pipeline Collector и backend, а не на стороне
instrumented приложения.

## Добавление Prometheus scrape target

Collector сейчас собирает:

- собственные метрики;
- VictoriaMetrics, Loki, Tempo и Grafana;
- Hubble metrics;
- аннотированные Cilium agent/operator pods через Kubernetes discovery;
- Velero;
- четыре metrics service Kyverno;
- opt-in services с `prometheus.io/scrape: "true"`;
- cluster metrics, Kubernetes events и internal HTTP health checks;
- host/kubelet metrics и container logs через OTel Agent DaemonSet.

Чтобы добавить новый статический target, измените `scrape_configs` в
[`otel-collector/values.yaml`](../argocd/platform/observability/otel-collector/values.yaml):

```yaml
- job_name: my-service
  scrape_interval: 30s
  metrics_path: /metrics
  static_configs:
    - targets:
        - my-service.my-namespace.svc.cluster.local:9090
```

Перед изменением подтвердите фактические Service и port:

```bash
kubectl -n my-namespace get svc my-service -o yaml
kubectl -n my-namespace get endpointslice \
  -l kubernetes.io/service-name=my-service
```

Если используется Kubernetes service discovery, добавляйте узкие relabel
filters. Не оставляйте cluster-wide discovery без namespace/label/annotation
ограничений: это создаёт непредсказуемую cardinality и может собирать
непредназначенные для публикации endpoints.

После sync проверьте target:

```promql
up{job="my-service"}
```

При переименовании Service или port одновременно обновляйте scrape config,
дашборды и alert expressions, которые используют `job` label.

## Grafana: datasources, dashboards и alerts

Три datasource создаются provisioning-механизмом chart и не требуют ручной
настройки:

| UID | Тип | Назначение |
| --- | --- | --- |
| `victoriametrics` | Prometheus | default datasource для метрик |
| `loki` | Loki | логи |
| `tempo` | Tempo | трейсы, service map и переходы traces-to-logs |

В папке `Observability` декларативно создаются dashboards:

- `Observability Overview` — доступность targets и объём принятой телеметрии;
- `OpenTelemetry Collector` — отправка и ошибки exporters;
- `Cilium Hubble` — flows, drops, DNS, TCP и scrape health;
- `Velero Kyverno` — backup и policy metrics.

Dashboards имеют `allowUiUpdates: false`. Изменения через UI не являются
источником истины и будут потеряны при reconciliation. Экспортируйте нужный
dashboard JSON, нормализуйте его и внесите в Git в `grafana/values.yaml`.

Там же provisioning создаёт правила:

- `Observability Target Down`;
- `OTel Exporter Failures`;
- `Hubble Drops High`;
- `Cilium Metrics Missing`;
- `Velero Backup Failures`;
- `Kyverno Policy Violations`;
- `Synthetic Endpoint Down`;
- `OTel Exporter Queue Saturation`.

Проверяйте их в Grafana через **Alerting → Alert rules**. Канал доставки и
notification policy настраиваются отдельно после выбора реального получателя;
секреты интеграции не должны попадать в Git или Helm values.

## Retention, storage и ресурсы

Текущий storage profile:

| Компонент | PVC | Размер | Комментарий |
| --- | --- | --- | --- |
| VictoriaMetrics | включён | `20Gi` | retention `30d` |
| Loki SingleBinary | включён | `20Gi` | filesystem TSDB schema v13, retention `336h` |
| Tempo monolithic | включён | `20Gi` | local trace backend, retention `168h` |
| Grafana | включён | `10Gi` | UI state и Grafana database |

Все PVC используют StorageClass из environment contract. Размер PVC и
retention — разные ограничения: retention не гарантирует, что диск не
заполнится раньше при высокой ingestion rate.

Для изменения VictoriaMetrics retention сначала измените
`platform.observability.victoriametrics.retention` в environment contract,
затем выполните `task sync-env-contract`. Для размеров PVC измените
соответствующий Helm values. До уменьшения PVC проверьте возможности
StorageClass: Kubernetes обычно не поддерживает shrink существующего volume.

Увеличение retention, cardinality или объёма логов требует одновременной оценки:

- фактической скорости ingestion;
- свободного места LINSTOR pool;
- requests/limits памяти и CPU;
- времени compaction и query latency;
- политики backup/restore для stateful namespace.

Single-node backends не обеспечивают доступность при рестарте/перемещении pod и
не дают репликации на уровне приложения. Репликация LINSTOR volume защищает от
части storage failures, но не превращает VictoriaMetrics Single, Loki
SingleBinary или локальный Tempo backend в HA deployment.

## Валидация изменений

Для изменений только в документации достаточно:

```bash
task check:documentation
```

Для observability manifests или Helm values выполните:

```bash
task check:env-contract
task check:versions
task check:runtime-secret-contract
task check:platform-layout
task check:kustomize-platform
task check:helm-observability
task check:yamllint
task check:documentation
```

Перед реальным GitOps bootstrap:

```bash
task gitops:preflight
```

После публикации изменения проверяйте live cluster только через read-only
команды, пока отдельная операция sync/restart не требуется явно:

```bash
kubectl -n argocd get applications \
  observability-prereqs victoria-metrics loki tempo otel-collector otel-agent grafana
kubectl -n observability get pods,pvc
kubectl -n observability logs deploy/otel-collector \
  --all-containers --tail=200
kubectl -n observability logs daemonset/otel-agent-agent \
  --all-containers --tail=200
```

## Диагностика

### `observability-prereqs` не становится Healthy

Проверьте ESO, certificate и Gateway API:

```bash
kubectl -n observability describe externalsecret grafana-admin-secret
kubectl -n observability describe externalsecret grafana-oidc
kubectl -n observability describe certificate grafana-tls
kubectl -n observability describe gateway grafana
kubectl -n observability describe httproute grafana
```

Частые причины: отсутствующий OpenBao path/key, неготовый
`ClusterSecretStore/openbao`, ошибка DNS-01, неподходящий Gateway address или
несинхронизированный environment contract.

### Grafana не запускается

```bash
kubectl -n observability get secret grafana-admin-secret grafana-oidc
kubectl -n observability get configmap homelab-root-ca
kubectl -n observability describe pod -l app.kubernetes.io/name=grafana
kubectl -n observability logs deploy/grafana --tail=200
```

Grafana зависит от двух Secrets и CA bundle. Если secret существует, но имеет
старое значение, проверьте status ExternalSecret и `refreshTime`; не редактируйте
materialized Secret вручную.

### Вход через Authentik зацикливается или возвращает ошибку

Проверьте совпадение Grafana URL, Authentik provider redirect URI и credentials:

```bash
task check:env-contract
kubectl -n authentik get externalsecret grafana-sso-blueprint
kubectl -n observability get externalsecret grafana-oidc
kubectl -n authentik logs deploy/authentik-server --tail=200
kubectl -n observability logs deploy/grafana --tail=200
```

Оба ExternalSecret должны читать один OpenBao path. После осознанной ротации
OIDC credentials дождитесь reconciliation ESO и Authentik blueprint, затем
перезапустите только те pods, которые не перечитывают Secret автоматически.
Не ротируйте только одну сторону пары.

### Метрики отсутствуют

```bash
kubectl -n observability get svc victoria-metrics otel-collector
kubectl -n observability logs deploy/otel-collector \
  --all-containers --tail=200
kubectl -n observability port-forward svc/victoria-metrics 8428:8428
```

В другом терминале можно проверить локальный query endpoint:

```bash
curl -fsS --get 'http://127.0.0.1:8428/api/v1/query' \
  --data-urlencode 'query=up'
```

Для конкретного target проверьте DNS/Service/port из pod Collector. Не
устанавливайте диагностические пакеты в production container; при
необходимости используйте отдельный временный debug pod.

### Логи отсутствуют в Loki

Проверьте node agent, затем central pipeline и Loki. Для OTLP logs отдельно
подтвердите, что приложение действительно использует exporter.

```bash
kubectl -n observability logs deploy/otel-collector \
  --all-containers --tail=200
kubectl -n observability logs daemonset/otel-agent-agent \
  --all-containers --tail=200
kubectl -n observability logs -l app.kubernetes.io/name=loki \
  --all-containers --tail=200
```

В Grafana Explore выберите Loki и начните с широкого запроса по известному
resource/stream label. Набор Loki labels зависит от OTLP resource attributes и
преобразований Loki; не предполагайте наличие `namespace` или `pod`, если SDK
их не отправляет.

### Трейсы отсутствуют в Tempo

Проверьте OTLP exporter приложения, затем обе стороны pipeline:

```bash
kubectl -n observability logs deploy/otel-collector \
  --all-containers --tail=200
kubectl -n observability logs -l app.kubernetes.io/name=tempo \
  --all-containers --tail=200
```

Рост `otelcol_receiver_accepted_spans` при отсутствии трейсов указывает на
ошибку exporter/query/backend. Нулевой accepted counter обычно означает
неверный endpoint/protocol, отсутствие instrumentation или сетевую блокировку
между приложением и Collector.

### PVC или backend заполняется

```bash
kubectl -n observability get pvc
kubectl -n observability describe pvc
kubectl -n observability get events --sort-by=.lastTimestamp
kubectl linstor storage-pool list
```

Сначала определите, какой signal и labels создают рост. Простое увеличение PVC
без ограничения cardinality, log volume или retention лишь откладывает
повторение проблемы. Не удаляйте PVC и не меняйте retention аварийно через
`helm`/`kubectl`; исправление должно пройти через GitOps, а удаление данных
требует отдельного подтверждённого recovery plan.

## Плановые изменения

### Добавление dashboard или alert

1. Сформулируйте signal, query и ожидаемую cardinality.
2. Проверьте query в Grafana Explore на репрезентативном временном диапазоне.
3. Добавьте dashboard JSON или provisioning rule в `grafana/values.yaml`.
4. Не помещайте credentials notification channel в Git.
5. Выполните локальные проверки и опубликуйте обычным GitOps workflow.
6. После sync подтвердите dashboard/rule и отсутствие provisioning errors в
   логах Grafana.

### Сбор Kubernetes stdout/stderr

OTel Agent работает node-local и монтирует только необходимые host paths для
container logs, host metrics и checkpoint. `includeCollectorLogs: false`
предотвращает рекурсивный сбор собственных логов агента. При добавлении
исключений, multiline parsing или redaction меняйте только agent values; не
добавляйте host mounts к central gateway.

### Переход к HA или object storage

Переход VictoriaMetrics/Loki/Tempo на распределённые topology и object storage
затрагивает формат и миграцию данных, ресурсы, credentials, buckets и backup.
Это отдельная migration-задача. Не меняйте deployment mode существующих
releases как обычный chart upgrade без плана сохранения данных и rollback.
