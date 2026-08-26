from __future__ import annotations

import json
from datetime import UTC, datetime

from homelabctl.cli import duration, parser
from homelabctl.commands.check_tfvars_example import required_variables, variable_defaults
from homelabctl.commands.operations import (
    SECRET_CONTRACT,
    application_operation_issues,
    argocd_identity_contract_issues,
    latest_completed_backup_age_hours,
    otlp_trace_payload,
    pod_readiness_issues,
    prometheus_metric_sum,
    telemetry_log_error_count,
)
from homelabctl.commands.validate_env_contract import render_stalwart_identity_plan
from homelabctl.environment import materialize_contract
from homelabctl.project import ROOT
from homelabctl.yamlutil import deep_merge


def test_duration() -> None:
    assert duration("10m") == 600
    assert duration("45s") == 45


def test_taskfile_facing_commands_parse() -> None:
    cases = (
        ["internal", "task-var", "environment-contract"],
        ["cluster", "reconcile-lb-pool"],
        ["bao", "port-forward", "stop"],
        ["gitops", "apply", "--kubeconfig", "out/kubeconfig"],
        ["ops", "post-check", "--kubeconfig", "out/kubeconfig"],
        ["ops", "observability-smoke", "--kubeconfig", "out/kubeconfig"],
        [
            "ops",
            "identity-smoke",
            "--kubeconfig",
            "out/kubeconfig",
            "--contract",
            "out/homelab.effective.yaml",
            "--root-ca",
            "out/homelab-root-ca.crt",
        ],
        [
            "ops",
            "argocd-access-finalize",
            "--kubeconfig",
            "out/kubeconfig",
            "--contract",
            "out/homelab.effective.yaml",
            "--root-ca",
            "out/homelab-root-ca.crt",
        ],
        [
            "ops",
            "harbor-smoke",
            "--kubeconfig",
            "out/kubeconfig",
            "--contract",
            "out/homelab.effective.yaml",
            "--root-ca",
            "out/homelab-root-ca.crt",
        ],
    )
    for argv in cases:
        parsed, unknown = parser().parse_known_args(argv)
        assert parsed.domain
        assert not unknown


def test_deep_merge_does_not_mutate_base() -> None:
    base = {"cluster": {"name": "a", "cidr": "one"}, "keep": True}
    merged = deep_merge(base, {"cluster": {"name": "b"}})
    assert merged == {"cluster": {"name": "b", "cidr": "one"}, "keep": True}
    assert base["cluster"]["name"] == "a"


def test_runtime_secret_contract_contains_platform_admin() -> None:
    assert SECRET_CONTRACT["platform/authentik/platform-admin"] == ("password",)


def test_materialized_contract_has_derived_hosts() -> None:
    # The tracked base contract is the authoritative realistic fixture.
    from homelabctl.yamlutil import load

    raw = load(ROOT / "envs/homelab.yaml")
    result = materialize_contract(raw)
    assert result["hosts"]["authentik"].endswith(result["cluster"]["base_domain"])
    assert result["platform"]["forgejo"]["sso"]["discovery_url"].endswith(
        "/.well-known/openid-configuration"
    )
    assert result["platform"]["velero"]["s3_url"] == (
        "http://" + result["platform"]["garage"]["s3_service"]
    )


def test_tfvars_example_requires_only_variables_without_defaults() -> None:
    declarations = variable_defaults(
        'variable "required" {\n  type = string\n}\n'
        'variable "optional" {\n  type = string\n  default = null\n}\n'
    )

    assert declarations == {"required": False, "optional": True}
    assert required_variables("infrastructure") == set()
    assert required_variables("cluster") == {
        "controlplane_node_defaults",
        "controlplane_nodes",
        "proxmox",
        "talos_schematic_id",
        "worker_node_defaults",
        "worker_nodes",
    }


def test_stalwart_oidc_scopes_render_as_registry_map() -> None:
    from homelabctl.yamlutil import load

    env = materialize_contract(load(ROOT / "envs/homelab.yaml"))
    operations = [json.loads(line) for line in render_stalwart_identity_plan(env).splitlines()]
    directory = next(item for item in operations if item["object"] == "Directory")

    assert directory["value"]["authentik"]["requireScopes"] == {
        "openid": True,
        "email": True,
    }


def test_velero_alerts_cover_storage_and_backup_freshness() -> None:
    from homelabctl.yamlutil import load

    values = load(ROOT / "argocd/platform/observability/grafana/values.yaml")
    assert values["deploymentStrategy"]["type"] == "Recreate"
    rules = values["alerting"]["rules.yaml"]["groups"][0]["rules"]
    alerts = {rule["uid"]: rule for rule in rules}

    storage = alerts["velero-storage-unavailable"]
    stale = alerts["velero-backup-stale"]
    assert storage["noDataState"] == "Alerting"
    assert "velero_backup_location_status_gauge" in storage["data"][0]["model"]["expr"]
    assert stale["noDataState"] == "Alerting"
    assert "velero_backup_last_successful_timestamp" in stale["data"][0]["model"]["expr"]


def test_observability_smoke_payload_and_metric_parser() -> None:
    payload = json.loads(
        otlp_trace_payload(
            "00112233445566778899aabbccddeeff",
            "0011223344556677",
            1_000_000_000,
        )
    )
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == "00112233445566778899aabbccddeeff"
    assert span["endTimeUnixNano"] == "1001000000"

    metrics = (
        'otelcol_exporter_sent_spans{exporter="otlp/tempo"} 10\n'
        'otelcol_exporter_sent_spans{exporter="other"} 50\n'
        'otelcol_exporter_sent_spans{exporter="otlp/tempo"} 2\n'
    )
    assert (
        prometheus_metric_sum(metrics, "otelcol_exporter_sent_spans", 'exporter="otlp/tempo"') == 12
    )


def test_argocd_identity_contract() -> None:
    oidc = """
name: Authentik
issuer: https://auth.example/application/o/argocd/
clientID: $argocd-oidc:client_id
clientSecret: $argocd-oidc:client_secret
requestedScopes: [openid, profile, email, groups]
"""
    rbac = {
        "scopes": "[groups]",
        "policy.default": "role:authenticated",
        "policy.csv": "g, platform-admins, role:admin\n",
    }
    assert not argocd_identity_contract_issues(
        oidc,
        rbac,
        issuer="https://auth.example/application/o/argocd/",
        admin_group="platform-admins",
    )
    rbac["policy.csv"] = ""
    assert argocd_identity_contract_issues(
        oidc,
        rbac,
        issuer="https://auth.example/application/o/argocd/",
        admin_group="platform-admins",
    ) == ["administrator group is not mapped to role:admin"]


def test_harbor_ignores_only_eso_owned_redis_url() -> None:
    from homelabctl.yamlutil import load

    application = load(ROOT / "argocd/platform/delivery/applications/harbor/app.yaml")
    differences = application["spec"]["ignoreDifferences"]

    assert differences == [
        {
            "group": "",
            "kind": "Secret",
            "name": "harbor-trivy",
            "namespace": "harbor",
            "jsonPointers": ["/data/redisURL"],
        }
    ]


def test_runtime_workload_validator_rejects_latest_and_missing_baseline() -> None:
    from homelabctl.commands.check_runtime_workloads import validate_documents

    workload = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "bad", "namespace": "echo"},
        "spec": {"containers": [{"name": "bad", "image": "nginx:latest"}]},
    }

    errors = validate_documents([workload], "test")

    assert any("uses latest" in error for error in errors)
    assert any("requests or limits missing" in error for error in errors)
    assert any("restricted securityContext missing" in error for error in errors)
    assert any("pod seccompProfile is missing" in error for error in errors)


def test_runtime_policy_scope_uses_only_system_namespace_exclusions() -> None:
    from homelabctl.yamlutil import load

    expected = {
        "argocd",
        "cert-manager",
        "external-secrets",
        "gateway",
        "kube-system",
        "kyverno",
        "openbao",
        "piraeus-datastore",
        "reloader",
        "trust-manager",
    }
    policies = ROOT / "argocd/platform/policy/kyverno/policies"
    for path in [*policies.glob("disallow-*.yaml"), *policies.glob("require-*.yaml")]:
        policy = load(path)
        expressions = policy["spec"]["matchConstraints"]["namespaceSelector"]["matchExpressions"]
        assert set(expressions[0]["values"]) == expected

    for name in ("require-basic-security-context", "require-resource-requests-and-limits"):
        policy = load(policies / f"{name}.yaml")
        assert policy["spec"]["validationActions"] == ["Deny", "Audit"]


def test_post_check_detects_incomplete_operation_and_crashloop() -> None:
    applications = {
        "items": [
            {
                "metadata": {"name": "stalwart"},
                "status": {
                    "operationState": {
                        "phase": "Running",
                        "message": "waiting for completion of hook",
                    }
                },
            }
        ]
    }
    pods = {
        "items": [
            {
                "metadata": {"namespace": "stalwart", "name": "oidc-hook"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "configure",
                            "ready": False,
                            "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                        }
                    ],
                },
            }
        ]
    }

    assert application_operation_issues(applications, {"stalwart"}) == [
        "stalwart: Running: waiting for completion of hook"
    ]
    assert pod_readiness_issues(pods, {"stalwart"}) == [
        "stalwart/oidc-hook/configure: CrashLoopBackOff"
    ]


def test_post_check_requires_fresh_backup_and_clean_telemetry() -> None:
    backups = {
        "items": [
            {
                "metadata": {"name": "hourly"},
                "status": {
                    "phase": "Completed",
                    "completionTimestamp": "2026-08-22T16:15:00Z",
                },
            }
        ]
    }
    latest = latest_completed_backup_age_hours(
        backups,
        now=datetime(2026, 8, 22, 17, 15, tzinfo=UTC),
    )

    assert latest == ("hourly", 1.0)
    assert telemetry_log_error_count("Failed to scrape Prometheus endpoint\nDropping data") == 2
