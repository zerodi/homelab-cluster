# Garage + Velero

Этот документ фиксирует план интеграции `Garage` как нового S3-compatible backend для `Velero`.

Текущий bootstrap path остаётся безопасным:

- `Velero` продолжает смотреть в текущий backend
- `Garage` добавляется как отдельный runtime app
- переключение `Velero` делается только после ручного bootstrap bucket/key

## Что уже добавлено в repo

- `argocd/platform/garage-prereqs.yaml`
- `argocd/platform/garage.yaml`
- `argocd/platform/garage/prereqs/*`
- `argocd/platform/garage/resources/*`

Сейчас это минимальный single-node runtime layout:

- namespace `garage`
- `ExternalSecret`, который рендерит `garage.toml` из `OpenBao`
- internal headless service для pod DNS
- internal S3 service `garage-s3.garage.svc.cluster.local:3900`
- internal admin service `garage-admin.garage.svc.cluster.local:3903`
- внешний S3 endpoint `https://garage.home.arpa`
- `StatefulSet` с PVC на `linstor-pool1-r1`

## Secret contract

Нужно подготовить runtime secret в `OpenBao`:

- `secret/platform/garage/runtime`

Свойства:

- `rpc_secret`
- `admin_token`
- `metrics_token`

Пример:

```bash
bao kv put secret/platform/garage/runtime \
  rpc_secret="$(openssl rand -hex 32)" \
  admin_token="$(openssl rand -hex 32)" \
  metrics_token="$(openssl rand -hex 32)"
```

## Следующий шаг после sync Garage

После того как `garage` pod поднялся, нужно вручную сделать bootstrap bucket и S3 key для `Velero`.

Ожидаемый flow:

1. инициализировать layout `Garage`
2. создать bucket `homelab-velero`
3. создать отдельный S3 key для `Velero`
4. обновить `secret/platform/velero/s3` новыми `access_key_id` / `secret_access_key`
5. только после этого переключить `Velero` с `minio.home.arpa` на internal Garage endpoint

Планируемый endpoint для Velero:

- `http://garage-s3.garage.svc.cluster.local:3900`

Path-style доступ должен остаться включённым.

Внешний endpoint нужен не для самого `Velero`, а для operator bootstrap и ручной проверки S3 API:

- `https://garage.home.arpa`

## Ручной bootstrap Garage

Короткая памятка:

```bash
task ops:garage-velero-guide
```

Helper tasks:

```bash
task ops:garage-status
task ops:garage-node-id
task ops:garage-velero-bootstrap
```

### 1. Подготовить runtime secret

```bash
bao kv put secret/platform/garage/runtime \
  rpc_secret="$(openssl rand -hex 32)" \
  admin_token="$(openssl rand -hex 32)" \
  metrics_token="$(openssl rand -hex 32)"
```

### 2. Синкнуть `garage-prereqs` и `garage`

Проверка появления namespace и секрета:

```bash
kubectl get namespace garage
kubectl -n garage get externalsecret garage-config
kubectl -n garage get secret garage-config
kubectl -n garage get pods
kubectl -n garage get gateway,httproute,certificate
```

Ожидается:

- `garage-config` создан ESO
- pod `garage-0` в `Running`
- `garage.home.arpa` обслуживается через `Gateway`

### 3. Инициализировать layout

Сначала узнать node ID:

```bash
kubectl -n garage exec garage-0 -- /garage status
```

Или helper-ом:

```bash
task ops:garage-node-id
task ops:garage-velero-bootstrap
```

Затем назначить single-node layout и применить его:

```bash
kubectl -n garage exec garage-0 -- /garage layout assign -z homelab -c 20G <NODE_ID>
kubectl -n garage exec garage-0 -- /garage layout apply --version 1
kubectl -n garage exec garage-0 -- /garage status
```

Для текущего bootstrap path это single-node layout с `replication_factor = 1`.

### 4. Создать bucket и key для Velero

```bash
kubectl -n garage exec garage-0 -- /garage bucket create homelab-velero
kubectl -n garage exec garage-0 -- /garage key create velero
kubectl -n garage exec garage-0 -- /garage bucket allow --read --write --owner homelab-velero --key velero
kubectl -n garage exec garage-0 -- /garage key info velero --show-secret
```

Из `key info` нужно сохранить:

- `Key ID`
- `Secret key`

### 5. Обновить runtime secret для Velero

```bash
bao kv put secret/platform/velero/s3 \
  access_key_id='REPLACE_WITH_GARAGE_KEY_ID' \
  secret_access_key='REPLACE_WITH_GARAGE_SECRET_KEY'
```

Проверка:

```bash
bao kv get secret/platform/velero/s3
kubectl -n velero get secret velero-credentials -o yaml
```

### 6. Проверить S3 endpoint вручную

До cutover `Velero` полезно отдельно проверить bucket любым S3 client.

Пример с `awscli`:

```bash
AWS_ACCESS_KEY_ID='REPLACE_WITH_GARAGE_KEY_ID' \
AWS_SECRET_ACCESS_KEY='REPLACE_WITH_GARAGE_SECRET_KEY' \
aws --endpoint-url https://garage.home.arpa s3 ls
```

Если root CA ещё не импортирован локально, используйте cluster-internal endpoint через port-forward или локальный trust store после `task ops:export-root-ca`.

## План переключения Velero

После ручного bootstrap `Garage` нужно будет изменить [argocd/platform/velero/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/velero/values.yaml):

- `s3Url: http://garage-s3.garage.svc.cluster.local:3900`
- `s3ForcePathStyle: "true"` оставить
- `bucket: homelab-velero` оставить
- `provider: aws` оставить

Безопасная последовательность:

1. убедиться, что `garage-0` healthy и bucket/key уже созданы
2. обновить `secret/platform/velero/s3`
3. переключить `s3Url` в repo
4. дождаться sync `velero`
5. проверить `BackupStorageLocation`
6. выполнить ad hoc smoke backup

## Проверка после переключения

Проверки:

```bash
kubectl -n velero get backupstoragelocation
kubectl -n velero describe backupstoragelocation default
velero backup create garage-smoke-$(date +%Y%m%d%H%M) --include-namespaces forgejo
kubectl -n velero get backups
```
