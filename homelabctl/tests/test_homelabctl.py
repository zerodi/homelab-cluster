from __future__ import annotations

from homelabctl.cli import duration, parser
from homelabctl.commands.operations import SECRET_CONTRACT
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
