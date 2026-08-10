# Единая авторизация приложений платформы

Этот runbook описывает создание пользователей, групп, OAuth/OIDC applications
и настройку входа через Authentik для всех пользовательских endpoints
платформы. Он рассчитан на greenfield bootstrap.

Документ различает:

- **реализовано** — конфигурация уже есть в репозитории;
- **ручной шаг** — состояние создаётся оператором после bootstrap;
- **целевая настройка** — рекомендуемый контракт для последующей реализации в
  GitOps.

Настройка SSO не меняет ownership компонентов:

- конфигурация Argo CD остаётся в `infrastructure/`;
- Authentik и runtime-приложения остаются в `argocd/`;
- client secrets хранятся только в OpenBao и доставляются через ESO там, где
  consumer поддерживает Kubernetes Secret; ручные consumers получают значение
  только во время operator setup;
- пароли, client secrets и tokens не записываются в `envs/`, Helm values,
  Terraform variables или документацию.

## Целевая схема

```text
browser
  -> application
  -> Authentik OIDC provider
  -> Authentik user/group/application policy
  -> application-local role

browser
  -> Woodpecker
  -> Forgejo OAuth2
  -> Authentik OIDC
  -> Forgejo repository permissions
```

Для Woodpecker нельзя заменить Forgejo прямым OIDC provider: Woodpecker
получает от forge не только identity, но и OAuth token с доступом к
репозиториям.

## Матрица приложений

| Компонент | Публичный endpoint | Текущий вход | Целевая модель | Состояние |
| --- | --- | --- | --- | --- |
| Authentik | `https://auth.lab.zerodi.ru` | `akadmin` | центральный IdP | реализовано |
| Forgejo | `https://git.lab.zerodi.ru` | local admin + Authentik OIDC | Authentik OIDC, local admin как break-glass | реализовано, требуется доводка регистрации |
| Woodpecker | `https://ci.lab.zerodi.ru` | Forgejo OAuth2 | Forgejo OAuth2 поверх Authentik SSO | реализовано, OAuth application создаётся вручную |
| Argo CD | environment contract | local `admin` | прямой Authentik OIDC + Argo CD RBAC | provider/application реализованы; consumer остаётся в `infrastructure/` |
| Harbor | `https://harbor.lab.zerodi.ru` | local `admin` | Authentik OIDC + Harbor groups | provider/application реализованы; переход после bootstrap |
| Grafana | `https://grafana.lab.zerodi.ru` | local admin | Authentik Generic OAuth + entitlements | provider/application реализованы; consumer ещё не включён |
| Stalwart | `https://stalwart.lab.zerodi.ru` | recovery admin + Authentik OIDC | Authentik OIDC для WebUI и совместимых клиентов, app passwords для остальных | provider, callbacks и OIDC Directory реализованы декларативно |
| Hubble UI | `https://hubble.lab.zerodi.ru` | отсутствует | Authentik proxy/outpost или сетевое ограничение | известный gap |
| echo | `https://echo.lab.zerodi.ru` | отсутствует | оставить diagnostic endpoint либо закрыть proxy policy | осознанное решение |
| Garage | S3/admin API | S3 keys/admin token | service credentials, не пользовательский OIDC | реализовано |
| OpenBao | только operator access | token + Kubernetes auth | сохранить bootstrap auth; OIDC возможен только как day-1 дополнение | реализовано |
| Velero, Kyverno, Loki, Tempo, VictoriaMetrics, OTel | ClusterIP/API | Kubernetes service identity | Kubernetes RBAC и service credentials | реализовано |

## Предварительные условия

До настройки SSO должны быть готовы:

1. `task infra:apply` и `task infra:health`;
2. инициализированный и unsealed OpenBao;
3. `task ops:openbao-day0` и `task ops:seed-runtime-secrets`;
4. готовые Authentik, Forgejo и остальные Argo CD Applications;
5. DNS для всех hostnames из effective environment contract;
6. homelab root CA в trust store браузера и операторской машины.

Проверка:

```bash
task check:env-contract
task ops:openbao-runtime-preflight
task ops:post-argocd-check
```

## Пользователи, группы и роли

Создайте в Authentik минимальный набор глобальных групп:

| Группа | Назначение |
| --- | --- |
| `platform-admins` | администраторы платформы |
| `platform-operators` | эксплуатация без управления identity |
| `platform-developers` | Forgejo, Woodpecker и developer endpoints |
| `platform-viewers` | read-only dashboards |
| `mail-users` | почтовые учётные записи |

Для ролей конкретного приложения предпочтительнее Authentik Application
Entitlements, а не размножение глобальных групп. Рекомендуемые entitlements:

| Application | Entitlements |
| --- | --- |
| Argo CD | `argocd-admin`, `argocd-readonly` |
| Harbor | `harbor-admin`, `harbor-user` |
| Grafana | `Grafana Admins`, `Grafana Editors`, `Grafana Viewers` |
| Forgejo | команды организации Forgejo, синхронизированные из OIDC groups |

Не назначайте административную роль всем аутентифицированным пользователям.
У каждого приложения должен остаться один локальный break-glass administrator,
пароль которого хранится в OpenBao или в штатном bootstrap Secret.

## Общий шаблон OIDC application

Для каждого прямого OIDC consumer создавайте отдельную пару
`Application + OAuth2/OIDC Provider` в Authentik:

1. Используйте отдельный slug: `forgejo`, `argocd`, `harbor`, `grafana` или
   `stalwart`.
2. Для browser applications выберите confidential client и Authorization Code
   flow. Stalwart использует отдельный public client с Device Authorization
   flow, поскольку mail server только валидирует уже полученный access token.
3. Укажите только точные `Strict` authorization redirect URI из таблицы ниже.
4. Выберите signing key.
5. Добавьте scopes `openid`, `profile`, `email`; `offline_access` добавляйте
   только приложению, которому нужен refresh token.
6. Привяжите к Application разрешённые группы или policy.
7. Client ID и client secret создаются через OpenBao-backed blueprints;
   Stalwart public client использует только client ID.

Закреплённая версия Authentik `2026.5.6` поддерживает типизированные redirect
URI. Blueprints явно задают `redirect_uri_type: authorization` и только
разрешённые grant types.

| Consumer | Authentik slug | Redirect URI |
| --- | --- | --- |
| Forgejo | `forgejo` | `https://git.lab.zerodi.ru/user/oauth2/authentik/callback` |
| Argo CD, direct OIDC | `argocd` | `<ARGOCD_URL>/auth/callback` |
| Harbor | `harbor` | `https://harbor.lab.zerodi.ru/c/oidc/callback` |
| Grafana | `grafana` | `https://grafana.lab.zerodi.ru/login/generic_oauth` |
| Stalwart | `stalwart` | отсутствует: public Device Authorization client |

Per-provider issuer и discovery URL имеют вид:

```text
https://auth.lab.zerodi.ru/application/o/<slug>/
https://auth.lab.zerodi.ru/application/o/<slug>/.well-known/openid-configuration
```

Blueprint-модель и специальные YAML tags сверены с официальными разделами
[Blueprints](https://docs.goauthentik.io/customize/blueprints),
[File structure](https://docs.goauthentik.io/customize/blueprints/v1/structure/)
и [YAML tags](https://docs.goauthentik.io/customize/blueprints/v1/tags).
Redirect URI и scopes основаны на integration guides Authentik для
[Grafana](https://docs.goauthentik.io/integrations/services/grafana/),
[Argo CD](https://docs.goauthentik.io/integrations/services/argocd/) и
[Harbor](https://docs.goauthentik.io/integrations/services/harbor/), а
Stalwart provider и directory — на актуальных контрактах
[OIDC backend](https://stalw.art/docs/auth/backend/oidc/) и
[WebUI OAuth client](https://stalw.art/docs/auth/oauth/client-registration/#webui-client).

## Secret contract

Декларативные Authentik blueprints используют следующий контракт:

| OpenBao path | Keys | Consumer |
| --- | --- | --- |
| `secret/platform/forgejo/oidc` | `client_id`, `client_secret` | Authentik и Forgejo |
| `secret/platform/argocd/oidc` | `client_id`, `client_secret` | Authentik; Argo CD подключается в `infrastructure/` |
| `secret/platform/harbor/oidc` | `client_id`, `client_secret` | Authentik; Harbor подключается после greenfield bootstrap |
| `secret/platform/observability/grafana-oidc` | `client_id`, `client_secret` | Authentik; Grafana получает secret через ESO при включении OAuth |
| `secret/platform/woodpecker/runtime` | `agent_secret`, `forgejo_client`, `forgejo_secret` | Woodpecker через Forgejo |

Все paths создаются `task ops:seed-runtime-secrets`, проверяются runtime secret
contract и не содержат значений в Git.

## 1. Authentik

Первичный пользователь — `akadmin`. Получите bootstrap password:

```bash
task ops:authentik-admin-password
```

После первого входа:

1. создайте постоянного пользователя из `platform-admins`;
2. включите MFA для административных пользователей;
3. проверьте доступ нового администратора;
4. оставьте `akadmin` только как recovery account;
5. создайте группы и entitlements из этого runbook.

`AUTHENTIK_BOOTSTRAP_PASSWORD` применяется только при первом запуске. Recovery
существующего instance выполняйте командой из `day0-bootstrap.md`, а не
повторным bootstrap.

## 2. Forgejo через Authentik

В репозитории декларативно реализованы provider/application pairs для Forgejo,
Argo CD, Harbor, Grafana и Stalwart. Для Forgejo дополнительно реализованы:

- Authentik blueprint с provider slug `forgejo`;
- доставка одной пары client credentials в Authentik и Forgejo из
  `secret/platform/forgejo/oidc`;
- bootstrap Job, создающий или обновляющий Forgejo authentication source.

После sync проверьте в Forgejo:

```text
Site Administration -> Authentication Sources -> Authentik
```

Для бесшовного первого входа целевая конфигурация Forgejo должна содержать:

```yaml
gitea:
  config:
    oauth2_client:
      ENABLE_AUTO_REGISTRATION: true
      USERNAME: preferred_username
      ACCOUNT_LINKING: disabled
      UPDATE_AVATAR: true
    service:
      ALLOW_ONLY_EXTERNAL_REGISTRATION: true
```

Не используйте `ACCOUNT_LINKING=auto`: совпадение email или username не должно
автоматически давать доступ к существующему локальному аккаунту.

Для централизованной авторизации настройте на Forgejo authentication source:

- group claim: `groups`;
- mapping Authentik groups в Forgejo organization teams;
- удаление пользователя из синхронизируемых teams при исчезновении группы.

Локальный Forgejo administrator из `secret/platform/forgejo/admin` остаётся
break-glass account.

## 3. Woodpecker через Forgejo и Authentik

Вход должен идти через Forgejo:

```text
Woodpecker -> Forgejo OAuth2 -> Authentik OIDC
```

Создайте в Forgejo system-wide OAuth2 application:

```text
Name: Woodpecker CI
Redirect URI: https://ci.lab.zerodi.ru/authorize
```

Используйте раздел site administration
`/admin/settings/applications`, а не OAuth application отдельного пользователя.
Полученные credentials заменяют provisional значения
`forgejo_client`/`forgejo_secret` в полном OpenBao path
`secret/platform/woodpecker/runtime`; существующий `agent_secret` нужно
сохранить.

Ограничьте регистрацию и задайте administrator явно:

```yaml
server:
  env:
    WOODPECKER_OPEN: "true"
    WOODPECKER_ORGS: platform
    WOODPECKER_ADMIN: <forgejo-username>
```

`WOODPECKER_ORGS` проверяет membership в Forgejo, поэтому Authentik group
сначала должна быть сопоставлена с team в организации `platform`.

Если `ci.lab.zerodi.ru` разрешается в private IP, разрешите Forgejo webhook
доступ к этому точному hostname. Не отключайте TLS verification: Woodpecker и
Forgejo уже получают homelab CA.

## 4. Argo CD через Authentik

Argo CD принадлежит `infrastructure/`, поэтому его OIDC configuration и
ExternalSecret нельзя переносить в `argocd/`.

Для текущей архитектуры с `dex.enabled=false` используйте прямой OIDC:

```yaml
configs:
  cm:
    url: <ARGOCD_URL>
    oidc.config: |
      name: Authentik
      issuer: https://auth.lab.zerodi.ru/application/o/argocd/
      clientID: $argocd-oidc:client_id
      clientSecret: $argocd-oidc:client_secret
      requestedScopes: ["openid", "profile", "email", "groups"]
  rbac:
    scopes: '[groups]'
    policy.csv: |
      g, argocd-admin, role:admin
      g, argocd-readonly, role:readonly
```

Secret `argocd-oidc` должен иметь label
`app.kubernetes.io/part-of: argocd`. Для internal CA передайте Argo CD server
доверенный root CA через `oidc.config.rootCA`; не включайте
`oidc.tls.insecure.skip.verify`.

Для web login callback равен `<ARGOCD_URL>/auth/callback`. CLI login через SSO
проверяйте отдельно; если используется PKCE/public client, зарегистрируйте для
него отдельный client/redirect contract.

После успешной проверки SSO отключите обычное использование built-in `admin`,
но сохраните документированный break-glass способ его временного включения.

## 5. Harbor через Authentik

Harbor допускает переход с database auth на OIDC только пока в базе нет
локальных пользователей кроме `admin`. Поэтому выполняйте этот шаг сразу после
greenfield deployment.

В Authentik создайте provider `harbor`:

- redirect URI: `https://harbor.lab.zerodi.ru/c/oidc/callback`;
- scopes: `openid,profile,email,offline_access`;
- group claim: `groups`;
- optional entitlement `harbor-admin`.

В Harbor откройте:

```text
Administration -> Configuration -> Authentication
```

Установите:

```text
Auth Mode: OIDC
OIDC Provider Name: authentik
OIDC Endpoint: https://auth.lab.zerodi.ru/application/o/harbor/
Group Claim Name: groups
OIDC Admin Group: harbor-admin
OIDC Scope: openid,profile,email,offline_access
Automatic onboarding: enabled
Username Claim: preferred_username
Verify Certificate: enabled
```

Нажмите `Test OIDC Server`, затем `Save`. Local database login для recovery
остаётся доступен через `/account/sign-in`.

Docker и Helm CLI не выполняют browser redirect. После первого OIDC login
пользователь должен получить Harbor CLI secret в своём профиле и использовать
его вместо пароля Authentik.

## 6. Grafana через Authentik

Создайте provider `grafana` с redirect URI
`https://grafana.lab.zerodi.ru/login/generic_oauth`. Добавьте scope
`entitlements` и entitlements `Grafana Admins`, `Grafana Editors`,
`Grafana Viewers`.

Целевая конфигурация Helm values:

```yaml
grafana.ini:
  auth:
    oauth_auto_login: true
    signout_redirect_url: https://auth.lab.zerodi.ru/application/o/grafana/end-session/
  auth.generic_oauth:
    enabled: true
    name: Authentik
    scopes: openid profile email entitlements
    auth_url: https://auth.lab.zerodi.ru/application/o/authorize/
    token_url: https://auth.lab.zerodi.ru/application/o/token/
    api_url: https://auth.lab.zerodi.ru/application/o/userinfo/
    role_attribute_path: "contains(entitlements[*], 'Grafana Admins') && 'Admin' || contains(entitlements[*], 'Grafana Editors') && 'Editor' || 'Viewer'"
```

Client secret нельзя добавлять в values. Доставьте его ExternalSecret и
передайте Grafana через secret-backed environment. До удаления local admin
создайте отдельного OAuth-backed администратора и проверьте его роль.

## 7. Stalwart и почтовые клиенты

Stalwart 0.16 поддерживает внешний OIDC directory для WebUI и протокольных
клиентов. Authentik provider использует public client `stalwart-webui`, PKCE,
authorization code, refresh token и device code grants. Разрешены только
строгие callbacks `/admin/oauth/callback` и `/account/oauth/callback`.

PostSync Job идемпотентно применяет через `stalwart-cli apply`:

```text
issuerUrl: https://auth.lab.zerodi.ru/application/o/stalwart/
requireAudience: stalwart-webui
requireScopes: [openid, email]
claimUsername: email
claimName: name
claimGroups: groups
```

Тот же план назначает созданный Directory в `Authentication.directoryId`.
Recovery credential остаётся доступен для декларативного Job и аварийного
входа. Почтовые principals необходимо создать заранее: OIDC не предоставляет
Stalwart offline directory lookup, и письмо неизвестному до первого входа
адресу будет отклонено.

Многие распространённые почтовые клиенты не умеют third-party OIDC через
`OAUTHBEARER`. Для них используйте отдельные Stalwart app passwords, а не пароль
Authentik. Recovery administrator из OpenBao остаётся только для аварийного
доступа и первоначальной настройки.

## 8. Hubble UI и echo

Hubble UI не предоставляет собственную пользовательскую OIDC/RBAC модель.
Сейчас endpoint опубликован без authentication; до внедрения Authentik
proxy/outpost ограничьте его trusted network/DNS.

Если нужен внешний доступ, создайте Authentik Proxy Provider в forward-auth
режиме и защитите HTTPRoute через поддерживаемый gateway/proxy integration.
До появления декларативного outpost, health checks и проверенного logout flow
не считайте Hubble защищённым Authentik.

`echo` является диагностическим workload. Выберите один из двух явно
зафиксированных режимов:

- оставить его без authentication только в trusted homelab network;
- защитить тем же proxy/outpost pattern, что Hubble.

Не используйте proxy provider для Garage S3 API, Woodpecker callbacks,
Forgejo webhooks или machine-to-machine endpoints.

## 9. Service authentication

Следующие компоненты не должны получать пользовательский OIDC только ради
унификации:

- Garage использует S3 access keys и отдельный admin token;
- Velero использует S3 credentials;
- ESO использует Kubernetes auth в OpenBao;
- Argo CD repository access использует deploy token/SSH key;
- Woodpecker agents используют `WOODPECKER_AGENT_SECRET`;
- Kyverno, Loki, Tempo, VictoriaMetrics и OTel доступны только внутри кластера
  и используют Kubernetes/network identity.

Machine credentials должны иметь отдельный lifecycle и не должны быть
привязаны к интерактивной сессии пользователя Authentik.

## Порядок внедрения

1. Завершите greenfield bootstrap и настройте CA/DNS.
2. Создайте постоянного Authentik administrator, группы и MFA.
3. Проверьте уже декларативную связку Authentik -> Forgejo.
4. Создайте system-wide Forgejo OAuth application для Woodpecker и замените
   provisional secret.
5. Добавьте Forgejo auto-registration, group/team mapping и ограничения
   Woodpecker.
6. Настройте Argo CD OIDC и RBAC, не меняя ownership `infrastructure/`.
7. Переключите новый Harbor на OIDC до создания локальных пользователей.
8. Настройте Grafana Generic OAuth и role mapping.
9. Проверьте Stalwart WebUI OIDC и список поддерживаемых mail clients.
10. Закройте Hubble UI и при необходимости echo через Authentik proxy или сеть.
11. Выполните финальные проверки и только затем ограничивайте local login.

## Проверка

Для каждого browser application выполните тест в отдельном private/incognito
окне:

1. неаутентифицированный пользователь перенаправляется в Authentik;
2. пользователь без binding получает отказ;
3. viewer не получает write/admin permissions;
4. administrator получает только ожидаемую application-local роль;
5. удаление пользователя из группы применяется после logout/login;
6. callback возвращает на правильный hostname без TLS warning;
7. local break-glass login проверен и не используется повседневно.

Общие проверки репозитория:

```bash
task check:env-contract
task check:runtime-secret-contract
task check:kustomize-bootstrap
task check:kustomize-platform
task check:yamllint
task ops:openbao-runtime-preflight-final
task ops:post-argocd-check
```

Дополнительно проверьте:

```bash
kubectl -n authentik get pods
kubectl -n forgejo get job forgejo-sso-bootstrap
kubectl get externalsecrets -A
kubectl -n argocd get applications
```

Не выводите содержимое Secrets в CI logs или общий terminal transcript.

## Deprovisioning и rotation

При удалении пользователя:

1. disable пользователя или удалите bindings/groups в Authentik;
2. завершите активные Authentik sessions;
3. удалите Forgejo team membership, если mapping ещё не автоматизирован;
4. отзовите Harbor CLI secret, personal access tokens и app passwords;
5. отзовите пользовательские Forgejo tokens и SSH keys при необходимости;
6. проверьте доступ после полного повторного login.

OIDC Single Logout поддерживается приложениями неодинаково. Logout из
Authentik не следует считать немедленным отзывом всех уже выданных application
sessions и CLI credentials.

При rotation client secret сначала обновите OpenBao, дождитесь ESO refresh и
rollout consumer, затем обновите provider/consumer в согласованном порядке.
Для ручной Harbor configuration обновите сохранённый secret и в OpenBao, и в
Harbor, после чего выполните `Test OIDC Server`.

## Официальные руководства

- [Authentik OAuth2/OIDC provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/)
- [Authentik + Argo CD](https://integrations.goauthentik.io/infrastructure/argocd/)
- [Argo CD user management and OIDC](https://argo-cd.readthedocs.io/en/latest/operator-manual/user-management/)
- [Authentik + Harbor](https://integrations.goauthentik.io/infrastructure/harbor/)
- [Harbor OIDC authentication](https://goharbor.io/docs/main/administration/configure-authentication/oidc-auth/)
- [Authentik + Grafana](https://integrations.goauthentik.io/monitoring/grafana/)
- [Woodpecker Forgejo provider](https://woodpecker-ci.org/docs/administration/configuration/forges/forgejo)
- [Woodpecker user registration](https://woodpecker-ci.org/docs/administration/configuration/server)
- [Forgejo OIDC group mappings](https://forgejo.org/docs/latest/admin/advanced/oidc-group-mappings/)
- [Stalwart external OIDC directory](https://stalw.art/docs/auth/backend/oidc/)
- [Stalwart declarative apply](https://stalw.art/docs/management/cli/apply/)
- [Stalwart WebUI OAuth client](https://stalw.art/docs/auth/oauth/client-registration/#webui-client)
