# Prerequisites

Этот документ фиксирует локальный operator toolchain для greenfield bootstrap path.

## Required Tools

Без этих инструментов основной путь репозитория не работает:

- `tofu`
  Нужен для `bootstrap/` и `infrastructure/`.
- `kubectl`
  Нужен для readiness checks, GitOps bootstrap и day-0 operator actions.
- `talosctl`
  Нужен для проверки Talos cluster health и работы с Talos API.
- `task`
  Основной локальный entrypoint репозитория.
- `helm`
  Нужен для локальной валидации chart-backed manifests.
- `bao`
  Нужен для обязательной day-0 настройки OpenBao и secret management.
- `htpasswd`
  Нужен для генерации согласованной bcrypt-записи Harbor registry; входит в
  пакет `apacheHttpd` проектного Flox environment.

## Следующий шаг

После установки toolchain используйте:

1. [Day-0 bootstrap](day0-bootstrap.md) для greenfield bootstrap path.
2. [Day-1 operations](../configuration/day1-operations.md) после завершения
   развёртывания.

## Notes

- Репозиторий не должен сам устанавливать system-wide packages.
- Runtime secrets не должны подменяться отсутствием tooling и всё равно должны проходить через `OpenBao` + `ESO`.
