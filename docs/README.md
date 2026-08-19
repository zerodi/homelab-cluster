# Документация

## Канонические документы

- root [`README`](../README.md) — краткая точка входа и локальная validation;
- [deployment map](deployment-map.md) — владельцы слоёв и ручные границы;
- [day-0 bootstrap](day0-bootstrap.md) — единственная полная последовательность
  greenfield-развёртывания;
- [environment contract](environment-contract.md) — изменение non-secret
  координат и синхронизация consumers;
- [`argocd/README`](../argocd/README.md) — runtime/GitOps workflow после
  platform bootstrap.

Специализированные runbook не должны повторять полный day-0 сценарий: они
описывают только собственную область и ссылаются на канонический документ.

## Развёртывание

Greenfield-развёртывание кластера и platform bootstrap:

- [Карта этапов развёртывания](deployment-map.md)
- [Day-0 bootstrap](day0-bootstrap.md)

Основная последовательность:

```text
cluster/ -> infrastructure/ -> OpenBao init/unseal -> GitOps bootstrap
```

## Настройка и эксплуатация

Короткие практические runbook:

- [Day-1 operations](day1-operations.md)
- [Environment contract](environment-contract.md)
- [Homelab automation application](homelabctl.md)
- [Единая авторизация приложений платформы](platform-authentication.md)
- [Cutover Argo CD с test-ssh-git на Forgejo](forgejo-argocd-cutover.md)
- [Версии компонентов](chart-versions.md)
- [Backup и restore](backup-restore.md)
- [Garage и Velero](garage-velero.md)
- [Stalwart Mail Server](stalwart.md)
- [Kyverno policies](kyverno-policies.md)

Аналитические документы, audit snapshots и планы развития в документацию не
включены.
