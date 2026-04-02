# Prerequisites

Этот документ фиксирует локальный operator toolchain для greenfield bootstrap path.

## Required Tools

Без этих инструментов основной путь репозитория не работает:

- `tofu`
  Нужен для `bootstrap/` и `infrastructure/`.
- `kubectl`
  Нужен для readiness checks, GitOps bootstrap и day-0/day-1 operator actions.
- `talosctl`
  Нужен для проверки Talos cluster health и работы с Talos API.
- `task`
  Основной локальный entrypoint репозитория.
- `helm`
  Нужен для локальной валидации chart-backed manifests.

## Optional Tools

Эти инструменты не обязательны для минимального bootstrap path, но полезны:

- `kubectl-linstor`
  Нужен для ручной диагностики LINSTOR/Piraeus.
- `argocd`
  Нужен для ручной работы с Argo CD API и UI workflow.
- `bao`
  Нужен для day-0 OpenBao bootstrap и secret management.
- `fish`
  Нужен только для запуска [argocd/scripts/post-argocd-check.fish](/home/zerodi/code/talos-proxmox-no-ssh/argocd/scripts/post-argocd-check.fish).
- `shellcheck`
  Нужен для локальной проверки shell scripts.
- `yamllint`
  Нужен для локальной YAML validation baseline.
- `pre-commit`
  Удобный способ запускать тот же baseline, что и CI.

## Expected Workflow

Минимальный local path:

1. `task init`
2. `task bootstrap:apply-cluster`
3. `task bootstrap:health`
4. `task infra:apply-bootstrap`
5. `task infra:health`
6. `task ops:day0-guide`

После day-0 secret bootstrap:

1. `task gitops:apply-bootstrap`
2. `fish argocd/scripts/post-argocd-check.fish`

## Notes

- Репозиторий не должен сам устанавливать system-wide packages.
- Если какого-то optional tool нет локально, это должно влиять только на соответствующий operator helper, а не на весь bootstrap path.
- Runtime secrets не должны подменяться отсутствием tooling и всё равно должны проходить через `OpenBao` + `ESO`.
