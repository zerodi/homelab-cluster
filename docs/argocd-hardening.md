# Argo CD hardening и critical promotion

## Permission model

Root Application может создавать только repository Secrets, AppProjects,
Applications, ExternalSecrets и один ClusterSecretStore в `argocd`.
`platform-orchestration` и `apps-orchestration` создают только дочерние
Applications. Runtime AppProjects разделены по domain и destination namespace.

Cluster-scoped permissions вынесены в отдельные projects:

- `platform-core-gateway` — Namespace, GatewayClass и ClusterIssuer;
- `platform-core-reloader` — ClusterRole и ClusterRoleBinding;
- `platform-identity-authentik` — cluster RBAC только Authentik;
- `platform-observability-rbac` — cluster RBAC только Grafana, Loki и OTel;
- `platform-policy-controller` — Kyverno CRD и cluster RBAC;
- `platform-policy-rules` — только ClusterPolicy и ValidatingPolicy;
- `platform-storage-velero` — Velero CRD и ClusterRoleBinding.

Остальные projects не могут создавать CRD или cluster RBAC. Все projects
ограничены фактическими Git/Helm sources, destination namespaces и
namespaced kinds.

## Staged promotion

Applications в `platform/identity`, `platform/storage` и `platform/policy`
используют `gitops.critical_revision` из environment contract. В strict mode
это полный 40-символьный Git SHA. Их AppProjects имеют постоянно активное deny
window: automated sync запрещён, manual sync разрешён.

Promotion состоит из двух публикаций:

1. Оставьте `gitops.critical_revision` без изменения, закоммитьте candidate и
   выполните `task gitops:push`. Обычные domains обновятся, критические останутся
   на прежнем snapshot.
2. Проверьте опубликованный Forgejo SHA и результаты CI/audit этого snapshot.
3. Запишите SHA в `envs/homelab.override.yaml`, выполните
   `task sync-env-contract`, `task check:validate`, проверьте diff и снова
   выполните `task gitops:push`.
4. В Argo CD вручную синхронизируйте только требуемые critical Applications в
   порядке prereqs → database/cache/controller → workload/policies.
5. Выполните `task ops:post-argocd-check` с
   `EXPECTED_GITOPS_REVISION=<published-main-sha>`.

Rollback использует тот же процесс: вернуть `critical_revision` на последний
проверенный SHA, опубликовать pointer change и вручную синхронизировать только
затронутые Applications. Изменения данных и storage rollback выполняются по
отдельным application runbook и не выводятся автоматически из Git revision.

## Internal transport

При greenfield bootstrap namespace `argocd` создаёт `infrastructure/` до
Certificate и Helm release. Для кластера, где namespace раньше был неявно
создан Helm, перед первым apply этого изменения выполните однократное adoption
без пересоздания объекта:

```bash
tofu -chdir=infrastructure import kubernetes_namespace_v1.argocd argocd
```

Внешний TLS завершается на Cilium Ingress; `argocd-server` поэтому остаётся в
режиме `server.insecure` только на внутреннем backend listener. Вход на него
разрешён лишь на API/UI port, metrics — только из `observability`.

Repo-server использует TLS с сертификатом `argocd-repo-server-tls`, который
выпускает `homelab-ca`. Server и application-controller включают strict
certificate validation. Terraform создаёт namespace и Certificate до Helm
release, поэтому TLS participants сразу стартуют с постоянным сертификатом.
После ротации Secret repo-server и его clients требуется перезапустить во время
планового `task infra:apply`, как предписывает Argo CD. Repo-server
ingress разрешён только Argo CD clients, metrics — только observability.
Egress server/repo-server ограничен DNS, необходимыми Argo CD services,
Kubernetes API и Git/Helm HTTPS; SSH/22 сохранён только для documented
test-SSH bootstrap path.

Redis остаётся plaintext внутри namespace, но принимает соединения только от
server, repo-server и application-controller. Для текущего homelab это
принятый residual risk.

## Availability baseline

Homelab baseline сознательно single-replica: application-controller, server,
repo-server, ApplicationSet controller и Redis имеют `replicas: 1`, Redis HA
отключён. Потеря их worker временно останавливает reconciliation/UI, но не
останавливает уже работающие workloads. Kubernetes пересоздаёт stateless
components на доступном worker; состояние Argo CD хранится в Kubernetes API и
Git, Redis используется как cache.

Переход на HA нужен, если reconciliation/UI получают availability SLO или
обслуживание одного worker не должно создавать паузу. Тогда одновременно
включаются минимум две replicas server/repo-server/ApplicationSet, HA
application-controller и Redis HA, topology spread/anti-affinity и PDB; это
отдельное capacity/change решение, а не часть текущего baseline.
