# Документация

## Развёртывание

Greenfield-развёртывание кластера и platform bootstrap:

- [Требования к окружению](prerequisites.md)
- [Day-0 bootstrap](day0-bootstrap.md)

Основная последовательность:

```text
bootstrap/ -> infrastructure/ -> OpenBao init/unseal -> GitOps bootstrap
```

## Настройка и эксплуатация

Короткие практические runbook:

- [Day-1 operations](day1-operations.md)
- [Environment contract](environment-contract.md)
- [Версии компонентов](chart-versions.md)
- [Renovate](renovate.md)
- [Backup и restore](backup-restore.md)
- [Garage и Velero](garage-velero.md)
- [Kyverno policies](kyverno-policies.md)

Аналитические документы, audit snapshots и планы развития в документацию не
включены.
