# Roadmap развития: Terraform vs ArgoCD

Цель: разделить ответственность так, чтобы `Terraform` закрывал bootstrap инфраструктуры, а `ArgoCD` управлял runtime в Kubernetes.

## Принцип разделения

`Terraform`:
- инфраструктура вне кластера (Proxmox VM, Talos bootstrap)
- критичный Day-0 bootstrap внутри кластера (без которого GitOps не взлетит)
- одноразовые/низкоуровневые операции, которые плохо выражаются декларативно в ArgoCD

`ArgoCD`:
- все long-lived Kubernetes workloads и их конфигурация
- большинство манифестов приложений, ingress, certificates, ExternalSecret
- versioned rollout/rollback приложений через Git

## Что оставить в Terraform (целевая зона)

1. `bootstrap/` полностью:
- Talos image, VM, machine config, bootstrap control-plane, kubeconfig/talosconfig.

2. Минимальный bootstrap в `infrastructure/`:
- `helm_release.argocd`
- `helm_release.cert_manager`
- `helm_release.openbao`
- `helm_release.external_secrets`
- `helm_release.piraeus_operator`
- storage bootstrap для LINSTOR/Piraeus, который сейчас завязан на `kubectl linstor` и readiness loops

3. Опционально оставить в Terraform:
- trust bootstrap (`trust-manager` + корневой `ClusterIssuer`), если нужен максимально ранний TLS до старта GitOps.

## Что переносить в ArgoCD (целевая зона)

1. Приложения и их runtime:
- `authentik` (сейчас `infrastructure/authentik.tf`)
- `forgejo` (сейчас `infrastructure/forgejo.tf`)
- `echo` demo (сейчас `infrastructure/echo.tf`)

2. Kubernetes-манифесты, создаваемые через `terraform_data + kubectl apply`:
- `ClusterSecretStore openbao`
- все `ExternalSecret` (authentik runtime, forgejo admin, forgejo oidc, argocd repo creds)
- `AppProject` и GitOps bootstrap-объекты
- `LinstorSatelliteConfiguration`, `LinstorCluster` (после стабилизации CRD readiness через sync waves)

3. Namespace policy/config:
- labels для trust bundle distribution
- app-specific certificates/ingress

## Фаза 0 (текущее состояние)

Сейчас почти весь platform-layer управляется Terraform-модулем `infrastructure`, а `populate` вручную подготавливает ArgoCD/Forgejo/Authentik через local-exec.

Критичные ограничения:
- смешение декларативного и императивного подходов (`terraform_data` + shell)
- drift между GitOps-желаемым состоянием и Terraform state
- сложнее делать app-level rollback

## Фаза 1 (1-2 недели): стабилизация bootstrap-контракта

Цель: зафиксировать минимальный Terraform baseline.

Сделать:
1. Ввести явный контракт: Terraform доводит кластер до "ArgoCD + ESO + OpenBao + Storage ready".
2. Добавить outputs/документацию readiness-критериев (какие namespace/CRD/issuer гарантируются).
3. Упростить `make`-цели под 3 шага:
- `apply-cluster`
- `apply-platform-bootstrap`
- `apply-gitops-bootstrap` (пока может вызывать существующий `populate`).

Результат:
- воспроизводимый Day-0/Day-1 bootstrap без деплоя runtime-приложений Terraform-ом.

## Фаза 2 (2-4 недели): ArgoCD App-of-Apps bootstrap

Цель: перенести runtime desired state в Git.

Сделать:
1. Создать GitOps repo-структуру:
- `bootstrap/` (core apps)
- `platform/` (auth, scm, observability)
- `apps/` (user workloads)
2. В ArgoCD внедрить `App-of-Apps` root application.
3. Перенести из Terraform в ArgoCD:
- `echo`
- `authentik`
- `forgejo`
- связанные ingress/certificate manifests.

Результат:
- runtime-приложения обновляются только через Git commit.

## Фаза 3 (4-6 недель): перенос secret/bootstrap manifest-слоя

Цель: убрать `terraform_data` с `kubectl apply` для runtime-объектов.

Сделать:
1. Перенести `ExternalSecret`/`ClusterSecretStore` в GitOps (с sync waves).
2. Перенести `populate`-ресурсы ArgoCD project/repo secrets в managed manifests.
3. Оставить в Terraform только передачу минимальных bootstrap credentials (если нужно).

Результат:
- Terraform state перестает быть источником правды для runtime K8s объектов.

## Фаза 4 (6+ недель): hardening и операционная модель

Сделать:
1. Политика ownership:
- запрет на создание app manifests через Terraform в `default`/app namespaces.
2. Проверки drift:
- CI на GitOps repo (`kustomize build`/`helm template` + policy checks).
3. Процедуры recovery:
- отдельные runbook для `Terraform disaster recovery` и `ArgoCD reconciliation`.

Результат:
- четкая модель: Infra lifecycle через Terraform, App lifecycle через ArgoCD.

## План развития (12 недель)

### Итерация 1 (недели 1-2): закрепить bootstrap границы

1. `Terraform`: выделить минимальный набор bootstrap-ресурсов и зафиксировать его в документации/`make`-целях.
2. `Terraform`: убрать из runtime-потока все не обязательные для старта ArgoCD ресурсы.
3. `ArgoCD`: подготовить пустой GitOps-репозиторий со структурой `bootstrap/`, `platform/`, `apps/`.

Критерий завершения:
- после `make apply-cluster` и `make apply-platform-bootstrap` кластер стабильно доходит до `ArgoCD + OpenBao + ESO + Piraeus ready`.

### Итерация 2 (недели 3-4): запустить App-of-Apps

1. `ArgoCD`: создать root `Application` (App-of-Apps) и включить auto-sync для `bootstrap/`.
2. `ArgoCD`: вынести `echo` из Terraform в GitOps для проверки базового цикла доставки.
3. `ArgoCD`: добавить sync waves/depends-on для CRD-first компонентов.

Критерий завершения:
- `echo` отсутствует в Terraform state и управляется только через ArgoCD.

### Итерация 3 (недели 5-8): перенос основных приложений

1. `ArgoCD`: перенести `authentik` chart + ingress/certificate manifests.
2. `ArgoCD`: перенести `forgejo` chart + ingress/certificate manifests.
3. `ArgoCD`: вынести app-level namespace labels и trust bundle targets в GitOps.

Критерий завершения:
- изменения `authentik`/`forgejo` выполняются только через PR в GitOps-репозиторий.

### Итерация 4 (недели 9-10): перенос secret-manifests

1. `ArgoCD`: перенести `ExternalSecret` для `authentik-runtime`, `forgejo-admin-secret`, `forgejo-oidc`.
2. `ArgoCD`: перенести `ClusterSecretStore openbao` и bootstrap `AppProject`/repo secrets.
3. `Terraform`: удалить соответствующие `terraform_data` с `kubectl apply`.

Критерий завершения:
- `tofu plan` больше не показывает runtime `ExternalSecret`/`ClusterSecretStore`/`AppProject`.

### Итерация 5 (недели 11-12): операционное усиление

1. `Terraform`: добавить guardrails, чтобы app-level манифесты не возвращались в infra слой.
2. `ArgoCD`: внедрить policy-checks в CI (`kustomize build`/`helm template` + валидации).
3. `Runbooks`: оформить процедуры восстановления для Terraform bootstrap и ArgoCD reconciliation.

Критерий завершения:
- полное восстановление runtime после bootstrap выполняется через `argocd sync` без ручного `kubectl apply`.

## Практическая матрица ответственности

`Terraform`:
- Proxmox/Talos lifecycle
- Cilium/LB базовый networking
- Bootstrap operators (ArgoCD, cert-manager, ESO, OpenBao, Piraeus)
- low-level storage bootstrap (LINSTOR device pools)

`ArgoCD`:
- Authentik, Forgejo, Echo и следующие приложения
- Ingress/Certificate/ExternalSecret для приложений
- AppProject/ApplicationSet/app overlays
- namespace-level app policies

## Критерии готовности миграции

1. `tofu plan` не содержит app-level ресурсов (`authentik`, `forgejo`, `echo`, runtime ExternalSecret).
2. Любое изменение runtime проходит только через GitOps PR.
3. После `tofu apply` и bootstrap ArgoCD кластер полностью восстанавливается через `argocd sync` без ручного `kubectl apply`.
