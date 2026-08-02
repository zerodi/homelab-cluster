# Day-1 operations

Короткий runbook для проверки уже развёрнутого кластера.

## Health

```bash
task bootstrap:health
task infra:health
task ops:post-argocd-check
kubectl -n argocd get applications
```

## OpenBao и External Secrets

OpenBao остаётся source of truth для runtime secrets, ESO — каналом доставки.

```bash
bao status
task ops:openbao-runtime-preflight
kubectl get externalsecret -A
kubectl get clustersecretstore openbao
```

Не записывайте runtime secrets в Git, `terraform.tfvars`, Helm values или
Terraform state.

## Сертификаты и storage

```bash
kubectl get certificate -A
kubectl get storageclass
kubectl -n piraeus-datastore get pods
kubectl linstor node list
kubectl linstor storage-pool list
```

## GitOps-изменения

Перед sync:

```bash
task check:env-contract
task check:chart-versions
task check:kustomize-platform
task gitops:preflight
```

Для backup/restore, Garage/Velero и policies используйте отдельные runbook из
[индекса документации](../README.md).
