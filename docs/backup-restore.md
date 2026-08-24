# Backup и restore

Velero разворачивается через Argo CD в namespace `velero`.

## Предварительные условия

- `BackupStorageLocation/default` доступен
- ESO создал `Secret/velero-credentials`
- OpenBao path `secret/platform/velero/s3` содержит:
  `access_key_id`, `secret_access_key`

```bash
kubectl -n velero get backupstoragelocation
kubectl -n velero get secret velero-credentials
kubectl -n velero get pods
```

## Ручной backup

```bash
velero backup create platform-manual \
  --include-namespaces argocd,authentik,forgejo,observability \
  --storage-location default \
  --ttl 168h

velero backup describe platform-manual --details
```

Declarative schedules находятся в
[`argocd/platform/storage/velero/values.yaml`](../argocd/platform/storage/velero/values.yaml).

## Проверка restore

Восстанавливайте тестовую копию в отдельный namespace. Для регулярного
безопасного smoke-test используйте `echo` и ограничьте restore ConfigMap
объектами: так проверяется полный путь Garage -> Velero -> Kubernetes API без
создания дублирующих Gateway, HTTPRoute и workloads.

```bash
velero backup create echo-restore-smoke \
  --include-namespaces echo \
  --storage-location default \
  --wait

velero restore create echo-restore-smoke \
  --from-backup echo-restore-smoke \
  --include-namespaces echo \
  --include-resources configmaps \
  --namespace-mappings echo:echo-restore-smoke \
  --wait

velero restore describe echo-restore-smoke --details
kubectl -n echo-restore-smoke get configmap homelab-root-ca
```

Имя smoke backup/restore и целевого namespace должно быть уникальным для
повторных запусков. Удаление test namespace и соответствующих Velero CR —
отдельная destructive операция и выполняется только явно.

Grafana alerts `Velero Backup Storage Unavailable` и `Velero Backup Stale`
контролируют доступность `BackupStorageLocation/default` и наличие успешного
`velero-platform-hourly` backup не старше трёх часов.

Velero backup Kubernetes resources не заменяет application-consistent backup
PostgreSQL и других stateful services.

Для Garage backend используйте [Garage и Velero](garage-velero.md).
