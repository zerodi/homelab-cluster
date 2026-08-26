# Kyverno: политики и эксплуатация

Kyverno относится к runtime/GitOps-слою и полностью управляется Argo CD из
[`argocd/platform/policy`](../argocd/platform/policy). OpenTofu entrypoints
`cluster/` и `infrastructure/` не создают Kyverno resources.

Документ описывает текущую реализацию policy pack, порядок её применения,
проверку нарушений и безопасное изменение enforcement. Общий greenfield
сценарий остаётся в [day-0 runbook](day0-bootstrap.md).

## Состав и порядок синхронизации

Kyverno разворачивается тремя дочерними Applications:

| Sync wave | Application | Назначение |
| --- | --- | --- |
| `5` | `kyverno-prereqs` | Создаёт namespace `kyverno` |
| `10` | `kyverno` | Устанавливает chart, CRD и контроллеры |
| `15` | `kyverno-policies` | Применяет repository policy pack |

Application index находится в
[`platform/policy/applications`](../argocd/platform/policy/applications), Helm
values — в
[`platform/policy/kyverno/values.yaml`](../argocd/platform/policy/kyverno/values.yaml),
а политики — в
[`platform/policy/kyverno/policies`](../argocd/platform/policy/kyverno/policies).

Такой порядок не позволяет Argo CD отправить `ValidatingPolicy` до появления
соответствующего CRD. Для chart Application включён `ServerSideApply`, а для
всех трёх Applications — automated sync, prune и self-heal. Версия chart
задаётся централизованным version contract и не должна отдельно фиксироваться
в этом runbook.

## Контроллеры и отчётность

Helm release запускает по одной реплике admission, background, cleanup и
reports controller. Для каждого контроллера заданы requests и limits.

Текущая конфигурация также означает:

- Kyverno CRD устанавливаются chart'ом;
- встроенные Grafana и reports server отключены;
- OpenReports отключён;
- ServiceMonitor отключён;
- метрики четырёх контроллеров собирает OTel Collector напрямую с сервисов
  Kyverno и отправляет в VictoriaMetrics;
- Grafana содержит dashboard `Velero Kyverno` и alert
  `Kyverno Policy Violations`.

Отсутствие ServiceMonitor здесь не означает отсутствие мониторинга. При
изменении service names или ports одновременно обновляйте scrape targets в
[`otel-collector/values.yaml`](../argocd/platform/observability/otel-collector/values.yaml).

## Текущий policy pack

Все правила используют `policies.kyverno.io/v1` `ValidatingPolicy`, проверяют
операции `CREATE` и `UPDATE` для Pods и включают background evaluation.
Autogen распространяет правила на Deployments, DaemonSets, StatefulSets,
Jobs, CronJobs, ReplicaSets и ReplicationControllers.

| Policy | Severity | Действие | Что проверяется |
| --- | --- | --- | --- |
| `disallow-latest-tag` | medium | `Deny`, `Audit` | Запрещён суффикс `:latest` у обычных и init containers |
| `disallow-privileged-containers` | high | `Deny`, `Audit` | Запрещено `securityContext.privileged: true` |
| `disallow-hostpath-volumes` | high | `Deny`, `Audit` | Запрещены volumes с `hostPath` |
| `require-resource-requests-and-limits` | medium | `Deny`, `Audit` | Нужны CPU/memory requests и limits у обычных, init и ephemeral containers |
| `require-basic-security-context` | medium | `Deny`, `Audit` | Нужны seccomp, non-root, запрет privilege escalation и drop `ALL` capabilities |

`Deny` отклоняет несовместимый admission request. `Audit` сохраняет результат
для отчётности. Security-context и resource baseline переведены в enforcement
после полного render/live аудита управляемых runtime workloads.

### Ограничения текущих выражений

Policy pack является baseline, а не полной реализацией Pod Security Standards:

- `disallow-latest-tag` блокирует `:latest` и `:latest@sha256:...`; image без
  tag/digest отклоняется локальным render gate, но не admission expression;
- проверки охватывают `containers`, `initContainers` и
  `ephemeralContainers`;
- privileged policy запрещает только явное `privileged: true`; наличие полного
  restricted security context контролируется отдельной Audit policy;
- hostPath policy не проверяет `hostNetwork`, `hostPID`, `hostIPC` или host
  ports;
- policy pack не выполняет mutation, image signature verification или
  генерацию ресурсов.

Расширяйте baseline отдельными небольшими правилами. Не усложняйте одно CEL
выражение несколькими несвязанными security requirements: раздельные policy
дают понятные admission messages, reports и rollback.

## Область применения и исключения

Каждая policy содержит `namespaceSelector` только с системными/operator
исключениями:

```text
argocd, cert-manager, external-secrets, gateway, kube-system, kyverno,
openbao, piraeus-datastore, reloader, trust-manager
```

Namespace'ы, которых нет в этом списке, входят в область действия правил. Pack
проверяет Authentik, Forgejo, Harbor, Woodpecker, Garage, Stalwart,
Observability, Velero, Echo и новые application namespaces.

Единственное workload-level исключение — `velero` Pod с label
`name=node-agent`: filesystem backup требует root и hostPath-доступа к kubelet
pod data. Исключение применяется только к basic security-context и hostPath
выражениям; image и resources для node-agent продолжают проверяться. Harbor
chart не умеет задавать pod-level seccomp, поэтому узкая mutation policy
добавляет только `RuntimeDefault`; container security/resources проверяются
без исключений.

В Helm values дополнительно настроен controller-level список
`resourceFiltersExcludeNamespaces`, синхронизированный с системными
namespace-исключениями. Это два разных механизма:

- `matchConstraints.namespaceSelector` определяет admission scope конкретной
  policy;
- `resourceFiltersExcludeNamespaces` исключает namespace из обработки
  контроллерами Kyverno на более общем уровне.

При изменении исключений проверяйте оба списка. Не добавляйте namespace в
глобальный controller filter, если требуется исключить его только из одного
правила. Исключения должны быть узкими, иметь техническое обоснование и
вноситься декларативно через Git.

## Локальный render gate

Перед публикацией runtime изменений выполните:

```bash
task check:runtime-workloads
```

Gate параллельно рендерит все 19 Helm releases и локальные Kustomize/raw
workloads, а также отклоняет chart Application без зарегистрированного render
spec. Для обычных, init, sidecar и ephemeral containers он проверяет:

- отсутствие `latest` и image без tag/digest;
- обязательный digest для Bitnami workload/exporter images;
- CPU/memory requests и limits;
- pod seccomp и restricted container security context.

Версии charts берутся непосредственно из `versions.yaml`. Поэтому добавление
нового runtime Helm Application требует регистрации его render spec в
`check_runtime_workloads.py`; иначе общий gate не считается полным.

## Проверка состояния

Сначала проверьте Argo CD и контроллеры:

```bash
kubectl -n argocd get applications \
  kyverno-prereqs kyverno kyverno-policies
kubectl -n kyverno get deployments,pods
kubectl -n kyverno get events --sort-by=.lastTimestamp
```

Проверьте API и установленные policies:

```bash
kubectl api-resources | grep -Ei 'validatingpolic|policyreport'
kubectl get validatingpolicies.policies.kyverno.io
kubectl describe validatingpolicy.policies.kyverno.io disallow-latest-tag
```

Отчёты можно просматривать как сводно, так и по namespace:

```bash
kubectl get policyreport -A
kubectl get clusterpolicyreport
kubectl -n <namespace> describe policyreport
```

Если имя ресурса отличается из-за версии установленных reporting CRD,
используйте результат `kubectl api-resources`, а не предполагайте API group.
Для оперативной диагностики контроллеров:

```bash
kubectl -n kyverno logs deploy/kyverno-admission-controller \
  --all-containers --tail=200
kubectl -n kyverno logs deploy/kyverno-background-controller \
  --all-containers --tail=200
kubectl -n kyverno logs deploy/kyverno-reports-controller \
  --all-containers --tail=200
```

## Безопасная проверка Deny

Server-side dry-run вызывает admission webhooks, но не сохраняет объект. Этот
Pod должен быть отклонён policy `disallow-latest-tag` в namespace, который не
исключён из policy scope:

```bash
kubectl apply --dry-run=server -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: kyverno-deny-latest-test
  namespace: default
spec:
  containers:
    - name: test
      image: nginx:latest
EOF
```

Ожидаемый результат — admission denial с сообщением
`Container images must not use the latest tag.` Объект после server-side
dry-run удалять не требуется.

Dry-run подходит для Deny, но не для проверки background reports: объект не
сохраняется, поэтому reports controller не сможет обработать его позднее.

## Перевод Audit policy в Deny

Усиление enforcement выполняйте поэтапно:

1. Найдите нарушения конкретной policy в PolicyReports и метриках.
2. Исправьте существующие workloads во всех namespace'ах из policy scope.
3. Проверьте типовые manifests через `kubectl apply --dry-run=server`.
4. Добавьте `Deny` в `validationActions`, сохранив `Audit` для наблюдаемости.
5. Выполните локальные проверки и опубликуйте изменение через обычный GitOps
   workflow.
6. После sync проверьте admission errors, policy results и состояние
   Applications.

Не переключайте policy командой `kubectl edit`: Argo CD self-heal вернёт
состояние из Git. Для rollback верните `validationActions` в Audit-only через
Git и синхронизируйте `kyverno-policies`.

## Добавление или изменение policy

Для нового правила:

1. Создайте отдельный YAML в
   [`policies/`](../argocd/platform/policy/kyverno/policies).
2. Зарегистрируйте файл в
   [`policies/kustomization.yaml`](../argocd/platform/policy/kyverno/policies/kustomization.yaml).
3. Укажите title, category, severity, subject и понятное description.
4. Явно задайте admission operations, namespace scope, background evaluation
   и нужный набор autogen controllers.
5. Начните с `Audit`, если совместимость существующих workloads не доказана.
6. Добавьте policy в таблицу этого runbook и опишите известные ограничения.

Перед публикацией выполните во Flox:

```bash
flox activate -- task check:platform-layout
flox activate -- task check:kustomize-platform
flox activate -- task check:yamllint
flox activate -- task check:documentation
```

Для проверки CEL используйте server-side dry-run на доступном тестовом
кластере. Локальный Kustomize подтверждает структуру YAML и Argo CD wiring, но
не исполняет admission expression.

## Диагностика типовых отказов

### `kyverno-policies` не синхронизируется

Проверьте, что Application `kyverno` уже Healthy и API server знает CRD:

```bash
kubectl get crd validatingpolicies.policies.kyverno.io
kubectl -n argocd describe application kyverno-policies
```

Если CRD отсутствует, сначала диагностируйте chart Application и не применяйте
policy manifests вручную в обход sync waves.

### Workload неожиданно отклоняется

В admission error найдите имя policy и её message, затем проверьте:

- namespace входит ли в policy scope;
- Pod template итогового workload, а не только исходный Helm values;
- init containers, которые часто добавляются chart'ом;
- autogen, из-за которого ошибка может быть показана на Deployment или Job.

Исправление workload предпочтительнее нового исключения. Временное ослабление
enforcement выполняйте только декларативным изменением конкретной policy.

### PolicyReport пустой

Проверьте reports и background controllers, наличие reporting API, включённую
`evaluation.background.enabled` и controller-level resource filters. Также
учитывайте, что server-side dry-run не создаёт background report.

### Метрики Kyverno отсутствуют

Проверьте сервисы метрик, OTel scrape targets и доступность targets из
collector pod:

```bash
kubectl -n kyverno get services | grep metrics
kubectl -n observability logs deploy/otel-collector \
  --all-containers --tail=200
```

После восстановления scrape проверьте dashboard `Velero Kyverno` и alert
`Kyverno Policy Violations` в Grafana.
