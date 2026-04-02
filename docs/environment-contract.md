# Environment Contract

Этот документ описывает единый non-secret contract для окружения, который лежит в [`envs/homelab.yaml`](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml).

Цель файла:

- собрать в одном месте `repoURL`, hostnames и storage naming
- уменьшить расхождение между Terraform bootstrap inputs и `argocd/` manifests
- дать оператору один reference перед заменой placeholder-значений

Это не source of truth для секретов.
Runtime secrets по-прежнему живут в `OpenBao`, а day-0 Terraform secrets не выносятся сюда.

## Что хранить в контракте

В [`envs/homelab.yaml`](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml) должны находиться только non-secret значения:

- `cluster.name` и `cluster.base_domain`
- `gitops.repo_url` и `gitops.revision`
- ingress hostnames для `argocd`, `authentik`, `forgejo`, `echo`, `grafana`, `hubble`
- storage naming для `Piraeus` и LINSTOR
- runtime naming contracts вроде namespace, secret names, `root_url`, `discovery_url`

## Mapping

`cluster.name`
- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)

`hosts.argocd`
- [terraform.tfvars.example](/home/zerodi/code/talos-proxmox-no-ssh/terraform.tfvars.example)
- [bootstrap/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/bootstrap/variables.tf)
- [infrastructure/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/variables.tf)

`gitops.repo_url`
- [argocd/bootstrap/root-application.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/bootstrap/root-application.yaml)
- [argocd/bootstrap/applications/platform.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/bootstrap/applications/platform.yaml)
- [argocd/bootstrap/applications/apps.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/bootstrap/applications/apps.yaml)
- [argocd/bootstrap/projects/platform.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/bootstrap/projects/platform.yaml)
- [argocd/bootstrap/projects/apps.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/bootstrap/projects/apps.yaml)
- [argocd/platform/authentik-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-prereqs.yaml)
- [argocd/platform/authentik-postgresql.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-postgresql.yaml)
- [argocd/platform/authentik-redis.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-redis.yaml)
- [argocd/platform/authentik.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik.yaml)
- [argocd/platform/forgejo-postgresql.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo-postgresql.yaml)
- [argocd/platform/forgejo-valkey.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo-valkey.yaml)
- [argocd/platform/forgejo-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo-prereqs.yaml)
- [argocd/platform/forgejo.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo.yaml)
- [argocd/platform/observability-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability-prereqs.yaml)
- [argocd/platform/victoria-metrics.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/victoria-metrics.yaml)
- [argocd/platform/loki.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/loki.yaml)
- [argocd/platform/tempo.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/tempo.yaml)
- [argocd/platform/otel-collector.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/otel-collector.yaml)
- [argocd/platform/grafana.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/grafana.yaml)
- [argocd/platform/hubble.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/hubble.yaml)
- [argocd/apps/echo.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo.yaml)

`gitops.revision`
- те же `Application` manifests в [`argocd/`](/home/zerodi/code/talos-proxmox-no-ssh/argocd)

`hosts.authentik`
- [argocd/platform/authentik/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/values.yaml)
- [argocd/platform/authentik/prereqs/certificate.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/certificate.yaml)
- [argocd/platform/authentik/prereqs/gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/gateway.yaml)
- [argocd/platform/authentik/prereqs/httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/httproute.yaml)
- [argocd/platform/authentik/prereqs/redirect-httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/redirect-httproute.yaml)
- [argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml)
- [argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml)

`hosts.forgejo`
- [argocd/platform/forgejo/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/values.yaml)
- [argocd/platform/forgejo/prereqs/certificate.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/certificate.yaml)
- [argocd/platform/forgejo/prereqs/gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/gateway.yaml)
- [argocd/platform/forgejo/prereqs/httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/httproute.yaml)
- [argocd/platform/forgejo/prereqs/redirect-httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/redirect-httproute.yaml)
- [argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml)
- [argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml)
- [argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml)

`hosts.echo`
- [argocd/apps/echo/resources/certificate.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/certificate.yaml)
- [argocd/apps/echo/resources/gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/gateway.yaml)
- [argocd/apps/echo/resources/httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/httproute.yaml)
- [argocd/apps/echo/resources/redirect-httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/apps/echo/resources/redirect-httproute.yaml)

`hosts.grafana`
- [argocd/platform/observability/prereqs/certificate.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/prereqs/certificate.yaml)
- [argocd/platform/observability/prereqs/gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/prereqs/gateway.yaml)
- [argocd/platform/observability/prereqs/httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/prereqs/httproute.yaml)
- [argocd/platform/observability/prereqs/redirect-httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/prereqs/redirect-httproute.yaml)

`hosts.hubble`
- [argocd/platform/hubble/httproute.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/hubble/httproute.yaml)
- [argocd/platform/hubble.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/hubble.yaml)

`storage.piraeus.namespace`
- [bootstrap/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/bootstrap/variables.tf)
- [infrastructure/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/variables.tf)
- [infrastructure/providers.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/providers.tf)
- [infrastructure/piraeus.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/piraeus.tf)

`storage.piraeus.pool_name`
- [bootstrap/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/bootstrap/variables.tf)
- [infrastructure/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/variables.tf)
- [infrastructure/providers.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/providers.tf)
- [infrastructure/piraeus.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/piraeus.tf)

`storage.piraeus.replica_count`
- [bootstrap/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/bootstrap/variables.tf)
- [infrastructure/variables.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/variables.tf)
- [infrastructure/providers.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/providers.tf)
- [infrastructure/piraeus.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/piraeus.tf)

`storage.piraeus.storage_class`
- [argocd/platform/authentik/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/values.yaml)
- [argocd/platform/forgejo/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/values.yaml)
- [infrastructure/outputs.tf](/home/zerodi/code/talos-proxmox-no-ssh/infrastructure/outputs.tf)

`platform.authentik.*`
- [argocd/platform/authentik/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/values.yaml)
- [argocd/platform/authentik-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-prereqs.yaml)
- [argocd/platform/authentik-postgresql.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-postgresql.yaml)
- [argocd/platform/authentik-redis.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-redis.yaml)
- [argocd/platform/authentik/prereqs/runtime-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/runtime-external-secret.yaml)
- [argocd/platform/authentik/prereqs/postgresql-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/postgresql-auth-external-secret.yaml)
- [argocd/platform/authentik/prereqs/redis-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/redis-auth-external-secret.yaml)

`platform.gateway.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/gateway.yaml)
- [argocd/platform/gateway/gateway-class.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/gateway/gateway-class.yaml)
- [argocd/platform/gateway/internal-gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/gateway/internal-gateway.yaml)
- [argocd/platform/gateway/external-gateway.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/gateway/external-gateway.yaml)

`platform.authentik.postgresql.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/authentik/postgresql/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/postgresql/values.yaml)
- [argocd/platform/authentik-postgresql.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-postgresql.yaml)
- [argocd/platform/authentik/prereqs/postgresql-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/postgresql-auth-external-secret.yaml)
- [argocd/platform/authentik/prereqs/runtime-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/runtime-external-secret.yaml)

`platform.authentik.redis.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/authentik/redis/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/redis/values.yaml)
- [argocd/platform/authentik-redis.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik-redis.yaml)
- [argocd/platform/authentik/prereqs/redis-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/redis-auth-external-secret.yaml)
- [argocd/platform/authentik/prereqs/runtime-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/runtime-external-secret.yaml)

`platform.forgejo.*`
- [argocd/platform/forgejo/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/values.yaml)
- [argocd/platform/forgejo/prereqs/admin-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/admin-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/postgresql-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/postgresql-auth-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/valkey-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/valkey-auth-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/oidc-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/oidc-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml)
- [argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml)
- [argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml)

`platform.forgejo.postgresql.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/forgejo/postgresql/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/postgresql/values.yaml)
- [argocd/platform/forgejo-postgresql.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo-postgresql.yaml)
- [argocd/platform/forgejo/prereqs/postgresql-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/postgresql-auth-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml)
- [docs/forgejo-postgresql-migration.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/forgejo-postgresql-migration.md)

`platform.forgejo.valkey.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/forgejo/valkey/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/valkey/values.yaml)
- [argocd/platform/forgejo-valkey.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo-valkey.yaml)
- [argocd/platform/forgejo/prereqs/valkey-auth-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/valkey-auth-external-secret.yaml)
- [argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml)
- [argocd/platform/forgejo/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/values.yaml)
- [docs/forgejo-postgresql-migration.md](/home/zerodi/code/talos-proxmox-no-ssh/docs/forgejo-postgresql-migration.md)

`platform.forgejo.sso.provider_name`, `platform.forgejo.sso.application_slug`, `platform.forgejo.sso.authentik_host`, `platform.forgejo.sso.forgejo_root_url`
- [argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml)
- [argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml)

`platform.forgejo.sso.discovery_url`
- [argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml)
- [argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml)

`platform.observability.*`
- [envs/homelab.yaml](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
- [argocd/platform/observability-prereqs.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability-prereqs.yaml)
- [argocd/platform/victoria-metrics.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/victoria-metrics.yaml)
- [argocd/platform/loki.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/loki.yaml)
- [argocd/platform/tempo.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/tempo.yaml)
- [argocd/platform/otel-collector.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/otel-collector.yaml)
- [argocd/platform/grafana.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/grafana.yaml)
- [argocd/platform/observability/prereqs/grafana-admin-external-secret.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/prereqs/grafana-admin-external-secret.yaml)
- [argocd/platform/observability/victoria-metrics/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/victoria-metrics/values.yaml)
- [argocd/platform/observability/loki/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/loki/values.yaml)
- [argocd/platform/observability/tempo/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/tempo/values.yaml)
- [argocd/platform/observability/otel-collector/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/otel-collector/values.yaml)
- [argocd/platform/observability/grafana/values.yaml](/home/zerodi/code/talos-proxmox-no-ssh/argocd/platform/observability/grafana/values.yaml)

## Operator workflow

Перед изменением доменов, `repoURL` или storage naming:

1. сначала обновите [`envs/homelab.yaml`](/home/zerodi/code/talos-proxmox-no-ssh/envs/homelab.yaml)
2. затем синхронно обновите перечисленные Terraform и ArgoCD файлы
3. после этого прогоните локальную валидацию и нужный bootstrap path

Пока контракт не подключён к генерации manifests, он используется как явный human-readable reference.
