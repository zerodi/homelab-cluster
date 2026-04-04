#!/usr/bin/env bash

set -euo pipefail

rand_alnum() {
  local length="$1"
  local out=""
  while ((${#out} < length)); do
    out+="$(
      set +o pipefail
      tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$length"
    )"
  done
  printf '%s' "${out:0:length}"
}

rand_b64ish() {
  local length="$1"
  local out=""
  while ((${#out} < length)); do
    out+="$(
      set +o pipefail
      tr -dc 'A-Za-z0-9._~!@#%^*-+=' </dev/urandom 2>/dev/null | head -c "$length"
    )"
  done
  printf '%s' "${out:0:length}"
}

rand_ini_safe() {
  rand_alnum "$1"
}

authentik_secret_key="$(rand_b64ish 64)"
authentik_postgresql_password="$(rand_b64ish 40)"
authentik_redis_password="$(rand_b64ish 40)"
forgejo_admin_password="$(rand_ini_safe 40)"
forgejo_postgresql_password="$(rand_ini_safe 40)"
forgejo_valkey_password="$(rand_ini_safe 40)"
harbor_admin_password="$(rand_ini_safe 40)"
harbor_postgresql_password="$(rand_ini_safe 40)"
harbor_valkey_password="$(rand_ini_safe 40)"
harbor_secret_key="$(rand_alnum 16)"
harbor_core_secret="$(rand_alnum 16)"
harbor_xsrf_key="$(rand_alnum 32)"
harbor_jobservice_secret="$(rand_alnum 16)"
harbor_registry_http_secret="$(rand_alnum 16)"
harbor_registry_password="$(rand_ini_safe 40)"
grafana_password="$(rand_b64ish 32)"
woodpecker_agent_secret="$(rand_b64ish 64)"

cat <<EOF
# Runtime secrets for OpenBao day-0 bootstrap.
# Review before applying. Fields tied to external systems still require manual values.

bao kv put secret/platform/authentik/runtime \\
  secret_key='${authentik_secret_key}'

bao kv put secret/platform/authentik/postgresql \\
  password='${authentik_postgresql_password}'

bao kv put secret/platform/authentik/redis \\
  password='${authentik_redis_password}'

bao kv put secret/platform/forgejo/admin \\
  username='forgejo' \\
  password='${forgejo_admin_password}'

bao kv put secret/platform/forgejo/postgresql \\
  password='${forgejo_postgresql_password}'

bao kv put secret/platform/forgejo/valkey \\
  password='${forgejo_valkey_password}'

bao kv put secret/platform/forgejo/oidc \\
  client_id='REPLACE_WITH_AUTHENTIK_CLIENT_ID' \\
  client_secret='REPLACE_WITH_AUTHENTIK_CLIENT_SECRET'

bao kv put secret/platform/harbor/runtime \\
  admin_password='${harbor_admin_password}' \\
  secret_key='${harbor_secret_key}' \\
  core_secret='${harbor_core_secret}' \\
  xsrf_key='${harbor_xsrf_key}' \\
  jobservice_secret='${harbor_jobservice_secret}' \\
  registry_http_secret='${harbor_registry_http_secret}' \\
  registry_password='${harbor_registry_password}' \\
  registry_htpasswd='REPLACE_WITH_BCRYPT_HTPASSWD_LINE'

bao kv put secret/platform/harbor/postgresql \\
  password='${harbor_postgresql_password}'

bao kv put secret/platform/harbor/valkey \\
  password='${harbor_valkey_password}'

bao kv put secret/platform/observability/grafana \\
  username='admin' \\
  password='${grafana_password}'

bao kv put secret/platform/woodpecker/runtime \\
  agent_secret='${woodpecker_agent_secret}' \\
  forgejo_client='REPLACE_WITH_FORGEJO_OAUTH_CLIENT_ID' \\
  forgejo_secret='REPLACE_WITH_FORGEJO_OAUTH_CLIENT_SECRET'

bao kv put secret/platform/velero/s3 \\
  access_key_id='REPLACE_WITH_S3_ACCESS_KEY_ID' \\
  secret_access_key='REPLACE_WITH_S3_SECRET_ACCESS_KEY'
EOF
