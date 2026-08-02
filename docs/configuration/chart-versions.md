# Версии компонентов

[`versions.yaml`](../../versions.yaml) — единый source of truth для Helm chart
pins и связанных release versions.

Argo CD `targetRevision` — проверяемые mirrors, а не независимые значения.

## Изменение версии

1. Обновите нужный pin в `versions.yaml`.
2. Синхронизируйте consumers:

```bash
task sync-chart-versions
```

3. Проверьте результат:

```bash
task check:chart-versions
git diff -- versions.yaml argocd/platform
```

Не редактируйте `targetRevision` отдельно от `versions.yaml`.

OpenTofu provider versions управляются ограничениями в `required_providers` и
Renovate, а не `versions.yaml`.

Автоматизация описана в [Renovate](renovate.md).
