# Версии компонентов

[`versions.yaml`](../versions.yaml) — единый source of truth для версий
OpenTofu, OpenTofu providers, Talos Linux, Kubernetes, Helm charts и связанных
release versions.

Статические `terraform.required_version`, `required_providers`, CI
`tofu_version` и Argo CD `targetRevision` — проверяемые generated mirrors, а не
независимые значения. Talos Linux и Kubernetes читаются `cluster/` напрямую из
контракта.

## Изменение версии

1. Обновите нужный pin в `versions.yaml`.
2. Синхронизируйте consumers:

```bash
task sync-versions
```

3. Проверьте результат:

```bash
task check:versions
git diff -- versions.yaml cluster/versions.generated.tf infrastructure/versions.generated.tf .github/workflows/ci.yaml argocd/platform
```

Не редактируйте generated mirrors отдельно от `versions.yaml`.

Автоматизация описана в [Renovate](renovate.md).
