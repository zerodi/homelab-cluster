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
[`argocd/platform/velero/values.yaml`](../../argocd/platform/velero/values.yaml).

## Проверка restore

Восстанавливайте тестовую копию в отдельный namespace:

```bash
velero restore create forgejo-restore-test \
  --from-backup platform-manual \
  --include-namespaces forgejo \
  --namespace-mappings forgejo:forgejo-restore-test

velero restore describe forgejo-restore-test --details
kubectl get namespace forgejo-restore-test
```

Velero backup Kubernetes resources не заменяет application-consistent backup
PostgreSQL и других stateful services.

Для Garage backend используйте [Garage и Velero](garage-velero.md).
