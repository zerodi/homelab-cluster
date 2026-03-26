# AGENTS

## Scope

Этот файл задаёт рабочие правила для агентных изменений в репозитории `talos-proxmox-no-ssh`.

По умолчанию всегда считайте, что кластер поднимается с нуля.
Если задача явно не говорит об обратном, ориентируйтесь на greenfield bootstrap, а не на миграцию существующего живого кластера.

## Current Architecture

Текущий проект разделён так:

- root entrypoint: bootstrap-only
- `bootstrap/`: Proxmox VM, Talos image, Talos machine config, cluster bootstrap, локальные `kubeconfig` и `talosconfig`
- `infrastructure/`: минимальный platform bootstrap внутри Kubernetes
- `gitops/`: отдельный runtime/GitOps модуль, не подключён к root entrypoint

Runtime не должен возвращаться в root `main.tf`.
`authentik`, `forgejo`, `echo` и app-level GitOps bootstrap живут вне bootstrap-only entrypoint.

## Ownership Rules

`bootstrap/` владеет только:

- Talos image download/import
- Proxmox VM lifecycle
- Talos machine secrets and config
- control plane bootstrap
- `kubeconfig` / `talosconfig` files in `out/`
- базовым Cilium bootstrap, который нужен для старта кластера

`infrastructure/` владеет только:

- `cert-manager`
- `trust-manager`
- `openbao`
- `external-secrets`
- `piraeus-operator` / LINSTOR bootstrap
- `argocd`
- bootstrap CRD / issuer / storage / secret-store readiness

`gitops/` владеет только runtime-слоем:

- `echo`
- `authentik`
- `forgejo`
- app-level `ExternalSecret`
- GitOps bootstrap objects, относящиеся к runtime
- app namespace labels and similar runtime wiring

## Default Working Assumption

Если задача не требует миграции state, recovery или partial reconcile, агент должен:

1. считать, что выполняется первый bootstrap с пустого состояния
2. предпочитать чистый bootstrap path:
   - `make apply-cluster`
   - `make apply-platform-bootstrap`
   - затем отдельный запуск `gitops/`, если задача относится к runtime
3. не проектировать решение вокруг already-existing runtime resources

Если задача действительно про миграцию существующего state, это должно быть явно зафиксировано в ответе и в изменениях.

## What Not To Do

Не делать без явного запроса:

- не подключать `gitops/` обратно в текущий root entrypoint
- не возвращать runtime-ресурсы в `infrastructure/`
- не добавлять app-level manifests в `default` namespace как часть bootstrap baseline
- не хранить runtime secrets в `terraform.tfvars`, `outputs`, `values.yaml` или repo
- не предполагать, что можно опереться на уже существующие namespace, CRD или secrets, если это не гарантирует bootstrap-контракт
- не использовать destructive git-команды для очистки чужих изменений

## Secret Model

Всегда придерживайтесь этой модели:

- `OpenBao` — source of truth для runtime secrets
- `External Secrets Operator` — доставка runtime secrets в Kubernetes
- `SOPS/age` — только для day-0 bootstrap секретов Terraform
- root outputs не должны публиковать runtime secrets

Новые runtime secrets нельзя добавлять в root `variables.tf`, `terraform.tfvars.example` или root `outputs.tf`.

## Change Strategy

При изменениях сначала определяйте слой ownership:

- если изменение касается VM, Talos, bootstrap networking, `out/` артефактов: это `bootstrap/`
- если изменение нужно для доведения кластера до `ArgoCD + OpenBao + ESO + Storage ready`: это `infrastructure/`
- если изменение касается приложений или app-level manifests: это `gitops/`

Если изменение пересекает границу слоёв, агент должен сначала объяснить причину такой границы и минимизировать связность.

## Validation Expectations

Минимальная ожидаемая проверка после изменений:

- `tofu fmt`
- `tofu validate`
- `tofu plan`, если изменение затрагивает root bootstrap path

Если меняется только `gitops/`, проверять нужно отдельно в его own entrypoint/контексте.

Если локально нет `tofu` или доступного кластера, агент должен прямо сказать, что проверка не выполнена.

## Review Priority

При аудите и review в первую очередь ищите:

- утечку runtime обратно в bootstrap-only root
- зависимость bootstrap от уже существующего state
- хранение секретов не по модели `OpenBao/ESO/SOPS`
- `terraform_data + local-exec`, который создаёт long-lived runtime objects
- лишние baseline-ресурсы в `default` namespace
- разрывы в readiness chain для `Piraeus`, `OpenBao`, `ESO`, `ArgoCD`

## Reference Docs

Перед значимыми изменениями сверяйтесь с:

- `README.md`
- `docs/day0-bootstrap.md`
- `docs/roadmap-terraform-vs-argocd.md`

Если код и документация расходятся, сначала фиксируйте кодовую границу ownership, затем приводите документацию к ней.
