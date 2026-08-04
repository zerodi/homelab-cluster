# Renovate

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

## Проверка PR

```bash
task check:versions
task check:tofu-validate-cluster
task check:tofu-validate-infrastructure
```

Automerge отключён; обновления versions и providers требуют review.
