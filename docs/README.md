# Документация

## Развёртывание

Greenfield-развёртывание кластера и platform bootstrap:

- [Требования к окружению](deployment/prerequisites.md)
- [Day-0 bootstrap](deployment/day0-bootstrap.md)

Основная последовательность:

```text
bootstrap/ -> infrastructure/ -> OpenBao init/unseal -> GitOps bootstrap
```

## Настройка и эксплуатация

Короткие практические runbook:

- [Day-1 operations](configuration/day1-operations.md)
- [Environment contract](configuration/environment-contract.md)
- [Версии компонентов](configuration/chart-versions.md)
- [Renovate](configuration/renovate.md)
- [Backup и restore](configuration/backup-restore.md)
- [Garage и Velero](configuration/garage-velero.md)
- [Kyverno policies](configuration/kyverno-policies.md)

Аналитические документы, audit snapshots и планы развития в документацию не
включены.
