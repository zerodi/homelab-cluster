# Day-1 Operations

Этот документ описывает operator actions после успешного day-0 bootstrap.

Фокус:

- что уже автоматизировано безопасными helper scripts
- что всё ещё должно выполняться вручную
- какие действия относятся к day-1, а не к bootstrap graph

## Автоматизировано

Следующие шаги уже безопасно автоматизированы и должны запускаться через `task`:

- `task ops:openbao-day0`
  - настраивает `KV v2`
  - включает `auth/kubernetes`
  - пишет policy и role для `external-secrets`
- `task infra:bootstrap-piraeus-storage`
  - создаёт LINSTOR storage pools после готовности `LinstorCluster`
- `task infra:destroy`
  - выполняет staged destroy для `infrastructure/`
  - сначала удаляет CRD-backed ресурсы при живых CRD
  - затем чистит stale state для уже пропавших CRD

Эти helper scripts не должны становиться source of truth для long-lived runtime resources вне их текущего bootstrap contract.

## Что остаётся manual

Следующие шаги намеренно остаются ручными:

- `OpenBao init` и `unseal`
  - recovery material нельзя автоматизировать и хранить в repo/state
- запись runtime secrets в `OpenBao`
  - значения всё равно должны происходить из operator-controlled secret source
- миграции прикладных данных
  - пример: SQLite -> PostgreSQL для Forgejo
- любые destructive day-1 actions по storage devices
  - если требуется пересоздание pool или замена block device, это operator procedure, а не blind bootstrap helper
- runtime GitOps changes для приложений
  - они живут в `argocd/` и их rollout должен быть осознанным операторским действием

## Preconditions by helper

### `task ops:openbao-day0`

Нужно заранее:

- `OpenBao` уже initialized
- `OpenBao` уже unsealed
- экспортирован `BAO_TOKEN`
- доступен `kubectl`
- доступен `bao`

### `task infra:bootstrap-piraeus-storage`

Нужно заранее:

- CRD и operator Piraeus уже подняты
- `LinstorCluster/linstor` существует
- `kubectl linstor` plugin доступен локально
- raw block device на worker nodes уже подготовлен вручную

### `task infra:destroy`

Нужно заранее:

- локально доступен `tofu`
- желательно доступен актуальный `kubeconfig`, чтобы helper мог корректно убрать CRD-backed resources до исчезновения CRD

## Recommended day-1 checks

После bootstrap и после значимых runtime changes полезно проверять:

```bash
task gitops:apply-bootstrap
fish argocd/scripts/post-argocd-check.fish
```

Дополнительно вручную:

- проверить `Application` health в Argo CD
- проверить готовность `ExternalSecret` и materialized `Secret`
- проверить runtime endpoints для `authentik`, `forgejo`, `echo`, `grafana`, `hubble`
- открыть `grafana.home.arpa` и убедиться, что появились dashboards `Observability Overview`, `OpenTelemetry Collector` и `Cilium Hubble`
- проверить в Grafana Alerting, что загружены правила `Observability Target Down`, `OTel Exporter Failures` и `Hubble Drops High`
- проверить storage class и PVC binding для stateful workloads

Для reference runtime baseline можно смотреть на [argocd/apps/echo/resources/deployment.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/deployment.yaml) и [argocd/apps/echo/resources/networkpolicy.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/networkpolicy.yaml).

## Boundaries

Если шаг требует:

- хранения recovery material
- необратимого изменения block device layout
- прикладной data migration
- ручного решения по downtime / rollback

это day-1 operator action и не должно автоматически зашиваться в Terraform bootstrap path.
