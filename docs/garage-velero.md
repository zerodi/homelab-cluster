# Garage и Velero

Garage разворачивается как runtime application. Layout, bucket и S3 key
создаются вручную после sync.

## 1. Runtime secret

OpenBao path `secret/platform/garage/runtime` должен содержать:

- `rpc_secret`
- `admin_token`
- `metrics_token`

Для greenfield bootstrap путь создаётся командой
`task ops:seed-runtime-secrets`. Она не перезаписывает существующую запись.

После записи секрета проверьте:

```bash
kubectl -n garage get externalsecret,secret
kubectl -n garage get pods
```

## 2. Layout, bucket и key

```bash
task ops:garage-node-id
task ops:garage-velero-bootstrap
```

Выполните напечатанные команды для:

1. назначения single-node layout
2. создания bucket `homelab-velero`
3. создания key `velero`
4. выдачи key доступа к bucket

Команда `garage key info --show-secret` печатает credential: не сохраняйте её в
shell history или Git.

## 3. Передача credentials в OpenBao

Запишите полученные `Key ID` и `Secret key` в:

```text
secret/platform/velero/s3
```

с ключами `access_key_id` и `secret_access_key`.

Замените ими временные bootstrap credentials, созданные
`task ops:seed-runtime-secrets`; ESO доставит обновлённый Secret в namespace
`velero`. Используйте `bao kv put`, чтобы новая версия path больше не содержала
marker `bootstrap_provisional`.

Проверка после ротации:

```bash
task ops:openbao-runtime-preflight-final
```

## 4. Переключение Velero

Обновите environment contract и Velero consumer:

- endpoint: `http://garage-s3.garage.svc.cluster.local:3900`
- bucket: `homelab-velero`
- path-style access: включён

Затем:

```bash
task check:env-contract
kubectl -n velero get backupstoragelocation
velero backup create garage-smoke --include-namespaces echo
```
