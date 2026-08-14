# Карта этапов развёртывания

Этот документ фиксирует зависимости, владельцев и границы автоматизации
greenfield-развёртывания. Исполняемая операторская последовательность находится
в [day-0 runbook](day0-bootstrap.md).

## Последовательность и владельцы

```text
repository inputs
  -> cluster/          Proxmox VM, Talos, Kubernetes, Cilium, out/*config
  -> infrastructure/   CRD operators, PKI, LINSTOR, OpenBao, Argo CD
  -> operator           OpenBao init/unseal и внешние credentials
  -> argocd/            runtime applications и app-level GitOps resources
  -> operator           внешние интеграции, ротация и финальная проверка
```

| Этап | Владелец | Автоматизация | Ручная граница |
|---|---|---|---|
| Подготовка inputs | repository root | `task init`, environment/version contracts | Proxmox API token, SSH и проверка storage device |
| Kubernetes bootstrap | `cluster/` | `task cluster:apply` | Нет после подготовки inputs |
| Platform bootstrap | `infrastructure/` | `task infra:apply` | Не инициализирует OpenBao |
| OpenBao post-init | operator + `scripts/` | `task ops:openbao-day0` | Init, unseal и хранение recovery material |
| Runtime secrets | OpenBao + ESO | Seed и contract checks автоматизированы | OAuth/S3 credentials и их финальная ротация |
| GitOps bootstrap | `argocd/` + temporary/persistent Git | Test SSH и постоянный Git поддерживаются Task-командами | Доступный Git endpoint и Forgejo cutover |
| Финальная готовность | все слои | Health, preflight и smoke checks | Исправление внешних DNS/OAuth/storage зависимостей |

## Состав автоматизированных слоёв

`cluster/` создаёт Talos image и VM, применяет machine configuration,
bootstrap-ит control plane, устанавливает минимальный Cilium и записывает
`out/kubeconfig` с `out/talosconfig`.

`infrastructure/` устанавливает CRD-delivering releases до CRD-backed
resources, создаёт PKI, LINSTOR device pools и StorageClass, затем OpenBao и
Argo CD. Raw block device выбирает оператор до запуска; helper не должен
использоваться для диска с нужными данными.

`argocd/` запускается отдельно после готовности platform bootstrap. Он владеет
приложениями, app-level ExternalSecrets, routing, policies и runtime storage,
но не OpenBao, ESO или LINSTOR bootstrap.

## Намеренно ручные операции

- OpenBao init/unseal и хранение root token/recovery material;
- создание внешних OAuth applications;
- Garage layout, bucket и S3 key;
- настройка внешних DNS records и клиентских trust stores;
- ротация provisional Woodpecker и Velero credentials.

`task from-scratch` автоматизирует только cluster и infrastructure layers и
останавливается перед OpenBao init/unseal. Полностью unattended deployment до
готового runtime не является контрактом проекта.

Пошаговые команды и критерий завершения: [Day-0 bootstrap](day0-bootstrap.md).
