# Scripts

Скрипты разделены по роли в greenfield bootstrap. Метка `deploy` означает,
что скрипт изменяет состояние кластера или обязательной day-0 системы.
`deploy-support` означает чистую подготовку входов для такого изменения.
Скрипты с меткой `no-deploy` не имеют собственной полезной нагрузки на
развёртывание кластера: они только проверяют, показывают состояние, обслуживают
локальный доступ или выполняют recovery/destroy.

Общие side-effect-free shell-функции находятся в `lib/`. Исполняемые скрипты
остаются атомарными entrypoint-ами и не должны вызывать друг друга для
переиспользования отдельных функций; для этого следует добавлять модуль в
`lib/`.

| Скрипт | Метка | Назначение |
| --- | --- | --- |
| `argocd-apply-bootstrap.sh` | `deploy` | Применяет один root Application и ждёт его готовности. |
| `argocd-push.sh` | `deploy` | Публикует закоммиченный `argocd/` subtree в настроенный Forgejo GitOps repository без force-push. |
| `bootstrap-linstor-storage.sh` | `deploy` | Создаёт LINSTOR device pool на заданных узлах. |
| `forgejo-argocd-cutover.sh` | `deploy` | Оркестрирует проверяемый GitOps cutover с временного Git на Forgejo. |
| `generate-runtime-secret-puts.sh` | `deploy` | Создаёт только отсутствующие runtime secrets при `--apply-missing`; обязательный пароль platform administrator читает из `.env`, без флага только печатает команды. |
| `openbao-day0.sh` | `deploy` | Настраивает day-0 OpenBao для ESO после ручного init/unseal. |
| `reconcile-cilium-lb-pool.sh` | `deploy` | Применяет минимальный Cilium LoadBalancer pool после cluster apply. |
| `test-ssh-git-bootstrap.sh` | `deploy` | Поднимает временный Git source и запускает первичный Argo CD sync. |
| `forgejo-git-askpass.sh` | `deploy-support` | Передаёт credentials дочернему `git` процесса cutover. |
| `materialize_environment_contract.py` | `deploy-support` | Вычисляет производные значения effective environment contract. |
| `render-environment-contract.sh` | `deploy-support` | Атомарно материализует effective environment contract. |
| `task-vars.sh` | `deploy-support` | Разрешает один запрошенный Taskfile input за вызов. |
| `check-chart-versions.py` | `no-deploy: validation` | Проверяет или синхронизирует mirrors версий charts. |
| `check-image-versions.py` | `no-deploy: validation` | Проверяет или синхронизирует container image pins. |
| `check-tfvars-example.py` | `no-deploy: validation` | Проверяет полноту каталога OpenTofu inputs в `terraform.tfvars.example`. |
| `check-cluster-isolation.py` | `no-deploy: validation` | Проверяет ownership boundary слоя `cluster/`. |
| `check-documentation.py` | `no-deploy: validation` | Проверяет структуру документации и локальные ссылки. |
| `check-infrastructure-isolation.py` | `no-deploy: validation` | Проверяет ownership boundary слоя `infrastructure/`. |
| `check-platform-layout.py` | `no-deploy: validation` | Проверяет границу GitOps orchestration/payload. |
| `check-release-versions.py` | `no-deploy: validation` | Проверяет или синхронизирует release pins. |
| `openbao-runtime-preflight.py` | `no-deploy: validation` | Проверяет OpenBao secret contract без вывода значений. |
| `post-argocd-check.sh` | `no-deploy: validation` | Выполняет read-only post-deploy smoke checks. |
| `validate-env-contract.py` | `no-deploy: validation` | Проверяет или синхронизирует tracked consumers контракта. |
| `garage-velero-helper.sh` | `no-deploy: operations` | Показывает status/node id и печатает ручные команды; сам bootstrap не выполняет. |
| `hosts-entries.sh` | `no-deploy: operations` | Печатает клиентские hosts entries из фактических адресов. |
| `initial-app-credentials.sh` | `no-deploy: operations` | Читает и печатает первичные интерактивные admin credentials из OpenBao и bootstrap Secret Argo CD. |
| `openbao-port-forward.sh` | `no-deploy: operations` | Управляет только локальным port-forward к OpenBao. |
| `destroy-platform-bootstrap.sh` | `no-deploy: recovery` | Удаляет platform bootstrap и обрабатывает отсутствующие CRD при destroy. |

`--write` режимы validation-скриптов меняют только tracked/generated файлы
репозитория. Они не применяют ресурсы в Kubernetes и не входят в deployment
payload.
