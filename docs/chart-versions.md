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

## Renovate

Root [`renovate.json`](../renovate.json) управляет автоматическими
обновлениями.

Включены:

- regex manager для всех pins из `versions.yaml`
- GitHub Actions

Release pins обновляются только в `versions.yaml`. После обновления Renovate
запускает:

```bash
flox activate -- task sync-versions
```

Это обновляет OpenTofu/provider, CI и Argo CD mirrors в той же ветке.

### Проверка PR

```bash
task check:versions
task check:tofu-validate-cluster
task check:tofu-validate-infrastructure
```

Automerge отключён; обновления versions и providers требуют review.
