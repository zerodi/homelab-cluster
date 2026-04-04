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

## Garage Bootstrap For Velero

Если объектное хранилище для `Velero` переводится на `Garage`, сначала поднимите сам `Garage`, а потом отдельно создайте bucket и S3 key.

Короткая памятка:

```bash
task ops:garage-velero-guide
```

Helper-ы:

```bash
task ops:garage-status
task ops:garage-node-id
task ops:garage-velero-bootstrap
```

Подготовка secret:

```bash
bao kv put secret/platform/garage/runtime \
  rpc_secret="$(openssl rand -hex 32)" \
  admin_token="$(openssl rand -hex 32)" \
  metrics_token="$(openssl rand -hex 32)"
```

Проверка runtime:

```bash
kubectl -n garage get secret garage-config
kubectl -n garage get pods
kubectl -n garage get gateway,httproute,certificate
```

Инициализация single-node layout:

```bash
kubectl -n garage exec garage-0 -- /garage status
kubectl -n garage exec garage-0 -- /garage layout assign -z homelab -c 20G <NODE_ID>
kubectl -n garage exec garage-0 -- /garage layout apply --version 1
```

Создание bucket и key для `Velero`:

```bash
kubectl -n garage exec garage-0 -- /garage bucket create homelab-velero
kubectl -n garage exec garage-0 -- /garage key create velero
kubectl -n garage exec garage-0 -- /garage bucket allow --read --write --owner homelab-velero --key velero
kubectl -n garage exec garage-0 -- /garage key info velero --show-secret
```

Полученные `Key ID` и `Secret key` нужно записать обратно в `OpenBao`:

```bash
bao kv put secret/platform/velero/s3 \
  access_key_id='REPLACE_WITH_GARAGE_KEY_ID' \
  secret_access_key='REPLACE_WITH_GARAGE_SECRET_KEY'
```

Только после этого можно переключать `Velero` на `Garage`.

Планируемый internal endpoint для `Velero`:

- `http://garage-s3.garage.svc.cluster.local:3900`

Внешний endpoint для ручной проверки:

- `https://garage.home.arpa`

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

## Safe Cutover To Garage

Безопасная последовательность переключения:

1. убедиться, что `garage-0` healthy
2. проверить, что bucket `homelab-velero` уже создан
3. обновить `secret/platform/velero/s3`
4. изменить `s3Url` в [argocd/platform/velero/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero/values.yaml)
5. дождаться sync `velero`
6. проверить `BackupStorageLocation`
7. выполнить smoke backup

Проверка после cutover:

```bash
kubectl -n velero get backupstoragelocation
kubectl -n velero describe backupstoragelocation default
velero backup create garage-smoke-$(date +%Y%m%d%H%M) \
  --include-namespaces forgejo \
  --storage-location default \
  --ttl 24h
kubectl -n velero get backups
velero backup describe garage-smoke --details
```

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
