# Stalwart Mail Server

Stalwart разворачивается как runtime-приложение под управлением Argo CD. Оно
не входит в Terraform/OpenTofu entrypoint `cluster/` или `infrastructure/`.

## Архитектура

- `StatefulSet/stalwart`, одна реплика, RocksDB на `20Gi` RWO PVC из
  `linstor-pool1-r1`.
- WebUI загружается Stalwart при первом старте и распаковывается во временный
  writable `emptyDir`, смонтированный в `/tmp`.
- Web UI и management API публикуются через общий Cilium
  `Gateway/gateway/external` по сгенерированному Stalwart hostname.
- SMTP/IMAP публикуются отдельным `LoadBalancer` Service на
  сгенерированном mail hostname и адресе `.240` общей подсети. Открыты
  TCP-порты `25`, `465`, `587` и `993`.
- `externalTrafficPolicy: Local` сохраняет исходный адрес SMTP-клиента.
- Сертификаты выпускает `cert-manager` через Cloudflare DNS-01 и
  `ClusterIssuer/letsencrypt-cloudflare`.
- Recovery credential хранится в `secret/platform/stalwart/runtime` в OpenBao
  и доставляется через External Secrets Operator.
- Authentik OIDC provider использует public client `stalwart-webui`, PKCE и
  строгие callbacks WebUI. PostSync Job декларативно создаёт OIDC Directory и
  назначает его активным через актуальный `stalwart-cli apply`.

Поддомены, образ, storage class и размер PVC задаются в `envs/homelab.yaml` с
environment-specific override в `envs/homelab.override.yaml`. Полные hostname
и mail LB IP материализуются из общего домена и подсети.

## Развёртывание

Диапазон Cilium LB IP `.230-.250` включает сгенерированный mail Service `.240`.
`task cluster:apply` применяет актуальный pool как
при greenfield bootstrap, так и в уже работающий кластер:

```bash
task cluster:apply
kubectl --kubeconfig out/kubeconfig get ciliumloadbalancerippool external \
  -o jsonpath='{.spec.blocks}{"\n"}'
```

Затем создайте отсутствующий OpenBao path и запустите обычный GitOps bootstrap:

```bash
export BAO_TOKEN='...'
task ops:seed-runtime-secrets
task gitops:preflight
task gitops:test-ssh-bootstrap
```

Проверка после sync:

```bash
kubectl -n argocd get applications stalwart-prereqs stalwart
kubectl -n stalwart get externalsecret,certificate,pvc,pod,svc,httproute
kubectl -n stalwart rollout status statefulset/stalwart --timeout=240s
task ops:hosts-entries
```

Проверьте применение Authentik Directory:

```bash
kubectl -n stalwart logs job/stalwart-authentik-oidc-configuration
```

OIDC не предоставляет offline directory lookup: почтовые accounts нужно
создать в Stalwart до первого входа, иначе входящая почта для ещё неизвестного
адреса будет отклонена.

`task ops:hosts-entries` читает фактические адреса из Kubernetes status и
добавляет обе записи: web hostname с адресом общего Gateway и mail hostname с
адресом `Service/stalwart-mail`.

## Первичный доступ

Откройте `https://stalwart.lab.zerodi.ru/admin`. Начальный login — `admin`,
пароль получите из OpenBao:

```bash
task ops:stalwart-admin-password
```

Если Gateway ещё не готов, используйте официальный bootstrap path через
management Service:

```bash
kubectl -n stalwart port-forward svc/stalwart 8080:8080
```

и откройте `http://127.0.0.1:8080/admin`.

То же значение из materialized Secret:

```bash
kubectl -n stalwart get secret stalwart-runtime \
  -o jsonpath='{.data.STALWART_RECOVERY_ADMIN}' | base64 -d && echo
```

Второй вариант выводит строку `admin:<password>`. После первого входа:

1. завершите setup wizard и создайте постоянного администратора;
2. в `Settings -> TLS -> Certificates` добавьте certificate с file references
   `/etc/stalwart/tls/tls.crt` и `/etc/stalwart/tls/tls.key` и назначьте его
   default certificate;
3. проверьте listeners SMTP, submissions и IMAPS;
4. удалите переменную `STALWART_RECOVERY_ADMIN` из StatefulSet и
   синхронизируйте Argo CD, чтобы recovery credential не оставался постоянно
   активным в основном контейнере. PostSync Job продолжит читать отдельный
   password key напрямую из Secret.

OpenBao path при этом можно сохранить для аварийного доступа. Для recovery
временно верните secret в environment, выполните работу и снова удалите его.

Для `mail` hostname используется публично доверенный сертификат, выпускаемый
через Cloudflare DNS-01. Настройка token и проверка ACME resources описаны в
[Cloudflare runbook](cloudflare-dns01.md).

## DNS и почтовая доставляемость

Строки в `/etc/hosts` достаточны только для локального UI и тестовых клиентов.
Для реальной почты настройте в authoritative DNS:

- `A`/`AAAA` для `mail.<domain>` на внешний адрес/NAT, ведущий к mail LB;
- `MX` почтового домена на `mail.<domain>`;
- обратную `PTR`-запись внешнего адреса на тот же hostname;
- SPF, DKIM и DMARC; DKIM public key экспортируется после создания домена в
  Stalwart;
- при необходимости MTA-STS и TLS-RPT.

Провайдер и firewall должны пропускать входящий TCP/25. Для исходящей доставки
TCP/25 также не должен блокироваться. Не публикуйте management port `8080`
напрямую: он доступен снаружи только через HTTPS Gateway.

## Обновление адресов и версии

Mail IP автоматически получает адрес `.240`, а Cilium pool занимает адреса
`.230-.250` из `cluster.ipv4_cidr` effective environment contract. Полные
имена Stalwart и mail формируются из `service_subdomains` и общего
`cluster.base_domain`. После изменения:

```bash
task cluster:apply
task sync-env-contract
task check:env-contract
```

Версия контейнера фиксируется minor-тегом `platform.stalwart.image_tag`.
Обновляйте её осознанно и проверяйте release notes перед Argo CD sync.
