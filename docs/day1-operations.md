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
неготовые runtime Pods, ошибки OpenTelemetry, неуспешный synthetic trace,
устаревшие Velero Backup/verified Restore, отсутствующий Garage bucket,
нарушения Kyverno вне точного allowlist, некорректный OIDC/RBAC или оставшийся
bootstrap admin Secret. Проверка стабильности отклоняет недавние неожиданные
container restarts и сообщения etcd о таймаутах/медленном диске. Её окно по
умолчанию — 15 минут и задаётся `POST_CHECK_STABILITY_WINDOW_MINUTES`.
Допустимый возраст Backup по умолчанию — три часа, Restore — семь суток;
пороги задаются `POST_CHECK_MAX_BACKUP_AGE_HOURS` и
`POST_CHECK_MAX_RESTORE_AGE_HOURS`.

Перед первым строгим gate и затем периодически выполните явный restore
checkpoint:

```bash
task ops:backup-restore-smoke
```

По умолчанию ожидаемый root snapshot равен локальному `git rev-parse HEAD`.
Для проверки другого опубликованного commit задайте
`EXPECTED_GITOPS_REVISION`.

## OpenBao и External Secrets

OpenBao остаётся source of truth для runtime secrets, ESO — каналом доставки.

### Однократный переход существующего OpenBao на TLS

Для уже работающего HTTP-инстанса применяйте переход поэтапно. Helm chart
использует `StatefulSet` strategy `OnDelete`, поэтому изменение listener не
перезапускает pod неожиданно:

1. Выполните `task infra:apply`, дождитесь `Certificate/openbao-tls`.
2. Выполните `task ops:export-root-ca`.
3. Удалите только `pod/openbao-0`, дождитесь его повторного создания и
   разлочьте OpenBao через `https://127.0.0.1:8200` с `BAO_CACERT`.
4. Опубликуйте обновлённый `argocd/bootstrap/openbao-cluster-secret-store.yaml`
   и дождитесь `ClusterSecretStore/openbao Ready=True`.

Существующий PVC и OpenBao data не заменяются. На коротком переходном окне ESO
может сообщать transport errors, но уже материализованные Kubernetes Secrets
не удаляются.

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
export BAO_ADDR='https://127.0.0.1:8200'
export BAO_CACERT="$PWD/out/homelab-root-ca.crt"
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

## Runtime security baseline

Перед публикацией chart, image или workload изменений выполните:

```bash
task check:runtime-workloads
task check:kustomize-platform
```

Первый gate рендерит все runtime charts с dependencies и остальные управляемые
manifests и блокирует mutable/missing
image references, незакреплённые Bitnami images, отсутствующие resources и
неполный restricted security context. После sync `task ops:post-argocd-check`
дополнительно требует отсутствие необъяснённых Kyverno PolicyReport
fail/error/warn. Принятые точные исключения хранятся в
`argocd/audit/kyverno-policy-allowlist.yaml`; wildcard не поддерживается.

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
