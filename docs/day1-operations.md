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

## Harbor convergence smoke

После изменения Harbor chart/values или secret delivery выполните:

```bash
task ops:openbao-port-forward-start
export BAO_ADDR='http://127.0.0.1:8200'
export BAO_TOKEN='...'
task ops:harbor-smoke
task ops:openbao-port-forward-stop
```

Helper проверяет health всех Harbor components, OIDC primary authentication до
MFA, выполняет временный registry push/pull образа `pause:3.10`, запускает
Trivy scan, ждёт успешный report и удаляет smoke repository. Credentials
передаются через временные файлы с mode `0600` и не попадают в process
arguments или output.

Chart Harbor 1.19.2 не поддерживает отдельный existing Secret для Trivy Redis
URL и использует API-dependent `lookup`, недоступный Argo CD repo-server.
Поэтому ESO заменяет только `Secret/harbor-trivy.data.redisURL`, а Argo CD
игнорирует только `/data/redisURL`. Не расширяйте исключение до всего `/data`:
chart-owned keys должны оставаться под drift detection.

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
