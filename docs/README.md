# Документация

## Развёртывание

Greenfield-развёртывание кластера и platform bootstrap:

- [Требования к окружению](prerequisites.md)
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
- [Единая авторизация приложений платформы](platform-authentication.md)
- [Cutover Argo CD с test-ssh-git на Forgejo](forgejo-argocd-cutover.md)
- [Версии компонентов](chart-versions.md)
- [Renovate](renovate.md)
- [Backup и restore](backup-restore.md)
- [Garage и Velero](garage-velero.md)
- [Stalwart Mail Server](stalwart.md)
- [Kyverno policies](kyverno-policies.md)

Аналитические документы, audit snapshots и планы развития в документацию не
включены.
