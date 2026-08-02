# Environment contract

[`envs/homelab.yaml`](../../envs/homelab.yaml) — базовый non-secret contract.
[`envs/homelab.override.yaml`](../../envs/homelab.override.yaml) содержит
tracked environment-specific отличия и рекурсивно накладывается поверх базы.

В нём хранятся:

- имя кластера и base domain
- GitOps repository URL и revision
- hostnames и Gateway addresses
- Piraeus/LINSTOR naming
- namespace и Secret names
- non-secret coordinates для Garage, Velero и runtime services

В нём не хранятся:

- пароли, tokens и private keys
- OpenBao secret values
- day-0 Terraform credentials
- версии Helm charts — они находятся в [`versions.yaml`](../../versions.yaml)

## Изменение contract

1. Для общего значения измените `envs/homelab.yaml`.
2. Для значения конкретного окружения измените `envs/homelab.override.yaml`,
   оставляя в нём только отличающиеся keys. Example используется как шаблон для
   нового окружения.
3. Consumers в `bootstrap/` и `infrastructure/` читают effective contract
   напрямую; tracked mirrors в `argocd/` обновите командой синхронизации.
4. Выполните:

```bash
task render-env-contract
task sync-env-contract
task check:env-contract
```

Effective contract создаётся в `out/homelab.effective.yaml` и не коммитится.
Environment-specific override коммитится, чтобы локальная проверка и CI
использовали один contract.

`task sync-env-contract` изменяет tracked mirrors в `argocd/`: repository
coordinates, hostnames, Gateway addresses, storage settings, runtime naming и
другие поля из machine-checkable mapping. После команды проверьте `git diff` и
закоммитьте изменения вместе с соответствующим environment contract.

Пути можно изменить через:

- `HOMELAB_CONFIG_PATH`
- `HOMELAB_OVERRIDE_PATH`
- `HOMELAB_EFFECTIVE_PATH`

Перед реальным GitOps bootstrap используйте strict-проверку:

```bash
task gitops:preflight
```

Она отклоняет scaffold placeholders вроде `git.example.invalid` и
`*.home.arpa`, а также проверяет обязательные OpenBao paths/keys.

`homelab.override.yaml` является tracked-файлом, поэтому должен оставаться
non-secret: runtime secrets по-прежнему живут только в OpenBao.
