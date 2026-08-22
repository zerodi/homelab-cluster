# Day-1 operations

Короткий runbook для проверки уже развёрнутого кластера.

## Health

```bash
task cluster:health
task infra:health
task ops:post-argocd-check
kubectl -n argocd get applications
```

`ops:post-argocd-check` также отклоняет незавершённые/ошибочные Argo CD hooks,
неготовые runtime Pods, ошибки OpenTelemetry scrape/export за последние две
минуты и устаревший Velero Backup. Допустимый возраст Backup по умолчанию —
три часа; для другого расписания задайте `POST_CHECK_MAX_BACKUP_AGE_HOURS`.

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

## Forgejo OAuth для Woodpecker

При greenfield bootstrap или плановой ротации:

```bash
task ops:forgejo-woodpecker-oauth
task ops:forgejo-woodpecker-oauth -- --rotate  # только явная ротация
```

Нужны `BAO_TOKEN`, доступный `BAO_ADDR`, kubeconfig и рабочее DNS/CA-доверие к
Forgejo. Helper не печатает credentials и сохраняет существующий Woodpecker
`agent_secret`.

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
task check:versions
task check:kustomize-platform
task gitops:preflight
```

Для backup/restore, Garage/Velero и policies используйте отдельные runbook из
[индекса документации](../README.md).
