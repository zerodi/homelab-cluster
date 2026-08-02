# Renovate

Root [`renovate.json`](../renovate.json) управляет автоматическими
обновлениями.

Включены:

- regex manager для pins из `versions.yaml`
- Terraform manager только для OpenTofu providers
- GitHub Actions

Chart pins обновляются только в `versions.yaml`. После обновления Renovate
запускает:

```bash
flox activate -- task sync-chart-versions
```

Это обновляет Argo CD mirrors в той же ветке.

## Проверка PR

```bash
task check:chart-versions
task check:tofu-validate-bootstrap
task check:tofu-validate-infrastructure
```

Automerge отключён; обновления versions и providers требуют review.
