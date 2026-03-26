.PHONY: help init fmt validate \
	plan-cluster apply-cluster \
	plan-platform-bootstrap apply-platform-bootstrap \
	day0-guide \
	plan apply \
	from-scratch destroy-infrastructure destroy-bootstrap destroy

help:
	@printf '%s\n' \
		'Цели:' \
		'  make init                     - tofu init' \
		'  make fmt                      - tofu fmt -recursive' \
		'  make validate                 - tofu validate' \
		'  make plan-cluster             - plan только для module.bootstrap' \
		'  make apply-cluster            - apply только для module.bootstrap' \
		'  make plan-platform-bootstrap  - plan bootstrap-операторов и их CRD' \
		'  make apply-platform-bootstrap - apply bootstrap-операторов и их CRD' \
		'  make day0-guide               - вывести ручные шаги day-0 для OpenBao' \
		'  make plan                     - полный tofu plan для bootstrap-only root entrypoint' \
		'  make apply                    - полный tofu apply для bootstrap-only root entrypoint' \
		'  make from-scratch             - поднять кластер, platform bootstrap и вывести дальнейшие шаги' \
		'  make destroy                  - сначала удалить infrastructure, затем bootstrap'

init:
	tofu init

fmt:
	tofu fmt -recursive

validate:
	tofu validate

plan-cluster:
	tofu plan -target=module.bootstrap

apply-cluster:
	tofu apply -target=module.bootstrap

plan-platform-bootstrap:
	tofu plan \
		-target=module.infrastructure.helm_release.cert_manager \
		-target=module.infrastructure.helm_release.openbao \
		-target=module.infrastructure.helm_release.external_secrets \
		-target=module.infrastructure.helm_release.trust_manager \
		-target=module.infrastructure.helm_release.piraeus_operator

apply-platform-bootstrap:
	tofu apply \
		-target=module.infrastructure.helm_release.cert_manager \
		-target=module.infrastructure.helm_release.openbao \
		-target=module.infrastructure.helm_release.external_secrets \
		-target=module.infrastructure.helm_release.trust_manager \
		-target=module.infrastructure.helm_release.piraeus_operator

day0-guide:
	@printf '%s\n' \
		'Day-0 bootstrap OpenBao:' \
		'  1. Инициализируйте и разлочьте OpenBao.' \
		'  2. Включите KV v2 на пути secret/.' \
		'  3. Включите Kubernetes auth.' \
		'  4. Создайте policy для ESO с доступом к secret/platform/*.' \
		'  5. Создайте role external-secrets для service account external-secrets/external-secrets.' \
		'  6. Запишите runtime secrets:' \
		'     - secret/platform/authentik/runtime' \
		'     - secret/platform/forgejo/admin' \
		'     - secret/platform/forgejo/oidc' \
		'  7. Runtime и GitOps bootstrap теперь выполняются через отдельный модуль gitops/.' \
		'  8. Полный runbook: docs/day0-bootstrap.md'

plan:
	tofu plan

apply:
	tofu apply

from-scratch:
	tofu apply -target=module.bootstrap
	tofu apply \
		-target=module.infrastructure.helm_release.cert_manager \
		-target=module.infrastructure.helm_release.openbao \
		-target=module.infrastructure.helm_release.external_secrets \
		-target=module.infrastructure.helm_release.trust_manager \
		-target=module.infrastructure.helm_release.piraeus_operator
	@$(MAKE) day0-guide

destroy-infrastructure:
	tofu destroy -target=module.infrastructure

destroy-bootstrap:
	tofu destroy -target=module.bootstrap -refresh=false

destroy:
	tofu destroy -target=module.infrastructure
	tofu destroy -target=module.bootstrap -refresh=false
