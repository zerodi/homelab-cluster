# Cloudflare DNS-01 and Cilium Gateway

Cilium Gateway API остаётся единственным HTTP reverse proxy. Публичные TLS
сертификаты выпускает `cert-manager` через `ClusterIssuer/letsencrypt-cloudflare`
и ACME DNS-01 challenge в Cloudflare.

## Cloudflare API token

Создайте scoped API token только для DNS-зоны общего `cluster.base_domain`:

- Zone / DNS / Edit
- Zone / Zone / Read
- Zone Resources — только нужная DNS zone

Не используйте Global API Key.

Перед day-0 seed передайте token только через environment:

```bash
export CLOUDFLARE_API_TOKEN='...'
export BAO_TOKEN='...'
task ops:seed-runtime-secrets
```

Helper создаст отсутствующий OpenBao path:

```text
secret/platform/cert-manager/cloudflare
└── api_token
```

ESO материализует его как `Secret/cloudflare-api-token` в namespace
`cert-manager`. Token не должен попадать в Git, tfvars, Terraform state или
Helm values.

## DNS records

DNS-01 подтверждает владение зоной, но не создаёт постоянные service records.
Создайте `A`/`AAAA` записи для нужных service hostnames на опубликованные
Cilium LoadBalancer IP. Для RFC1918-адресов используйте DNS-only records или
внутреннюю DNS-зону; Cloudflare proxy не маршрутизирует приватный адрес до
домашнего кластера.

## Проверка

```bash
kubectl -n cert-manager get externalsecret cloudflare-api-token
kubectl -n cert-manager get secret cloudflare-api-token
kubectl get clusterissuer letsencrypt-cloudflare
kubectl get certificate -A
kubectl get challenge,order -A
kubectl get gateway -A
```

`ClusterIssuer` должен иметь `Ready=True`, а Certificates — `Ready=True`.
ACME account key хранится в Kubernetes Secret
`letsencrypt-cloudflare-account-key`, который создаёт cert-manager.
