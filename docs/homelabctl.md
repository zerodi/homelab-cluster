# Homelab automation application

`Taskfile` остаётся единственной поддерживаемой пользовательской точкой входа.
Задачи `task cluster:*`, `task infra:*`, `task gitops:*`, `task ops:*` и
`task check:*` вызывают repository-local Python application `homelabctl` через
`uv run --project homelabctl --locked`.

Самостоятельный Python-проект расположен в `homelabctl/`: исходный код — в
`homelabctl/src/homelabctl/`, тесты — в `homelabctl/tests/`, а зависимости и
lock-файл — в `homelabctl/pyproject.toml` и `homelabctl/uv.lock`. Его команды
разделены по тем же ownership boundaries, что и репозиторий; наличие общего CLI
не объединяет cluster, infrastructure и runtime lifecycle.

## Окружение

Flox предоставляет Python, uv и внешние platform CLI. Python dependencies
описаны и зафиксированы внутри `homelabctl/`.

Для локальной разработки:

```bash
flox activate
uv sync --project homelabctl --locked
task check:validate
```

Прямой вызов `uv run --project homelabctl --locked homelabctl ...` предназначен
для разработки и диагностики. Операторские runbook должны использовать
соответствующую Task-команду.

`homelabctl` управляет внешними `tofu`, `kubectl`, `bao`, `talosctl`, `git`,
`docker` и `kustomize`, но не заменяет их SDK-реализациями.

## Безопасность

- Runtime secrets остаются в OpenBao и передаются через временные файлы mode
  `0600`, а не через process arguments.
- Mutating команды требуют явных режимов или отдельных Task-команд.
- Forgejo push остаётся без force-push и проверяет чистоту `argocd/`.
- OpenBao init/unseal, recovery material, storage selection и destructive
  teardown не становятся частью неявного общего deploy.
