# Environment contract

[`envs/homelab.yaml`](../envs/homelab.yaml) — базовый non-secret contract.
[`envs/homelab.override.yaml`](../envs/homelab.override.yaml) содержит
tracked environment-specific отличия и рекурсивно накладывается поверх базы.

В нём хранятся:

- optional имя кластера (fallback `talos-pve`), общий base domain и IPv4 `/24` подсеть
- только короткие поддомены сервисов
- GitOps repository URL и revision
- техническая identity администратора: username, display name, email localpart
  и группа; effective email формируется с `cluster.base_domain`
- Piraeus/LINSTOR naming
- namespace и Secret names
- non-secret coordinates для Garage, Velero и runtime services

Полные hostnames, service URLs и LoadBalancer IP не задаются вручную. Команда
render формирует их в effective contract:

- `hosts.<service>` = `<service_subdomains.service>.<cluster.base_domain>`
- Gateway addresses = `.231-.239` из `cluster.ipv4_cidr`
- Stalwart mail LoadBalancer = `.240`
- control plane, workers, VIP и Cilium pool используют ту же подсеть

Пример минимального environment-specific override:

```yaml
cluster:
  base_domain: lab.example.net
  ipv4_cidr: 192.168.100.0/24

service_subdomains:
  argocd: cd

identity:
  administrator:
    username: administrator
    display_name: Администратор
    email_localpart: administrator
    group: platform-admins
```

В нём не хранятся:

- пароли, tokens и private keys
- OpenBao secret values
- day-0 Terraform credentials
- release/tool/container versions — они находятся в [`versions.yaml`](../versions.yaml)

Пароль `administrator` не является частью environment contract. Его можно
задать локально в root `.env` как `PLATFORM_ADMIN_PASSWORD`; при отсутствии
helper генерирует пароль. После seed источником истины остаётся OpenBao.

## Изменение contract

1. Для общего значения измените `envs/homelab.yaml`.
2. Для значения конкретного окружения измените `envs/homelab.override.yaml`,
   оставляя в нём только отличающиеся base domain, subnet или поддомены. Example
   используется как шаблон для нового окружения.
3. Render объединяет base и override, затем материализует производные FQDN,
   URL и IP в effective contract.
4. Consumers в `cluster/` и `infrastructure/` читают effective contract
   напрямую; tracked mirrors в `argocd/` обновите командой синхронизации.
5. Выполните:

```bash
task render-env-contract
task sync-env-contract
task check:env-contract
```

Effective contract создаётся в `out/homelab.effective.yaml` и не коммитится.
Environment-specific override коммитится, чтобы локальная проверка и CI
использовали один contract.

`task sync-env-contract` изменяет tracked mirrors в `argocd/`: repository
coordinates, сгенерированные hostnames и Gateway addresses, storage settings,
runtime naming, Authentik blueprint и Stalwart accounts из identity contract.
После команды
проверьте `git diff` и закоммитьте изменения вместе с environment contract.

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
