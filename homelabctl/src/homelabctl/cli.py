from __future__ import annotations

import argparse
import sys
from pathlib import Path

from homelabctl.commands import (
    check_chart_versions,
    check_cluster_isolation,
    check_documentation,
    check_image_versions,
    check_infrastructure_isolation,
    check_platform_layout,
    check_release_versions,
    check_tfvars_example,
    forgejo_woodpecker_oauth,
    gitops,
    openbao_runtime_preflight,
    operations,
    validate_env_contract,
)
from homelabctl.project import ROOT
from homelabctl.runtime import CommandError, invoke_main


def path(value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def duration(value: str) -> int:
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("s"):
        return int(value[:-1])
    return int(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="homelabctl")
    domains = root.add_subparsers(dest="domain", required=True)
    internal = domains.add_parser("internal").add_subparsers(dest="command", required=True)
    variables = internal.add_parser("task-var")
    variables.add_argument("name")
    variables.add_argument("values", nargs="*")

    env = domains.add_parser("env").add_subparsers(dest="command", required=True)
    render = env.add_parser("render")
    render.add_argument("--base", default="envs/homelab.yaml")
    render.add_argument("--override", default="envs/homelab.override.yaml")
    render.add_argument("--output", default="out/homelab.effective.yaml")
    env.add_parser("validate")

    checks = domains.add_parser("check").add_subparsers(dest="command", required=True)
    for name in (
        "release-versions",
        "chart-versions",
        "image-versions",
        "cluster-isolation",
        "infrastructure-isolation",
        "platform-layout",
        "tfvars-example",
        "documentation",
        "runtime-secrets",
        "operator-helpers",
    ):
        checks.add_parser(name)
    checks.add_parser("yaml").add_argument("paths", nargs="*", default=["."])

    cluster = domains.add_parser("cluster").add_subparsers(dest="command", required=True)
    cluster.add_parser("reconcile-lb-pool")
    infra = domains.add_parser("infrastructure").add_subparsers(dest="command", required=True)
    linstor = infra.add_parser("bootstrap-linstor")
    linstor.add_argument("--kubeconfig", required=True)
    linstor.add_argument("--namespace", required=True)
    linstor.add_argument("--pool-name", required=True)
    linstor.add_argument("--device", required=True)
    linstor.add_argument("--nodes", required=True)
    destroy = infra.add_parser("destroy")
    destroy.add_argument("args", nargs=argparse.REMAINDER)

    secrets = domains.add_parser("secrets").add_subparsers(dest="command", required=True)
    for name in ("print", "seed", "list-paths", "list-contract"):
        secrets.add_parser(name)

    bao = domains.add_parser("bao").add_subparsers(dest="command", required=True)
    day0 = bao.add_parser("configure-day0")
    day0.add_argument("--kubeconfig", required=True)
    day0.add_argument("--bao-addr", default="http://127.0.0.1:8200")
    day0.add_argument("--eso-namespace", default="external-secrets")
    day0.add_argument("--eso-service-account", default="external-secrets")
    day0.add_argument("--policy-name", default="external-secrets")
    day0.add_argument("--role-name", default="external-secrets")
    day0.add_argument("--kv-path", default="secret")
    pf = bao.add_parser("port-forward")
    pf.add_argument("action", choices=("start", "stop", "status"))
    pf.add_argument("--kubeconfig")

    gd = domains.add_parser("gitops").add_subparsers(dest="command", required=True)
    apply = gd.add_parser("apply")
    apply.add_argument("--kubeconfig", required=True)
    apply.add_argument("--root-manifest", default="argocd/bootstrap/root-application.yaml")
    apply.add_argument("--timeout", default="10m")
    apply.add_argument("--test-ssh-git", action="store_true")
    push = gd.add_parser("push")
    push.add_argument("--kubeconfig", required=True)
    push.add_argument("--contract", required=True)
    test = gd.add_parser("test-ssh-bootstrap")
    test.add_argument("--kubeconfig", required=True)
    test.add_argument("--hostname", required=True)
    test.add_argument("--port", type=int, default=2222)
    test.add_argument("--timeout", default="10m")
    cut = gd.add_parser("forgejo-cutover")
    cut.add_argument("--kubeconfig", required=True)
    cut.add_argument("--contract", required=True)
    cut.add_argument("--timeout", default="10m")

    forgejo = domains.add_parser("forgejo").add_subparsers(dest="command", required=True)
    forgejo.add_parser("woodpecker-oauth")

    ops = domains.add_parser("ops").add_subparsers(dest="command", required=True)
    hosts = ops.add_parser("hosts")
    hosts.add_argument("--kubeconfig", required=True)
    hosts.add_argument("--contract", required=True)
    creds = ops.add_parser("credentials")
    creds.add_argument("--kubeconfig", required=True)
    creds.add_argument("--contract", required=True)
    garage = ops.add_parser("garage")
    garage.add_argument(
        "action",
        choices=("status", "detect-node-id", "print-bootstrap", "bootstrap-velero"),
    )
    garage.add_argument("--kubeconfig", required=True)
    post = ops.add_parser("post-check")
    post.add_argument("--kubeconfig", required=True)
    observability = ops.add_parser("observability-smoke")
    observability.add_argument("--kubeconfig", required=True)
    identity = ops.add_parser("identity-smoke")
    identity.add_argument("--kubeconfig", required=True)
    identity.add_argument("--contract", required=True)
    identity.add_argument("--root-ca", required=True)
    finalize_access = ops.add_parser("argocd-access-finalize")
    finalize_access.add_argument("--kubeconfig", required=True)
    finalize_access.add_argument("--contract", required=True)
    finalize_access.add_argument("--root-ca", required=True)
    harbor = ops.add_parser("harbor-smoke")
    harbor.add_argument("--kubeconfig", required=True)
    harbor.add_argument("--contract", required=True)
    harbor.add_argument("--root-ca", required=True)
    return root


def dispatch(args: argparse.Namespace) -> int:
    if args.domain == "internal":
        return operations.task_var(args.name, args.values)
    if args.domain == "env":
        return (
            operations.render_environment(args.base, args.override, args.output)
            if args.command == "render"
            else invoke_main(validate_env_contract.main, getattr(args, "args", []))
        )
    if args.domain == "check":
        modules = {
            "release-versions": check_release_versions,
            "chart-versions": check_chart_versions,
            "image-versions": check_image_versions,
            "cluster-isolation": check_cluster_isolation,
            "infrastructure-isolation": check_infrastructure_isolation,
            "platform-layout": check_platform_layout,
            "tfvars-example": check_tfvars_example,
            "documentation": check_documentation,
            "runtime-secrets": openbao_runtime_preflight,
            "operator-helpers": forgejo_woodpecker_oauth,
        }
        if args.command == "yaml":
            from yamllint.cli import run as yaml_run

            previous = sys.argv
            try:
                sys.argv = ["yamllint", *args.paths]
                return int(yaml_run() or 0)
            finally:
                sys.argv = previous
        extra = getattr(args, "args", [])
        if args.command == "operator-helpers":
            extra = ["--self-test", *extra]
        return invoke_main(modules[args.command].main, extra)
    if args.domain == "cluster":
        return operations.reconcile_cilium()
    if args.domain == "infrastructure":
        if args.command == "destroy":
            return operations.destroy_infrastructure(args.args)
        return operations.bootstrap_linstor(
            path(args.kubeconfig), args.namespace, args.pool_name, args.device, args.nodes.split()
        )
    if args.domain == "secrets":
        return operations.secrets_command("apply" if args.command == "seed" else args.command)
    if args.domain == "bao":
        if args.command == "port-forward":
            return operations.port_forward(
                args.action, path(args.kubeconfig) if args.kubeconfig else None
            )
        return operations.openbao_day0(
            path(args.kubeconfig),
            args.bao_addr,
            args.eso_namespace,
            args.eso_service_account,
            args.policy_name,
            args.role_name,
            args.kv_path,
        )
    if args.domain == "gitops":
        if args.command == "apply":
            return operations.argocd_apply(
                path(args.kubeconfig),
                path(args.root_manifest),
                duration(args.timeout),
                args.test_ssh_git,
            )
        if args.command == "push":
            return gitops.push(path(args.kubeconfig), path(args.contract))
        if args.command == "test-ssh-bootstrap":
            return gitops.test_ssh_bootstrap(
                path(args.kubeconfig), args.hostname, args.port, duration(args.timeout)
            )
        return gitops.cutover(path(args.kubeconfig), path(args.contract), duration(args.timeout))
    if args.domain == "forgejo":
        return invoke_main(forgejo_woodpecker_oauth.main, getattr(args, "args", []))
    if args.domain == "ops":
        if args.command == "hosts":
            return operations.hosts_entries(path(args.kubeconfig), path(args.contract))
        if args.command == "credentials":
            return operations.initial_credentials(path(args.kubeconfig), path(args.contract))
        if args.command == "post-check":
            return operations.post_argocd_check(path(args.kubeconfig))
        if args.command == "observability-smoke":
            return operations.observability_smoke(path(args.kubeconfig))
        if args.command == "identity-smoke":
            return operations.identity_smoke(
                path(args.kubeconfig), path(args.contract), path(args.root_ca)
            )
        if args.command == "argocd-access-finalize":
            return operations.argocd_access_finalize(
                path(args.kubeconfig), path(args.contract), path(args.root_ca)
            )
        if args.command == "harbor-smoke":
            return operations.harbor_smoke(
                path(args.kubeconfig), path(args.contract), path(args.root_ca)
            )
        return operations.garage(path(args.kubeconfig), args.action)
    raise CommandError("unsupported command")


def main() -> int:
    try:
        parsed, unknown = parser().parse_known_args()
        if unknown:
            if parsed.domain in {"env", "check", "forgejo"}:
                parsed.args = unknown
            else:
                raise CommandError("unrecognized arguments: " + " ".join(unknown))
        return dispatch(parsed)
    except (CommandError, KeyError, ValueError) as exc:
        print(f"[homelabctl] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
