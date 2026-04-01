.PHONY: help init fmt validate \
	plan-cluster apply-cluster \
	plan-platform-bootstrap apply-platform-bootstrap wait-platform-crds bootstrap-piraeus-storage \
	day0-guide openbao-day0 apply-gitops-bootstrap \
	plan apply \
	from-scratch destroy-infrastructure destroy-bootstrap destroy

help:
	@printf '%s\n' \
		'Цели:' \
		'  make init                     - tofu init в bootstrap/ и infrastructure/' \
		'  make fmt                      - tofu fmt -recursive' \
		'  make validate                 - validate bootstrap/ и infrastructure/' \
		'  make plan-cluster             - plan bootstrap entrypoint' \
		'  make apply-cluster            - apply bootstrap entrypoint' \
		'  make plan-platform-bootstrap  - plan первой стадии platform bootstrap (до CRD-backed manifests)' \
		'  make apply-platform-bootstrap - staged apply bootstrap-операторов, storage и readiness' \
		'  make wait-platform-crds       - дождаться регистрации cert-manager/piraeus/trust-manager CRD' \
		'  make bootstrap-piraeus-storage - создать LINSTOR device pools вне Terraform graph' \
		'  make openbao-day0             - автоматизировать post-init настройку OpenBao для ESO' \
		'  make apply-gitops-bootstrap   - применить root Application ArgoCD после preflight checks' \
		'  make day0-guide               - вывести ручные шаги day-0 для OpenBao' \
		'  make plan                     - alias для bootstrap entrypoint' \
		'  make apply                    - alias для bootstrap entrypoint' \
		'  make from-scratch             - поднять кластер, platform bootstrap и вывести дальнейшие шаги' \
		'  make destroy-infrastructure   - staged destroy infrastructure/ с CRD-backed cleanup' \
		'  make destroy-bootstrap        - удалить bootstrap/ без refresh' \
		'  make destroy                  - сначала удалить infrastructure, затем bootstrap'

init:
	tofu -chdir=bootstrap init
	tofu -chdir=infrastructure init

fmt:
	tofu fmt -recursive

validate:
	tofu -chdir=bootstrap validate
	tofu -chdir=infrastructure validate

plan-cluster:
	tofu -chdir=bootstrap plan -var-file=../terraform.tfvars

apply-cluster:
	tofu -chdir=bootstrap apply -var-file=../terraform.tfvars

plan-platform-bootstrap:
	tofu -chdir=infrastructure plan \
		-var=crd_backed_resources_enabled=false \
		-target=helm_release.cert_manager \
		-target=helm_release.external_secrets \
		-target=helm_release.trust_manager \
		-target=kubernetes_namespace_v1.piraeus \
		-target=kubernetes_labels.piraeus_namespace_pod_security \
		-target=helm_release.piraeus_operator

wait-platform-crds:
	KUBECONFIG="$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" kubectl wait --for=condition=Established --timeout=10m crd/clusterissuers.cert-manager.io
	KUBECONFIG="$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" kubectl wait --for=condition=Established --timeout=10m crd/certificates.cert-manager.io
	KUBECONFIG="$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" kubectl wait --for=condition=Established --timeout=10m crd/bundles.trust.cert-manager.io
	KUBECONFIG="$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" kubectl wait --for=condition=Established --timeout=10m crd/linstorsatelliteconfigurations.piraeus.io
	KUBECONFIG="$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" kubectl wait --for=condition=Established --timeout=10m crd/linstorclusters.piraeus.io

bootstrap-piraeus-storage:
	./infrastructure/scripts/bootstrap-linstor-storage.sh \
		--kubeconfig "$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")" \
		--namespace "$$(tofu -chdir=bootstrap output -raw piraeus_namespace)" \
		--pool-name "$$(tofu -chdir=bootstrap output -raw piraeus_storage_pool_name)" \
		--device "$$(tofu -chdir=bootstrap output -raw piraeus_storage_device)" \
		--nodes "$$(tofu -chdir=bootstrap output -raw piraeus_storage_nodes_csv)"

apply-platform-bootstrap:
	tofu -chdir=infrastructure apply \
		-var=crd_backed_resources_enabled=false \
		-target=helm_release.cert_manager \
		-target=helm_release.external_secrets \
		-target=helm_release.trust_manager \
		-target=kubernetes_namespace_v1.piraeus \
		-target=kubernetes_labels.piraeus_namespace_pod_security \
		-target=helm_release.piraeus_operator

	@$(MAKE) wait-platform-crds
	tofu -chdir=infrastructure apply \
		-target=kubernetes_manifest.selfsigned_clusterissuer \
		-target=kubernetes_manifest.homelab_root_ca \
		-target=kubernetes_manifest.homelab_ca_clusterissuer \
		-target=kubernetes_cluster_role_binding_v1.external_secrets_openbao_auth_delegator

	tofu -chdir=infrastructure apply \
		-target=helm_release.piraeus_operator \
		-target=terraform_data.piraeus_operator_ready \
		-target=kubernetes_manifest.linstor_satellite_configuration_talos \
		-target=kubernetes_manifest.linstor_cluster \
		-target=terraform_data.linstor_cluster_ready
	@$(MAKE) bootstrap-piraeus-storage
	tofu -chdir=infrastructure apply

day0-guide:
	@printf '%s\n' \
		'Day-0 bootstrap OpenBao:' \
		'  1. Инициализируйте и разлочьте OpenBao.' \
		'  2. Экспортируйте BAO_TOKEN и запустите make openbao-day0.' \
		'  3. Запишите runtime secrets:' \
		'     - secret/platform/authentik/runtime' \
		'     - secret/platform/forgejo/admin' \
		'     - secret/platform/forgejo/oidc' \
		'  4. Обновите repoURL/sourceRepos и домены в argocd/.' \
		'  5. Запустите make apply-gitops-bootstrap.' \
		'  6. Полный runbook: docs/day0-bootstrap.md'

openbao-day0:
	./infrastructure/scripts/openbao-day0.sh \
		--kubeconfig "$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")"

apply-gitops-bootstrap:
	./argocd/scripts/apply-bootstrap.sh \
		--kubeconfig "$$(cd bootstrap && realpath "$$(tofu output -raw kubeconfig_path)")"

plan:
	tofu -chdir=bootstrap plan -var-file=../terraform.tfvars

apply:
	tofu -chdir=bootstrap apply -var-file=../terraform.tfvars

from-scratch:
	tofu -chdir=bootstrap apply -var-file=../terraform.tfvars
	@$(MAKE) apply-platform-bootstrap
	@$(MAKE) day0-guide

destroy-infrastructure:
	./infrastructure/scripts/destroy-platform-bootstrap.sh

destroy-bootstrap:
	tofu -chdir=bootstrap destroy -var-file=../terraform.tfvars -refresh=false

destroy:
	@$(MAKE) destroy-infrastructure
	@$(MAKE) destroy-bootstrap
