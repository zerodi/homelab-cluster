# Kyverno policies

Runtime policy pack находится в
[`argocd/platform/kyverno/policies`](../argocd/platform/kyverno/policies).

Текущие `ValidatingPolicy`:

- `disallow-latest-tag`
- `disallow-privileged-containers`
- `disallow-hostpath-volumes`
- `require-resource-requests-and-limits`
- `require-basic-security-context`

Policies применяются к создаваемым и обновляемым Pods и автоматически
распространяются на стандартные workload controllers. Platform/system
namespaces исключены через `namespaceSelector`.

## Проверка

```bash
kubectl get validatingpolicies.policies.kyverno.io
kubectl get policyreport -A
kubectl get clusterpolicyreport
```

Перед изменением:

```bash
task check:kustomize-platform
task check:yamllint
```

Меняйте `validationActions` и исключения только декларативно в Git. Сначала
проверяйте нарушения в reports, затем усиливайте enforcement.
