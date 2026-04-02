# Backup And Restore

Этот документ описывает первый проход для `Velero` в runtime-слое `argocd/`.

Границы:

- установка `Velero` выполняется через Argo CD
- object storage предполагается S3-compatible
- автоматизация application-aware database dump не входит в первый проход
- основной сценарий здесь: backup Kubernetes resources и restore test для namespace

## Что разворачивается

`Velero` живёт в namespace `velero` и ставится как отдельный runtime app:

- [argocd/platform/velero-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero-prereqs.yaml)
- [argocd/platform/velero.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero.yaml)
- [argocd/platform/velero/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero/values.yaml)

Текущий baseline:

- S3-compatible `BackupStorageLocation`
- `kopia` uploader
- `node-agent` включён
- CSI snapshot integration выключена
- примерные `Schedule` создаются сразу chart values

## Secret Contract

Runtime credentials для object storage приходят из `OpenBao` через `ExternalSecret`.

Ожидаемый путь:

- `secret/platform/velero/s3`

Ожидаемые поля:

- `access_key_id`
- `secret_access_key`

Пример записи:

```bash
bao kv put secret/platform/velero/s3 \
  access_key_id='replace-me' \
  secret_access_key='replace-me'
```

Non-secret object storage параметры живут в [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml) и в [argocd/platform/velero/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero/values.yaml):

- bucket
- prefix
- region
- `s3Url`

## Создание backup

После sync `Velero` можно делать ad hoc backup через `velero` CLI или через CR.

Пример через CLI:

```bash
velero backup create platform-manual-$(date +%Y%m%d%H%M) \
  --include-namespaces argocd,authentik,forgejo,observability,echo,gateway,kyverno \
  --storage-location default \
  --ttl 168h
```

Пример через CR:

```yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: platform-manual
  namespace: velero
spec:
  includedNamespaces:
    - argocd
    - authentik
    - forgejo
    - observability
    - echo
    - gateway
    - kyverno
  storageLocation: default
  ttl: 168h0m0s
```

Проверка:

```bash
kubectl -n velero get backups
velero backup describe platform-manual --details
```

## Scheduled backup

Chart уже создаёт примерные schedules:

- `cluster-daily`
- `platform-hourly`

Проверка:

```bash
kubectl -n velero get schedules
kubectl -n velero get backupstoragelocation
```

Если нужен другой retention или namespace scope, правьте [argocd/platform/velero/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero/values.yaml), а не ad hoc runtime state.

## Restore namespace

Базовый restore test лучше делать в отдельный namespace mapping.

Пример:

```bash
velero restore create forgejo-restore-test \
  --from-backup platform-manual \
  --include-namespaces forgejo \
  --namespace-mappings forgejo:forgejo-restore-test
```

Проверка:

```bash
kubectl -n velero get restores
velero restore describe forgejo-restore-test --details
kubectl get namespace forgejo-restore-test
```

## Restore testing

Рекомендуемый безопасный цикл:

1. создать ad hoc backup выбранного namespace
2. восстановить его в новый namespace через `--namespace-mappings`
3. проверить, что namespace, workloads, secrets и PVC manifests восстановились
4. удалить test namespace после проверки

Пример удаления test restore namespace:

```bash
kubectl delete namespace forgejo-restore-test
```

## Ограничения первого прохода

- application-consistent backup для PostgreSQL не автоматизирован
- restore PVC data зависит от выбранной стратегии `Velero` и конкретного workload
- первый проход ориентирован на GitOps-friendly bootstrap и restore rehearsal, а не на полноту DR-платформы

Официальные reference docs:

- https://velero.io/docs/main
- https://velero.io/docs/main/file-system-backup/
- https://velero.io/docs/main/restore-reference/
