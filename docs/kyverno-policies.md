# Kyverno Policies

Этот документ описывает baseline policy rollout для `Kyverno`.

Границы первого прохода:

- `Kyverno` ставится в отдельный namespace `kyverno`
- rollout начинается с mix `Audit`/`Enforce`
- policies ориентированы на app workloads
- system/platform namespaces исключены из baseline policy pack

## Что разворачивается

`Kyverno` и policy pack живут отдельными Argo CD apps:

- [argocd/platform/kyverno-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/kyverno-prereqs.yaml)
- [argocd/platform/kyverno.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/kyverno.yaml)
- [argocd/platform/kyverno-policies.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/kyverno-policies.yaml)

Helm values лежат в [argocd/platform/kyverno/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/kyverno/values.yaml).
Сами baseline policies лежат в [argocd/platform/kyverno/policies](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/kyverno/policies).

## Policy layout

Первый набор политик:

- `disallow-latest-tag`
- `require-resource-requests-and-limits`
- `require-basic-security-context`
- `disallow-privileged-containers`
- `disallow-hostpath-volumes`

Все они:

- `ClusterPolicy`
- `background: true`
- нацелены на `Pod`, чтобы работал autogen для стандартных workload controllers

Текущий режим:

- `disallow-latest-tag` -> `Enforce`
- `disallow-privileged-containers` -> `Enforce`
- `disallow-hostpath-volumes` -> `Enforce`
- `require-resource-requests-and-limits` -> `Audit`
- `require-basic-security-context` -> `Audit`

## Исключения

Из первого прохода сознательно исключены namespace'ы платформы и системы:

- `kube-system`
- `argocd`
- `cert-manager`
- `trust-manager`
- `external-secrets`
- `openbao`
- namespace `Piraeus`, заданный bootstrap contract
- `gateway`
- `authentik`
- `forgejo`
- `observability`
- `velero`
- `kyverno`

Это сделано для least-disruptive rollout.

На первом шаге исключения реализованы через `exclude` в самих политиках и через `resourceFiltersExcludeNamespaces` в Helm values.
Отдельные `PolicyException` пока не включаются, чтобы не увеличивать surface area rollout.

Официальный reference по exceptions:

- https://main.kyverno.io/docs/guides/exceptions/

## Как читать результаты

После sync проверяйте:

```bash
kubectl get cpol
kubectl get policyreport -A
kubectl get clusterpolicyreport
```

Для конкретной политики:

```bash
kubectl describe cpol disallow-latest-tag
```

`Audit` означает:

- admission не блокируется
- нарушения попадают в policy reports
- можно увидеть реальные отклонения до включения `Enforce`

`Enforce` означает:

- admission блокирует новые несоответствующие ресурсы
- существующие ресурсы не переписываются автоматически
- background reports всё ещё полезны для контроля drift

## Переход от Audit к Enforce

Рекомендуемый порядок:

1. держать policy в `Audit`, пока не понятен фактический шум
2. исправить app manifests в namespace'ах, которые должны соответствовать baseline
3. перевести в `Enforce` только выбранные политики
4. делать это по одной политике, а не всем пакетом

Этот репозиторий уже перевёл в `Enforce`:

- `disallow-latest-tag`
- `disallow-privileged-containers`
- `disallow-hostpath-volumes`

Они выбраны как least-disruptive baseline, потому что:

- не требуют глубокого refactor manifests
- уже соответствуют текущим app workloads
- platform/system namespaces исключены из их scope

Следующими кандидатами остаются:

- `require-resource-requests-and-limits`
- `require-basic-security-context`

Их лучше переводить позже, когда весь app layer стабильно выровнен.

## Когда нужен отдельный exception path

Если policy должна действовать почти везде, но нужен редкий целевой обход, есть два варианта:

- оставить namespace/resource-level `exclude` в policy
- отдельно включить `PolicyException` как следующую фазу rollout

Во втором случае сначала нужно явно принять это как новый operating model для кластера.

Официальные reference docs:

- https://kyverno.io/docs
- https://kyverno.io/docs/policy-types/cluster-policy/validate/
